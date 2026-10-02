"""阶段与预计时间 — where a team stands, what is happening right now and roughly how long it will
still take, for HaloWebUI's stage rail, the team list and Telegram.

Durations come from this machine's own history (cached ``STATS_TTL``): every finished attempt on
every team board by executor, the lead's conclusions (``conclusion.seconds`` in the team record),
its acceptance checks, and its plans (``record_plan``, written while planning). With too little
history the defaults below stand in.

The execution estimate replays the remaining tasks on their dependencies with the team's parallel
cap (and one member per runner kind at a time, like the bridge), each task taking its executor's
median; a running task counts what is typically left of it, a task waiting for a quota reset its
reset time. A team that needs the user (a member asks, a task failed) has no estimate — it waits
for them.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .common import RUNNER_EXECUTORS, board_conn, logger, now, read_team, redact, team_boards

STATS_TTL = 600
MIN_SAMPLES = 3
# Seconds, when this machine has (almost) no history of its own.
DEFAULTS = {"task": 180, "plan": 45, "conclusion": 40, "acceptance": 25}
HOST_PARALLEL = 2          # kanban.max_in_progress (host-wide), the usual cap
HIGH_SPREAD = 1.35
PLAN_TIMES_MAX = 60
_cache: dict[str, Any] = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
_planning: dict[str, dict] = {}
_planning_lock = threading.Lock()

TOOL_LABELS = {
    "terminal": "运行命令", "process": "看进程", "read_file": "读文件", "write_file": "写文件", "patch": "改文件",
    "search_files": "找文件", "web_search": "搜索", "search_web": "搜索", "web_extract": "读网页",
    "fetch_url": "读网页", "fetch_url_rendered": "读网页", "skill_view": "看技能说明", "skills_list": "看技能",
    "execute_code": "运行代码", "delegate_task": "派出子代理", "todo": "列待办", "memory": "查记忆",
    "session_search": "查历史会话", "send_message": "发消息", "clarify": "提问", "image_generate": "生成图片",
    "generate_image": "生成图片", "edit_image": "改图", "vision_analyze": "看图", "kanban_show": "读任务",
    "kanban_complete": "交付结果", "kanban_comment": "写留言", "kanban_block": "停下来问你",
}
STAGE_LABELS = {
    "planning": "负责人制定计划", "approval": "等你批准", "starting": "启动成员", "running": "成员执行中",
    "attention": "需要你处理", "paused": "已暂停派发", "concluding": "整理完整结果", "checking": "对照目标验收",
    "done": "已完成", "stopped": "已停止",
}


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _plan_times_file() -> Path:
    return _home() / "halo-teams" / "plan-times.json"


# --- history ----------------------------------------------------------------------------------------

def _summary(values: list[float]) -> Optional[dict]:
    values = sorted(v for v in values if v and v > 0)
    if len(values) < MIN_SAMPLES:
        return None
    p75 = values[min(len(values) - 1, int(round(len(values) * 0.75)) - 1)]
    return {"n": len(values), "median": round(statistics.median(values)), "p75": round(max(p75, statistics.median(values)))}


def _collect() -> dict:
    by_executor: dict[str, list[float]] = {}
    every: list[float] = []
    conclusion: list[float] = []
    acceptance: list[float] = []
    for slug in team_boards():
        team = read_team(slug) or {}
        task_map = team.get("tasks") or {}
        kinds = {m.get("name"): m.get("kind") for m in team.get("members") or [] if isinstance(m, dict)}
        entry = team.get("conclusion") or {}
        if entry.get("seconds"):
            conclusion.append(float(entry["seconds"]))
        acc = entry.get("acceptance") or {}
        if acc.get("status") == "ready" and acc.get("at") and entry.get("generated_at"):
            spent = int(acc["at"]) - int(entry["generated_at"])
            if 0 < spent < 900:
                acceptance.append(float(spent))
        try:
            with board_conn(slug) as conn:
                rows = conn.execute(
                    "SELECT task_id, started_at, ended_at FROM task_runs WHERE outcome = 'completed' "
                    "AND started_at IS NOT NULL AND ended_at IS NOT NULL").fetchall()
        except Exception:  # noqa: BLE001 — one broken board must not hide the rest
            continue
        for task_id, started, ended in rows:
            spent = float(ended) - float(started)
            if spent <= 0 or spent > 6 * 3600:
                continue
            entry = task_map.get(task_id) or {}
            executor = entry.get("executor") or "hermes"
            by_executor.setdefault(executor, []).append(spent)
            kind = kinds.get(entry.get("member"))
            if kind:  # research on Hermes takes ~4× a writing task: kind matters as much as the runner
                by_executor.setdefault(f"{executor}/{kind}", []).append(spent)
            every.append(spent)
    plans = []
    try:
        plans = [float(x) for x in json.loads(_plan_times_file().read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        pass
    return {
        "task": {name: s for name, values in by_executor.items() if (s := _summary(values))},
        "task_all": _summary(every),
        "conclusion": _summary(conclusion),
        "acceptance": _summary(acceptance),
        "plan": _summary(plans),
        "at": now(),
    }


def history(force: bool = False) -> dict:
    with _cache_lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < STATS_TTL:
            return _cache["data"]
    try:
        data = _collect()
    except Exception:  # noqa: BLE001
        logger.warning("halowebui-teams: progress history failed", exc_info=True)
        data = {"task": {}, "task_all": None, "conclusion": None, "acceptance": None, "plan": None, "at": now()}
    with _cache_lock:
        _cache.update(at=time.time(), data=data)
    return data


KIND_LABELS = {"code": "代码", "ui": "前端/UI", "complex": "复杂", "research": "调研", "writing": "写作"}


def typical(kind: str, executor: Optional[str] = None, stats: Optional[dict] = None,
            task_kind: Optional[str] = None) -> dict:
    """{median, p75, n, basis} for a stage ("plan" / "conclusion" / "acceptance") or a task by
    executor and task kind (the member's: research / writing / code …)."""
    stats = stats or history()
    if kind == "task":
        table = stats.get("task") or {}
        found = table.get(f"{executor}/{task_kind}") if executor and task_kind else None
        if found:
            return {**found, "basis": f"本机最近 {found['n']} 次 {executor} {KIND_LABELS.get(task_kind, task_kind)}任务"}
        found = table.get(executor or "") if executor else None
        if found:
            return {**found, "basis": f"本机最近 {found['n']} 次 {executor} 任务"}
        found = stats.get("task_all")
        if found:
            return {**found, "basis": f"本机最近 {found['n']} 次成员任务"}
    else:
        found = stats.get(kind)
        if found:
            return {**found, "basis": f"本机最近 {found['n']} 次"}
    base = DEFAULTS.get(kind, DEFAULTS["task"])
    return {"median": base, "p75": round(base * 1.8), "n": 0, "basis": "经验值（本机记录还不够）"}


def record_plan(seconds: float) -> None:
    """One plan the lead made (seconds), for the planning estimate."""
    path = _plan_times_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, list):
            values = []
    except (OSError, ValueError):
        values = []
    values = [round(float(seconds), 1)] + [v for v in values if isinstance(v, (int, float))]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(values[:PLAN_TIMES_MAX]), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    with _cache_lock:
        _cache["at"] = 0.0


