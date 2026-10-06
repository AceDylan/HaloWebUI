"""Hooks that run inside a Kanban worker of a team board (``hermes chat -q "work kanban task
…"`` spawned by the gateway's dispatcher with HERMES_KANBAN_BOARD / HERMES_KANBAN_TASK /
HERMES_KANBAN_RUN_ID set). They record what the member does as events of its task, in the
same task_events sequence as the Kanban's own events:

* ``halo_tool`` — each tool call of the member (name, a short redacted preview, ok, ms), and
  of its native subagents (``subagent`` = the subagent id);
* ``halo_subagent`` — native subagent start / stop (goal, role, status, summary);
* every image the member generates (``image_generate`` → gpt-image) is copied from Hermes' media
  cache (cleared after a day) into the workspace as ``images/<task key>-<n>.<ext>`` with its prompt
  in ``images/<task key>-<n>.prompt.md`` — the conclusion shows the images and their prompts;
* ``halo_comment_delivered`` — a user's note written on the task reached the running member:
  Hermes' worker polls new comments (at most every 6 s) and steers them into the agent, and
  ``tools.kanban_tools._comment_watermark`` moves past the comment id when it did.

Everything here is best effort and never raises: a hook failure must not cost the member
its tool call. Outside team boards every hook returns at once.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .common import BOARD_PREFIX, append_event, board_conn, logger, read_team, redact, task_key

MAX_TOOL_EVENTS_PER_RUN = int(os.environ.get("HALO_TEAMS_MAX_TOOL_EVENTS", "400") or 400)
# Kanban tools that already leave their own events (complete → handoff, comment → message, …).
SKIP_TOOLS = {"kanban_heartbeat", "kanban_show", "kanban_complete", "kanban_block", "kanban_comment",
              "kanban_request_review", "todo"}
_state = {"tool_events": 0, "truncated": False, "delivered_upto": None, "read_upto": 0, "reported": set()}
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
    for key in ("command", "cmd", "path", "file_path", "url", "query", "pattern", "goal", "summary", "body", "prompt",
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


IMAGE_TOOLS = {"image_generate", "generate_image", "edit_image"}
IMAGES_DIR = "images"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def keep_image(workspace: str, key: str, args: Any, result: Any, *, who: str = "", folder: str = IMAGES_DIR) -> str:
    """Copy a generated image (``image_generate``'s result) out of Hermes' media cache into
    ``<workspace>/<folder>/<key>-<n>.<ext>`` (``images/`` by default) with its prompt next to it
    (``.prompt.md``). Returns the path relative to the workspace, or "" when there is nothing to keep."""
    data = _as_dict(result)
    source = str(data.get("image") or data.get("path") or "")
    if data.get("success") is False or not source or source.startswith(("http://", "https://", "data:")):
        return ""
    src = Path(source)
    if not src.is_file() or src.suffix.lower() not in IMAGE_SUFFIXES:
        return ""
    if not workspace or not Path(workspace).is_dir():
        return ""
    rel_folder = folder
    folder = Path(workspace) / rel_folder
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while any((folder / f"{key}-{n}{ext}").exists() for ext in IMAGE_SUFFIXES):
        n += 1
    dest = folder / f"{key}-{n}{src.suffix.lower()}"
    shutil.copy2(src, dest)
    params = _as_dict(args)
    prompt = str(params.get("prompt") or "").strip()
    facts = ([f"- {who}"] if who else []) + [
        f"- 模型：{data.get('model') or 'gpt-image'}" + (f"（{data['provider']}）" if data.get("provider") else ""),
        f"- 画幅：{params.get('aspect_ratio') or data.get('aspect_ratio') or '—'}"
        + (f" · 实际 {data['actual_size']}" if data.get("actual_size") else ""),
        f"- 生成于：{time.strftime('%Y-%m-%d %H:%M')}"]
    dest.with_suffix(".prompt.md").write_text(
        f"# {dest.name} 的生图提示词\n\n" + "\n".join(facts) + "\n\n## 提示词\n\n````\n"
        + redact(prompt, 20000, one_line=False) + "\n````\n", encoding="utf-8")
    return f"{rel_folder}/{dest.name}"


def save_image(board: str, task: str, args: Any, result: Any) -> str:
    """A member's image: ``images/T3-1.png`` (its task key), see ``keep_image``."""
    team = read_team(board) or {}
    member = ((team.get("tasks") or {}).get(task) or {}).get("member") or "—"
    key = task_key(team, task) or "image"
    return keep_image(team.get("workspace") or "", key, args, result, who=f"任务：{key}（成员 {member}）")


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
    if mark is None:  # 0 is a real watermark: the first poll saw no comments yet
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
            ids = [int(r[0]) for r in rows if (r[1] or "").strip() != own and str(r[1] or "").startswith("user:")
                   and int(r[0]) not in _state["reported"]]
            if ids:
                _state["reported"].update(ids)
                append_event(conn, task, "halo_comment_delivered", {"comment_ids": ids, "via": "steer"}, run_id=run_id)
    except Exception:
        logger.debug("halowebui-teams: delivery check failed", exc_info=True)


def _record_read() -> None:
    """kanban_show returns the task's comments: user notes that existed when the member read its
    task reached it that way (the usual path for a note written just after the member started)."""
    ctx = _context()
    if ctx is None:
        return
    board, task, run_id = ctx
    try:
        with board_conn(board) as conn:
            rows = conn.execute(
                "SELECT id FROM task_comments WHERE task_id = ? AND id > ? AND author LIKE 'user:%' ORDER BY id",
                (task, int(_state["read_upto"] or 0)),
            ).fetchall()
            ids = [int(r[0]) for r in rows if int(r[0]) not in _state["reported"]]
            if rows:
                _state["read_upto"] = max(int(r[0]) for r in rows)
            if ids:
                _state["reported"].update(ids)
                append_event(conn, task, "halo_comment_delivered", {"comment_ids": ids, "via": "task_read"}, run_id=run_id)
    except Exception:
        logger.debug("halowebui-teams: read check failed", exc_info=True)


def on_post_tool_call(tool_name: str = "", args: Any = None, result: Any = None, task_id: str = "",
                      duration_ms: Any = None, status: Any = None, **_: Any) -> None:
    if _context() is None:
        return
    try:
        if tool_name == "kanban_show" and not str(task_id or "").startswith("sa-"):
            _record_read()
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
        if tool_name in IMAGE_TOOLS:
            ctx = _context()
            try:
                saved = save_image(ctx[0], ctx[1], args, result) if ctx else ""
            except Exception:  # noqa: BLE001 — never cost the member its tool call
                logger.warning("halowebui-teams: could not keep a generated image", exc_info=True)
                saved = ""
            if saved:
                payload["saved"] = saved
                payload["preview"] = redact(f"已保存 {saved} · {payload['preview']}", 160)
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
