"""协作台 (agent teams) — the HaloWebUI side of the Hermes ``halowebui-teams`` plugin.

HaloWebUI owns who may see and drive a team (``agent_team`` rows) and the plan the user
approves; Hermes owns execution (one Kanban board per team, workers, the reclaude bridge) and
the event history. Every Hermes call sends ``X-Halo-Owner`` and Hermes refuses teams recorded
for another owner, so ownership is checked on both sides.

ENABLE_AGENT_TEAMS=false turns the whole feature off (routes answer 404, the UI hides it).
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.models.agent_teams import AgentTeamModel, AgentTeams

log = logging.getLogger(__name__)

ENABLE_AGENT_TEAMS = os.environ.get("ENABLE_AGENT_TEAMS", "true").strip().lower() not in ("0", "false", "no", "off")
PLAN_TIMEOUT_SECONDS = 240
CALL_TIMEOUT_SECONDS = 30
PLANNING_STALE_SECONDS = 600     # a planning row this old lost its background job (restart)
STARTING_STALE_SECONDS = 120     # an approve that never recorded its outcome
GOAL_MAX_CHARS = 8000
FEEDBACK_MAX_CHARS = 2000
_background: set = set()


class TeamsError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class HermesTarget:
    """Where Hermes' api_server is for this user, captured while the request is alive."""

    def __init__(self, api_root: str, headers: dict, owner: str):
        self.api_root = api_root.rstrip("/")
        self.headers = {**headers, "X-Halo-Owner": owner, "Content-Type": "application/json"}

    def url(self, path: str) -> str:
        return f"{self.api_root}/v1/halo-teams{path}"


async def hermes_target(request, user) -> HermesTarget:
    from open_webui.utils.hermes_sessions import HermesSessionsError, _connection, resolve_hermes_model

    try:
        model = await resolve_hermes_model(request, user)
        api_root, headers = _connection(request, user, model)
    except HermesSessionsError as exc:
        raise TeamsError(exc.status_code if exc.status_code != 422 else 403, "你的账号没有可用的 Hermes 连接，不能使用协作台") from exc
    return HermesTarget(api_root, headers, str(user.id))


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
        if body.get("detail"):
            return str(body["detail"])[:500]
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return f"Hermes 返回 {status}"


async def hermes_call(target: HermesTarget, method: str, path: str, *, json_body: Any = None,
                      params: Optional[dict] = None, timeout: int = CALL_TIMEOUT_SECONDS) -> Any:
    """One call to the plugin API; TeamsError with Hermes' own message on any failure."""
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.request(method, target.url(path), headers=target.headers, json=json_body,
                                       params=params, ssl=AIOHTTP_CLIENT_SESSION_SSL) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = await resp.text()
                if resp.status == 404 and isinstance(body, str) and "halo-teams" not in body:
                    raise TeamsError(503, "Hermes 上没有协作台插件（halowebui-teams 未启用）")
                if resp.status >= 400:
                    raise TeamsError(resp.status if resp.status in (400, 404, 409) else 502, _message(body, resp.status))
                return body
    except TeamsError:
        raise
    except asyncio.TimeoutError as exc:
        raise TeamsError(504, f"Hermes 超过 {timeout} 秒没有响应") from exc
    except aiohttp.ClientError as exc:
        raise TeamsError(502, f"连不上 Hermes：{type(exc).__name__}") from exc


FILE_MAX_BYTES = 26 * 1024 * 1024


async def hermes_file(target: HermesTarget, path: str, *, timeout: int = 60) -> tuple[bytes, dict]:
    """A raw (non-JSON) GET from the plugin API: (body, headers). TeamsError on failure."""
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(target.url(path), headers=target.headers, ssl=AIOHTTP_CLIENT_SESSION_SSL) as resp:
                if resp.status >= 400:
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = await resp.text()
                    raise TeamsError(resp.status if resp.status in (400, 404, 409) else 502, _message(body, resp.status))
                if (resp.content_length or 0) > FILE_MAX_BYTES:
                    raise TeamsError(413, "文件太大")
                data = await resp.content.read(FILE_MAX_BYTES + 1)
                if len(data) > FILE_MAX_BYTES:
                    raise TeamsError(413, "文件太大")
                return data, dict(resp.headers)
    except TeamsError:
        raise
    except asyncio.TimeoutError as exc:
        raise TeamsError(504, f"Hermes 超过 {timeout} 秒没有响应") from exc
    except aiohttp.ClientError as exc:
        raise TeamsError(502, f"连不上 Hermes：{type(exc).__name__}") from exc