# --- planning progress (in memory, while the lead plans) -----------------------------------------------

def planning_step(team_id: str, step: str, text: str, **extra: Any) -> None:
    if not team_id:
        return
    with _planning_lock:
        entry = _planning.setdefault(team_id, {"started_at": now()})
        entry.update(step=step, text=text, at=now(), **extra)


def planning_done(team_id: str) -> Optional[dict]:
    with _planning_lock:
        return _planning.pop(team_id, None) if team_id else None


def planning(team_id: str) -> dict:
    with _planning_lock:
        entry = dict(_planning.get(team_id) or {})
    t = typical("plan")
    return {"progress": entry or None, "typical": {"median": t["median"], "p75": t["p75"], "basis": t["basis"]}}


# --- execution estimate -------------------------------------------------------------------------------

def _simulate(tasks: list[dict], durations: dict[str, float], cap: int) -> float:
    """Seconds until every task is done: list scheduling on the dependencies, *cap* at once, one
    member per runner kind at a time. ``durations``: remaining seconds of each unfinished task."""
    done = {t["id"] for t in tasks if t["id"] not in durations}
    pending = [t for t in tasks if t["id"] in durations]
    running: dict[str, tuple[float, str]] = {}
    clock = 0.0
    for _guard in range(4 * len(tasks) + 4):
        if not pending and not running:
            break
        busy_runners = {ex for _end, ex in running.values() if ex in RUNNER_EXECUTORS}
        for t in list(pending):
            if len(running) >= cap:
                break
            if any(p not in done for p in t.get("parents") or []):
                continue
            executor = t.get("executor") or "hermes"
            if executor in RUNNER_EXECUTORS and executor in busy_runners:
                continue
            running[t["id"]] = (clock + durations[t["id"]], executor)
            busy_runners.add(executor)
            pending.remove(t)
        if not running:
            break  # waiting on a task outside this set (should not happen): stop counting
        task_id = min(running, key=lambda k: running[k][0])
        clock = running.pop(task_id)[0]
        done.add(task_id)
    return clock


