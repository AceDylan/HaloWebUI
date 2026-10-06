"""精答工作台 (answer desk) engine.

One question, answered by the right assistant. A dispatcher model reads the user's assistants
(workspace models: a base model plus a system prompt) and decides to use one as it is, upgrade
one whose field fits but lacks what the question needs (its system prompt is rewritten, the old
one kept so the upgrade can be undone), or create a new reusable specialist when none fits. It
also decides whether the question needs fresh facts from the web. The chosen assistant then
answers, streaming to the page.

A run is an ordinary chat with the assistant as its model (so it gets an automatic title, folder
auto-assignment, search and a place in the sidebar, and follow-ups happen in the normal chat),
marked by ``chat.meta.answer_desk`` and ``chat.chat.answerDesk``. Its assistant message's
``content`` is the answer; ``answer_desk`` on that message holds the run: the plan, the
assistant, the web sources and the answer's timings. Live state lives in memory while a run
goes (single worker); events reach the page over the socket (``chat-events`` with
``type: "answer"``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import urllib.parse
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from open_webui.env import GLOBAL_LOG_LEVEL, SRC_LOG_LEVELS
from open_webui.utils.discussion_room import (
    _short_error,
    detect_lang,
    iterate_completion,
    now_ms,
    retry_wait,
    strip_think,
    transient_reason,
)
from open_webui.utils.mode_chats import sources_from_docs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", GLOBAL_LOG_LEVEL))

META_KEY = "answer_desk"
CHAT_KEY = "answerDesk"
MESSAGE_KEY = "answer_desk"
ASSISTANT_TAG = "精答"

QUESTION_MAX_CHARS = 8000
MAX_RUNNING_PER_USER = 3
CATALOG_LIMIT = 80
PROMPT_EXCERPT_CHARS = 500
SYSTEM_PROMPT_MAX_CHARS = 8000
SYSTEM_PROMPT_MIN_CHARS = 40
NAME_MAX_CHARS = 24
DESCRIPTION_MAX_CHARS = 160
MAX_REVISIONS = 5
BACKGROUND_PLAN_CHARS = 3000
PLAN_TIMEOUT_SECONDS = 120
ANSWER_TIMEOUT_SECONDS = 300
RESEARCH_TIMEOUT_SECONDS = 150
RESEARCH_MAX_SOURCES = 8
RESEARCH_EXCERPT_CHARS = 1600
DELTA_FLUSH_SECONDS = 0.12
RETRY_DELAYS = (8, 20, 45)

ACTIONS = ("use", "update", "create")
RUNNING_STATUSES = {"routing", "researching", "answering"}
TERMINAL_STATUSES = {"done", "stopped", "error", "interrupted"}


class AnswerError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def clean_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------------------------
# The library: which assistants there are, which base models a new one can stand on


def _excluded(model: dict) -> bool:
    """Not an answerer: Hermes (an agent run takes minutes), image models, hidden and arena entries."""
    from open_webui.utils.hermes_agent import is_hermes_agent_model
    from open_webui.utils.task import is_dedicated_image_generation_model

    info = model.get("info") or {}
    if (info.get("meta") or {}).get("hidden") or model.get("owned_by") == "arena":
        return True
    # (an assistant standing on Hermes or an image model is not one either)
    base = str(info.get("base_model_id") or "")
    return (
        is_hermes_agent_model(model)
        or (bool(base) and is_hermes_agent_model(base))
        or is_dedicated_image_generation_model(model)
    )


def _selection_id(model: dict) -> str:
    return str(model.get("selection_id") or model.get("id") or "").strip()


def library(models_map: dict, user: Any) -> tuple[list[dict], list[dict]]:
    """(assistants, bases) the user can use. ``models_map`` is the per-request lookup (several
    keys may point at the same model)."""
    from open_webui.utils.access_control import can_write_resource

    seen: set[str] = set()
    assistants: list[dict] = []
    bases: list[dict] = []
    for model in models_map.values():
        if not isinstance(model, dict):
            continue
        ref = _selection_id(model)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if _excluded(model):
            continue
        info = model.get("info") or {}
        name = str(model.get("name") or ref)
        if info.get("base_model_id"):
            meta = info.get("meta") or {}
            desk = meta.get(META_KEY) or {}
            owner = type("Owner", (), {"user_id": info.get("user_id"), "access_control": info.get("access_control")})()
            assistants.append(
                {
                    "id": ref,
                    "name": name,
                    "description": clean_text(meta.get("description"), DESCRIPTION_MAX_CHARS),
                    "emoji": clean_text(desk.get("emoji"), 8),
                    "prompt": str((info.get("params") or {}).get("system") or ""),
                    "base": str(info.get("base_model_id") or ""),
                    "editable": can_write_resource(user, owner),
                    "byDesk": bool(desk),
                    "updatedAt": info.get("updated_at"),
                }
            )
        else:
            bases.append({"id": ref, "name": name})
    assistants.sort(key=lambda a: -(a.get("updatedAt") or 0))
    return assistants[:CATALOG_LIMIT], bases


def public_assistant(entry: dict) -> dict:
    """An assistant as the page shows it (no full system prompt)."""
    return {k: entry.get(k) for k in ("id", "name", "description", "emoji", "base", "editable", "byDesk")}


def base_name(bases: list[dict], ref: str) -> str:
    entry = next((b for b in bases if b["id"] == ref), None)
    if entry:
        return entry["name"]
    return ref.rsplit("::", 1)[-1] if ref else ""


# ---------------------------------------------------------------------------------------------
# The dispatcher


PLAN_SYSTEM = """You are the dispatcher of 精答 (precise answers) in HaloWebUI. The user keeps a library of assistants; each is a base model plus a system prompt that makes it a specialist. For the user's question, pick how it gets the best possible answer:

