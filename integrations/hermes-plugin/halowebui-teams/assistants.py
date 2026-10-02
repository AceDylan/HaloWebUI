"""The roles a lead can staff a team with: HaloWebUI's own assistant templates.

HaloWebUI ships its assistant templates in ``src/lib/data/agents-zh.json`` (the 助手模板 page
and the chat's assistant picker read the same file). The templates in the group 「协作」 carry a
``team_kind`` (code / ui / complex / research / writing) and are the catalog the lead picks
members from, so a team's 后端开发 is the same 开发工程师 the user can chat with — no second
role system. A member the catalog does not cover keeps the lead's own role text and is shown as
a custom role.

The file is found next to this plugin (the plugin directory is a symlink into the HaloWebUI
checkout) or at ``HALO_TEAMS_ASSISTANTS_FILE``; without it the lead simply has no catalog.
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
_cache: dict[str, Any] = {"path": None, "mtime": None, "items": []}

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


def catalog() -> list[dict]:
    """The 「协作」 templates: [{id, name, emoji, description, kind, prompt}] (cached by mtime)."""
    from .runners import normalize_kind

    path = templates_file()
    if path is None:
        return []
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _cache["path"] == str(path) and _cache["mtime"] == mtime:
        return _cache["items"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("halowebui-teams: assistant templates %s unreadable", path)
        return []
    items = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or COLLAB_GROUP not in (entry.get("group") or []):
            continue
        items.append({
            "id": str(entry.get("id")),
            "name": str(entry.get("name") or "").strip(),
            "emoji": str(entry.get("emoji") or "").strip(),
            "description": re.sub(r"\s+", " ", str(entry.get("description") or "")).strip()[:120],
            "kind": normalize_kind(entry.get("team_kind")) or "code",
            "prompt": clean_prompt(entry.get("prompt") or ""),
        })
    _cache.update(path=str(path), mtime=mtime, items=items)
    return items


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
    """A template from what the lead wrote: its id, its name, or {"id": ..}."""
    if isinstance(value, dict):
        return by_id(value.get("id")) or by_name(value.get("name"))
    return by_id(value) or by_name(value)


def catalog_text() -> str:
    """The catalog as the lead sees it: one line per template."""
    lines = [f"- {item['id']}：{item['name']}（{item['kind']}）— {item['description']}" for item in catalog()]
    return "\n".join(lines)


def public(item: Optional[dict]) -> Optional[dict]:
    if not item:
        return None
    return {"id": item["id"], "name": item["name"], "emoji": item["emoji"], "kind": item["kind"],
            "description": item["description"]}