def _remaining(task: dict, t: dict, field: str, at: int) -> tuple[float, bool]:
    """(seconds left, overtime) of one unfinished task."""
    whole = float(t[field])
    sub = task.get("sub_status")
    run = task.get("current_run") or {}
    if sub == "quota_wait" and run.get("resume_at"):
        return max(0.0, float(run["resume_at"]) - at) + whole, False
    if task.get("status") == "running" and run.get("started_at"):
        spent = max(0.0, at - float(run["started_at"]))
        left = whole - spent
        if left > 0:
            return left, False
        return max(30.0, 0.3 * whole), True
    return whole, False


def estimate(tasks: list[dict], *, cap: int = HOST_PARALLEL, stats: Optional[dict] = None,
             with_conclusion: bool = True, at: Optional[int] = None) -> dict:
    """{seconds, high, overtime, basis} until the result is there: the tasks not done yet, then the
    conclusion and the acceptance check."""
    stats = stats or history()
    at = at or now()
    open_tasks = [t for t in tasks if t.get("status") not in ("done", "archived")]
    medians: dict[str, float] = {}
    highs: dict[str, float] = {}
    overtime = False
    bases = set()
    for task in open_tasks:
        t = typical("task", task.get("executor"), stats, task.get("kind"))
        bases.add(t["basis"])
        medians[task["id"]], late = _remaining(task, t, "median", at)
        highs[task["id"]], _ = _remaining(task, t, "p75", at)
        overtime = overtime or late
    cap = max(1, min(int(cap or HOST_PARALLEL), HOST_PARALLEL))
    seconds = _simulate(tasks, medians, cap)
    high = _simulate(tasks, highs, cap)
    if with_conclusion:
        c, a = typical("conclusion", stats=stats), typical("acceptance", stats=stats)
        seconds += c["median"] + a["median"]
        high += c["p75"] + a["p75"]
    basis = "按" + "、".join(sorted(bases)) + "的用时估算" if bases else ""
    # Member tasks vary a lot (a search that finds little, a member that retries): the high end
    # is never closer than a third above the estimate.
    high = max(high, seconds * HIGH_SPREAD)
    return {"seconds": int(round(seconds)), "high": int(round(high)), "overtime": overtime,
            "basis": basis}


def estimate_plan(plan: dict) -> Optional[dict]:
    """Before approval: about how long the plan takes once started (tasks, conclusion, acceptance)."""
    tasks = []
    members = {m.get("name"): m for m in plan.get("members") or [] if isinstance(m, dict)}
    for t in plan.get("tasks") or []:
        if not isinstance(t, dict) or not t.get("key"):
            continue
        member = members.get(t.get("member")) or {}
        tasks.append({"id": t["key"], "parents": list(t.get("depends_on") or []), "status": "todo",
                      "executor": member.get("runner") or member.get("executor") or "hermes", "kind": member.get("kind")})
    if not tasks:
        return None
    try:
        return estimate(tasks, cap=int(plan.get("max_parallel") or HOST_PARALLEL))
    except Exception:  # noqa: BLE001
        logger.warning("halowebui-teams: plan estimate failed", exc_info=True)
        return None


# --- what is happening now ------------------------------------------------------------------------------

def _tool_text(payload: dict) -> str:
    name = str(payload.get("name") or "")
    label = TOOL_LABELS.get(name) or ("浏览网页" if name.startswith("browser_") else name or "工具")
    preview = redact(payload.get("preview") or "", 90)
    return f"{label} · {preview}" if preview else label


