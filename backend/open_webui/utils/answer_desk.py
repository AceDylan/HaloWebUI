"""精答工作台 (answer desk) engine.

One question, answered by the right assistant. A dispatcher model reads a shortlist of the
shared assistant library (utils/assistant_library.py: the user's assistants and the built-in
templates) and, by the library's rules, uses one as it is, upgrades one whose field fits but lacks
what the question needs (a new version, undoable), or creates a new reusable specialist (hidden
from the model menus) when none fits. It also decides whether the question needs fresh facts from
the web. The chosen assistant then answers, streaming to the page.

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
import json
import logging
import re
import time
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
from open_webui.utils import assistant_library as lib
from open_webui.utils.mode_chats import sources_from_docs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", GLOBAL_LOG_LEVEL))

META_KEY = "answer_desk"
CHAT_KEY = "answerDesk"
MESSAGE_KEY = "answer_desk"

QUESTION_MAX_CHARS = 8000
MAX_RUNNING_PER_USER = 3
PLAN_TIMEOUT_SECONDS = 120
ANSWER_TIMEOUT_SECONDS = 300
RESEARCH_TIMEOUT_SECONDS = 150
RESEARCH_MAX_SOURCES = 8
RESEARCH_EXCERPT_CHARS = 2800
DELTA_FLUSH_SECONDS = 0.12
RETRY_DELAYS = (8, 20, 45)

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
# The dispatcher: the shared library's rules (utils/assistant_library.py), one unit — the question


UNIT_KEY = "q"
WEB_RULE = (
    'Also give a top-level "web_search": true only when a good answer needs current or real-world facts that may '
    "have changed (news, prices, releases, versions, schedules, recent events, specific products or people); false "
    "for reasoning, writing, coding, maths, explanations of stable knowledge, or anything personal."
)


def plan_messages(
    question: str,
    assistants: list[dict],
    templates: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_create: bool,
    web_allowed: bool,
    background: str = "",
    chosen: str = "",
) -> list[dict]:
    rules = [WEB_RULE if web_allowed else 'Web search is off for this question: "web_search" must be false.']
    if chosen:
        rules.append(
            f'The user chose "{chosen}" for this question: it answers. Keep it as it is ("use") unless the question is squarely in '
            'its field and it lacks a reusable capability ("update"); never widen it into another field.'
        )
    return lib.dispatch_messages(
        [{"key": UNIT_KEY, "question": question}],
        assistants,
        templates,
        bases,
        default_base=default_base,
        may_write=may_create,
        lang_hint="Chinese" if detect_lang(question) == "zh" else "the question's language",
        task="精答 (precise answers): one assistant answers the user's question",
        rules=rules,
        extra_fields=', "web_search": true | false',
        background=background,
        max_create=1,
        max_update=1,
    )


def normalize_plan(
    raw: dict,
    assistants: list[dict],
    templates: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_create: bool,
    web_allowed: bool,
    chosen: str = "",
) -> dict:
    """The dispatcher's answer for the question: ``{"decision" (see
    assistant_library.normalize_decisions), "reason", "change", "webSearch", "note"}``; raises
    ValueError when nothing usable came back."""
    decisions = lib.normalize_decisions(
        raw,
        [{"key": UNIT_KEY}],
        assistants,
        templates,
        bases,
        default_base=default_base,
        may_write=may_create,
        max_create=1,
        max_update=1,
    )
    decision = decisions.get(UNIT_KEY)
    if chosen and (decision is None or not _is_chosen(decision, chosen)):
        # the user picked the assistant: the dispatcher only decides the rest
        target = next((a for a in assistants if a["ref"] == chosen), None)
        template = lib.builtin_by_ref(chosen) if target is None else None
        if target is None and template is None:
            raise ValueError("选定的助手已经不可用")
        decision = {
            "action": "use" if target else "template",
            "target": target,
            "template": template,
            "spec": lib.spec_of({}, bases, default_base),
            "reason": "你指定的助手",
            "change": "",
            "note": "",
        }
    if decision is None:
        raise ValueError("调度模型没有给出可用的助手")
    item = raw.get("units")[0] if isinstance(raw.get("units"), list) and raw["units"] and isinstance(raw["units"][0], dict) else raw
    return {
        "decision": decision,
        "action": decision["action"],
        "reason": decision.get("reason") or clean_text(item.get("reason"), 300),
        "change": decision.get("change") or "",
        "webSearch": bool(raw.get("web_search", item.get("web_search"))) and web_allowed,
        "note": decision.get("note") or "",
    }


def _is_chosen(decision: dict, chosen: str) -> bool:
    target, template = decision.get("target"), decision.get("template")
    return bool((target and target["ref"] == chosen) or (template and template["ref"] == chosen))


def parse_json_object(text: str) -> dict:
    return lib.parse_json_object(text)


# ---------------------------------------------------------------------------------------------
# State


def new_run(
    *,
    question: str,
    planner: dict,
    user_message_id: str,
    message_id: str,
    web_allowed: bool,
    context: Optional[dict] = None,
    origin: Optional[dict] = None,
) -> dict:
    """``origin``: the chat whose message became this run (派发方式「精答」, utils/mode_dispatch.py):
    ``{"chatId", "messageId"}`` — the answer goes back there when it is done."""
    run = {
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
    if origin:
        run["origin"] = deepcopy(origin)
    return run


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


def answer_messages(run: dict, browse: bool = False) -> list[dict]:
    """What the assistant is sent. A saved assistant brings its own system prompt (applied by the
    app when it is called by its id); a temporary one or the dispatcher's fallback gets it here.
    ``browse``: the model can search the web itself (native web search) while answering."""
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
    if browse:
        content += (
            "\n\n---\nYou can also search the web yourself when "
            + ("the notes miss something you need; cite those pages as markdown links." if sources else "the question needs current facts; cite the pages as markdown links.")
        )
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
    # (model id) -> whether it searches the web itself (native web search) when the plan looks things up
    can_browse: Optional[Callable[[str], Awaitable[bool]]] = None
    browse: bool = False
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
            research["queries"] = [q for q in (found or {}).get("queries") or [] if q][:6]
            research["sources"] = sources_from_docs(found, RESEARCH_MAX_SOURCES, RESEARCH_EXCERPT_CHARS, question=run["question"])
            research["status"] = "skipped" if (found or {}).get("skipped") else "done" if research["sources"] else "empty"
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
        model = self.run["assistant"]["id"]
        messages = answer_messages(self.run, browse=self.browse)
        response = await (self.call_model(model, messages, browse=True) if self.browse else self.call_model(model, messages))
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
        if self.can_browse is not None and (run.get("plan") or {}).get("webSearch"):
            try:
                self.browse = bool(await self.can_browse(run["assistant"]["id"]))
            except Exception as exc:
                log.info("answer %s: native web search check failed: %s", self.chat_id, exc)
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
            if (run.get("plan") or {}).get("webSearch") and (run.get("research") or {}).get("status") not in {"done", "skipped"}:
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
