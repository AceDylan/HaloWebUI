"""Moving a task to the next runner when the one it is on cannot work (see ``runners.py``).

Three moments, all recorded the same way (team record ``tasks[id].trail`` + a ``halo_runner``
event with phase ``fallback``, so the board, the feed and a replay all show "默认 cchclaude →
实际 codex，原因 …"):

* plan     — at approval the chosen runner is already down (``teams.create_team``);
* launch   — the bridge is about to start the task and the runner's check fails;
* runtime  — the runner's run failed for quota / login / network / a missing command, or it
             parked for a quota reset longer than ``runners.quota_wait_max()``.

A fallback only moves forward along the chain that starts at the task's chosen runner, and never
replaces an ordinary failure of the task itself (that stays failed; the user retries). When no
runner after the current one is available the task is blocked with every reason listed.
"""

from __future__ import annotations

from typing import Any, Optional

from . import runners
from .common import (
    EXECUTOR_ASSIGNEE,
    append_event,
    kb,
    kbc,
    logger,
    now,
    read_team,
    redact,
    task_executor,
    update_team,
)

ALL_DOWN = "所有执行来源都不可用"


def _record(slug: str, task_id: str, step: dict, executor: Optional[str]) -> None:
    def mutate(rec: dict) -> None:
        entry = (rec.setdefault("tasks", {})).setdefault(task_id, {})
        entry.setdefault("chosen", step["from"])
        entry["trail"] = list(entry.get("trail") or []) + [step]
        if executor:
            entry["executor"] = executor

    update_team(slug, mutate)


def _assign(conn: Any, task_id: str, executor: str) -> None:
    kb().assign_task(conn, task_id, EXECUTOR_ASSIGNEE[executor])
    from .teams import NATIVE_MAX_RUNTIME

    # A new runner starts fresh, like Kanban's own reassignment does for the failure streak: the
    # outage that moved the task here must not count toward the block-loop breaker (triage).
    with kbc().write_txn(conn, allow_nested=True):
        conn.execute("UPDATE tasks SET max_runtime_seconds = ?, block_kind = NULL, block_recurrences = 0 WHERE id = ?",
                     (NATIVE_MAX_RUNTIME if executor == "hermes" else None, task_id))


def reroute(slug: str, conn: Any, task_id: str, current: str, reason: str, *, phase: str,
            fail_kind: str = "", run_row: Optional[int] = None) -> Optional[str]:
    """Give *task_id* (ready or blocked, not claimed) to the next available runner after
    *current*. Returns the new executor, or None when the chain is exhausted (task blocked)."""
    team = read_team(slug) or {}
    entry = (team.get("tasks") or {}).get(task_id) or {}
    chosen = entry.get("chosen") or current
    if fail_kind and phase == "runtime":
        runners.mark_down(current, "recent_failure", reason)
    picked = runners.select_after(chosen, current)
    target = picked["executor"]
    stamp = now()
    reason = redact(reason, 300)
    if target is None:
        others = "；".join(s["reason"] for s in picked["skipped"])
        text = f"{ALL_DOWN}：{reason}" + (f"；{others}" if others else "")
        _record(slug, task_id, {"from": current, "to": None, "reason": text, "at": stamp, "phase": phase,
                                "fail_kind": fail_kind}, None)
        task = kb().get_task(conn, task_id)
        if task is not None and task.status != "blocked":
            try:
                kb().block_task(conn, task_id)  # no reason: see teams.control (no synthesized attempt)
            except Exception:
                logger.warning("halowebui-teams: could not block %s", task_id, exc_info=True)
        append_event(conn, task_id, "halo_runner", {
            "phase": "unavailable", "runner": current, "reason": text, "fail_kind": fail_kind,
            "text": redact(text, 600)}, run_id=run_row)
        return None
    _record(slug, task_id, {"from": current, "to": target, "reason": reason, "at": stamp, "phase": phase,
                            "fail_kind": fail_kind}, target)
    task = kb().get_task(conn, task_id)
    try:
        _assign(conn, task_id, target)
        if task is not None and task.status == "blocked":
            kb().unblock_task(conn, task_id)
    except Exception:
        logger.warning("halowebui-teams: reassign %s → %s failed", task_id, target, exc_info=True)
        return None
    skipped = [s["name"] for s in picked["skipped"]]
    via = f"（也跳过了 {'、'.join(skipped)}）" if skipped else ""
    label = {"launch": "启动前检查", "runtime": "运行中", "retry": "重试时", "plan": "批准时"}.get(phase, "")
    append_event(conn, task_id, "halo_runner", {
        "phase": "fallback", "runner": current, "to": target, "reason": reason, "fail_kind": fail_kind,
        "text": f"{label}发现 {current} 不可用（{reason}），改由 {target} 执行{via}"}, run_id=run_row)
    return target


def reselect_for_retry(slug: str, conn: Any, task_id: str) -> Optional[str]:
    """A retried task starts again from its chosen runner (if that is back) — the user's or the
    automatic choice is preferred over whatever it fell back to last time."""
    team = read_team(slug) or {}
    entry = (team.get("tasks") or {}).get(task_id) or {}
    task = kb().get_task(conn, task_id)
    current = task_executor(team, task_id, task.assignee if task else None)
    chosen = entry.get("chosen") or current
    picked = runners.select(chosen)
    target = picked["executor"]
    if target is None or target == current:
        return current
    if target == chosen:
        reason = f"首选的 {chosen} 已恢复"
        text = f"重试：{chosen} 已恢复，改回由 {chosen} 执行"
    else:
        reason = runners.fallback_reason(picked) or f"{chosen} 不可用"
        text = f"重试：{reason}，改由 {target} 执行"
    _record(slug, task_id, {"from": current, "to": target, "reason": redact(reason, 300), "at": now(), "phase": "retry"},
            target)
    _assign(conn, task_id, target)
    append_event(conn, task_id, "halo_runner", {
        "phase": "fallback", "runner": current, "to": target, "reason": redact(reason, 300), "text": redact(text, 600)})
    return target
