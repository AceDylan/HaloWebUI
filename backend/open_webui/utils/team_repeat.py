"""协作台「再来一次」与定时: a team as a template for new runs.

再来一次 makes a new team with the goal, the plan (members, their runners and models, tasks)
and the settings (lead model, project, preferred assistants, input files) of one that ran
before — no new planning. It waits for approval, or starts at once (「直接开始」). Assistants
the first run created or upgraded are not made again: the plan keeps what approval did then
(``assistants_applied``). A project team gets its own ``halo/…`` branch at approval as usual.

定时 runs 再来一次 (直接开始) every day / week / month at a time in the owner's time zone
(models/agent_team_schedules.py). A sweep in this process looks for due schedules once a
minute; a run that was missed while the server was down starts once when it is back. An
occurrence is skipped while the previous scheduled run is still at work or waiting for
approval, so runs never pile up.
"""

import asyncio
import copy
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.agent_team_schedules import AgentTeamScheduleModel, AgentTeamSchedules
from open_webui.models.agent_teams import AgentTeamModel, AgentTeams, bucket_of
from open_webui.utils.agent_teams import (
    ENABLE_AGENT_TEAMS,
    AssistantAccess,
    TeamsError,
    auto_startable,
    hermes_target,
    start_team,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

FREQS = ("daily", "weekly", "monthly")
DEFAULT_TZ = "Asia/Shanghai"
SWEEP_SECONDS = 60
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# The settings of the source team a new run keeps (see utils/agent_teams.py _start).
_KEPT_META = ("lead_model", "project", "assistants", "inputs")


# --- 再来一次 -------------------------------------------------------------------------------------


def repeatable(team: AgentTeamModel) -> bool:
    plan = team.plan if isinstance(team.plan, dict) else {}
    return bool(plan.get("members")) and bool(plan.get("tasks"))


async def repeat_team(request, user, source: AgentTeamModel, *, auto_start: bool,
                      schedule_id: Optional[str] = None) -> AgentTeamModel:
    """A new team from ``source``: its own chat, the same plan, ready for approval (or started)."""
    from open_webui.utils import team_chats

    if not repeatable(source):
        raise TeamsError(409, "这个协作还没有计划，不能再来一次")
    target = await hermes_target(request, user)
    meta = {key: copy.deepcopy(source.meta[key]) for key in _KEPT_META if (source.meta or {}).get(key)}
    meta["repeat_of"] = source.id
    if schedule_id:
        meta["schedule_id"] = schedule_id
    if auto_start:
        meta["auto_start"] = True
    team = AgentTeams.insert(user.id, source.goal, None, source.title, meta=meta)
    team = AgentTeams.update(team.id, user.id, expect_status=("planning",), status="plan_ready",
                             plan=copy.deepcopy(source.plan), title=source.title) or team
    team = await team_chats.attach(request, user, team)
    if auto_start and auto_startable(team.plan or {}):
        try:
            team = await start_team(team, target, AssistantAccess(request, user))
        except TeamsError as exc:  # start_failed is recorded on the team, with the reason
            log.info("teams: the repeat %s of %s did not start (%s)", team.id, source.id, exc.detail)
            team = AgentTeams.get(team.id, user.id) or team
    return team


# --- 定时 ------------------------------------------------------------------------------------------


def zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def validate_schedule(freq: str, at: str, weekday: Optional[int], day: Optional[int], tz: str) -> dict:
    """The stored fields of a schedule, or TeamsError(400) saying what is wrong."""
    if freq not in FREQS:
        raise TeamsError(400, "频率只能是每天、每周或每月")
    if not TIME_RE.match(at or ""):
        raise TeamsError(400, "时间要写成 HH:MM")
    if freq == "weekly" and (weekday is None or not 0 <= weekday <= 6):
        raise TeamsError(400, "每周要选星期几")
    if freq == "monthly" and (day is None or not 1 <= day <= 28):
        raise TeamsError(400, "每月只能选 1–28 号")
    return {"freq": freq, "time": at, "weekday": weekday if freq == "weekly" else None,
            "day": day if freq == "monthly" else None, "tz": zone(tz).key}


def next_run_at(schedule, after: float) -> int:
    """The first occurrence strictly after ``after`` (a timestamp)."""
    tz = zone(schedule.tz)
    hour, minute = (int(part) for part in schedule.time.split(":"))
    start = datetime.fromtimestamp(after, tz).date()
    for offset in range(0, 62):
        date = start + timedelta(days=offset)
        if schedule.freq == "weekly" and date.weekday() != schedule.weekday:
            continue
        if schedule.freq == "monthly" and date.day != schedule.day:
            continue
        at = datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz).timestamp()
        if at > after:
            return int(at)
    raise ValueError(f"no occurrence for schedule {schedule}")  # pragma: no cover - 62 days cover a month