- "use": an existing assistant's speciality clearly covers the question. Prefer this whenever it is true.
- "update": an existing assistant is the right field but lacks something this kind of question needs (a skill, a method, an output format, a quality bar). Rewrite its whole system prompt: keep everything it already does and add the missing capability in general terms, so it still serves its old purpose and now also this kind of question. Only assistants with "editable": true.
- "create": no assistant fits. Design a new, reusable specialist for this KIND of question (never for this one question only).

Also decide "web_search": true only when a good answer needs current or real-world facts that may have changed (news, prices, releases, versions, schedules, recent events, specific products or people); false for reasoning, writing, coding, maths, explanations of stable knowledge, or anything personal.

A "background" field, when present, is the conversation the question was asked from: use it to understand the question.

A new or rewritten system prompt (the user's language) states: the role and its expertise; how it works through a question (clarify the goal, method, checks for mistakes); the output format (structure, length, when to use tables, lists or code); and the quality bar (precise, concrete, says what it does not know, no filler). 150-500 words. A name is 2-8 Chinese characters (or 1-3 English words for an English user), naming the speciality, without "助手" unless needed.

Reply with one JSON object and nothing else:
{"action": "use" | "update" | "create",
 "assistant_id": "<id from the library, for use / update>",
 "reason": "<one sentence in the user's language: why this assistant suits the question>",
 "web_search": true | false,
 "change": "<update / create: one short sentence in the user's language, what it can now do>",
 "assistant": {"name": "...", "emoji": "<one emoji>", "description": "<one sentence>", "system_prompt": "...", "base_model": "<a name from base_models>"}}
"assistant" is required for create; for update give "system_prompt" (the complete new prompt) and optionally "description"; omit it for use. Pick "base_model" by what the question needs (careful reasoning, writing, code, long documents, Chinese) or keep the default."""


def plan_messages(
    question: str,
    assistants: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_create: bool,
    web_allowed: bool,
    background: str = "",
) -> list[dict]:
    library_view = [
        {
            "id": a["id"],
            "name": a["name"],
            "description": a["description"],
            "editable": a["editable"],
            "base_model": base_name(bases, a["base"]),
            "system_prompt": a["prompt"][:PROMPT_EXCERPT_CHARS] + ("…" if len(a["prompt"]) > PROMPT_EXCERPT_CHARS else ""),
        }
        for a in assistants
    ]
    rules = []
    if not may_create:
        rules.append("This user may not create or edit assistants: answer with action \"use\" if one fits; otherwise still write \"create\" with a full assistant (it will be used once, not saved).")
    if not web_allowed:
        rules.append("Web search is off for this question: web_search must be false.")
    payload = {
        "question": question,
        **({"background": background[:BACKGROUND_PLAN_CHARS]} if background else {}),
        "language": "Chinese" if detect_lang(question) == "zh" else "the question's language",
        "library": library_view,
        "base_models": [b["name"] for b in bases],
        "default_base_model": base_name(bases, default_base),
    }
    content = json.dumps(payload, ensure_ascii=False, indent=1)
    if rules:
        content += "\n\n" + "\n".join(rules)
    return [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": content}]


def parse_json_object(text: str) -> dict:
    text = strip_think(text or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("调度模型没有给出 JSON")
    try:
        value = json.loads(text[start : end + 1])
    except Exception as exc:
        raise ValueError(f"调度模型的 JSON 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("调度模型的回答不是 JSON 对象")
    return value


def _match_base(bases: list[dict], wanted: Any, default: str) -> str:
    wanted = str(wanted or "").strip().lower()
    if wanted:
        for b in bases:
            if wanted in (b["name"].lower(), b["id"].lower()):
                return b["id"]
        for b in bases:
            if wanted in b["name"].lower() or b["name"].lower() in wanted:
                return b["id"]
    return default


EMOJI_RE = re.compile(r"[<>&\"'\s]")


def _spec(raw: Any, bases: list[dict], default_base: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "name": clean_text(raw.get("name"), NAME_MAX_CHARS),
        "emoji": EMOJI_RE.sub("", clean_text(raw.get("emoji"), 8))[:4] or "✦",
        "description": clean_text(raw.get("description"), DESCRIPTION_MAX_CHARS),
        "system": clean_text(raw.get("system_prompt") or raw.get("system"), SYSTEM_PROMPT_MAX_CHARS),
        "base": _match_base(bases, raw.get("base_model"), default_base),
    }


def normalize_plan(
    raw: dict,
    assistants: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_create: bool,
    web_allowed: bool,
) -> dict:
    """The dispatcher's answer made safe: an action that can be carried out, with what it needs.
    ``{"action", "target" (an assistant entry for use/update), "spec" (create/update), "reason",
    "change", "webSearch", "note"}``; raises ValueError when nothing usable came back."""
    action = str(raw.get("action") or "").strip().lower()
    by_id = {a["id"]: a for a in assistants}
    target = by_id.get(str(raw.get("assistant_id") or "").strip())
    if target is None and raw.get("assistant_id"):
        wanted = str(raw.get("assistant_id")).strip().lower()
        target = next((a for a in assistants if a["name"].lower() == wanted), None)
    spec = _spec(raw.get("assistant"), bases, default_base)
    if not spec["system"] and raw.get("system_prompt"):
        spec["system"] = clean_text(raw.get("system_prompt"), SYSTEM_PROMPT_MAX_CHARS)
    plan = {
        "action": action,
        "target": target,
        "spec": spec,
        "reason": clean_text(raw.get("reason"), 300),
        "change": clean_text(raw.get("change"), 300),
        "webSearch": bool(raw.get("web_search")) and web_allowed,
        "note": "",
    }
    if action not in ACTIONS:
        raise ValueError(f"调度模型给了未知的做法：{action or '空'}")

    if action == "update":
        if target is None:
            action = "create"
        elif not target["editable"] or not may_create:
            plan["note"] = f"没有修改「{target['name']}」的权限，直接用它回答"
            action = "use"
        elif len(spec["system"]) < SYSTEM_PROMPT_MIN_CHARS:
            plan["note"] = "调度模型没写出新的设定，直接用原助手回答"
            action = "use"
    if action == "use" and target is None:
        if spec["system"] and spec["name"]:
            action = "create"
        else:
            raise ValueError("调度模型选了一个不存在的助手")
    if action == "create":
        if len(spec["system"]) < SYSTEM_PROMPT_MIN_CHARS or not spec["name"]:
            raise ValueError("调度模型没写出新助手的名字或设定")
        same = next((a for a in assistants if a["name"].strip().lower() == spec["name"].strip().lower()), None)
        if same is not None:
            # the library already has it under this name: use that one
            action, target = "use", same
            plan["note"] = f"已有同名助手「{same['name']}」，直接用它"
        elif not spec["base"]:
            raise ValueError("没有可用的底座模型")
    plan["action"] = action
    plan["target"] = target
    return plan


# ---------------------------------------------------------------------------------------------
# The library, written: a new assistant, an upgrade and its undo


def emoji_avatar(emoji: str, seed: str) -> str:
    """A round tile with the emoji, as a data URL (the app shows a model's profile_image_url)."""
    hue = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:4], 16) % 360
    glyph = EMOJI_RE.sub("", emoji or "")[:4] or "✦"
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        f"<rect width='64' height='64' rx='32' fill='hsl({hue},72%,90%)'/>"
        f"<text x='32' y='43' font-size='30' text-anchor='middle'>{glyph}</text></svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def create_assistant(user: Any, spec: dict, *, chat_id: str, question: str) -> dict:
    """A new workspace assistant, private to the user, tagged 精答. Returns the model row."""
    from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models

    model_id = f"answer-{uuid.uuid4().hex[:10]}"
    meta = {
        "profile_image_url": emoji_avatar(spec["emoji"], model_id),
        "description": spec["description"] or None,
        "tags": [{"name": ASSISTANT_TAG}],
        META_KEY: {
            "emoji": spec["emoji"],
            "createdFor": {"chatId": chat_id, "question": clean_text(question, 200), "at": now_ms()},
            "revisions": [],
        },
    }
    row = Models.insert_new_model(
        ModelForm(
            id=model_id,
            base_model_id=spec["base"],
            name=spec["name"],
            meta=ModelMeta(**meta),
            params=ModelParams(system=spec["system"]),
            access_control={},
            is_active=True,
        ),
        user.id,
    )
    if row is None:
        raise AnswerError(500, "新建助手失败")
    return row