def _event_text(kind: str, payload: dict) -> str:
    if kind == "halo_tool":
        return _tool_text(payload)
    if kind == "halo_subagent":
        goal = redact(payload.get("goal") or payload.get("summary") or "", 80)
        return ("派出子代理" if payload.get("phase") == "start" else "子代理完成") + (f" · {goal}" if goal else "")
    if kind == "halo_runner":
        phase = payload.get("phase")
        runner = payload.get("runner") or "runner"
        if phase == "quota_wait":
            at = payload.get("resume_at")
            when = time.strftime("%H:%M", time.localtime(int(at))) if at else "重置后"
            return f"{runner} 额度用完，约 {when} 自动继续"
        if phase == "question":
            return f"{runner} 停下来问你：{redact(payload.get('text') or '', 80)}"
        return {"launched": f"已启动 {runner}", "continued": f"{runner} 续跑", "answered": f"{runner} 收到回答，继续",
                "fallback": f"改由 {payload.get('to') or '下一个'} 执行"}.get(phase, f"{runner} {phase or ''}".strip())
    if kind in ("claimed", "spawned"):
        return "开始执行"
    return ""


def _latest_activity(slug: str, task_ids: list[str]) -> dict[str, dict]:
    if not task_ids:
        return {}
    out: dict[str, dict] = {}
    marks = ",".join("?" for _ in task_ids)
    with board_conn(slug) as conn:
        rows = conn.execute(
            f"SELECT task_id, kind, payload, created_at FROM task_events WHERE id IN (SELECT MAX(id) FROM task_events "
            f"WHERE task_id IN ({marks}) AND kind IN ('halo_tool','halo_subagent','halo_runner','claimed','spawned') "
            f"GROUP BY task_id)", task_ids).fetchall()
    for task_id, kind, raw, created in rows:
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}
        text = _event_text(kind, payload if isinstance(payload, dict) else {})
        if text:
            out[task_id] = {"text": text, "at": int(created or 0)}
    return out


def _step_states(key: str) -> list[dict]:
    order = ["plan", "approve", "run", "conclude", "check"]
    position = {"planning": 0, "approval": 1, "starting": 2, "running": 2, "attention": 2, "paused": 2,
                "concluding": 3, "checking": 4, "done": 5, "stopped": 5}.get(key, 2)
    out = []
    for i, name in enumerate(order):
        state = "done" if i < position else ("active" if i == position else "pending")
        out.append({"key": name, "state": state})
    return out