# --- planning ---------------------------------------------------------------------------------

def _keep(task: "asyncio.Task") -> None:
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _plan_job(team: AgentTeamModel, target: HermesTarget, feedback: str, previous: Optional[dict]) -> None:
    try:
        body = await hermes_call(target, "POST", "/plan", json_body={
            "goal": team.goal, "team_id": team.id, "feedback": feedback, "previous": previous,
            "lead_model": (team.meta or {}).get("lead_model") or "",
            "project": (team.meta or {}).get("project") or "",
        }, timeout=PLAN_TIMEOUT_SECONDS)
        ok = isinstance(body, dict) and body.get("ok") and isinstance(body.get("plan"), dict)
        if ok:
            plan = body["plan"]
            updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_ready",
                                        plan=plan, error=None, title=(plan.get("title") or team.title)[:60])
            if updated is not None and (team.meta or {}).get("auto_start") and auto_startable(plan):
                try:  # 「计划好直接开始」: no approval step
                    updated = await start_team(updated, target)
                except TeamsError as exc:
                    log.info("teams: auto-start of %s did not go through (%s)", team.id, exc.detail)
                    updated = AgentTeams.get(team.id, team.user_id) or updated
        else:
            error = (body or {}).get("error") if isinstance(body, dict) else None
            updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                        error=str(error or "负责人没有给出可用的计划")[:1000])
    except TeamsError as exc:
        updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                    error=exc.detail)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("agent team planning failed")
        updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                    error=f"规划出错：{type(exc).__name__}")
    if updated is not None and team_origin(updated):
        await _tell_origin(updated, target)


async def _tell_origin(team: AgentTeamModel, target: HermesTarget) -> None:
    """A team started from a chat outside HaloWebUI (Telegram): Hermes sends the plan (or why
    there is none) back there, with buttons to approve or cancel. Best effort."""
    try:
        await hermes_call(target, "POST", "/notify", json_body={"event": team.status, "team": public_team(team),
                                                              "origin": team_origin(team)},
                          timeout=CALL_TIMEOUT_SECONDS)
    except TeamsError as exc:
        log.info("teams: could not hand the plan of %s to Hermes for its chat (%s)", team.id, exc.detail)


def auto_startable(plan: dict) -> bool:
    """A plan starts without approval only when every member has a runner that can take it now
    (otherwise the user should see why first)."""
    members = [m for m in plan.get("members") or [] if isinstance(m, dict)]
    return bool(members) and all(m.get("runner") for m in members)


async def start_team(team: AgentTeamModel, target: HermesTarget) -> AgentTeamModel:
    """Hand the plan to Hermes: the board and its tasks are created and the members start.
    The approve button, Telegram's 批准 and 「计划好直接开始」 all go through here."""
    if not team.plan:
        raise TeamsError(409, "还没有可批准的计划")
    starting = AgentTeams.update(team.id, team.user_id, expect_status=("plan_ready", "start_failed"),
                                 status="starting", error=None)
    if starting is None:
        raise TeamsError(409, "这个计划已经批准过或状态已变化")
    try:
        result = await hermes_call(target, "POST", "", json_body={
            "team_id": team.id, "plan": team.plan, "goal": team.goal, "title": team.title, "chat_id": team.chat_id or "",
            "origin": team_origin(team),
        }, timeout=60)
    except TeamsError as exc:
        AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="start_failed",
                          error=f"启动失败：{exc.detail}")
        raise TeamsError(exc.status_code if exc.status_code < 500 else 502, f"启动失败：{exc.detail}")
    updated = AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="running", phase="running",
                                board=(result or {}).get("board"), approved_at=int(time.time()), error=None)
    return updated or team


def start_planning(team: AgentTeamModel, target: HermesTarget, feedback: str = "", previous: Optional[dict] = None) -> None:
    _keep(asyncio.create_task(_plan_job(team, target, feedback, previous)))


def default_title(goal: str) -> str:
    first = " ".join(goal.split())
    return (first[:28] + "…") if len(first) > 28 else first or "协作任务"


# --- reconciliation ---------------------------------------------------------------------------

