"""
Progress of background runners (reclaude / codex / agy) launched from a chat.

A runner started with ``--detach`` works for many minutes after the hermes
turn that launched it has ended. Its reporter (``runner-progress.py`` on the
hermes host) posts ``mode=progress`` notifications - at the start, every few
minutes, at the end - and the chat shows "reclaude · 已运行 12 分钟 · 第 198
步 · 最近…" without asking hermes (a "查看进度" turn cost about two minutes).

In memory only: a restart forgets them until the next report arrives.
"""

import time
from typing import Optional

from open_webui.models.chats import Chats

# A reporter posts at least every few minutes; after this long without one the
# runner (or its reporter) is gone and the entry would only mislead.
PROGRESS_STALE_SECONDS = 20 * 60
TERMINAL_RUNNER_STATUSES = {"finished", "success", "failed", "error", "cancelled", "stopped"}
ACTIVITY_MAX_CHARS = 300

_PROGRESS: dict[str, dict] = {}


def _prune(now: float) -> None:
    for run_id, entry in list(_PROGRESS.items()):
        if now - float(entry.get("updated_at") or 0) > PROGRESS_STALE_SECONDS:
            _PROGRESS.pop(run_id, None)


def record_runner_progress(
    *,
    chat_id: str,
    run_id: str,
    agent: str = "",
    status: str = "running",
    started_at: Optional[float] = None,
    step: Optional[int] = None,
    last_activity: str = "",
    now: Optional[float] = None,
) -> Optional[dict]:
    """Store one progress report; returns the entry (None once the run ended
    or when the chat is unknown)."""
    now = time.time() if now is None else now
    _prune(now)
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    status = str(status or "running").strip().lower()
    if status in TERMINAL_RUNNER_STATUSES:
        _PROGRESS.pop(run_id, None)
        return None
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return None
    previous = _PROGRESS.get(run_id, {})
    entry = {
        "run_id": run_id,
        "chat_id": chat_id,
        "user_id": chat.user_id,
        "agent": str(agent or previous.get("agent") or "runner")[:32],
        "status": status[:32],
        "started_at": float(started_at) if started_at else previous.get("started_at"),
        "step": int(step) if step is not None else previous.get("step"),
        "last_activity": " ".join(str(last_activity or "").split())[:ACTIVITY_MAX_CHARS]
        or previous.get("last_activity", ""),
        "updated_at": now,
    }
    _PROGRESS[run_id] = entry
    return entry


def clear_runner_progress(run_id: Optional[str]) -> None:
    """The run's report arrived: it is no longer running."""
    if run_id:
        _PROGRESS.pop(str(run_id), None)


def list_runner_progress(user_id: str, now: Optional[float] = None) -> list:
    now = time.time() if now is None else now
    _prune(now)
    runs = [
        {
            **{key: value for key, value in entry.items() if key != "user_id"},
            "title": Chats.get_chat_title_by_id(entry["chat_id"]),
        }
        for entry in _PROGRESS.values()
        if entry.get("user_id") == user_id
    ]
    runs.sort(key=lambda entry: entry.get("started_at") or entry.get("updated_at") or 0)
    return runs
