"""助手库: the assistants every workbench shares (精答, 协作台, 讨论台, the chat).

An assistant is a workspace model with a base model and a system prompt (a row of the ``model``
table with ``base_model_id``). Its library record lives in ``meta.assistant``:

- ``source``: who made it — manual / answer / team / discuss, or ``builtin:<id>`` when it was
  saved from a built-in template;
- ``domain``: its field, a short phrase;
- ``version``: +1 whenever its name, description or system prompt changes (by hand too);
- ``revisions``: what it was before each change (the last ``MAX_REVISIONS``), with the change's
  source and the run that made it, so a run's upgrade can be undone;
- ``archived``: put away (the row is also inactive, so nothing offers or picks it).

Built-in templates (``src/lib/data/agents-zh.json``, copied next to this module in the image)
are read-only: a workbench uses one as it is, or saves an upgraded copy as the user's own.

``meta.hidden`` only keeps an assistant out of the model menus; the workbenches still pick it.

A dispatcher model staffs a run's units (one question, each member's duty, each discussion seat)
from a shortlist of the library: it uses an assistant, upgrades one, or creates one. The rules
for what may be written (permissions, how many per run, one version per assistant per run,
compare-and-set on the version) live here, so the three workbenches behave alike.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from open_webui.env import GLOBAL_LOG_LEVEL, SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", GLOBAL_LOG_LEVEL))

LIB_KEY = "assistant"
LEGACY_KEY = "answer_desk"
PIN_META_KEY = "assistant_pins"

SOURCES = ("manual", "answer", "team", "discuss")
SOURCE_TAGS = {"answer": "精答", "team": "协作台", "discuss": "讨论台"}
SOURCE_LABELS = {"manual": "手动", "answer": "精答", "team": "协作台", "discuss": "讨论台", "builtin": "内置模板"}

MAX_REVISIONS = 20
MAX_CREATE_PER_RUN = 2
MAX_UPDATE_PER_RUN = 2
SHORTLIST_USER = 20
SHORTLIST_BUILTIN = 15
PROMPT_EXCERPT_CHARS = 300
NAME_MAX_CHARS = 24
DOMAIN_MAX_CHARS = 24
DESCRIPTION_MAX_CHARS = 160
SYSTEM_PROMPT_MAX_CHARS = 8000
SYSTEM_PROMPT_MIN_CHARS = 40

# use: as it is (a library assistant or a template) · update: upgraded, then used · create: new and
# saved · temporary: written for this run only (no right to save, or over the per-run limit) ·
# generic: no specialist, the unit's plain role
ACTIONS = ("use", "update", "create")


class LibraryError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def clean_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------------------------
# Built-in templates


_templates_cache: dict[str, Any] = {"path": None, "mtime": None, "items": [], "by_id": {}}


def templates_file() -> Optional[Path]:
    env = os.environ.get("HALO_ASSISTANT_TEMPLATES_FILE")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    bundled = here.parent.parent / "assistant_templates.json"
    if bundled.exists():
        return bundled
    for parent in here.parents:
        candidate = parent / "src" / "lib" / "data" / "agents-zh.json"
        if candidate.exists():
            return candidate
    return None


def builtin_templates() -> list[dict]:
    """[{ref, id, name, emoji, description, groups, prompt, kind}] (cached by mtime)."""
    path = templates_file()
    if path is None:
        return []
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _templates_cache["path"] == str(path) and _templates_cache["mtime"] == mtime:
        return _templates_cache["items"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("assistant templates %s unreadable", path)
        return []
    items = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("prompt"):
            continue
        template_id = str(entry["id"]).strip()
        items.append(
            {
                "ref": f"builtin:{template_id}",
                "id": template_id,
                "name": clean_text(entry.get("name"), 40),
                "emoji": clean_text(entry.get("emoji"), 8),
                "description": re.sub(r"\s+", " ", str(entry.get("description") or "")).strip()[:DESCRIPTION_MAX_CHARS],
                "groups": [str(g) for g in (entry.get("group") or []) if g],
                "prompt": str(entry.get("prompt") or "").replace("\r\n", "\n").strip(),
                "kind": entry.get("team_kind") or None,
            }
        )
    _templates_cache.update(path=str(path), mtime=mtime, items=items, by_id={t["id"]: t for t in items})
    return items


def builtin_by_ref(ref: Any) -> Optional[dict]:
    key = str(ref or "").strip()
    if key.startswith("builtin:"):
        key = key[len("builtin:") :]
    builtin_templates()
    return _templates_cache["by_id"].get(key)


# ---------------------------------------------------------------------------------------------
# The library record in meta.assistant


def _dump(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def lib_meta(meta: Any) -> dict:
    """``meta.assistant`` with defaults; an assistant 精答 made before the library existed
    (``meta.answer_desk``) reads as one made by 精答."""
    meta = _dump(meta)
    lib = dict(meta.get(LIB_KEY) or {}) if isinstance(meta.get(LIB_KEY), dict) else {}
    legacy = meta.get(LEGACY_KEY) if isinstance(meta.get(LEGACY_KEY), dict) else None
    if legacy and not lib:
        old = [r for r in (legacy.get("revisions") or []) if isinstance(r, dict)]
        lib = {
            "source": "answer",
            "emoji": legacy.get("emoji") or "",
            "createdFor": legacy.get("createdFor"),
            "version": len(old) + 1,
            "revisions": [
                {
                    "version": i + 1,
                    "at": r.get("at"),
                    "source": "answer",
                    "runRef": f"answer:{r['chatId']}" if r.get("chatId") else None,
                    "change": r.get("change") or "",
                    "system": r.get("system") or "",
                    "description": r.get("description") or "",
                }
                for i, r in enumerate(old)
            ],
        }
    source = str(lib.get("source") or "manual")
    if source not in SOURCES and not source.startswith("builtin:"):
        source = "manual"
    try:
        version = max(1, int(lib.get("version") or 1))
    except (TypeError, ValueError):
        version = 1
    return {
        **lib,
        "source": source,
        "domain": clean_text(lib.get("domain"), DOMAIN_MAX_CHARS),
        "emoji": clean_text(lib.get("emoji"), 8),
        "version": version,
        "revisions": [r for r in (lib.get("revisions") or []) if isinstance(r, dict)][-MAX_REVISIONS:],
        "archived": bool(lib.get("archived")),
    }


def with_lib_meta(meta: Any, lib: dict) -> dict:
    out = _dump(meta)
    out[LIB_KEY] = lib
    out.pop(LEGACY_KEY, None)
    return out


def source_kind(source: str) -> str:
    return "builtin" if str(source or "").startswith("builtin:") else str(source or "manual")


# ---------------------------------------------------------------------------------------------
# Which models are assistants a workbench may pick, which are bases


def _is_agent_or_image(model: dict) -> bool:
    from open_webui.utils.hermes_agent import is_hermes_agent_model
    from open_webui.utils.task import is_dedicated_image_generation_model

    info = model.get("info") or {}
    base = str(info.get("base_model_id") or "")
    return (
        model.get("owned_by") == "arena"
        or is_hermes_agent_model(model)
        or (bool(base) and is_hermes_agent_model(base))
        or is_dedicated_image_generation_model(model)
    )


def selection_id(model: dict) -> str:
    return str(model.get("selection_id") or model.get("id") or "").strip()


def _owner(info: dict):
    return type("Owner", (), {"user_id": info.get("user_id"), "access_control": info.get("access_control")})()


def _offered_to(info: dict, user: Any) -> bool:
    """Whether a workbench may pick this assistant for ``user``: their own, or shared with them.
    An admin can read every user's private assistants, but no workbench picks those for them."""
    from open_webui.utils.access_control import has_access

    if info.get("user_id") == getattr(user, "id", None):
        return True
    access = info.get("access_control")
    if access is None:
        return True
    return has_access(getattr(user, "id", None), "read", access)