def stage(slug: str, team: dict, tasks: list[dict], phase: str, stats: Optional[dict] = None) -> dict:
    """The team's stage for the snapshot: key, label, what is happening now, since when, the
    estimate (seconds left, a high end) and the five steps (计划 → 批准 → 执行 → 结论 → 验收)."""
    stats = stats or history()
    at = now()
    kinds = {m.get("name"): m.get("kind") for m in team.get("members") or [] if isinstance(m, dict)}
    tasks = [{**t, "kind": kinds.get(t.get("member"))} for t in tasks]
    done = sum(1 for t in tasks if t.get("status") in ("done", "archived"))
    out: dict[str, Any] = {"done": done, "total": len(tasks)}
    entry = team.get("conclusion") or {}
    acceptance = entry.get("acceptance") or {}
    if phase == "stopped":
        out.update(key="stopped", now="团队已停止，已完成的产出保留", started_at=team.get("stopped_at"))
    elif phase == "completed":
        if entry.get("status") == "generating" or not entry.get("status"):
            t = typical("conclusion", stats=stats)
            a = typical("acceptance", stats=stats)
            started = int(entry.get("started_at") or team.get("completed_at") or at)
            left = t["median"] - (at - started)
            model = entry.get("model") or (team.get("lead_model") or {}).get("model") or ""
            out.update(key="concluding", started_at=started,
                       now=f"负责人{f'（{model}）' if model else ''}在把 {len(tasks)} 个任务的成果整合成完整结果",
                       eta={"seconds": int(max(10, left) + a["median"]), "high": int(max(left, 0) + t["p75"] + a["p75"]),
                            "overtime": left <= 0, "basis": f"按{t['basis']}写结论的用时估算"})
        elif acceptance.get("status") == "checking":
            a = typical("acceptance", stats=stats)
            started = int(acceptance.get("started_at") or entry.get("generated_at") or at)
            left = a["median"] - (at - started)
            out.update(key="checking", started_at=started, now="结果已经写好，负责人在对照目标逐项验收",
                       eta={"seconds": int(max(5, left)), "high": int(max(left, 0) + a["p75"]), "overtime": left <= 0,
                            "basis": f"按{a['basis']}验收的用时估算"})
        else:
            failed = entry.get("status") == "failed"
            out.update(key="done", started_at=team.get("completed_at"),
                       now="结果没写成，可以在「结论」里重新生成" if failed else "完整结果已经整理好")
    elif phase == "paused":
        out.update(key="paused", now="已暂停派发：正在执行的成员会做完手上的任务，不再开始新任务")
    elif phase == "attention":
        stuck = next((t for t in tasks if t.get("sub_status") in ("waiting_user", "failed", "blocked")
                      or t.get("status") == "triage"), None)
        if stuck:
            why = {"waiting_user": "停下来问你", "failed": "失败了", "blocked": "受阻"}.get(stuck.get("sub_status"), "需要处理")
            reason = redact(stuck.get("block_reason") or "", 80)
            out.update(key="attention", task=stuck.get("key"),
                       now=f"#{stuck.get('key')} {stuck.get('member')} {why}" + (f"：{reason}" if reason else ""))
        else:
            out.update(key="attention", now="有任务需要你处理")
    else:
        out["key"] = "running"
    if out["key"] in ("running", "attention", "paused"):
        running = [t for t in tasks if t.get("status") == "running"]
        activity = _latest_activity(slug, [t["id"] for t in running])
        lines = []
        for t in running[:4]:
            act = activity.get(t["id"]) or {}
            run = t.get("current_run") or {}
            typ = typical("task", t.get("executor"), stats, t.get("kind"))
            lines.append({"key": t.get("key"), "member": t.get("member"), "executor": t.get("executor"),
                          "model": t.get("model") or "", "title": t.get("title") or "",
                          "text": act.get("text") or "开始执行", "at": act.get("at"),
                          "since": run.get("started_at") or t.get("started_at"),
                          "typical": typ["median"], "typical_high": typ["p75"]})
        out["running"] = lines
        queued = [t for t in tasks if t.get("sub_status") == "queued"]
        if out["key"] == "running":
            if lines:
                first = lines[0]
                more = f"（另有 {len(lines) - 1} 个成员在并行）" if len(lines) > 1 else ""
                out["now"] = f"#{first['key']} {first['member']}：{first['text']}{more}"
            elif queued:
                out["now"] = f"#{queued[0].get('key')} 排队等空位（同时最多 {HOST_PARALLEL} 个成员）"
            else:
                out["now"] = "派发器马上会开始下一个任务"
            starts = [t.get("started_at") for t in tasks if t.get("started_at")]
            out["started_at"] = team.get("approved_at") or (min(starts) if starts else None)
            out["eta"] = estimate(tasks, cap=int(team.get("max_parallel") or HOST_PARALLEL), stats=stats, at=at)
    out["label"] = STAGE_LABELS.get(out["key"], out["key"])
    out["steps"] = _step_states(out["key"])
    return out


def brief(stage_data: Optional[dict]) -> Optional[dict]:
    """The part of a stage the team list and Telegram show."""
    if not isinstance(stage_data, dict) or not stage_data.get("key"):
        return None
    eta = stage_data.get("eta") or {}
    return {k: v for k, v in {
        "key": stage_data["key"], "label": stage_data.get("label"), "now": redact(stage_data.get("now") or "", 120),
        "eta": eta.get("seconds"), "eta_high": eta.get("high"), "overtime": eta.get("overtime") or None,
        "started_at": stage_data.get("started_at"), "done": stage_data.get("done"), "total": stage_data.get("total"),
    }.items() if v not in (None, "")}


def eta_text(seconds: Optional[float], high: Optional[float] = None) -> str:
    """「约 3 分钟」「约 3–6 分钟」「不到 1 分钟」 (Telegram / logs; the page formats its own)."""
    if seconds is None:
        return ""
    def minutes(s: float) -> int:
        return max(1, int(round(s / 60)))
    if seconds < 50:
        return "不到 1 分钟"
    low = minutes(seconds)
    if high and minutes(high) > low:
        return f"约 {low}–{minutes(high)} 分钟"
    return f"约 {low} 分钟"