async def reconcile(team: AgentTeamModel, target: Optional[HermesTarget]) -> tuple[AgentTeamModel, Optional[dict], Optional[str]]:
    """Fix rows whose background step died with the process, and read the live snapshot.

    Returns (team, snapshot or None, live error or None)."""
    now = int(time.time())
    if team.status == "planning" and now - team.updated_at > PLANNING_STALE_SECONDS:
        team = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                 error="规划被中断（服务重启或超时），请重新生成计划") or team
    if team.status not in ("running", "starting") or target is None:
        return team, None, None
    try:
        snap = await hermes_call(target, "GET", f"/{team.id}")
    except TeamsError as exc:
        if team.status == "starting" and exc.status_code == 404 and now - team.updated_at > STARTING_STALE_SECONDS:
            team = AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="start_failed",
                                     error="启动没有完成（Hermes 上找不到这个团队），请重新批准") or team
        return team, None, exc.detail
    live = snap.get("team") if isinstance(snap, dict) else None
    phase = (live or {}).get("phase")
    fields: dict = {}
    if team.status == "starting":
        fields.update(status="running", board=(live or {}).get("board"), approved_at=team.approved_at or now, error=None)
    if phase and phase != team.phase:
        fields["phase"] = phase
        if phase in ("completed", "stopped") and not team.finished_at:
            fields["finished_at"] = now
        elif phase not in ("completed", "stopped") and team.finished_at:
            fields["finished_at"] = None  # a finished team that got new work runs again
    progress = snapshot_progress(snap)
    if progress is not None and progress != (team.meta or {}).get("progress"):
        fields["meta"] = {**(team.meta or {}), "progress": progress}
    if fields:
        team = AgentTeams.update(team.id, team.user_id, **fields) or team
    return team, snap, None


def snapshot_progress(snap: Any) -> Optional[dict]:
    """How far a running team is, for the list: tasks done / running / needing you / total."""
    tasks = snap.get("tasks") if isinstance(snap, dict) else None
    if not isinstance(tasks, list):
        return None
    out = {"done": 0, "running": 0, "attention": 0, "total": len(tasks)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        sub = task.get("sub_status") or task.get("status")
        if task.get("status") in ("done", "archived"):
            out["done"] += 1
        elif sub in ("running", "review"):
            out["running"] += 1
        elif sub in ("failed", "blocked", "waiting_user", "stopped", "triage") or task.get("status") == "triage":
            out["attention"] += 1
    return out


def team_origin(team: AgentTeamModel) -> Optional[dict]:
    """Where the team was started from when that was not the browser (Telegram via Hermes)."""
    origin = (team.meta or {}).get("origin")
    return origin if isinstance(origin, dict) and origin.get("platform") else None


def deletable(team: AgentTeamModel) -> bool:
    """Only a team nothing is happening in can go: never planned, cancelled, failed, or finished."""
    if team.status in ("plan_ready", "plan_failed", "start_failed", "cancelled"):
        return True
    return team.status == "running" and team.phase in ("completed", "stopped")


def public_team(team: AgentTeamModel, *, with_plan: bool = True) -> dict:
    data = team.model_dump()
    data.pop("user_id", None)
    meta = data.pop("meta", None) or {}
    data["lead_model"] = meta.get("lead_model")
    data["auto_start"] = bool(meta.get("auto_start"))
    plan = data.get("plan") or {}
    data["member_count"] = len(plan.get("members") or [])
    data["task_count"] = len(plan.get("tasks") or [])
    data["executors"] = plan.get("executors") or []
    data["progress"] = meta.get("progress")
    data["origin"] = (meta.get("origin") or {}).get("platform") if isinstance(meta.get("origin"), dict) else None
    project = plan.get("project") if isinstance(plan.get("project"), dict) else None
    data["project"] = {"name": project.get("name"), "path": project.get("path")} if project else None
    data["deletable"] = deletable(team)
    # Where the conclusion went (the chat it was posted to, the knowledge base it was saved in).
    knowledge = meta.get("knowledge") if isinstance(meta.get("knowledge"), dict) else None
    posted = meta.get("chat_posted") if isinstance(meta.get("chat_posted"), dict) else None
    data["outputs"] = {
        "knowledge": {"id": knowledge.get("id"), "generated_at": knowledge.get("generated_at")} if knowledge else None,
        "chat_posted": {"generated_at": posted.get("generated_at")} if posted else None,
    }
    # Who is on the team, for the list's avatar stack (names and roles only).
    data["roster"] = [
        {"name": str(m.get("name") or "")[:40], "role": str(m.get("role") or "")[:40]}
        for m in (plan.get("members") or [])[:8]
        if isinstance(m, dict)
    ]
    if not with_plan:
        data.pop("plan", None)
    return data