def model_entry(model: dict, user: Any) -> dict:
    """An assistant as the workbenches see it."""
    from open_webui.utils.access_control import can_write_resource

    info = model.get("info") or {}
    meta = info.get("meta") or {}
    lib = lib_meta(meta)
    ref_id = selection_id(model)
    return {
        "ref": f"model:{ref_id}",
        "id": ref_id,
        "name": str(model.get("name") or ref_id),
        "description": clean_text(meta.get("description"), DESCRIPTION_MAX_CHARS),
        "domain": lib["domain"],
        "emoji": lib["emoji"],
        "prompt": str((info.get("params") or {}).get("system") or ""),
        "base": str(info.get("base_model_id") or ""),
        "owned": info.get("user_id") == getattr(user, "id", None),
        "editable": can_write_resource(user, _owner(info)),
        "hidden": bool(meta.get("hidden")),
        "source": lib["source"],
        "version": lib["version"],
        "updatedAt": info.get("updated_at"),
    }


def library(models_map: dict, user: Any) -> tuple[list[dict], list[dict]]:
    """(assistants, bases) a workbench may pick for ``user``. Hidden assistants are in (hiding is
    for the model menus only); archived and inactive ones are not (inactive models are not in the
    map at all). A base model an admin hid is not offered as a base."""
    seen: set[str] = set()
    assistants: list[dict] = []
    bases: list[dict] = []
    for model in models_map.values():
        if not isinstance(model, dict):
            continue
        ref = selection_id(model)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if _is_agent_or_image(model):
            continue
        info = model.get("info") or {}
        meta = info.get("meta") or {}
        if info.get("base_model_id"):
            if info.get("is_active") is False or lib_meta(meta)["archived"] or not _offered_to(info, user):
                continue
            assistants.append(model_entry(model, user))
        elif not meta.get("hidden"):
            bases.append({"id": ref, "name": str(model.get("name") or ref)})
    assistants.sort(key=lambda a: -(a.get("updatedAt") or 0))
    return assistants, bases


