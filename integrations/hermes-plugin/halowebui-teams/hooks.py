"""Hooks that run inside a Kanban worker of a team board (``hermes chat -q "work kanban task
…"`` spawned by the gateway's dispatcher with HERMES_KANBAN_BOARD / HERMES_KANBAN_TASK /
HERMES_KANBAN_RUN_ID set). They record what the member does as events of its task, in the
same task_events sequence as the Kanban's own events:

* ``halo_tool`` — each tool call of the member (name, a short redacted preview, ok, ms), and
  of its native subagents (``subagent`` = the subagent id);
* ``halo_subagent`` — native subagent start / stop (goal, role, status, summary);
* ``halo_comment_delivered`` — a user's note written on the task reached the running member:
  Hermes' worker polls new comments (at most every 6 s) and steers them into the agent, and
  ``tools.kanban_tools._comment_watermark`` moves past the comment id when it did.

Everything here is best effort and never raises: a hook failure must not cost the member
its tool call. Outside team boards every hook returns at once.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .common import BOARD_PREFIX, append_event, board_conn, logger, redact

MAX_TOOL_EVENTS_PER_RUN = int(os.environ.get("HALO_TEAMS_MAX_TOOL_EVENTS", "400") or 400)
SKIP_TOOLS = {"kanban_heartbeat", "kanban_show", "todo"}
_state = {"tool_events": 0, "truncated": False, "delivered_upto": None}
_state_lock = threading.Lock()
_subagent_ids: dict[str, str] = {}


def _context() -> tuple[str, str, int | None] | None:
    board = os.environ.get("HERMES_KANBAN_BOARD") or ""
    task = os.environ.get("HERMES_KANBAN_TASK") or ""
    if not board.startswith(BOARD_PREFIX) or not task:
        return None
    try:
        run_id = int(os.environ.get("HERMES_KANBAN_RUN_ID") or 0) or None
    except ValueError:
        run_id = None
    return board, task, run_id


def _args_preview(tool_name: str, args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return redact(args, 160)
    if not isinstance(args, dict):
        return ""
    for key in ("command", "cmd", "path", "file_path", "url", "query", "pattern", "goal", "summary", "body",
                "code", "name"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return redact(value, 160)
    if tool_name == "delegate_task" and isinstance(args.get("tasks"), list):
        return redact(f"{len(args['tasks'])} 个子任务", 160)
    try:
        return redact(json.dumps(args, ensure_ascii=False), 160)
    except (TypeError, ValueError):
        return ""


def _write(kind: str, payload: dict) -> None:
    ctx = _context()
    if ctx is None:
        return
    board, task, run_id = ctx
    try:
        with board_conn(board) as conn:
            append_event(conn, task, kind, payload, run_id=run_id)
    except Exception:
        logger.debug("halowebui-teams: could not record %s", kind, exc_info=True)


def _check_delivery() -> None:
    """Record user notes the worker has steered into the agent since the last check."""
    ctx = _context()
    if ctx is None:
        return
    board, task, run_id = ctx
    try:
        from tools import kanban_tools
    except Exception:
        return
    mark = (getattr(kanban_tools, "_comment_watermark", None) or {}).get(task)
    if not mark:
        return
    with _state_lock:
        previous = _state["delivered_upto"]
        if previous is None:
            # The first poll only seeds the watermark (what was already in the context
            # when the attempt started); nothing was steered yet.
            _state["delivered_upto"] = mark
            return
        if mark <= previous:
            return
        _state["delivered_upto"] = mark
    own = (os.environ.get("HERMES_PROFILE") or "").strip()
    try:
        with board_conn(board) as conn:
            rows = conn.execute(
                "SELECT id, author FROM task_comments WHERE task_id = ? AND id > ? AND id <= ? ORDER BY id",
                (task, previous, mark),
            ).fetchall()
            ids = [int(r[0]) for r in rows if (r[1] or "").strip() != own and str(r[1] or "").startswith("user:")]
            if ids:
                append_event(conn, task, "halo_comment_delivered", {"comment_ids": ids, "via": "steer"}, run_id=run_id)
    except Exception:
        logger.debug("halowebui-teams: delivery check failed", exc_info=True)


def on_post_tool_call(tool_name: str = "", args: Any = None, result: Any = None, task_id: str = "",
                      duration_ms: Any = None, status: Any = None, **_: Any) -> None:
    if _context() is None:
        return
    try:
        _check_delivery()
        if tool_name in SKIP_TOOLS:
            return
        with _state_lock:
            if _state["tool_events"] >= MAX_TOOL_EVENTS_PER_RUN:
                if _state["truncated"]:
                    return
                _state["truncated"] = True
                truncated = True
            else:
                _state["tool_events"] += 1
                truncated = False
        if truncated:
            _write("halo_tool", {"name": "…", "preview": f"工具记录超过 {MAX_TOOL_EVENTS_PER_RUN} 条，后面的不再逐条记录",
                                 "truncated": True})
            return
        subagent = _subagent_ids.get(task_id) or (task_id if str(task_id).startswith("sa-") else None)
        ok = None if status in (None, "") else str(status).lower() in ("ok", "success", "completed")
        try:
            ms = int(duration_ms) if duration_ms is not None else None
        except (TypeError, ValueError):
            ms = None
        payload = {"name": str(tool_name)[:60], "preview": _args_preview(tool_name, args), "ok": ok, "ms": ms}
        if subagent:
            payload["subagent"] = subagent
        _write("halo_tool", payload)
    except Exception:
        logger.debug("halowebui-teams: post_tool_call hook failed", exc_info=True)


def on_subagent_start(child_subagent_id: str = "", child_session_id: str = "", child_role: Any = None,
                      child_goal: Any = None, **_: Any) -> None:
    if _context() is None:
        return
    try:
        if child_session_id and child_subagent_id:
            _subagent_ids[str(child_session_id)] = str(child_subagent_id)
        _write("halo_subagent", {"phase": "start", "id": str(child_subagent_id or "")[:40],
                                 "session": str(child_session_id or "")[:80], "role": redact(child_role, 40),
                                 "goal": redact(child_goal, 400)})
    except Exception:
        logger.debug("halowebui-teams: subagent_start hook failed", exc_info=True)


def on_subagent_stop(child_session_id: str = "", child_role: Any = None, child_summary: Any = None,
                     child_status: Any = None, tool_call_history: Any = None, duration_ms: Any = None,
                     **_: Any) -> None:
    if _context() is None:
        return
    try:
        tools = len(tool_call_history) if isinstance(tool_call_history, list) else None
        _write("halo_subagent", {"phase": "stop", "id": _subagent_ids.get(str(child_session_id or ""), ""),
                                 "session": str(child_session_id or "")[:80], "role": redact(child_role, 40),
                                 "status": redact(child_status, 20), "summary": redact(child_summary, 600),
                                 "tools": tools, "ms": duration_ms if isinstance(duration_ms, int) else None})
    except Exception:
        logger.debug("halowebui-teams: subagent_stop hook failed", exc_info=True)
