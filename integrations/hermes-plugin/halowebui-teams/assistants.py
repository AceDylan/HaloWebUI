"""The roles a lead can staff a team with: HaloWebUI's own assistant templates.

HaloWebUI ships its assistant templates in ``src/lib/data/agents-zh.json`` (the 助手模板 page
and the chat's assistant picker read the same file). The templates in the group 「协作」 carry a
``team_kind`` (code / ui / complex / research / writing) and are the catalog the lead picks
members from, so a team's 后端开发 is the same 开发工程师 the user can chat with — no second
role system. A member the catalog does not cover keeps the lead's own role text and is shown as
a custom role.

The file is found next to this plugin (the plugin directory is a symlink into the HaloWebUI
checkout) or at ``HALO_TEAMS_ASSISTANTS_FILE``; without it the lead simply has no catalog.

The user's own assistants (HaloWebUI's 助手库) come with each plan request instead — this process
cannot read HaloWebUI's model table; see ``library.py``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .common import logger

COLLAB_GROUP = "协作"
PROMPT_LIMIT = 1800
_cache: dict[str, Any] = {"path": None, "mtime": None, "items": [], "all": [], "by_id": {}}

# Chat-style template lines that make no sense as a team member's role.
_CHAT_ONLY = re.compile(
    r"(我的第一个(请求|要求|问题|任务)是[:：]?.*$)|(请在这个角色下(为我|帮助我)?[^。\n]*[。.]?)|(整个对话(和|及)?指令都?应?以中文(进行|提供)[。.]?)",
    re.M,
)


def templates_file() -> Optional[Path]:
    env = os.environ.get("HALO_TEAMS_ASSISTANTS_FILE")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "src" / "lib" / "data" / "agents-zh.json"
        if candidate.exists():
            return candidate
    return None


def clean_prompt(text: str) -> str:
    value = _CHAT_ONLY.sub("", str(text or "").replace("\r\n", "\n"))
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if len(value) > PROMPT_LIMIT:
        value = value[: PROMPT_LIMIT - 1].rstrip() + "…"
    return value


def _load() -> None:
    """Read the template file once per change (by mtime): every template, and the 「协作」 ones."""
    from .runners import normalize_kind

    path = templates_file()
    if path is None:
        _cache.update(path=None, mtime=None, items=[], all=[], by_id={})
        return
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache.update(path=None, mtime=None, items=[], all=[], by_id={})
        return
    if _cache["path"] == str(path) and _cache["mtime"] == mtime:
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("halowebui-teams: assistant templates %s unreadable", path)
        _cache.update(path=None, mtime=None, items=[], all=[], by_id={})
        return
    items, every = [], []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        collab = COLLAB_GROUP in (entry.get("group") or [])
        item = {
            "id": str(entry.get("id")),
            "name": str(entry.get("name") or "").strip(),
            "emoji": str(entry.get("emoji") or "").strip(),
            "description": re.sub(r"\s+", " ", str(entry.get("description") or "")).strip()[:120],
            # only the 「协作」 templates carry a team_kind; another template's kind comes from the member
            "kind": normalize_kind(entry.get("team_kind")) or ("code" if collab else ""),
            "prompt": clean_prompt(entry.get("prompt") or ""),
        }
        every.append(item)
        if collab:
            items.append(item)
    _cache.update(path=str(path), mtime=mtime, items=items, all=every, by_id={t["id"]: t for t in every})


def catalog() -> list[dict]:
    """The 「协作」 templates: [{id, name, emoji, description, kind, prompt}] (cached by mtime)."""
    _load()
    return _cache["items"]


def template(ref: Any) -> Optional[dict]:
    """Any built-in template (not only 「协作」) by ``builtin:<id>`` or its bare id."""
    key = str(ref or "").strip()
    if key.startswith("builtin:"):
        key = key[len("builtin:"):]
    if not key:
        return None
    _load()
    return _cache["by_id"].get(key)


def by_id(template_id: Any) -> Optional[dict]:
    key = str(template_id or "").strip()
    if not key:
        return None
    for item in catalog():
        if item["id"] == key:
            return item
    return None


def by_name(name: Any) -> Optional[dict]:
    key = str(name or "").strip()
    if not key:
        return None
    for item in catalog():
        if item["name"] == key:
            return item
    return None


def resolve(value: Any) -> Optional[dict]:
    """A template from what the lead wrote: its id, ``builtin:<id>``, its name, or {"id": ..}. The
    「协作」 catalog first, then any built-in template by id."""
    if isinstance(value, dict):
        return resolve(value.get("ref") or value.get("id")) or by_name(value.get("name"))
    key = str(value or "").strip()
    if key.startswith("builtin:"):
        key = key[len("builtin:"):]
    return by_id(key) or by_name(key) or template(key)


def catalog_text() -> str:
    """The catalog as the lead sees it: one line per template."""
    lines = [f"- {item['id']}：{item['name']}（{item['kind']}）— {item['description']}" for item in catalog()]
    return "\n".join(lines)


def public(item: Optional[dict]) -> Optional[dict]:
    if not item:
        return None
    return {"id": item["id"], "ref": f"builtin:{item['id']}", "name": item["name"], "emoji": item["emoji"],
            "kind": item["kind"], "description": item["description"]}
