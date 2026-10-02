"""Team operations on the Kanban: create a team board from an approved plan, the authoritative
snapshot, the normalized event timeline (with the task status after every event, so a replay
is a plain fold), task detail, member messages, pause / resume / stop and retry."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from . import assistants
from .common import (
    ASSIGNEE_EXECUTOR,
    EXECUTOR_ASSIGNEE,
    LEAD_NAME,
    RUNNER_EXECUTORS,
    RUNNER_FAIL_PREFIXES,
    TEAM_EVENT_TASK,
    append_event,
    board_conn,
    board_slug,
    executor_of,
    is_runner,
    task_executor,
    kb,
    logger,
    member_of,
    now,
    read_team,
    redact,
    set_board_archived,
    task_key,
    update_team,
)

WORKSPACE_ROOT = Path(os.environ.get("HALO_TEAMS_WORKSPACE_ROOT", "/root/work/agent-teams"))
NATIVE_MAX_RUNTIME = int(os.environ.get("HALO_TEAMS_NATIVE_MAX_RUNTIME", "3600") or 3600)
EVENT_LIMIT_MAX = 2000
TIMELINE_HARD_CAP = 50000
USER_AUTHOR_PREFIX = "user:"
STOP_REASON = "用户停止了协作任务"
# str.startswith takes the tuple; a task whose whole runner chain is down is failed too.
RUNNER_FAIL_PREFIX = RUNNER_FAIL_PREFIXES + ("所有执行来源都不可用",)
VALID_STATUSES = {"triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"}
# Kanban event kind -> task status after it (when the payload does not say).
STATUS_BY_KIND = {
    "claimed": "running",
    "spawned": "running",
    "completed": "done",
    "gave_up": "blocked",
    "blocked": "blocked",
    "archived": "archived",
    "review_requested": "review",
    "dependency_wait": "todo",
    "descendant_invalidated": "todo",
    "scheduled": "scheduled",
    "block_loop_detected": "triage",
    "reclaimed": "ready",
    "crashed": "ready",
    "timed_out": "ready",
    "stale": "ready",
    "rate_limited": "ready",
    "spawn_failed": "ready",
    "protocol_violation": "ready",
    "reconciled": "ready",
    "unblocked": "ready",   # payload is None exactly when it went back to ready
}
ATTEMPT_END_KINDS = {"completed", "crashed", "timed_out", "stale", "reclaimed", "rate_limited",
                     "spawn_failed", "protocol_violation", "gave_up", "blocked", "review_requested"}
QUIET_KINDS = {"heartbeat", "claim_extended", "reclaim_deferred"}
_lock = threading.RLock()


class TeamError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --- create ------------------------------------------------------------------------------------

def default_workspace(slug: str) -> str:
    return str(WORKSPACE_ROOT / slug)


def _task_body(team: dict, task: dict, member: dict) -> str:
    deps = "、".join(task["depends_on"]) or "无"
    template = assistants.by_id((member.get("assistant") or {}).get("id")) if isinstance(member.get("assistant"), dict) else None
    role = ""
    if template and template.get("prompt"):
        role = (f"你的角色设定（来自 HaloWebUI 助手模板「{template['name']}」，团队里你负责的部分以下面的任务为准）：\n"
                f"{template['prompt']}\n\n")
    return (
        f"你是协作团队「{team['title']}」的成员 {member['name']}（{member['role']}）。"
        f"负责人是 {LEAD_NAME}，团队里还有：{'、'.join(m['name'] + '（' + m['role'] + '）' for m in team['members'] if m['name'] != member['name']) or '无'}。\n\n"
        + role
        + f"团队目标：\n{team['goal']}\n\n"
        f"你的任务 {task['key']}：{task['title']}\n{task['description']}\n\n"
        f"前置任务：{deps}（它们的完成摘要会出现在你的上下文「Parent task results」里）。\n"
        f"工作目录：{team['workspace']}（全队共用；只写你的任务说明里指定的文件，不要改别人的产出）。\n\n"
        "完成后调用 kanban_complete，summary 写清楚：做了什么、产出物在哪个文件、给后续成员的交接要点；"
        "result 写完整的结果（负责人会据此写最终结论；图片、截图等产出写明它在工作目录里的相对路径）。"
        "需要和别的成员沟通时用 kanban_comment 写在你的任务上。"
        "确实无法继续（缺信息、需要用户决定）时调用 kanban_block 并写明原因，不要编造结果。"
    )


def create_team(team_id: str, plan: dict, *, owner: str, chat_id: str = "", goal: str = "",
                title: str = "") -> dict:
    """Create (or return) the board for *team_id* from a validated *plan*; idempotent."""
    from .plan import validate_plan

    slug = board_slug(team_id)
    with _lock:
        existing = read_team(slug)
        if existing and existing.get("team_id") != team_id:
            raise TeamError(409, "board already belongs to another team")
        if existing and existing.get("tasks"):
            return {"board": slug, "created": False, "tasks": existing.get("keys") or {}}
        checked, errors = validate_plan(plan)
        if checked is None:
            raise TeamError(400, "计划没有通过检查：" + "；".join(errors))
        workspace = default_workspace(slug)
        Path(workspace).mkdir(parents=True, exist_ok=True)
        team_title = redact(title or checked["title"], 60) or "协作任务"
        team = {
            "team_id": team_id,
            "title": team_title,
            "lead_model": checked.get("lead_model") or {},
            "goal": redact(goal, 4000, one_line=False),
            "summary": checked.get("summary") or "",
            "owner": str(owner),
            "chat_id": str(chat_id or ""),
            "workspace": workspace,
            "lead": checked["lead"],
            "members": checked["members"],
            "max_parallel": checked["max_parallel"],
            "state": "running",
            "created_at": now(),
            "approved_at": now(),
            "tasks": {},
            "keys": {},
        }
        kb().create_board(slug, name=team_title, description=team["goal"][:200], default_workdir=workspace)
        update_team(slug, lambda rec: (rec.clear(), rec.update(team)))
        members = {m["name"]: m for m in checked["members"]}
        stamp = now()
        keys: dict[str, str] = {}
        task_map: dict[str, dict] = {}
        order = [key for layer in checked["layers"] for key in layer]
        by_key = {t["key"]: t for t in checked["tasks"]}
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {
                "action": "approved", "by": str(owner), "title": team_title,
                "members": [m["name"] for m in checked["members"]], "tasks": len(order),
            })
            for seq, key in enumerate(order, 1):
                task = by_key[key]
                member = members[task["member"]]
                chosen = member["executor"]
                # Where the member's chain stands now; with nothing available it stays on the chosen
                # runner and the bridge blocks it with the reasons when it would start.
                executor = member.get("runner") or chosen
                task_id = kb().create_task(
                    conn,
                    title=f"{key} {task['title']}",
                    body=_task_body(team, task, member),
                    assignee=EXECUTOR_ASSIGNEE[executor],
                    created_by=f"halowebui:{owner}",
                    workspace_kind="dir",
                    workspace_path=workspace,
                    tenant=team_id,
                    parents=[keys[d] for d in task["depends_on"]],
                    idempotency_key=f"{team_id}:{key}",
                    max_runtime_seconds=NATIVE_MAX_RUNTIME if executor == "hermes" else None,
                    board=slug,
                )
                keys[key] = task_id
                trail = []
                if executor != chosen:
                    trail.append({"from": chosen, "to": executor, "reason": member.get("runner_note") or "", "at": stamp,
                                  "phase": "plan"})
                task_map[task_id] = {"key": key, "member": member["name"], "seq": seq, "executor": executor,
                                     "chosen": chosen, "chosen_by": member.get("executor_source") or "auto",
                                     "trail": trail, "depends_on": task["depends_on"]}
                if trail:
                    append_event(conn, task_id, "halo_runner", {
                        "phase": "fallback", "runner": chosen, "to": executor, "reason": trail[0]["reason"],
                        "text": f"{chosen} 现在不可用，改由 {executor} 执行（{trail[0]['reason'] or '原因未知'}）"})
        update_team(slug, lambda rec: rec.update({"tasks": task_map, "keys": keys}))
    nudge_dispatch(slug)
    return {"board": slug, "created": True, "tasks": keys}


# --- dispatch nudge ------------------------------------------------------------------------------

_settings_cache: dict[str, Any] = {}


def _dispatch_kwargs() -> dict:
    if "kwargs" in _settings_cache:
        return _settings_cache["kwargs"]
    kwargs: dict[str, Any] = {}
    try:
        from dataclasses import asdict

        from gateway.kanban_watchers_dispatcher import _resolve_dispatcher_settings
        from hermes_cli.config import load_config

        cfg = (load_config() or {}).get("kanban") or {}
        settings = _resolve_dispatcher_settings(cfg if isinstance(cfg, dict) else {}, kb())
        kwargs = {k: v for k, v in asdict(settings).items() if k != "interval"}
    except Exception:
        logger.debug("halowebui-teams: dispatcher settings unavailable", exc_info=True)
        kwargs = {}
    _settings_cache["kwargs"] = kwargs
    return kwargs


def nudge_dispatch(slug: str) -> None:
    """Run one dispatcher tick for *slug* now instead of waiting for the gateway's next one
    (60 s). Same settings and the same per-board lock as the gateway's tick. Best effort;
    only in the gateway process (HERMES_HALO_TEAMS_NO_NUDGE=1 turns it off, tests use that)."""
    if os.environ.get("HERMES_HALO_TEAMS_NO_NUDGE") == "1":
        return
    team = read_team(slug)
    if not team or team.get("archived") or team.get("state") in ("stopped", "paused"):
        return
    try:
        from hermes_cli import kanban_db_dispatch as kbd

        with board_conn(slug) as conn:
            kbd.dispatch_once(conn, board=slug, **_dispatch_kwargs())
    except Exception:
        logger.warning("halowebui-teams: dispatch nudge failed for %s", slug, exc_info=True)


# --- snapshot ------------------------------------------------------------------------------------

def _json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _require_team(team_id: str, owner: Optional[str]) -> tuple[str, dict]:
    slug = board_slug(team_id)
    team = read_team(slug)
    if not team or team.get("team_id") != team_id:
        raise TeamError(404, "team not found")
    if owner is not None and str(team.get("owner")) != str(owner):
        raise TeamError(404, "team not found")
    return slug, team


def _runner_meta(run_meta: dict) -> dict:
    keep = ("runner", "runner_run_id", "runner_status", "runner_phase", "resume_at", "parent_runner_run_id",
            "question")
    return {k: run_meta[k] for k in keep if run_meta.get(k) not in (None, "")}


def _sub_status(task: Any, team: dict, last_event: Optional[dict], run_meta: dict) -> str:
    status = task.status
    if status == "blocked":
        if team.get("state") == "stopped" or (task.last_failure_error or "") == STOP_REASON:
            return "stopped"
        reason = str(((last_event or {}).get("payload") or {}).get("reason") or "")
        if run_meta.get("runner_phase") == "failed" or reason.startswith(RUNNER_FAIL_PREFIX):
            return "failed"
        if (task.block_kind or "") == "needs_input":
            return "waiting_user"
        if last_event and last_event.get("kind") == "gave_up":
            return "failed"
        return "failed" if (task.consecutive_failures or 0) else "blocked"
    if status == "running" and run_meta.get("runner_phase") in ("quota_wait", "question"):
        return {"quota_wait": "quota_wait", "question": "waiting_user"}[run_meta["runner_phase"]]
    if status == "todo":
        return "waiting_deps"
    if status == "ready":
        return "queued"
    return status


def snapshot(team_id: str, owner: Optional[str] = None) -> dict:
    slug, team = _require_team(team_id, owner)
    task_map = team.get("tasks") or {}
    tasks_out = []
    counts: dict[str, int] = {}
    with board_conn(slug) as conn:
        latest = conn.execute("SELECT COALESCE(MAX(id), 0) FROM task_events").fetchone()[0]
        links = conn.execute("SELECT parent_id, child_id FROM task_links").fetchall()
        parents: dict[str, list] = {}
        children: dict[str, list] = {}
        for row in links:
            parents.setdefault(row[1], []).append(row[0])
            children.setdefault(row[0], []).append(row[1])
        last_events = {
            row[0]: {"kind": row[1], "payload": _json(row[2])}
            for row in conn.execute(
                "SELECT task_id, kind, payload FROM task_events WHERE id IN "
                "(SELECT MAX(id) FROM task_events WHERE kind NOT IN ('heartbeat','claim_extended','commented',"
                "'halo_tool','halo_subagent','halo_comment_delivered') GROUP BY task_id)"
            ).fetchall()
        }
        for task in kb().list_tasks(conn, include_archived=True):
            if task.id not in task_map:
                continue
            entry = task_map[task.id]
            runs = kb().list_runs(conn, task.id)
            current = None
            run_meta: dict = {}
            if runs:
                last = runs[-1]
                run_meta = _json(last.metadata)
                current = {
                    "id": last.id,
                    "status": last.status,
                    "outcome": last.outcome,
                    "started_at": last.started_at,
                    "ended_at": last.ended_at,
                    **_runner_meta(run_meta),
                }
            sub = _sub_status(task, team, last_events.get(task.id), run_meta)
            counts[sub] = counts.get(sub, 0) + 1
            tasks_out.append({
                "id": task.id,
                "key": entry.get("key"),
                "seq": entry.get("seq"),
                "title": re.sub(r"^\S+\s+", "", task.title, count=1) if entry.get("key") and task.title.startswith(entry["key"] + " ") else task.title,
                "member": entry.get("member"),
                "executor": ASSIGNEE_EXECUTOR.get(task.assignee or "", "") or entry.get("executor") or "hermes",
                "chosen": entry.get("chosen") or entry.get("executor"),
                "chosen_by": entry.get("chosen_by") or "auto",
                "trail": entry.get("trail") or [],
                "status": task.status,
                "sub_status": sub,
                "parents": parents.get(task.id, []),
                "children": children.get(task.id, []),
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "attempts": len(runs),
                "current_run": current,
                "result": redact(task.result, 1200, one_line=False) if task.result else "",
                "block_reason": _block_reason(task, last_events.get(task.id)),
                "consecutive_failures": task.consecutive_failures,
            })
    tasks_out.sort(key=lambda t: (t.get("seq") or 0, t["id"]))
    phase = team_phase(team, tasks_out)
    if phase == "completed" and not team.get("completed_at"):
        _mark_completed(slug, team)
    members = []
    for m in team.get("members") or []:
        mine = [t for t in tasks_out if t["member"] == m["name"]]
        members.append({**m, "status": member_status(mine), "task_ids": [t["id"] for t in mine],
                        "current_task": next((t["id"] for t in mine if t["status"] == "running"), None)})
    return {
        "team": {
            "team_id": team_id,
            "board": slug,
            "title": team.get("title"),
            "goal": team.get("goal"),
            "summary": team.get("summary"),
            "chat_id": team.get("chat_id"),
            "workspace": team.get("workspace"),
            "state": team.get("state"),
            "archived": team.get("archived"),
            "phase": phase,
            "created_at": team.get("created_at"),
            "approved_at": team.get("approved_at"),
            "completed_at": team.get("completed_at"),
            "stopped_at": team.get("stopped_at"),
            "max_parallel": team.get("max_parallel"),
            "lead": {**(team.get("lead") or {"name": LEAD_NAME, "role": "负责人"}), "status": lead_status(phase)},
            "lead_model": team.get("lead_model") or {},
            "conclusion": _conclusion_brief(team),
        },
        "members": members,
        "tasks": tasks_out,
        "counts": counts,
        "latest_seq": int(latest or 0),
        "generated_at": now(),
    }


def _mark_completed(slug: str, team: dict) -> None:
    with _lock:
        fresh = read_team(slug) or {}
        if fresh.get("completed_at"):
            return
        stamp = now()
        update_team(slug, lambda rec: rec.update({"completed_at": stamp, "state": "completed"}))
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "completed"})
    team["completed_at"] = stamp
    team["state"] = "completed"
    # Every finished team gets its conclusion written by the lead (in the background).
    from . import conclusion

    team["conclusion"] = conclusion.start(slug, by="auto")


def _conclusion_brief(team: dict) -> dict:
    entry = team.get("conclusion") or {}
    keep = ("status", "source", "model", "model_label", "generated_at", "started_at", "chars", "error",
            "tasks_done", "tasks_total")
    return {k: entry[k] for k in keep if entry.get(k) not in (None, "")}


def _task_runner_info(team: dict, task_id: str, assignee: Optional[str]) -> dict:
    """Chosen vs actual runner of a task and why they differ (the fallback trail)."""
    entry = (team.get("tasks") or {}).get(task_id) or {}
    actual = task_executor(team, task_id, assignee)
    return {"chosen": entry.get("chosen") or actual, "chosen_by": entry.get("chosen_by") or "auto",
            "actual": actual, "trail": entry.get("trail") or []}


def _block_reason(task: Any, last_event: Optional[dict]) -> str:
    if task.status not in ("blocked", "triage"):
        return ""
    reason = ((last_event or {}).get("payload") or {}).get("reason") or task.last_failure_error or ""
    return redact(reason, 400)


def team_phase(team: dict, tasks: list[dict]) -> str:
    state = team.get("state")
    if state == "stopped":
        return "stopped"
    if tasks and all(t["status"] in ("done", "archived") for t in tasks):
        return "completed"
    if state == "paused":
        return "paused"
    if any(t["sub_status"] in ("failed", "blocked", "waiting_user") or t["status"] == "triage" for t in tasks):
        return "attention"
    return "running"


def lead_status(phase: str) -> str:
    return {"completed": "done", "stopped": "stopped", "paused": "paused", "attention": "waiting_user"}.get(phase, "coordinating")


MEMBER_PRIORITY = ("running", "quota_wait", "waiting_user", "failed", "stopped", "blocked", "queued", "waiting_deps")


def member_status(tasks: list[dict]) -> str:
    if not tasks:
        return "idle"
    subs = {t["sub_status"] for t in tasks}
    for state in MEMBER_PRIORITY:
        if state in subs:
            return state
    if all(t["status"] in ("done", "archived") for t in tasks):
        return "done"
    return "idle"


# --- timeline ------------------------------------------------------------------------------------

def _status_after(kind: str, payload: dict, previous: Optional[str]) -> Optional[str]:
    candidate = payload.get("status") if isinstance(payload, dict) else None
    if kind in ("created", "promoted", "unblocked", "changes_requested", "status") and candidate in VALID_STATUSES:
        return candidate
    if kind == "promoted":
        return "ready"
    if kind == "status":
        for key in ("to", "new_status", "new"):
            if payload.get(key) in VALID_STATUSES:
                return payload[key]
        return previous
    return STATUS_BY_KIND.get(kind, previous)


def _comment_rows(conn: Any) -> dict[str, list]:
    out: dict[str, list] = {}
    for row in conn.execute("SELECT id, task_id, author, body, created_at FROM task_comments ORDER BY id"):
        out.setdefault(row[1], []).append({"id": row[0], "author": row[2], "body": row[3], "created_at": row[4]})
    return out


def _author_kind(author: str, member: str) -> tuple[str, str]:
    author = author or ""
    if author.startswith(USER_AUTHOR_PREFIX):
        return "user", author[len(USER_AUTHOR_PREFIX):] or "用户"
    if author in ("default", *RUNNER_EXECUTORS, member) or (member and author.startswith(member)):
        return "member", member or author
    return "system", author


def timeline(team_id: str, owner: Optional[str] = None, after: int = 0, limit: int = 500) -> dict:
    """Normalized events with ``seq > after`` (oldest first) plus the fold state they imply.

    Every event carries the task's status after it (``status``/``sub_status``) when the event
    changes it, so a client reconstructs any point in time by applying events in order. The
    fold always starts from the first event so incremental pages agree with a full read.
    When the fold of the full history disagrees with the live task rows (history pruned, an
    event kind this version does not know), a ``reconciled`` notice says so explicitly."""
    slug, team = _require_team(team_id, owner)
    limit = max(1, min(int(limit or 500), EVENT_LIMIT_MAX))
    task_map = team.get("tasks") or {}
    with board_conn(slug) as conn:
        rows = conn.execute(
            "SELECT id, task_id, run_id, kind, payload, created_at FROM task_events ORDER BY id LIMIT ?",
            (TIMELINE_HARD_CAP,),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        comments = _comment_rows(conn)
        live = {row[0]: row[1] for row in conn.execute("SELECT id, status FROM tasks")}
        block_kinds = {row[0]: row[1] for row in conn.execute("SELECT id, block_kind FROM tasks")}
        children = {}
        for row in conn.execute("SELECT parent_id, child_id FROM task_links"):
            children.setdefault(row[0], []).append(row[1])
    status: dict[str, str] = {}
    sub: dict[str, str] = {}
    comment_cursor: dict[str, int] = {}
    delivered: dict[int, dict] = {}
    attempts: dict[str, int] = {}
    events: list[dict] = []
    pending_user_comments: dict[str, list] = {}
    for seq, task_id, run_id, kind, payload_raw, created_at in rows:
        payload = _json(payload_raw)
        member = member_of(team, task_id)
        key = task_key(team, task_id)
        base = {"seq": seq, "ts": created_at, "task_id": task_id if task_id != TEAM_EVENT_TASK else None,
                "key": key or None, "member": member or None, "kind": kind, "run_id": run_id}
        if task_id != TEAM_EVENT_TASK and task_id not in task_map:
            continue
        if kind in QUIET_KINDS:
            continue
        ev: Optional[dict] = None
        if kind == "commented":
            index = comment_cursor.get(task_id, 0)
            comment_cursor[task_id] = index + 1
            rows_for_task = comments.get(task_id) or []
            row = rows_for_task[index] if index < len(rows_for_task) else None
            if row is None:
                ev = {**base, "type": "message", "who": "system", "author": payload.get("author"),
                      "text": "（这条评论的内容已不在记录里）", "data": {"missing": True}}
            else:
                who, author = _author_kind(row["author"], member)
                ev = {**base, "type": "message", "who": who, "author": author,
                      "text": redact(row["body"], 2000, one_line=False), "data": {"comment_id": row["id"]}}
                if who == "user":
                    pending_user_comments.setdefault(task_id, []).append(ev)
        elif kind == "halo_comment_delivered":
            ids = [int(i) for i in payload.get("comment_ids") or [] if str(i).isdigit()]
            for cid in ids:
                delivered.setdefault(cid, {"seq": seq, "via": payload.get("via") or "steer"})
            ev = {**base, "type": "delivery", "text": _delivery_text(payload.get("via")),
                  "data": {"comment_ids": ids, "via": payload.get("via")}}
            pending_user_comments[task_id] = [c for c in pending_user_comments.get(task_id, [])
                                              if c["data"].get("comment_id") not in ids]
        elif kind == "halo_tool":
            ev = {**base, "type": "tool", "text": redact(payload.get("preview"), 300),
                  "data": {"name": payload.get("name"), "ok": payload.get("ok"), "ms": payload.get("ms"),
                           "subagent": payload.get("subagent"), "truncated": payload.get("truncated")}}
        elif kind == "halo_subagent":
            ev = {**base, "type": "subagent", "text": redact(payload.get("goal") or payload.get("summary"), 400),
                  "data": {k: payload.get(k) for k in ("phase", "id", "session", "role", "status", "tools", "ms")}}
        elif kind == "halo_runner":
            phase = payload.get("phase")
            ev = {**base, "type": "runner", "text": redact(payload.get("text"), 600, one_line=False),
                  "data": {k: payload.get(k) for k in ("phase", "runner", "runner_run_id", "resume_at", "status", "to",
                                                       "reason", "fail_kind")}}
            if phase in ("quota_wait", "question"):
                sub[task_id] = "quota_wait" if phase == "quota_wait" else "waiting_user"
                ev["status"] = status.get(task_id)
                ev["sub_status"] = sub[task_id]
            elif phase == "unavailable" and status.get(task_id) == "blocked":
                sub[task_id] = "failed"
                ev["status"] = "blocked"
                ev["sub_status"] = "failed"
            elif phase in ("continued", "answered", "launched"):
                if status.get(task_id) == "running":
                    sub[task_id] = "running"
                    ev["status"] = "running"
                    ev["sub_status"] = "running"
        elif kind == "halo_team":
            ev = {**base, "type": "team", "text": _team_text(payload), "data": payload}
        elif kind == "halo_task_stopped":
            sub[task_id] = "stopped"
            ev = {**base, "type": "status", "text": "已停止", "status": status.get(task_id, "blocked"),
                  "sub_status": "stopped", "data": {}}
        else:
            before = status.get(task_id)
            after_status = _status_after(kind, payload, before)
            if after_status is not None:
                status[task_id] = after_status
                sub[task_id] = _fold_sub(kind, after_status, payload)
            if kind in ("claimed",):
                attempts[task_id] = attempts.get(task_id, 0) + 1
                # Comments written before this attempt reached its context.
                for c in pending_user_comments.pop(task_id, []):
                    delivered.setdefault(c["data"]["comment_id"], {"seq": seq, "via": "attempt_context"})
            text = _kind_text(kind, payload, attempts.get(task_id, 0))
            etype = "attempt" if kind in ("claimed", "spawned") or (kind in ATTEMPT_END_KINDS and run_id) else "status"
            ev = {**base, "type": etype, "text": text, "status": status.get(task_id), "sub_status": sub.get(task_id),
                  "data": _public_payload(kind, payload)}
            if kind == "completed":
                summary = payload.get("summary") or payload.get("result")
                if summary:
                    events.append(ev)
                    ev = {**base, "id": f"{seq}:handoff", "type": "handoff", "text": redact(summary, 1500, one_line=False),
                          "status": status.get(task_id), "sub_status": sub.get(task_id),
                          "data": {"to": [{"task_id": c, "key": task_key(team, c), "member": member_of(team, c)}
                                          for c in children.get(task_id, [])]}}
            if kind in ("completed", "archived"):
                for c in pending_user_comments.pop(task_id, []):
                    c["data"]["undelivered"] = True
        if ev is not None:
            events.append(ev)
    for ev in events:
        ev.setdefault("id", str(ev["seq"]))
    # Delivery state of every user message (and when it changed, for replays).
    for ev in events:
        if ev["type"] == "message" and ev.get("who") == "user":
            cid = ev["data"].get("comment_id")
            info = delivered.get(cid)
            if info:
                ev["data"]["delivered_seq"] = info["seq"]
                ev["data"]["delivered_via"] = info["via"]
            else:
                ev["data"]["delivery"] = "undelivered" if ev["data"].get("undelivered") else "queued"
    mismatches = []
    for task_id in task_map:
        if task_id in live and status.get(task_id) not in (None, live[task_id]):
            mismatches.append({"task_id": task_id, "key": task_key(team, task_id), "history": status.get(task_id),
                               "live": live[task_id]})
        elif task_id in live and status.get(task_id) is None:
            mismatches.append({"task_id": task_id, "key": task_key(team, task_id), "history": None, "live": live[task_id]})
    latest = rows[-1][0] if rows else 0
    page = [ev for ev in events if ev["seq"] > after]
    has_more = len(page) > limit
    page = page[:limit]
    next_cursor = page[-1]["seq"] if has_more and page else max(after, latest)
    return {
        "events": page,
        "next_after": next_cursor,
        "has_more": has_more,
        "latest_seq": latest,
        "total_raw_events": total,
        "truncated": total > TIMELINE_HARD_CAP,
        "reconcile": mismatches,
        "block_kinds": {k: v for k, v in block_kinds.items() if v},
    }


def _fold_sub(kind: str, status: str, payload: dict) -> str:
    if status == "blocked":
        if kind == "gave_up":
            return "failed"
        if payload.get("kind") == "needs_input":
            return "waiting_user"
        if payload.get("reason") == STOP_REASON:
            return "stopped"
        if str(payload.get("reason") or "").startswith(RUNNER_FAIL_PREFIX):
            return "failed"
        return "blocked"
    return {"todo": "waiting_deps", "ready": "queued"}.get(status, status)


def _public_payload(kind: str, payload: dict) -> dict:
    keep = ("reason", "kind", "status", "assignee", "error", "outcome", "exit_code", "pid", "source_status",
            "recurrences", "limit", "failures", "attempts")
    out = {}
    for k in keep:
        if k in payload and payload[k] not in (None, ""):
            v = payload[k]
            out[k] = redact(v, 300) if isinstance(v, str) else v
    return out


KIND_TEXT = {
    "created": "任务已创建",
    "linked": "建立依赖",
    "promoted": "前置任务都已完成，可以开始",
    "claimed": "开始第 {n} 次执行",
    "spawned": "成员进程已启动",
    "completed": "完成",
    "blocked": "受阻",
    "unblocked": "解除阻塞，重新排队",
    "gave_up": "连续失败，已停止自动重试",
    "crashed": "执行进程意外退出",
    "timed_out": "执行超时",
    "stale": "长时间没有心跳，已收回",
    "reclaimed": "执行被收回",
    "rate_limited": "模型限流，稍后重试",
    "spawn_failed": "成员进程启动失败",
    "protocol_violation": "成员退出时没有报告完成",
    "dependency_wait": "等待前置任务",
    "archived": "已归档",
    "review_requested": "提交评审",
    "changes_requested": "评审要求修改",
    "claim_rejected": "前置任务未完成，不能开始",
    "respawn_guarded": "暂缓重启",
    "block_loop_detected": "反复受阻，需要人工处理",
    "edited": "更新了结果",
    "assigned": "重新分配",
}


def _kind_text(kind: str, payload: dict, attempt: int) -> str:
    if kind == "assigned" and payload.get("assignee"):
        return f"改由 {ASSIGNEE_EXECUTOR.get(payload['assignee'], payload['assignee'])} 执行"
    text = KIND_TEXT.get(kind, kind)
    if "{n}" in text:
        text = text.format(n=max(attempt, 1))
    reason = payload.get("reason") or payload.get("error")
    if kind in ("blocked", "gave_up", "crashed", "timed_out", "spawn_failed", "claim_rejected") and reason:
        text += "：" + redact(reason, 200)
    return text


def _delivery_text(via: Optional[str]) -> str:
    return {
        "steer": "补充说明已送达运行中的成员（当前工具批次结束后读到）",
        "attempt_context": "补充说明已随新的执行尝试送达",
        "runner_answer": "补充说明已通过续跑送达",
        "runner_task": "补充说明已写入 runner 的任务说明",
        "task_read": "成员读取任务时看到了补充说明",
    }.get(via or "", "补充说明已送达")


def _team_text(payload: dict) -> str:
    action = payload.get("action")
    return {
        "approved": "计划已批准，团队开始工作",
        "paused": "已暂停派发新任务（正在执行的成员继续）",
        "resumed": "已恢复派发",
        "stopped": "已停止整个协作任务",
        "completed": "所有任务已完成，负责人开始写结论",
        "concluded": "负责人写好了结论" if payload.get("source") != "assembled" else "结论已按任务记录整理（负责人模型没有回答）",
        "retry": "用户要求重试失败的任务",
    }.get(action, str(action or "团队事件"))


# --- task detail -----------------------------------------------------------------------------

def task_detail(team_id: str, task_id: str, owner: Optional[str] = None, *, log: bool = False) -> dict:
    slug, team = _require_team(team_id, owner)
    if task_id not in (team.get("tasks") or {}):
        raise TeamError(404, "task not found")
    with board_conn(slug) as conn:
        task = kb().get_task(conn, task_id)
        if task is None:
            raise TeamError(404, "task not found")
        runs = kb().list_runs(conn, task_id)
        comments = kb().list_comments(conn, task_id)
    member = member_of(team, task_id)
    attempts = []
    for index, run in enumerate(runs, 1):
        meta = _json(run.metadata)
        attempts.append({
            "n": index,
            "id": run.id,
            "status": run.status,
            "outcome": run.outcome,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "summary": redact(run.summary, 1500, one_line=False) if run.summary else "",
            "error": redact(run.error, 500) if run.error else "",
            **_runner_meta(meta),
        })
    out = {
        "task_id": task_id,
        "key": task_key(team, task_id),
        "member": member,
        "executor": task_executor(team, task_id, task.assignee),
        "title": task.title,
        "body": redact(task.body, 6000, one_line=False),
        "status": task.status,
        "result": redact(task.result, 20000, one_line=False) if task.result else "",
        "runner": _task_runner_info(team, task_id, task.assignee),
        "attempts": attempts,
        "comments": [
            {"id": c.id, "who": _author_kind(c.author, member)[0], "author": _author_kind(c.author, member)[1],
             "text": redact(c.body, 2000, one_line=False), "created_at": c.created_at}
            for c in comments
        ],
    }
    if log:
        out["log"] = worker_log(slug, team, task_id, runs, task.assignee)
    return out


def worker_log(slug: str, team: dict, task_id: str, runs: list, assignee: Optional[str] = None) -> dict:
    """Tail of the member's log, redacted and capped: the Kanban worker log for Hermes members,
    the runner's progress.log for runner members (reclaude, codex, ...)."""
    executor = task_executor(team, task_id, assignee)
    run_meta = _json(runs[-1].metadata) if runs else {}
    if run_meta.get("runner") in RUNNER_EXECUTORS:
        executor = run_meta["runner"]  # the log of the attempt shown, even if the task moved on since
    if is_runner(executor):
        from .reclaude import RUNNERS

        run_id = run_meta.get("runner_run_id")
        if not run_id or not re.match(r"^[0-9A-Za-z-]{8,80}$", str(run_id)):
            return {"text": "", "source": executor, "note": f"还没有 {executor} 运行记录"}
        path = RUNNERS[executor].runs_root / str(run_id) / "progress.log"
        try:
            data = path.read_bytes()[-16000:].decode("utf-8", "replace")
        except OSError:
            return {"text": "", "source": executor, "note": f"读不到 {executor} 进度日志"}
        return {"text": redact(data, 16000, one_line=False), "source": f"{executor} {run_id}", "truncated": True}
    try:
        text = kb().read_worker_log(task_id, tail_bytes=16000, board=slug) or ""
    except TypeError:
        text = kb().read_worker_log(task_id, tail_bytes=16000) or ""
    except Exception:
        text = ""
    return {"text": redact(text, 16000, one_line=False), "source": "kanban worker log", "truncated": len(text) >= 15000}