def base_name(bases: list[dict], ref: str) -> str:
    entry = next((b for b in bases if b["id"] == ref), None)
    if entry:
        return entry["name"]
    return ref.rsplit("::", 1)[-1] if ref else ""


def favorites_of(user: Any) -> list[str]:
    settings = getattr(user, "settings", None)
    ui = _dump(settings).get("ui") if settings is not None else None
    values = (ui or {}).get("assistantFavorites") if isinstance(ui, dict) else None
    return [str(v) for v in values if isinstance(v, str)] if isinstance(values, list) else []


# ---------------------------------------------------------------------------------------------
# Shortlist: a few dozen candidates for the dispatcher (781 templates do not fit a prompt)


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]{1,}")
_CJK_RE = re.compile(r"[㐀-鿿]+")


def _grams(text: str) -> set[str]:
    text = str(text or "").lower()
    grams = set(_WORD_RE.findall(text))
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            grams.add(run)
        grams.update(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def _score(query: set[str], *fields: tuple[str, int]) -> int:
    score = 0
    for text, weight in fields:
        score += weight * len(query & _grams(text))
    return score


def shortlist(
    text: str,
    assistants: list[dict],
    *,
    favorites: Iterable[str] = (),
    user_limit: int = SHORTLIST_USER,
    builtin_limit: int = SHORTLIST_BUILTIN,
    must: Iterable[str] = (),
) -> tuple[list[dict], list[dict]]:
    """(assistants, templates) worth showing the dispatcher for ``text``: favourites and refs in
    ``must`` always, then the best matches by name, field, description (and template groups)."""
    query = _grams(text)
    pinned = set(favorites) | set(must)

    def rank(entry: dict) -> int:
        return _score(query, (entry.get("name", ""), 4), (entry.get("domain", ""), 3), (entry.get("description", ""), 1), (" ".join(entry.get("groups") or []), 1))

    if len(assistants) <= user_limit:
        picked_assistants = list(assistants)
    else:
        scored = sorted(assistants, key=lambda a: (a["ref"] not in pinned, -rank(a), -(a.get("updatedAt") or 0)))
        picked_assistants = scored[:user_limit]

    templates = builtin_templates()
    scored_templates = [(t["ref"] in pinned, rank(t), t) for t in templates]
    chosen = [t for keep, score, t in scored_templates if keep]
    others = sorted((x for x in scored_templates if not x[0] and x[1] > 0), key=lambda x: -x[1])
    chosen += [t for _, _, t in others[: max(0, builtin_limit - len(chosen))]]
    return picked_assistants, chosen


def catalog_view(assistants: list[dict], templates: list[dict], bases: list[dict]) -> list[dict]:
    def excerpt(text: str) -> str:
        return text[:PROMPT_EXCERPT_CHARS] + ("…" if len(text) > PROMPT_EXCERPT_CHARS else "")

    view = [
        {
            "ref": a["ref"],
            "name": a["name"],
            "domain": a.get("domain") or "",
            "description": a.get("description") or "",
            "editable": bool(a.get("editable")),
            "base_model": base_name(bases, a.get("base") or ""),
            "system_prompt": excerpt(a.get("prompt") or ""),
        }
        for a in assistants
    ]
    view += [
        {
            "ref": t["ref"],
            "name": t["name"],
            "description": t.get("description") or "",
            "builtin": True,
            "system_prompt": excerpt(t.get("prompt") or ""),
        }
        for t in templates
    ]
    return view


# ---------------------------------------------------------------------------------------------
# The dispatcher


DISPATCH_SYSTEM = """You staff work in HaloWebUI with the user's assistants. An assistant is a base model plus a system prompt that makes it a specialist; the "library" lists the user's own ("ref": "model:…", "editable" says whether it may be rewritten) and built-in templates ("ref": "builtin:…", read-only). For every unit you are given (one question, a team member's duty or a discussion seat), pick:

- "use": a library assistant or a built-in template whose speciality clearly covers the unit. Prefer this whenever it is true.
- "update": a library assistant with "editable": true is the right field but lacks a capability this KIND of work needs (a skill, a method, an output format, a quality bar). Rewrite its whole system prompt: keep everything it already does and add the missing capability in general terms. Never widen an assistant into another field (a Python tutor does not become a database architect): that is a different assistant. A built-in template cannot be updated in place: to improve one, "create" a new assistant from it and set "from" to its ref.
- "create": nothing in the library or the templates covers the unit's FIELD. Design a new, reusable specialist for that field (never for this one unit only). A unit's duty in this run is not a reason to create: give it the closest assistant or template of its field and leave the specifics to the run. Name a new assistant after a lasting field (软件架构师), never after this run's topic (迁移节奏师).
{generic_rule}
Rules:
- One-off requirements (this question's details, this run's duty, a stance such as 正方/反方) belong to the run, never to a system prompt. Only what will serve later work of the same kind goes into an assistant.
- Several units may share one assistant. When several units need the same upgrade, give the same "ref" and the same complete "system_prompt" for each.
- At most {max_create} "create" and {max_update} "update" in this reply.
- A new or rewritten system prompt (in the user's language) states: the role and its expertise; how it works through a task (clarify the goal, method, checks for mistakes); the output format; the quality bar (precise, concrete, says what it does not know, no filler). 150-500 words. A name is 2-8 Chinese characters (or 1-3 English words for an English user), naming the speciality, without "助手" unless needed; "domain" is its field in 2-6 characters.

Reply with one JSON object and nothing else:
{{"units": [{{"key": "<the unit's key>", "action": "use" | "update" | "create"{generic_action}, "ref": "<library ref, for use / update>", "reason": "<one sentence in the user's language: why this assistant suits the unit>", "change": "<update / create: one short sentence, what it can now do>", "assistant": {{"name": "...", "emoji": "<one emoji>", "domain": "...", "description": "<one sentence>", "system_prompt": "...", "base_model": "<a name from base_models>", "from": "<builtin ref it grew from, if any>"}}}}]{extra_fields}}}
"assistant" is required for create; for update give "system_prompt" (the complete new prompt) and optionally "description"; omit it for use."""


def dispatch_messages(
    units: list[dict],
    assistants: list[dict],
    templates: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_write: bool,
    lang_hint: str,
    task: str,
    allow_generic: bool = False,
    rules: Iterable[str] = (),
    extra_fields: str = "",
    background: str = "",
    max_create: int = MAX_CREATE_PER_RUN,
    max_update: int = MAX_UPDATE_PER_RUN,
) -> list[dict]:
    system = DISPATCH_SYSTEM.format(
        generic_rule='- "generic": no specialist is needed for this unit; it keeps its plain role.\n' if allow_generic else "",
        generic_action=' | "generic"' if allow_generic else "",
        max_create=max_create,
        max_update=max_update,
        extra_fields=extra_fields,
    )
    notes = list(rules)
    if not may_write:
        notes.append('This user may not save assistants: "update" and "create" are used for this run only, not saved. Still prefer "use".')
    payload = {
        "task": task,
        **({"background": background[:3000]} if background else {}),
        "language": lang_hint,
        "units": units,
        "library": catalog_view(assistants, templates, bases),
        "base_models": [b["name"] for b in bases],
        "default_base_model": base_name(bases, default_base),
    }
    content = json.dumps(payload, ensure_ascii=False, indent=1)
    if notes:
        content += "\n\n" + "\n".join(notes)
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def parse_json_object(text: str) -> dict:
    from open_webui.utils.discussion_room import strip_think

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


def spec_of(raw: Any, bases: list[dict], default_base: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "name": clean_text(raw.get("name"), NAME_MAX_CHARS),
        "emoji": EMOJI_RE.sub("", clean_text(raw.get("emoji"), 8))[:4] or "✦",
        "domain": clean_text(raw.get("domain"), DOMAIN_MAX_CHARS),
        "description": clean_text(raw.get("description"), DESCRIPTION_MAX_CHARS),
        "system": clean_text(raw.get("system_prompt") or raw.get("system"), SYSTEM_PROMPT_MAX_CHARS),
        "base": _match_base(bases, raw.get("base_model"), default_base),
        "from": str(raw.get("from") or "").strip() if str(raw.get("from") or "").startswith("builtin:") else "",
    }


def _find(ref: Any, assistants: list[dict]) -> Optional[dict]:
    key = str(ref or "").strip()
    if not key:
        return None
    bare = key[len("model:") :] if key.startswith("model:") else key
    by_ref = next((a for a in assistants if a["ref"] == key or a["id"] == bare), None)
    if by_ref:
        return by_ref
    return next((a for a in assistants if a["name"].strip().lower() == key.lower()), None)


def normalize_decisions(
    raw: dict,
    units: list[dict],
    assistants: list[dict],
    templates: list[dict],
    bases: list[dict],
    *,
    default_base: str,
    may_write: bool,
    allow_generic: bool = False,
    max_create: int = MAX_CREATE_PER_RUN,
    max_update: int = MAX_UPDATE_PER_RUN,
) -> dict[str, dict]:
    """The dispatcher's answer made safe, per unit key: ``{action: use | template | update |
    create | temporary | generic, target (library entry), template, spec, reason, change, note}``.
    Units the reply leaves out or gets wrong are missing from the result (the caller falls back
    to the unit's own role). Enforces: permissions, one version per assistant, per-run limits,
    no duplicate names."""
    items = raw.get("units") if isinstance(raw.get("units"), list) else []
    keys = [str(u["key"]) for u in units]
    by_key: dict[str, dict] = {}
    for item in items:
        if isinstance(item, dict) and str(item.get("key") or "") in keys and str(item.get("key")) not in by_key:
            by_key[str(item["key"])] = item
    if not by_key and len(units) == 1 and (raw.get("action") or raw.get("assistant_id")):
        # a single-unit reply in the flat shape
        by_key[keys[0]] = {**raw, "ref": raw.get("ref") or raw.get("assistant_id")}

    out: dict[str, dict] = {}
    updates: dict[str, dict] = {}  # target id → the spec written once for the run
    creates: dict[str, dict] = {}  # lower name → the spec created once for the run
    template_by_ref = {t["ref"]: t for t in templates}

    for key in keys:
        item = by_key.get(key)
        if item is None:
            continue
        action = str(item.get("action") or "").strip().lower()
        ref = str(item.get("ref") or item.get("assistant_id") or "").strip()
        spec = spec_of(item.get("assistant"), bases, default_base)
        if not spec["system"] and item.get("system_prompt"):
            spec["system"] = clean_text(item.get("system_prompt"), SYSTEM_PROMPT_MAX_CHARS)
        decision = {
            "action": action,
            "target": None,
            "template": None,
            "spec": spec,
            "reason": clean_text(item.get("reason"), 300),
            "change": clean_text(item.get("change"), 300),
            "note": "",
        }
        if action == "generic":
            if allow_generic:
                out[key] = decision
            continue
        if action not in ACTIONS:
            continue
        template = template_by_ref.get(ref) or (builtin_by_ref(ref) if ref.startswith("builtin:") else None)
        target = None if template else _find(ref, assistants)

        if action == "update":
            if template is not None:
                # a template is read-only: an upgrade of one is a new assistant grown from it
                action = "create"
                spec["from"] = template["ref"]
                if not spec["name"]:
                    spec["name"] = clean_text(template["name"], NAME_MAX_CHARS)
                if not spec["emoji"] or spec["emoji"] == "✦":
                    spec["emoji"] = template.get("emoji") or "✦"
            elif target is None:
                action = "create"
            elif len(spec["system"]) < SYSTEM_PROMPT_MIN_CHARS:
                decision["note"] = "调度模型没写出新的设定，直接用原助手"
                action = "use"
            elif not target["editable"] or not may_write:
                decision["note"] = f"没有修改「{target['name']}」的权限，本次临时补充设定"
                action = "temporary"
                spec.update({"name": target["name"], "emoji": target.get("emoji") or spec["emoji"], "base": target.get("base") or spec["base"]})
            elif target["id"] in updates:
                spec = updates[target["id"]]
                decision["note"] = "与本次其他席位的升级合并为一个版本"
            elif len(updates) >= max_update:
                decision["note"] = f"本次已升级 {max_update} 个助手，这个直接使用"
                action = "use"
            else:
                updates[target["id"]] = spec
        if action == "use":
            if template is not None:
                action = "template"
            elif target is None:
                if spec["system"] and spec["name"]:
                    action = "create"
                else:
                    continue
        if action == "create":
            if len(spec["system"]) < SYSTEM_PROMPT_MIN_CHARS or not spec["name"]:
                continue
            lower = spec["name"].strip().lower()
            same = next((a for a in assistants if a["name"].strip().lower() == lower), None)
            same_template = next((t for t in templates if t["name"].strip().lower() == lower), None)
            if same is not None:
                action, target = "use", same
                decision["note"] = f"已有同名助手「{same['name']}」，直接用它"
            elif same_template is not None and not spec["from"]:
                action, template = "template", same_template
                decision["note"] = f"内置模板里已有「{same_template['name']}」，直接用它"
            elif lower in creates:
                spec = creates[lower]
                decision["note"] = "与本次其他席位共用同一个新助手"
            elif not spec["base"]:
                continue
            elif not may_write:
                action = "temporary"
            elif len(creates) >= max_create:
                action = "temporary"
                decision["note"] = f"本次已新建 {max_create} 个助手，这个只在本次使用"
            else:
                creates[lower] = spec
        decision.update(action=action, target=target, template=template, spec=spec)
        out[key] = decision
    return out


# ---------------------------------------------------------------------------------------------
# Writes: a new assistant, an upgrade, a restore, a run's undo


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


def _form(row: Any, *, meta: dict, params: dict, name: Optional[str] = None, is_active: Optional[bool] = None):
    from open_webui.models.models import ModelForm

    return ModelForm(
        id=row.id,
        base_model_id=row.base_model_id,
        name=name if name is not None else row.name,
        meta=meta,
        params=params,
        access_control=row.access_control,
        is_active=row.is_active if is_active is None else is_active,
    )


def create_assistant(user: Any, spec: dict, *, source: str, run_ref: str, question: str = "") -> Any:
    """A new assistant, private to the user, hidden from the model menus. Returns the row."""
    from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models

    model_id = f"asst-{uuid.uuid4().hex[:10]}"
    tags = [{"name": SOURCE_TAGS[source]}] if source in SOURCE_TAGS else []
    lib = {
        "source": f"builtin:{spec['from'][len('builtin:'):]}" if spec.get("from") else source,
        "domain": spec.get("domain") or "",
        "emoji": spec.get("emoji") or "",
        "version": 1,
        "revisions": [],
        "createdFor": {"runRef": run_ref, "by": source, "question": clean_text(question, 200), "at": now_ms()},
    }
    meta = {
        "profile_image_url": emoji_avatar(spec.get("emoji") or "", model_id),
        "description": spec.get("description") or None,
        "tags": tags,
        "hidden": True,
        LIB_KEY: lib,
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
        raise LibraryError(500, "新建助手失败")
    return row


def _revision(lib: dict, row: Any, params: dict, meta: dict, *, source: str, run_ref: Optional[str], change: str) -> dict:
    return {
        "version": lib["version"],
        "at": now_ms(),
        "source": source,
        "runRef": run_ref,
        "change": change,
        "name": row.name,
        "system": str(params.get("system") or ""),
        "description": meta.get("description") or "",
    }


def upgrade_assistant(
    user: Any,
    model_id: str,
    spec: dict,
    *,
    expected_version: Optional[int],
    source: str,
    run_ref: str,
    change: str,
) -> tuple[Any, int]:
    """Rewrite an assistant's system prompt (and description) as a new version. Refuses (409) when
    the assistant moved past ``expected_version`` since the dispatcher read it. Returns (row,
    new version)."""
    from open_webui.models.models import Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None or not can_write_resource(user, row):
        raise LibraryError(403, "没有修改这个助手的权限")
    params = row.params.model_dump()
    meta = row.meta.model_dump()
    lib = lib_meta(meta)
    if expected_version is not None and lib["version"] != expected_version:
        raise LibraryError(409, "这个助手刚被改过")
    revisions = [*lib["revisions"], _revision(lib, row, params, meta, source=source, run_ref=run_ref, change=change)]
    lib.update(version=lib["version"] + 1, revisions=revisions[-MAX_REVISIONS:])
    if spec.get("domain") and not lib.get("domain"):
        lib["domain"] = spec["domain"]
    meta = with_lib_meta(meta, lib)
    if spec.get("description"):
        meta["description"] = spec["description"]
    params["system"] = spec["system"]
    updated = Models.update_model_by_id(model_id, _form(row, meta=meta, params=params))
    if updated is None:
        raise LibraryError(500, "更新助手失败")
    return updated, lib["version"]


def undo_run(user: Any, model_id: str, run_ref: str, *, after_system: Optional[str] = None) -> Any:
    """Undo the upgrade ``run_ref`` made, if the assistant is still as that run left it (its
    version, and its system prompt when ``after_system`` is given)."""
    from open_webui.models.models import Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None:
        raise LibraryError(404, "这个助手已经不在了")
    if not can_write_resource(user, row):
        raise LibraryError(403, "没有修改这个助手的权限")
    params = row.params.model_dump()
    meta = row.meta.model_dump()
    lib = lib_meta(meta)
    index = next((i for i in range(len(lib["revisions"]) - 1, -1, -1) if lib["revisions"][i].get("runRef") == run_ref), None)
    if index is None:
        raise LibraryError(409, "找不到这次升级前的设定")
    before = lib["revisions"][index]
    if lib["version"] != int(before.get("version") or 0) + 1 or (
        after_system is not None and str(params.get("system") or "") != after_system
    ):
        raise LibraryError(409, "这个助手之后又改过，不能自动撤销；可以在助手库的版本记录里对比后手动恢复")
    revisions = [*lib["revisions"], _revision(lib, row, params, meta, source="undo", run_ref=run_ref, change="撤销这次升级")]
    lib.update(version=lib["version"] + 1, revisions=revisions[-MAX_REVISIONS:])
    meta = with_lib_meta(meta, lib)
    meta["description"] = before.get("description") or None
    params["system"] = before.get("system") or ""
    updated = Models.update_model_by_id(model_id, _form(row, meta=meta, params=params))
    if updated is None:
        raise LibraryError(500, "撤销失败")
    return updated


def restore_version(user: Any, model_id: str, version: int) -> Any:
    """Make an earlier version the current one (as a new version)."""
    from open_webui.models.models import Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None:
        raise LibraryError(404, "这个助手已经不在了")
    if not can_write_resource(user, row):
        raise LibraryError(403, "没有修改这个助手的权限")
    params = row.params.model_dump()
    meta = row.meta.model_dump()
    lib = lib_meta(meta)
    old = next((r for r in lib["revisions"] if int(r.get("version") or 0) == int(version)), None)
    if old is None:
        raise LibraryError(404, "这个版本已经不在记录里")
    revisions = [*lib["revisions"], _revision(lib, row, params, meta, source="manual", run_ref=None, change=f"恢复到第 {version} 版")]
    lib.update(version=lib["version"] + 1, revisions=revisions[-MAX_REVISIONS:])
    meta = with_lib_meta(meta, lib)
    meta["description"] = old.get("description") or None
    params["system"] = old.get("system") or ""
    updated = Models.update_model_by_id(model_id, _form(row, meta=meta, params=params, name=old.get("name") or row.name))
    if updated is None:
        raise LibraryError(500, "恢复失败")
    return updated


def set_archived(user: Any, model_id: str, archived: bool) -> Any:
    from open_webui.models.models import Models
    from open_webui.utils.access_control import can_write_resource

    row = Models.get_model_by_id(model_id)
    if row is None or not row.base_model_id:
        raise LibraryError(404, "这个助手不存在")
    if not can_write_resource(user, row):
        raise LibraryError(403, "没有修改这个助手的权限")
    meta = row.meta.model_dump()
    lib = lib_meta(meta)
    lib["archived"] = bool(archived)
    updated = Models.update_model_by_id(
        model_id, _form(row, meta=with_lib_meta(meta, lib), params=row.params.model_dump(), is_active=not archived)
    )
    if updated is None:
        raise LibraryError(500, "保存失败")
    return updated


def note_manual_edit(row: Any, form: Any) -> Any:
    """A hand edit through the workspace editor: a changed name, description or system prompt is a
    new version (the old one kept in the revisions). Returns the form to save."""
    if row is None or not getattr(row, "base_model_id", None):
        return form
    old_params = row.params.model_dump()
    old_meta = row.meta.model_dump()
    new_params = _dump(form.params)
    new_meta = _dump(form.meta)
    lib_old = lib_meta(old_meta)
    # the editor sends the meta it loaded: the library record is the server's, not the page's
    lib = dict(lib_old)
    incoming = new_meta.get(LIB_KEY) if isinstance(new_meta.get(LIB_KEY), dict) else {}
    if "domain" in incoming:
        lib["domain"] = clean_text(incoming.get("domain"), DOMAIN_MAX_CHARS)
    changed = (
        str(old_params.get("system") or "") != str(new_params.get("system") or "")
        or (row.name or "") != (form.name or "")
        or (old_meta.get("description") or "") != (new_meta.get("description") or "")
    )
    if changed:
        revisions = [*lib["revisions"], _revision(lib_old, row, old_params, old_meta, source="manual", run_ref=None, change="手动编辑")]
        lib.update(version=lib_old["version"] + 1, revisions=revisions[-MAX_REVISIONS:])
    if LEGACY_KEY in old_meta or LIB_KEY in old_meta or changed or incoming:
        new_meta = with_lib_meta(new_meta, lib)
        form.meta = type(form.meta)(**new_meta) if form.meta is not None and hasattr(form.meta, "model_dump") else new_meta
    return form


# ---------------------------------------------------------------------------------------------
# Carrying a run's decisions out


def snapshot(*, ref: str, id: str, name: str, emoji: str, version: Optional[int], system: str, base: str, source: str, description: str = "") -> dict:
    return {
        "ref": ref,
        "id": id,
        "name": name,
        "emoji": emoji,
        "version": version,
        "system": system,
        "base": base,
        "source": source,
        "description": description,
    }


def carry_out(
    user: Any,
    decisions: dict[str, dict],
    *,
    source: str,
    run_ref: str,
    question: str,
    may_write: bool,
) -> dict[str, dict]:
    """Write what ``decisions`` (from :func:`normalize_decisions`) call for — once per assistant,
    whatever number of units share it — and return per unit key the assistant used:
    ``{action, saved, reason, change, note, ...snapshot}``. ``saved`` means it is a library
    assistant (called by its id); otherwise ``system`` is applied to the unit's own model."""
    written: dict[int, dict] = {}  # id(spec) → what was written for it
    out: dict[str, dict] = {}
    for key, decision in decisions.items():
        action, target, template, spec = decision["action"], decision["target"], decision["template"], decision["spec"]
        common = {"reason": decision.get("reason") or "", "change": decision.get("change") or "", "note": decision.get("note") or ""}
        if action == "generic":
            out[key] = {"action": "generic", "saved": False, **common}
            continue
        if action == "use":
            out[key] = {
                "action": "use",
                "saved": True,
                **common,
                **snapshot(ref=target["ref"], id=target["id"], name=target["name"], emoji=target.get("emoji") or "", version=target.get("version"), system=target.get("prompt") or "", base=target.get("base") or "", source=target.get("source") or "manual", description=target.get("description") or ""),
            }
            continue
        if action == "template":
            out[key] = {
                "action": "template",
                "saved": False,
                **common,
                **snapshot(ref=template["ref"], id=template["ref"], name=template["name"], emoji=template.get("emoji") or "", version=None, system=template.get("prompt") or "", base=spec.get("base") or "", source="builtin", description=template.get("description") or ""),
            }
            continue
        if action == "temporary":
            out[key] = {
                "action": "temporary",
                "saved": False,
                **common,
                **snapshot(ref="", id="", name=spec["name"], emoji=spec.get("emoji") or "", version=None, system=spec["system"], base=spec.get("base") or "", source=source, description=spec.get("description") or ""),
            }
            continue
        done = written.get(id(spec))
        try:
            if done is None and action == "update":
                row, version = upgrade_assistant(user, target["id"], spec, expected_version=target.get("version"), source=source, run_ref=run_ref, change=decision.get("change") or "")
                done = {
                    "action": "update",
                    "saved": True,
                    "before": {"system": target.get("prompt") or "", "description": target.get("description") or "", "version": target.get("version")},
                    **snapshot(ref=target["ref"], id=row.id, name=row.name, emoji=target.get("emoji") or "", version=version, system=spec["system"], base=row.base_model_id or "", source=target.get("source") or "manual", description=(row.meta.description or "")),
                }
            elif done is None:
                row = create_assistant(user, spec, source=source, run_ref=run_ref, question=question)
                done = {
                    "action": "create",
                    "saved": True,
                    **snapshot(ref=f"model:{row.id}", id=row.id, name=row.name, emoji=spec.get("emoji") or "", version=1, system=spec["system"], base=spec["base"], source=lib_meta(row.meta)["source"], description=spec.get("description") or ""),
                }
            written[id(spec)] = done
            out[key] = {**done, **common}
        except LibraryError as exc:
            # moved on, gone or not ours any more: the unit still runs, with this run's version
            log.info("assistant %s for %s not written (%s): used for this run only", action, run_ref, exc.detail)
            if action == "update":
                out[key] = {
                    "action": "temporary",
                    "saved": False,
                    **common,
                    "note": f"{exc.detail}，本次临时补充设定",
                    **snapshot(ref=target["ref"], id="", name=target["name"], emoji=target.get("emoji") or "", version=None, system=spec["system"], base=target.get("base") or "", source=target.get("source") or "manual"),
                }
            else:
                out[key] = {
                    "action": "temporary",
                    "saved": False,
                    **common,
                    "note": exc.detail,
                    **snapshot(ref="", id="", name=spec["name"], emoji=spec.get("emoji") or "", version=None, system=spec["system"], base=spec.get("base") or "", source=source),
                }
    return out


def public_choice(choice: Optional[dict]) -> Optional[dict]:
    """What a page shows of a unit's assistant (the full system prompt only on request)."""
    if not isinstance(choice, dict):
        return None
    out = {k: v for k, v in choice.items() if k not in {"before", "system"}}
    out["hasSystem"] = bool(choice.get("system"))
    return out


# ---------------------------------------------------------------------------------------------
# A chat keeps the version of an assistant it started with


def pin_chat(chat_id: str, model_id: str, choice: dict) -> None:
    from open_webui.models.chats import Chats

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return
    pins = dict((chat.meta or {}).get(PIN_META_KEY) or {})
    pins[model_id] = {
        "version": choice.get("version"),
        "system": choice.get("system") or "",
        "name": choice.get("name") or "",
        "base": choice.get("base") or "",
        "at": now_ms(),
    }
    Chats.set_chat_meta_value_by_id(chat_id, PIN_META_KEY, pins)


def pinned_system(chat_id: Optional[str], model_row: Any, user_id: Optional[str] = None) -> Optional[str]:
    """The system prompt a chat should use for an assistant: the version it started with. The
    first time an assistant answers in a chat its current version is pinned (and ``None`` is
    returned: the model's own prompt applies). Only the chat's owner's requests read or pin."""
    if not chat_id or str(chat_id).startswith("local:") or model_row is None or not getattr(model_row, "base_model_id", None):
        return None
    from open_webui.models.chats import Chats

    try:
        chat = Chats.get_chat_by_id(chat_id)
    except Exception:
        return None
    if chat is None or (user_id is not None and chat.user_id != user_id):
        return None
    lib = lib_meta(model_row.meta)
    pins = (chat.meta or {}).get(PIN_META_KEY) or {}
    pin = pins.get(model_row.id) if isinstance(pins, dict) else None
    if not isinstance(pin, dict):
        system = str((model_row.params.model_dump() if model_row.params else {}).get("system") or "")
        pin_chat(chat_id, model_row.id, {"version": lib["version"], "system": system, "name": model_row.name, "base": model_row.base_model_id})
        return None
    if pin.get("version") == lib["version"]:
        return None
    return str(pin.get("system") or "")