def describe(schedule) -> str:
    """每天 09:00 / 每周一 09:00 / 每月 1 号 09:00"""
    if schedule.freq == "weekly":
        return f"每周{'一二三四五六日'[schedule.weekday or 0]} {schedule.time}"
    if schedule.freq == "monthly":
        return f"每月 {schedule.day} 号 {schedule.time}"
    return f"每天 {schedule.time}"


def public_schedule(schedule: Optional[AgentTeamScheduleModel]) -> Optional[dict]:
    if schedule is None:
        return None
    out = schedule.model_dump(exclude={"user_id", "id", "created_at", "updated_at"})
    out["label"] = describe(schedule)
    return out


def busy(team: Optional[AgentTeamModel]) -> bool:
    """Still at work or waiting for approval."""
    return team is not None and bucket_of(team.status, team.phase) in ("active", "review")


def _background_request(app):
    from open_webui.utils.hermes_agent import _background_request as make

    return make(app)


async def run_schedule(app, schedule: AgentTeamScheduleModel, now: int) -> Optional[AgentTeamModel]:
    """Start one due occurrence (once: the claim moves it forward before anything runs)."""
    from open_webui.models.users import Users

    if not AgentTeamSchedules.claim(schedule.id, schedule.next_run_at, next_run_at(schedule, now)):
        return None
    user = Users.get_user_by_id(schedule.user_id)
    source = AgentTeams.get(schedule.team_id, schedule.user_id)
    if user is None or source is None:
        AgentTeamSchedules.record(schedule.id, enabled=False, last_error="原来的协作已删除，定时已停用")
        return None
    previous = AgentTeams.get(schedule.last_team_id, schedule.user_id) if schedule.last_team_id else None
    if busy(previous):
        AgentTeamSchedules.record(schedule.id, last_error="上一次还没结束（或在等批准），这次跳过")
        return None
    try:
        team = await repeat_team(_background_request(app), user, source, auto_start=True, schedule_id=schedule.id)
    except TeamsError as exc:
        AgentTeamSchedules.record(schedule.id, last_run_at=now, last_error=exc.detail)
        return None
    error = None
    if team.status == "start_failed":
        error = team.error or "启动失败"
    elif team.status == "plan_ready":
        error = "有成员现在没有可用的执行器，这次的计划在等你批准"
    AgentTeamSchedules.record(schedule.id, last_run_at=now, last_team_id=team.id, last_error=error)
    return team


async def run_due_schedules(app, now: Optional[int] = None) -> int:
    now = int(now or time.time())
    started = 0
    for schedule in AgentTeamSchedules.due(now):
        try:
            if await run_schedule(app, schedule, now):
                started += 1
        except Exception:  # one broken schedule must not stop the others
            log.exception("teams: scheduled run of %s failed", schedule.team_id)
    return started


async def periodic_team_schedules(app) -> None:
    if not ENABLE_AGENT_TEAMS:
        return
    await asyncio.sleep(30)  # let the app finish starting (models, Hermes connection)
    while True:
        try:
            await run_due_schedules(app)
        except Exception:
            log.exception("teams: schedule sweep failed")
        await asyncio.sleep(SWEEP_SECONDS)