# --- messages / control / retry ---------------------------------------------------------------

def post_message(team_id: str, task_id: str, body: str, *, author_name: str, owner: Optional[str] = None) -> dict:
    slug, team = _require_team(team_id, owner)
    if task_id not in (team.get("tasks") or {}):
        raise TeamError(404, "task not found")
    text = (body or "").strip()
    if not text:
        raise TeamError(400, "说明不能为空")
    if len(text) > 4000:
        raise TeamError(400, "说明最多 4000 字")
    if team.get("state") == "stopped":
        raise TeamError(409, "协作任务已停止，不能再发送说明")
    with board_conn(slug) as conn:
        task = kb().get_task(conn, task_id)
        if task is None:
            raise TeamError(404, "task not found")
        if task.status in ("done", "archived"):
            raise TeamError(409, "这个任务已经结束，说明不会再被读到")
        author = USER_AUTHOR_PREFIX + (redact(author_name, 40) or "用户")
        comment_id = kb().add_comment(conn, task_id, author, text)
    executor = task_executor(team, task_id, task.assignee)
    if task.status == "running":
        expect = (f"{executor} 不能在运行中接收消息：会在它这一轮结束后续跑同一会话时送达" if is_runner(executor)
                  else "成员正在执行：会在它当前这批工具调用结束后读到（约 6 秒检查一次）")
    else:
        expect = "这个任务还没开始执行：会随它下一次开始执行时一起送达"
    return {"comment_id": comment_id, "delivery": "queued", "expect": expect}