def update_assistant(user: Any, model_id: str, spec: dict, *, chat_id: str, change: str) -> tuple[Any, dict]:
    """Rewrite an assistant's system prompt (and description); the old ones are kept in
    ``meta.answer_desk.revisions``. Returns (row, before)."""
    from open_webui.models.models import ModelForm, Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None or not can_write_resource(user, row):
        raise AnswerError(403, "没有修改这个助手的权限")
    params = row.params.model_dump()
    meta = row.meta.model_dump()
    before = {"system": str(params.get("system") or ""), "description": meta.get("description") or ""}
    desk = dict(meta.get(META_KEY) or {})
    revisions = [*(desk.get("revisions") or []), {"at": now_ms(), "chatId": chat_id, "change": change, **before}]
    desk["revisions"] = revisions[-MAX_REVISIONS:]
    meta[META_KEY] = desk
    if spec.get("description"):
        meta["description"] = spec["description"]
    params["system"] = spec["system"]
    updated = Models.update_model_by_id(
        model_id,
        ModelForm(
            id=row.id,
            base_model_id=row.base_model_id,
            name=row.name,
            meta=meta,
            params=params,
            access_control=row.access_control,
            is_active=row.is_active,
        ),
    )
    if updated is None:
        raise AnswerError(500, "更新助手失败")
    return updated, before


