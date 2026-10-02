"""Shared helpers: team boards on the Hermes Kanban, the team record in board.json, redaction.

One HaloWebUI collaboration task ("team") is one Kanban board ``halo-<id>``. The Kanban
tables stay the only record of tasks, dependencies, attempts, comments and events; the
board's ``board.json`` carries the team record under ``halowebui_team`` (members, which
member owns which task, executor per member, owner, chat, workspace, paused/stopped).
Kanban keeps unknown board.json keys when it rewrites the file (``write_board_metadata``
merges over what is there), and only this plugin writes this key.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("halowebui_teams")

BOARD_PREFIX = "halo-"
META_KEY = "halowebui_team"
# task_events.task_id for team-level events (approve, pause, stop): the column is NOT NULL
# without a foreign key, and no task id starts with "_" (Kanban ids are t_<hex>).
TEAM_EVENT_TASK = "_team"
EXECUTORS = ("hermes", "reclaude")
# Kanban assignee per executor. "default" is the Hermes profile the gateway's dispatcher
# spawns; "reclaude" is not a profile, so the dispatcher leaves it to an external claimer
# (skipped_nonspawnable) and the bridge in this plugin runs it.
EXECUTOR_ASSIGNEE = {"hermes": "default", "reclaude": "reclaude"}
ASSIGNEE_EXECUTOR = {v: k for k, v in EXECUTOR_ASSIGNEE.items()}
LEAD_NAME = "team-lead"
_TEAM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,63}$")
_meta_lock = threading.RLock()


def kb():
    from hermes_cli import kanban_db

    return kanban_db


def kbc():
    from hermes_cli import kanban_db_connect

    return kanban_db_connect


def now() -> int:
    return int(time.time())


def valid_team_id(team_id: Any) -> bool:
    return isinstance(team_id, str) and bool(_TEAM_ID_RE.match(team_id))


def board_slug(team_id: str) -> str:
    """``halo-`` + the first 16 alphanumerics of the HaloWebUI team id (a uuid)."""
    compact = re.sub(r"[^a-z0-9]", "", str(team_id).lower())[:16]
    if len(compact) < 8:
        raise ValueError("team id too short")
    return BOARD_PREFIX + compact


def is_team_board(slug: Optional[str]) -> bool:
    return bool(slug) and str(slug).startswith(BOARD_PREFIX)


def team_boards() -> list[str]:
    """Slugs of every team board on disk (archived = paused/stopped included)."""
    try:
        root = kb().boards_root()
    except Exception:
        return []
    if not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and child.name.startswith(BOARD_PREFIX) and (child / "board.json").exists()
    )


def read_board_raw(slug: str) -> dict:
    path = kb().board_metadata_path(slug)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def read_team(slug: str) -> Optional[dict]:
    """The team record of *slug* plus ``board`` and ``archived``; None when *slug* has none."""
    raw = read_board_raw(slug)
    team = raw.get(META_KEY)
    if not isinstance(team, dict):
        return None
    out = dict(team)
    out["board"] = slug
    out["archived"] = bool(raw.get("archived"))
    return out


def update_team(slug: str, mutate: Callable[[dict], None]) -> dict:
    """Read-modify-write the team record atomically (tmp file + rename) under one lock."""
    with _meta_lock:
        path = kb().board_metadata_path(slug)
        raw = read_board_raw(slug)
        team = raw.get(META_KEY)
        if not isinstance(team, dict):
            team = {}
        mutate(team)
        raw[META_KEY] = team
        raw.setdefault("created_at", now())
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return dict(team)


def set_board_archived(slug: str, archived: bool) -> None:
    """Archived boards are skipped by the gateway's dispatcher: that is 'pause dispatch'."""
    with _meta_lock:
        kb().write_board_metadata(slug, archived=archived)


@contextmanager
def board_conn(slug: str) -> Iterator[Any]:
    conn = kbc().connect(board=slug)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def append_event(conn: Any, task_id: str, kind: str, payload: Optional[dict] = None,
                 run_id: Optional[int] = None) -> None:
    """One task_events row in its own transaction (nested-safe)."""
    with kbc().write_txn(conn, allow_nested=True):
        kb()._append_event(conn, task_id, kind, payload, run_id=run_id)


def redact(text: Any, limit: int = 500, *, one_line: bool = True) -> str:
    """Hermes' secret redaction, then whitespace folding and a length cap."""
    value = "" if text is None else str(text)
    try:
        from agent.redact import redact_sensitive_text

        value = redact_sensitive_text(value)
    except Exception:
        pass
    if one_line:
        value = re.sub(r"\s+", " ", value).strip()
    else:
        value = re.sub(r"[ \t]+\n", "\n", value).strip()
    if limit and len(value) > limit:
        value = value[: max(0, limit - 1)].rstrip() + "…"
    return value


def member_of(team: Optional[dict], task_id: str) -> str:
    if not team:
        return ""
    entry = (team.get("tasks") or {}).get(task_id) or {}
    return str(entry.get("member") or "")


def task_key(team: Optional[dict], task_id: str) -> str:
    if not team:
        return ""
    entry = (team.get("tasks") or {}).get(task_id) or {}
    return str(entry.get("key") or "")


def executor_of(team: Optional[dict], member: str) -> str:
    for entry in (team or {}).get("members") or []:
        if entry.get("name") == member:
            return str(entry.get("executor") or "hermes")
    return "hermes"