def control(team_id: str, action: str, *, owner: Optional[str] = None, actor: str = "") -> dict:
    slug, team = _require_team(team_id, owner)
    state = team.get("state")
    if action not in ("pause", "resume", "stop"):
        raise TeamError(400, "unknown action")
    if state == "stopped":
        raise TeamError(409, "协作任务已停止")
    if state == "completed" and action != "stop":
        raise TeamError(409, "协作任务已完成")
    if action == "pause":
        if state == "paused":
            return {"state": "paused", "changed": False}
        set_board_archived(slug, True)
        update_team(slug, lambda rec: rec.update({"state": "paused", "paused_at": now()}))
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "paused", "by": actor})
        return {"state": "paused", "changed": True}
    if action == "resume":
        if state != "paused":
            return {"state": state, "changed": False}
        update_team(slug, lambda rec: rec.update({"state": "running", "paused_at": None}))
        set_board_archived(slug, False)
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "resumed", "by": actor})
        nudge_dispatch(slug)
        return {"state": "running", "changed": True}
    # stop: mark first, so neither the bridge nor a nudge starts anything from here on.
    update_team(slug, lambda rec: rec.update({"state": "stopped", "stopped_at": now()}))
    set_board_archived(slug, True)
    stopped_tasks = []
    with board_conn(slug) as conn:
        append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "stopped", "by": actor})
        for task_id in team.get("tasks") or {}:
            task = kb().get_task(conn, task_id)
            if task is None or task.status not in ("running", "ready", "review"):
                continue
            executor = task_executor(team, task_id, task.assignee)
            if task.status in ("running", "review") and executor == "hermes":
                try:
                    kb().reclaim_task(conn, task_id, reason=STOP_REASON)
                except Exception:
                    logger.warning("halowebui-teams: reclaim failed for %s", task_id, exc_info=True)
            if is_runner(executor):
                try:
                    from .bridge import stop_task_runner

                    stop_task_runner(slug, conn, task_id)
                except Exception:
                    logger.warning("halowebui-teams: runner stop failed for %s", task_id, exc_info=True)
            # No reason on the block: with a reason Kanban synthesizes an extra attempt row for a
            # task that has no open attempt (the reclaim above closed it), which would show as one
            # more execution. The reason travels on halo_task_stopped instead.
            try:
                if is_runner(executor):
                    from .reclaude import close_preserving

                    close_preserving(conn, task.current_run_id, lambda: kb().block_task(conn, task_id))
                else:
                    kb().block_task(conn, task_id)
            except Exception:
                logger.warning("halowebui-teams: block failed for %s", task_id, exc_info=True)
            append_event(conn, task_id, "halo_task_stopped", {"by": actor, "reason": STOP_REASON})
            stopped_tasks.append(task_id)
    return {"state": "stopped", "changed": True, "stopped_tasks": stopped_tasks}


def retry(team_id: str, task_id: str, *, owner: Optional[str] = None, actor: str = "") -> dict:
    slug, team = _require_team(team_id, owner)
    if task_id not in (team.get("tasks") or {}):
        raise TeamError(404, "task not found")
    if team.get("state") == "stopped":
        raise TeamError(409, "协作任务已停止，不能重试")
    with board_conn(slug) as conn:
        task = kb().get_task(conn, task_id)
        if task is None:
            raise TeamError(404, "task not found")
        if task.status not in ("blocked", "triage"):
            raise TeamError(409, "只有失败或受阻的任务可以重试")
        if task.status == "triage":
            conn.execute("UPDATE tasks SET status = 'blocked' WHERE id = ? AND status = 'triage'", (task_id,))
            conn.commit()
        from .fallback import reselect_for_retry

        try:
            reselect_for_retry(slug, conn, task_id)
        except Exception:
            logger.warning("halowebui-teams: runner reselect on retry failed for %s", task_id, exc_info=True)
        if not kb().unblock_task(conn, task_id):
            raise TeamError(409, "任务状态已变化，请刷新后再试")
        append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "retry", "task_id": task_id, "by": actor})
    nudge_dispatch(slug)
    return {"retried": True}