def revert_assistant(user: Any, model_id: str, *, chat_id: str, after_system: str) -> Any:
    """Undo the upgrade a run made, if the assistant has not been changed since."""
    from open_webui.models.models import ModelForm, Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None:
        raise AnswerError(404, "这个助手已经不在了")
    if not can_write_resource(user, row):
        raise AnswerError(403, "没有修改这个助手的权限")
    params = row.params.model_dump()
    meta = row.meta.model_dump()
    if str(params.get("system") or "") != after_system:
        raise AnswerError(409, "这个助手之后又改过，不能自动撤销；可以在工作空间里手动改")
    desk = dict(meta.get(META_KEY) or {})
    revisions = list(desk.get("revisions") or [])
    index = next((i for i in range(len(revisions) - 1, -1, -1) if revisions[i].get("chatId") == chat_id), None)
    if index is None:
        raise AnswerError(409, "找不到这次升级前的设定")
    before = revisions.pop(index)
    desk["revisions"] = revisions
    meta[META_KEY] = desk
    meta["description"] = before.get("description") or None
    params["system"] = before.get("system") or ""
    updated = Models.update_model_by_id(
        model_id,
        ModelForm(
            id=row.id,
            base_model_id=row.base_model_id,
            name=row.name,
            meta=meta,
            params=params,
            access_control=row.access_control,
            is_active=row.is_active,
        ),
    )
    if updated is None:
        raise AnswerError(500, "撤销失败")
    return updated


