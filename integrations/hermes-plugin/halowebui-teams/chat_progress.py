"""Progress views shared by Telegram and QQ. The web stage and the local Kanban are the sources."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from typing import Optional

from . import link, progress, teams
from .common import board_slug, now, read_team, redact, team_boards, valid_team_id
from .notify import duration, plain

LIVE_MOVING_STAGES = ("running", "paused", "concluding", "checking", "illustrating", "deploying")
ACTIVE_STAGES = ("planning", "approval", "starting", "attention", *LIVE_MOVING_STAGES)
TERMINAL_STAGES = ("done", "stopped", "plan_failed", "start_failed", "cancelled")
DEPLOY_TERMINAL = ("succeeded", "failed", "skipped")
POST_RUN_STAGES = ("concluding", "checking", "illustrating", "deploying")
PROGRESS_WORDS = {"进度", "状态", "详情", "progress", "status", "detail"}
QQ_SHORTCUT_WORDS = {"协作进度", "团队进度", "工作流进度", "看协作进度"}
CARD_MAX_CHARS = 3200
AUTO_DEPLOY_GRACE = 60

_SUMMARY_STAGES = {"plan_ready": "approval", "plan_failed": "plan_failed", "start_failed": "start_failed",
                   "cancelled": "cancelled", "completed": "done"}
_STAGE_LABELS = {**progress.STAGE_LABELS, "plan_failed": "计划没做成", "start_failed": "启动失败", "cancelled": "已取消"}
_STAGE_STEPS = {"plan": "计划", "approve": "批准", "run": "执行", "conclude": "结论", "check": "验收",
                "deploy": "发布"}
_TASK_STATES = {"done": ("✅", ""), "archived": ("✅", ""), "running": ("🔵", "执行中"),
                "review": ("🔵", "审查中"), "queued": ("⏳", "排队中"), "waiting_deps": ("⏳", "待执行"),
                "waiting_user": ("❓", "等你回复"), "quota_wait": ("⏸", "等待额度"), "failed": ("⚠️", "失败"),
                "blocked": ("⚠️", "受阻"), "triage": ("⚠️", "需处理"), "stopped": ("⏹", "已停止")}
_STEP_ICONS = {"done": "✓", "active": "●", "running": "●", "pending": "○", "failed": "✗", "skipped": "—"}
_DEPLOY_LABELS = {"succeeded": "发布完成", "failed": "发布失败", "skipped": "已跳过发布"}
_SELECTOR = re.compile(r"([\w]+)(?:[\s:：]+([0-9a-f][0-9a-f-]*))?", re.IGNORECASE)
_TAG = re.compile(r"</?[A-Za-z][\w-]*(?:\s+[^<>]*)?/?>")
_DONE = ("done", "archived")


def parse_progress_query(args: str) -> Optional[str]:
    """A command keyword optionally followed by a list number or UUID prefix."""
    match = _SELECTOR.fullmatch(args.strip().rstrip(":：").rstrip().lower())
    if match and match[1] in PROGRESS_WORDS:
        return match[2] or ""
    return None


def is_work_progress_query(args: str) -> bool:
    first = re.split(r"[\s:：]+", args.strip().lower(), maxsplit=1)[0]
    return first in PROGRESS_WORDS


def expects_auto_deploy(board: dict) -> bool:
    project = board.get("project") or {}
    acceptance = (board.get("conclusion") or {}).get("acceptance") or {}
    return bool(board.get("auto_deploy") and project.get("branch") and not project.get("discarded_at")
                and acceptance.get("verdict") != "unmet"
                and (project.get("deploy") or {}).get("status") not in DEPLOY_TERMINAL)


def _make_view(team: dict, stage: dict, tasks: list[dict], *, status: str, board: Optional[dict] = None) -> dict:
    board = board or {}
    team_id = str(team.get("team_id") or team.get("id") or board.get("team_id") or "")
    phase = team.get("phase") or ""
    key = stage.get("key") or _SUMMARY_STAGES.get(status, status)
    if key == "running" and phase:
        key = _SUMMARY_STAGES.get(phase, phase)
    deploy = (board.get("project") or {}).get("deploy") or team.get("deploy")
    deploy_status = (deploy or {}).get("status")
    if key == "done" and deploy_status == "running":
        key = "deploying"
        stage = {**stage, "label": None, "now": next(
            (s.get("detail") or s.get("label") for s in deploy.get("steps") or [] if s.get("status") == "running"), None)}
    conclusion = team.get("conclusion") or board.get("conclusion") or {}
    completed_at = team.get("completed_at") or team.get("finished_at")
    settled_at = max(completed_at or 0, conclusion.get("generated_at") or (board.get("conclusion") or {}).get("finished_at") or 0,
                     (conclusion.get("acceptance") or {}).get("at") or 0,
                     (conclusion.get("illustration") or {}).get("at") or 0)
    deploy_pending = (key == "done" and not deploy_status and expects_auto_deploy(board)
                      and now() - settled_at < AUTO_DEPLOY_GRACE)
    finished_at = None
    if key in TERMINAL_STAGES and not deploy_pending:
        finished_at = (team.get("stopped_at") if key == "stopped" else (deploy or {}).get("finished_at") or settled_at)
        finished_at = finished_at or team.get("updated_at") or now()
    eta = stage.get("eta")
    if isinstance(eta, dict):
        seconds, high, overtime = eta.get("seconds"), eta.get("high"), eta.get("overtime")
    else:
        seconds, high, overtime = eta, stage.get("eta_high"), stage.get("overtime")
    if stage.get("at") and seconds is not None:
        age = max(0, now() - stage["at"])
        overtime = overtime or seconds <= age
        seconds, high = max(0, seconds - age), max(0, (high or seconds) - age)
    fallback_steps = {"plan_failed": "planning", "start_failed": "starting", "cancelled": "approval", "stopped": "running"}
    steps = stage.get("steps") if key != "stopped" or completed_at else None
    steps = steps or progress._step_states(fallback_steps.get(key, key))
    if deploy_status or deploy_pending:
        state = {"running": "active", "succeeded": "done"}.get(deploy_status, deploy_status or "pending")
        steps = [*steps, {"key": "deploy", "state": state}]
    counts = team.get("progress") or {}
    return {
        "team_id": team_id, "board": team.get("board"), "title": team.get("title") or board.get("title") or "协作",
        "workflow": team.get("workflow") or board.get("workflow") or "auto",
        "status": status, "phase": phase, "stage_key": key,
        "stage_label": "等待自动发布" if deploy_pending else stage.get("label") or _STAGE_LABELS.get(key, key),
        "stage_now": "" if deploy_pending else stage.get("now") or team.get("error") or "",
        "steps": steps, "done": stage.get("done", counts.get("done", sum(t["status"] in _DONE for t in tasks))),
        "total": stage.get("total", counts.get("total", len(tasks) or team.get("task_count") or 0)),
        "started_at": team.get("approved_at") or stage.get("started_at") or team.get("created_at"),
        "finished_at": finished_at, "eta_seconds": seconds, "eta_high": high, "overtime": bool(overtime),
        "after_approval": stage.get("after_approval"), "after_approval_high": stage.get("after_approval_high"),
        "tasks": tasks, "deploy": deploy, "deploy_pending": deploy_pending, "url": link.team_url(team_id),
    }


def _task_view(task: dict, ids_to_keys: dict, activity: dict) -> dict:
    run = task.get("current_run") or {}
    status = task.get("status") or "todo"
    return {"id": task["id"], "key": task.get("key") or "", "title": task.get("title") or "",
            "member": task.get("member") or "", "executor": task.get("executor") or run.get("runner") or "",
            "model": task.get("model") or "", "status": status, "sub_status": task.get("sub_status") or status,
            "started_at": (run.get("started_at") or task.get("started_at")) if status == "running" else task.get("started_at"),
            "completed_at": task.get("completed_at"), "activity": activity.get(task.get("key"), ""),
            "resume_at": run.get("resume_at"), "trail_len": len(task.get("trail") or []),
            "block_reason": task.get("block_reason") or "",
            "wait_keys": [ids_to_keys[parent] for parent in task.get("parents") or [] if parent in ids_to_keys]}


def view_from_snapshot(snap: dict, board: Optional[dict] = None) -> dict:
    team = snap.get("team") or {}
    stage = team.get("stage") or {}
    tasks = snap.get("tasks") or []
    keys = {t["id"]: t.get("key") or t["id"] for t in tasks if t.get("status") not in _DONE}
    activity = {t["key"]: t.get("text") or "" for t in stage.get("running") or [] if t.get("key")}
    return _make_view(team, stage, [_task_view(t, keys, activity) for t in tasks], status="running", board=board)


def view_from_summary(team: dict, planning_info: Optional[dict] = None) -> dict:
    status = team.get("status") or team.get("phase") or "planning"
    stage = dict(team.get("stage") or {})
    plan = team.get("plan") or {}
    if status == "planning":
        info = planning_info if planning_info is not None else progress.planning(team["id"])
        current, typical = info.get("progress") or {}, info.get("typical") or {}
        started = current.get("started_at") or stage.get("started_at") or team.get("updated_at") or team.get("created_at") or now()
        spent = max(0, now() - started)
        median = typical.get("median") or progress.DEFAULTS["plan"]
        model = current.get("model")
        detail = current.get("text") or stage.get("now") or "负责人在理解目标、分配成员与任务"
        stage.update(key="planning", now=f"{model} · {detail}" if model else detail,
                     started_at=started, at=None, eta=max(5, median - spent),
                     eta_high=max(5, max(median, typical.get("p75") or 0) - spent), overtime=spent >= median)
    elif status == "plan_ready":
        estimate = plan.get("estimate") or {}
        stage.setdefault("now", "计划好了，批准后开始执行")
        stage.setdefault("after_approval", estimate.get("seconds"))
        stage.setdefault("after_approval_high", estimate.get("high"))
    elif status == "starting":
        stage.setdefault("now", "正在建立任务板并启动成员")
    members = {m["name"]: m for m in plan.get("members") or [] if m.get("name")}
    tasks = []
    for t in plan.get("tasks") or []:
        key = t.get("key") or str(len(tasks) + 1)
        member = members.get(t.get("member")) or {}
        tasks.append(_task_view({**t, "id": key, "key": key, "sub_status": "waiting_deps",
                                 "executor": t.get("runner") or member.get("runner") or member.get("executor"),
                                 "model": member.get("model"), "parents": t.get("depends_on")},
                                {dep: dep for dep in t.get("depends_on") or []}, {}))
    return _make_view(team, stage, tasks, status=status)


def resolve_team_view(owner: str, team_id: str, *, summary: Optional[dict] = None) -> Optional[dict]:
    if not valid_team_id(team_id):
        return view_from_summary(summary) if summary else None
    try:
        snap = teams.snapshot(team_id, owner)
    except teams.TeamError as exc:
        if exc.status != 404:
            raise
    else:
        return view_from_snapshot(snap, read_team(board_slug(team_id)))
    if summary and (summary.get("status") not in ("plan_ready", "starting", "start_failed") or summary.get("plan")):
        return view_from_summary(summary)
    try:
        team = link.get(owner, team_id)
    except link.HaloError as exc:
        if summary and exc.status not in (401, 403, 404):
            return view_from_summary(summary)
        if exc.status == 404:
            return None
        raise
    return view_from_summary({**(summary or {}), **team}) if team else None


def is_active(view: dict) -> bool:
    return view["stage_key"] in ACTIVE_STAGES or view["deploy_pending"]


def resolve_query_views(owner: str, selector: str = "", *, workflow_first: Optional[str] = None,
                        limit: int = 3) -> tuple[list[dict], list[dict]]:
    error = None
    try:
        recent = link.recent(owner)
    except link.HaloError as exc:
        if exc.status in (401, 403):
            raise
        error, recent = exc, []
    candidates = {t["id"]: t for t in recent if t.get("id")}
    settled_local = set()
    for slug in team_boards():
        board = read_team(slug)
        if not board or str(board.get("owner")) != str(owner) or not board.get("team_id"):
            continue
        team_id = board["team_id"]
        state = board.get("state")
        candidates[team_id] = {**candidates.get(team_id, {}), "id": team_id, "title": board.get("title"),
                               "status": "running", "phase": state, "workflow": board.get("workflow"),
                               "updated_at": board.get("completed_at") or board.get("approved_at") or 0}
        if state == "stopped":
            settled_local.add(team_id)
        elif state == "completed":
            conclusion = board.get("conclusion") or {}
            deploy = (board.get("project") or {}).get("deploy") or {}
            if (conclusion.get("status") in ("ready", "failed")
                    and (conclusion.get("acceptance") or {}).get("status") != "checking"
                    and (conclusion.get("illustration") or {}).get("status") != "generating"
                    and deploy.get("status") != "running" and not expects_auto_deploy(board)):
                settled_local.add(team_id)

    if selector:
        if len(selector) == 1 and selector in "12345678":
            index = int(selector) - 1
            ids = [recent[index]["id"]] if index < len(recent) else []
        else:
            ids = [team_id for team_id in candidates if team_id.lower() == selector]
            ids = ids or [team_id for team_id in candidates if team_id.lower().startswith(selector)]
        if len(ids) == 1:
            view = resolve_team_view(owner, ids[0], summary=candidates[ids[0]])
            return ([view] if view else []), recent
        if error and not ids:
            raise error
        return [], recent

    def priority(team: dict) -> tuple:
        status = team.get("status")
        return (bool(workflow_first and team.get("workflow") != workflow_first),
                status in ("planning", "plan_ready", "starting"), -(team.get("updated_at") or 0))

    views = []
    for team in sorted(candidates.values(), key=priority):
        if (team["id"] in settled_local or team.get("status") not in ("planning", "plan_ready", "starting", "running")
                or team.get("phase") == "stopped"):
            continue
        view = resolve_team_view(owner, team["id"], summary=team)
        if view and is_active(view):
            views.append(view)
            if len(views) == limit:
                break
    if not views and error:
        raise error
    return views, recent


def _text(value: object, limit: int) -> str:
    return redact(plain(_TAG.sub("", html.unescape(str(value or "")))), limit)


def _escape_line(line: str, limit: int = 440) -> str:
    """Clip a whole escaped line while keeping HTML entities intact."""
    escaped = html.escape(line, quote=False)
    if len(escaped) <= limit:
        return escaped
    parts = []
    remaining = limit - 1
    for char in line:
        entity = html.escape(char, quote=False)
        if len(entity) > remaining:
            break
        parts.append(entity)
        remaining -= len(entity)
    return "".join(parts).rstrip() + "…"


def _eta(view: dict) -> str:
    if view.get("overtime"):
        return "比平时久，仍在处理"
    eta = progress.eta_text(view.get("eta_seconds"), view.get("eta_high"))
    if eta:
        return "预计还需" + eta
    after = progress.eta_text(view.get("after_approval"), view.get("after_approval_high"))
    return f"批准后{after}出结果" if after else ""


def _task_name(task: dict) -> str:
    return " ".join(filter(None, (_text(task["key"], 14), _text(task["title"], 62))))


def _resume_text(task: dict) -> str:
    stamp = task.get("resume_at")
    return f"约 {time.strftime('%m-%d %H:%M', time.localtime(stamp))} 自动继续" if stamp else "额度恢复后自动继续"


def _task_lines(task: dict) -> list[str]:
    sub = task["sub_status"]
    icon, status = _TASK_STATES.get(sub, _TASK_STATES.get(task["status"], ("○", "")))
    executor = _text(task["executor"], 24)
    details = [f"{icon} {_task_name(task)}", _text(task["member"], 26), executor, _text(task["model"], 32), status]
    if task["started_at"] and (task["completed_at"] or task["status"] == "running"):
        took = duration((task["completed_at"] or now()) - task["started_at"])
        details.append(("已跑 " if task["status"] == "running" else "") + took)
    if task["trail_len"]:
        details.append("已兜底切换")
    if sub == "waiting_deps" and task["wait_keys"]:
        details.append("等 " + _text("、".join(task["wait_keys"]), 60))
    lines = [" · ".join(filter(None, details))]
    detail = (_resume_text(task) if sub == "quota_wait" else task["block_reason"]
              if sub in ("failed", "blocked", "triage", "waiting_user") else task["activity"])
    if detail := _text(detail, 140):
        lines.append("   └ " + detail)
    return lines


def _card_lines(view: dict) -> tuple[list[str], list[str]]:
    title = _text(view["title"], 80)
    head = f"📊 {title} · {_text(view['stage_label'], 40)}"
    if view["total"]:
        head += f" ({view['done']}/{view['total']})"
    rail = " → ".join(f"{_STAGE_STEPS[s['key']]} {_STEP_ICONS.get(s.get('state'), '○')}"
                      for s in view["steps"] if s.get("key") in _STAGE_STEPS)
    lines = [head, rail]
    elapsed = duration((view["finished_at"] or now()) - view["started_at"]) if view["started_at"] else ""
    timing = " · ".join(filter(None, (f"{'用时' if view['finished_at'] else '已用'} {elapsed}" if elapsed else "", _eta(view))))
    if timing:
        lines.append("⏱ " + timing)
    if detail := _text(view["stage_now"], 160):
        lines.append("📍 " + detail)
    deploy = view["deploy"] or {}
    footer = []
    if deploy:
        label = _DEPLOY_LABELS.get(deploy.get("status"), "发布进度")
        steps = " → ".join(f"{_STEP_ICONS.get(step.get('status'), '○')} {_text(step.get('label') or step.get('key'), 34)}"
                           for step in (deploy.get("steps") or [])[:8])
        footer.append(f"🚀 {label}：{steps}" if steps else f"🚀 {label}")
        if error := _text(deploy.get("error"), 180):
            footer.append("⚠️ " + error)
    return lines, footer


def _card(view: dict, head: list[str], footer: list[str], *, telegram: bool) -> str:
    def size(line: str) -> int:
        return len(line.encode("utf-16-le")) // 2

    tasks = view["tasks"]
    rows: dict[int, list[str]] = {}
    remaining = CARD_MAX_CHARS - size("\n".join([*head, "", "", *footer])) - 60
    # Keep active/blocked tasks visible even on a large board; present the selected rows in board order.
    ordered = sorted(enumerate(tasks), key=lambda pair: pair[1]["sub_status"] not in
                     ("running", "quota_wait", "review", "waiting_user", "failed", "blocked", "triage"))
    for index, task in ordered:
        lines = _task_lines(task)
        if telegram:
            lines = [_escape_line(line) for line in lines]
        cost = size("\n".join(lines)) + 1
        if cost > remaining:
            break
        rows[index] = lines
        remaining -= cost
    body = [line for index in sorted(rows) for line in rows[index]]
    if len(rows) < len(tasks):
        body.append(f"… 还有 {len(tasks) - len(rows)} 个任务，完整列表见工作台")
    return "\n\n".join("\n".join(part) for part in (head, body, footer) if part)


def render_telegram(view: dict, *, finalized: bool = False) -> tuple[str, list]:
    head, footer = _card_lines(view)
    head, footer = ([_escape_line(line) for line in lines] for lines in (head, footer))
    head[0] = f"<b>{head[0]}</b>"
    row = []
    if not finalized and is_active(view):
        row.append(("🔄 刷新进度", f"cb:pr:{view['team_id']}"))
    if view["url"]:
        row.append(("🌐 打开工作台", "url:" + view["url"]))
    deploy = view["deploy"] or {}
    ci = [("🔗 查看 CI", "url:" + deploy["ci_url"])] if deploy.get("ci_url") else []
    return _card(view, head, footer, telegram=True), [buttons for buttons in (row, ci) if buttons]


def render_qq(view: dict) -> str:
    head, footer = _card_lines(view)
    for label, url in (("🔗 CI", (view["deploy"] or {}).get("ci_url")), ("🌐 工作台", view["url"])):
        if url and len(url) <= 700:
            footer.append(f"{label}：{url}")
    footer.append("发 /team 进度 随时刷新")
    return _card(view, head, footer, telegram=False)


def _digest(value: list) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def fingerprints(view: dict) -> tuple[str, str]:
    deploy = view["deploy"] or {}
    steps = deploy.get("steps") or []
    milestone = _digest([
        view["stage_key"], view["deploy_pending"],
        [(t["id"], t["status"], t["sub_status"], t["executor"], t["trail_len"], t["resume_at"]) for t in view["tasks"]],
        deploy.get("status"), deploy.get("step"), [(s.get("key"), s.get("status")) for s in steps], deploy.get("ci_url"),
    ])
    full = _digest([milestone, view["stage_now"], [(t["id"], t["activity"]) for t in view["tasks"]],
                    next((s.get("detail") for s in steps if s.get("status") == "running"), None)])
    return milestone, full


def qq_milestone_state(view: dict) -> dict:
    deploy = view["deploy"] or {}
    return {"stage_key": view["stage_key"],
            "tasks": {t["id"]: {k: t[k] for k in ("key", "title", "member", "executor", "status", "sub_status", "trail_len")}
                      for t in view["tasks"]},
            "deploy_status": deploy.get("status") or "", "deploy_step": deploy.get("step") or "",
            "ci_url": deploy.get("ci_url") or ""}


def qq_milestone_message(prev: Optional[dict], view: dict) -> Optional[str]:
    stage = view["stage_key"]
    state = qq_milestone_state(view)
    if stage in ("attention", *TERMINAL_STAGES) or state["deploy_status"] in DEPLOY_TERMINAL:
        return None
    if prev is None and not view["done"] and stage not in POST_RUN_STAGES:
        return None
    prev = prev or {}
    before = prev.get("tasks") or {}
    updates = []
    if stage != prev.get("stage_key") and stage in ("concluding", "checking", "deploying"):
        updates.append("📍 " + view["stage_label"])
    if state["deploy_step"] == "ci" and (prev.get("deploy_step") != "ci" or
                                         (state["ci_url"] and prev.get("ci_url") != state["ci_url"])):
        updates.append("🔗 CI 已开始" + (f"：{state['ci_url']}" if state["ci_url"] else ""))
    task_updates = []
    for task in view["tasks"]:
        old = before.get(task["id"]) or {}
        name, executor = _task_name(task), _text(task["executor"], 24)
        if task["status"] in _DONE and old.get("status") not in _DONE:
            took = duration(task["completed_at"] - task["started_at"]) if task["completed_at"] and task["started_at"] else ""
            task_updates.append(f"✅ {name} 已完成" + (f"（{took}）" if took else ""))
        elif task["sub_status"] == "quota_wait" and old.get("sub_status") != "quota_wait":
            task_updates.append(f"⏸ {name} 等待 {executor or '执行器'} 额度，{_resume_text(task)}")
        elif task["trail_len"] > (old.get("trail_len") or 0):
            task_updates.append(f"🔁 {name} 已切换到 {executor or '备用执行器'}")
        elif task["status"] == "running" and old.get("status") != "running":
            task_updates.append(f"🔵 开始执行：{name}" + (f"（{executor}）" if executor else ""))
    if not updates and not task_updates:
        return None
    lines = [f"📌 协作「{_text(view['title'], 60)}」进度 {view['done']}/{view['total']}", *updates, *task_updates[:6]]
    if len(task_updates) > 6:
        lines.append(f"… 另有 {len(task_updates) - 6} 个任务状态变化")
    lines.append(" · ".join(filter(None, (_eta(view), "发 /team 进度 看详情"))))
    return "\n".join(lines)
