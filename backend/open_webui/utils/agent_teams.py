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


# --- planning ---------------------------------------------------------------------------------

def _keep(task: "asyncio.Task") -> None:
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _plan_job(team: AgentTeamModel, target: HermesTarget, feedback: str, previous: Optional[dict]) -> None:
    try:
        body = await hermes_call(target, "POST", "/plan", json_body={
            "goal": team.goal, "team_id": team.id, "feedback": feedback, "previous": previous,
        }, timeout=PLAN_TIMEOUT_SECONDS)
        ok = isinstance(body, dict) and body.get("ok") and isinstance(body.get("plan"), dict)
        if ok:
            plan = body["plan"]
            AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_ready",
                              plan=plan, error=None, title=(plan.get("title") or team.title)[:60])
        else:
            error = (body or {}).get("error") if isinstance(body, dict) else None
            AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                              error=str(error or "负责人没有给出可用的计划")[:1000])
    except TeamsError as exc:
        AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed", error=exc.detail)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("agent team planning failed")
        AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                          error=f"规划出错：{type(exc).__name__}")


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
    if fields:
        team = AgentTeams.update(team.id, team.user_id, **fields) or team
    return team, snap, None


def public_team(team: AgentTeamModel, *, with_plan: bool = True) -> dict:
    data = team.model_dump()
    data.pop("user_id", None)
    data.pop("meta", None)
    plan = data.get("plan") or {}
    data["member_count"] = len(plan.get("members") or [])
    data["task_count"] = len(plan.get("tasks") or [])
    data["executors"] = plan.get("executors") or []
    if not with_plan:
        data.pop("plan", None)
    return data