# ---------------------------------------------------------------------------------------------
# State


def new_run(
    *, question: str, planner: dict, user_message_id: str, message_id: str, web_allowed: bool, context: Optional[dict] = None
) -> dict:
    return {
        "v": 1,
        "id": message_id,
        "userMessageId": user_message_id,
        "question": question,
        "lang": detect_lang(question),
        "status": "routing",
        "planner": deepcopy(planner),
        "webAllowed": web_allowed,
        "context": context,
        "plan": {"status": "running", "startedAt": now_ms(), "endedAt": None},
        "assistant": None,
        "research": None,
        "answer": {"status": "waiting", "content": "", "thinking": False, "usage": {}, "startedAt": None, "endedAt": None, "error": None, "retry": None},
        "startedAt": now_ms(),
        "endedAt": None,
        "error": None,
    }


def public_run(run: dict) -> dict:
    out = deepcopy(run)
    assistant = out.get("assistant")
    if isinstance(assistant, dict):
        # what was written into the assistant, for 「看看它的设定」; the old prompt stays private
        assistant.pop("before", None)
    return out


def _plain(markdown: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown or "")
    text = re.sub(r"(\*\*|__|\*|`|~~)", "", text)
    text = re.sub(r"^\s{0,3}(#+|>|[-*+]|\d+\.)\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def summary_meta(run: dict) -> dict:
    assistant = run.get("assistant") or {}
    return {
        "v": 1,
        "status": run.get("status"),
        "question": clean_text(run.get("question"), 200),
        "preview": clean_text(_plain((run.get("answer") or {}).get("content") or ""), 180),
        "assistant": {k: assistant.get(k) for k in ("id", "name", "emoji", "action")} if assistant else None,
        "research": bool((run.get("research") or {}).get("sources")),
        "updatedAt": now_ms(),
    }


def research_block(sources: list[dict]) -> str:
    parts = [
        "Notes gathered from the web for this question. Cite them as [n] right after a claim that relies "
        "on them; they can be incomplete, outdated or wrong, so weigh them:"
    ]
    for source in sources:
        parts.append(f"[{source['n']}] {source.get('title') or source.get('url')} — {source.get('url')}\n{source.get('excerpt') or ''}")
    return "\n\n".join(parts)


def answer_messages(run: dict) -> list[dict]:
    """What the assistant is sent. A saved assistant brings its own system prompt (applied by the
    app when it is called by its id); a temporary one or the dispatcher's fallback gets it here."""
    assistant = run.get("assistant") or {}
    messages = []
    if not assistant.get("saved") and assistant.get("system"):
        messages.append({"role": "system", "content": assistant["system"]})
    content = run["question"]
    context = run.get("context") or {}
    if context.get("text"):
        title = f"「{context['title']}」" if context.get("title") else ""
        content = (
            f"Background: the user's earlier conversation{title}, which led to this question. Use it to "
            f"understand what they need; answer the question itself.\n\n{context['text']}\n\n---\nQuestion: {content}"
        )
    sources = (run.get("research") or {}).get("sources") or []
    if sources:
        content = f"{content}\n\n---\n{research_block(sources)}"
    messages.append({"role": "user", "content": content})
    return messages


def stored_content(run: dict) -> str:
    """The answer as the chat keeps it: with its sources listed, since the chat view has no panel."""
    content = ((run.get("answer") or {}).get("content") or "").strip()
    sources = (run.get("research") or {}).get("sources") or []
    if content and sources:
        lines = [f"{s['n']}. [{s.get('title') or s['url']}]({s['url']})" for s in sources]
        content += "\n\n---\n**资料来源**\n\n" + "\n".join(lines)
    return content


# ---------------------------------------------------------------------------------------------
# Runner


Emit = Callable[[dict], Awaitable[None]]
CallModel = Callable[[str, list[dict]], Awaitable[Any]]


@dataclass
class LiveAnswer:
    chat_id: str
    user_id: str
    run: dict
    emit: Emit
    call_model: CallModel
    # (run) -> (plan, assistant): the dispatcher's decision, carried out (assistant written)
    route: Callable[[dict], Awaitable[tuple[dict, dict]]]
    persist: Callable[[dict], None]
    after_done: Optional[Callable[[dict], Awaitable[None]]] = None
    # (question) -> {"queries": [...], "docs": [...]}
    search: Optional[Callable[[str], Awaitable[dict]]] = None
    task: Optional[asyncio.Task] = None
    pending: Optional[dict] = None
    version: int = 0
    retry_delays: tuple = RETRY_DELAYS

    async def send(self, kind: str, **data):
        self.version += 1
        try:
            await self.emit({"type": "answer", "data": {"kind": kind, "chatId": self.chat_id, "runId": self.run["id"], "v": self.version, **data}})
        except Exception:
            log.debug("answer event %s not delivered", kind, exc_info=True)

    async def send_state(self):
        await self.send("state", run=public_run(self.run))

    def save(self):
        try:
            self.persist(self.run)
        except Exception:
            log.exception("could not persist answer %s", self.chat_id)

    def queue_delta(self, offset: int, text: str):
        part = self.pending
        if part is None or offset <= part["o"]:
            self.pending = {"o": offset, "x": text}
        else:
            part["x"] = part["x"][: offset - part["o"]] + text

    async def flush(self):
        if not self.pending:
            return
        part, self.pending = self.pending, None
        await self.send("delta", offset=part["o"], text=part["x"])

    async def _flush_loop(self):
        try:
            while True:
                await asyncio.sleep(DELTA_FLUSH_SECONDS)
                await self.flush()
        except asyncio.CancelledError:
            pass

    # -- steps -------------------------------------------------------------------------------

    async def _route(self):
        run = self.run
        run["status"] = "routing"
        run["plan"] = {"status": "running", "startedAt": now_ms(), "endedAt": None}
        await self.send_state()
        try:
            plan, assistant = await asyncio.wait_for(self.route(run), PLAN_TIMEOUT_SECONDS)
            run["plan"].update(plan)
            run["plan"]["status"] = "done"
        except (asyncio.CancelledError, AnswerError):
            raise
        except Exception as exc:
            # the dispatcher failed: the dispatcher's own model answers, so the question still is
            planner = run["planner"]
            log.info("answer %s: dispatch failed (%s), %s answers directly", self.chat_id, exc, planner["model"])
            run["plan"].update(
                {"status": "error", "action": "direct", "error": _short_error(exc)[:200], "reason": f"调度没成功，直接由 {planner['name']} 回答", "webSearch": False}
            )
            assistant = {"id": planner["model"], "name": planner["name"], "emoji": "", "action": "direct", "saved": True, "base": planner["model"], "baseName": planner["name"]}
        run["plan"]["endedAt"] = now_ms()
        run["assistant"] = assistant
        self.save()
        await self.send_state()

    async def _research(self):
        run = self.run
        research = run["research"] = {"status": "running", "queries": [], "sources": [], "error": None, "startedAt": now_ms(), "endedAt": None}
        run["status"] = "researching"
        await self.send_state()
        try:
            if self.search is None:
                raise ValueError("联网搜索不可用")
            found = await asyncio.wait_for(self.search(run["question"]), RESEARCH_TIMEOUT_SECONDS)
            research["queries"] = [q for q in (found or {}).get("queries") or [] if q][:4]
            research["sources"] = sources_from_docs(found, RESEARCH_MAX_SOURCES, RESEARCH_EXCERPT_CHARS)
            research["status"] = "done" if research["sources"] else "empty"
        except asyncio.CancelledError:
            research["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            research.update({"status": "error", "error": f"超过 {RESEARCH_TIMEOUT_SECONDS} 秒没查完，直接回答"})
        except Exception as exc:
            research.update({"status": "error", "error": _short_error(exc)[:200]})
        finally:
            research["endedAt"] = now_ms()
            await self.send_state()

    async def _stream_answer(self):
        answer = self.run["answer"]
        answer.update({"status": "streaming", "startedAt": now_ms(), "content": "", "thinking": False, "retry": None, "error": None})
        await self.send_state()
        raw = ""
        response = await self.call_model(self.run["assistant"]["id"], answer_messages(self.run))
        async for kind, text in iterate_completion(response):
            if kind == "usage":
                answer["usage"] = text
            elif kind == "reasoning":
                if not answer.get("thinking"):
                    answer["thinking"] = True
                    await self.send("answer", answer=_brief(answer))
            elif kind == "content":
                raw += text
                visible = strip_think(raw)
                previous = answer["content"]
                if visible.startswith(previous):
                    if len(visible) > len(previous):
                        self.queue_delta(len(previous), visible[len(previous):])
                else:
                    self.queue_delta(0, visible)
                answer["content"] = visible
                if answer.get("thinking") and visible:
                    answer["thinking"] = False
        answer["content"] = strip_think(raw).strip()
        if not answer["content"]:
            raise ValueError("模型返回了空内容")

    async def _answer(self):
        run = self.run
        run["status"] = "answering"
        answer = run["answer"]
        tries = 0
        while True:
            try:
                await asyncio.wait_for(self._stream_answer(), ANSWER_TIMEOUT_SECONDS)
                break
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                raise ValueError(f"超过 {ANSWER_TIMEOUT_SECONDS} 秒没答完")
            except Exception as exc:
                reason = transient_reason(exc)
                if not reason or tries >= len(self.retry_delays):
                    raise
                wait = retry_wait(exc, self.retry_delays[tries])
                tries += 1
                answer.update(
                    {
                        "status": "waiting",
                        "thinking": False,
                        "retry": {"n": tries, "of": len(self.retry_delays), "reason": reason, "until": now_ms() + int(wait * 1000), "error": _short_error(exc)[:160]},
                    }
                )
                self.pending = None
                await self.send_state()
                await asyncio.sleep(wait)
        await self.flush()
        answer.update({"status": "done", "endedAt": now_ms(), "thinking": False, "retry": None})

    async def run_all(self):
        run = self.run
        flusher = asyncio.create_task(self._flush_loop())
        try:
            if not run.get("assistant"):
                await self._route()
            if (run.get("plan") or {}).get("webSearch") and (run.get("research") or {}).get("status") != "done":
                await self._research()
            await self._answer()
            run["status"] = "done"
        except asyncio.CancelledError:
            run["status"] = "stopped"
            if run.get("plan", {}).get("status") == "running":
                run["plan"].update({"status": "stopped", "endedAt": now_ms()})
            self._settle_answer("stopped")
        except Exception as exc:
            log.warning("answer %s failed: %s", self.chat_id, exc)
            run["status"] = "error"
            run["error"] = _short_error(exc)[:300]
            if run.get("plan", {}).get("status") == "running":
                run["plan"].update({"status": "error", "error": run["error"], "endedAt": now_ms()})
            self._settle_answer("error", run["error"])
        finally:
            flusher.cancel()
            try:
                await self.flush()
            except Exception:
                pass
            run["endedAt"] = now_ms()
            LIVE.pop(self.chat_id, None)
            self.save()
            await self.send_state()
            await self.send("end", status=run["status"])
            if run["status"] == "done" and self.after_done is not None:
                try:
                    await self.after_done(run)
                except Exception:
                    log.exception("answer %s after-done hook failed", self.chat_id)

    def _settle_answer(self, status: str, error: Optional[str] = None):
        answer = self.run["answer"]
        if answer.get("status") in {"streaming", "waiting"} and (answer.get("startedAt") or answer.get("retry")):
            answer.update({"status": status, "endedAt": now_ms(), "thinking": False, "retry": None})
            if error:
                answer["error"] = error


def _brief(answer: dict) -> dict:
    return {k: answer.get(k) for k in ("status", "thinking", "startedAt", "endedAt", "usage", "error", "retry")}


LIVE: dict[str, LiveAnswer] = {}


def running_for_user(user_id: str) -> int:
    return sum(1 for live in LIVE.values() if live.user_id == user_id)


def start_live(live: LiveAnswer) -> LiveAnswer:
    from open_webui.tasks import create_task

    LIVE[live.chat_id] = live
    _, task = create_task(live.run_all(), id=f"answer-{live.chat_id}", owner_id=live.user_id)
    live.task = task
    return live


async def stop_live(chat_id: str) -> bool:
    live = LIVE.get(chat_id)
    if not live or not live.task:
        return False
    live.task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(live.task), 10)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass
    return True
