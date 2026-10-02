"""协作台 (agent teams) API: /api/v1/teams.

Every route is per user: a team is only visible to and controllable by the user who created
it (administrators included — the global entry shows only your own teams). See
utils/agent_teams.py for the split between HaloWebUI and Hermes.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.models.agent_teams import AgentTeams
from open_webui.models.chats import Chats
from open_webui.utils.agent_teams import (
    ENABLE_AGENT_TEAMS,
    FEEDBACK_MAX_CHARS,
    GOAL_MAX_CHARS,
    TeamsError,
    default_title,
    hermes_call,
    hermes_target,
    public_team,
    reconcile,
    start_planning,
)
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)
router = APIRouter()


def _enabled():
    if not ENABLE_AGENT_TEAMS:
        raise HTTPException(status_code=404, detail="Not Found")


def _raise(exc: TeamsError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _own(team_id: str, user):
    team = AgentTeams.get(team_id, user.id)
    if team is None:
        raise HTTPException(status_code=404, detail="协作任务不存在")
    return team


class CreateTeamForm(BaseModel):
    goal: str = Field(min_length=1, max_length=GOAL_MAX_CHARS)
    chat_id: Optional[str] = Field(default=None, max_length=128)


class ReplanForm(BaseModel):
    feedback: str = Field(default="", max_length=FEEDBACK_MAX_CHARS)


class MemberExecutor(BaseModel):
    name: str = Field(max_length=40)
    executor: Literal["hermes", "reclaude"]


class PlanEditForm(BaseModel):
    members: list[MemberExecutor] = Field(max_length=12)


class MessageForm(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ControlForm(BaseModel):
    action: Literal["pause", "resume", "stop"]


@router.get("/", dependencies=[Depends(_enabled)])
async def list_teams(chat_id: Optional[str] = None, user=Depends(get_verified_user)):
    teams = AgentTeams.list_for_user(user.id, chat_id=chat_id)
    return {"teams": [public_team(t, with_plan=False) for t in teams]}


@router.post("/", dependencies=[Depends(_enabled)])
async def create_team(request: Request, form: CreateTeamForm, user=Depends(get_verified_user)):
    goal = form.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="请写下要协作完成的目标")
    chat_id = (form.chat_id or "").strip() or None
    if chat_id and Chats.get_chat_by_id_and_user_id(chat_id, user.id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    try:
        target = await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)
    team = AgentTeams.insert(user.id, goal, chat_id, default_title(goal))
    start_planning(team, target)
    return public_team(team)


@router.get("/{team_id}", dependencies=[Depends(_enabled)])
async def get_team(request: Request, team_id: str, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    target = None
    if team.status in ("running", "starting"):
        try:
            target = await hermes_target(request, user)
        except TeamsError as exc:
            return {"team": public_team(team), "live": None, "live_error": exc.detail}
    team, snap, live_error = await reconcile(team, target)
    return {"team": public_team(team), "live": snap, "live_error": live_error}


@router.post("/{team_id}/replan", dependencies=[Depends(_enabled)])
async def replan(request: Request, team_id: str, form: ReplanForm, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    try:
        target = await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)
    previous = team.plan
    updated = AgentTeams.update(team.id, user.id, expect_status=("plan_ready", "plan_failed", "start_failed"),
                                status="planning", error=None)
    if updated is None:
        raise HTTPException(status_code=409, detail="现在不能重新规划（计划已批准或正在规划）")
    start_planning(updated, target, form.feedback.strip(), previous)
    return public_team(updated)


@router.put("/{team_id}/plan", dependencies=[Depends(_enabled)])
async def edit_plan(team_id: str, form: PlanEditForm, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if team.status not in ("plan_ready", "start_failed") or not team.plan:
        raise HTTPException(status_code=409, detail="只有待批准的计划可以修改")
    plan = dict(team.plan)
    chosen = {m.name: m.executor for m in form.members}
    members = []
    for member in plan.get("members") or []:
        member = dict(member)
        if member.get("name") in chosen:
            member["executor"] = chosen[member["name"]]
        members.append(member)
    plan["members"] = members
    plan["executors"] = sorted({m.get("executor") or "hermes" for m in members})
    updated = AgentTeams.update(team.id, user.id, expect_status=("plan_ready", "start_failed"), plan=plan)
    if updated is None:
        raise HTTPException(status_code=409, detail="计划状态已变化，请刷新")
    return public_team(updated)


@router.post("/{team_id}/approve", dependencies=[Depends(_enabled)])
async def approve(request: Request, team_id: str, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if not team.plan:
        raise HTTPException(status_code=409, detail="还没有可批准的计划")
    try:
        target = await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)
    starting = AgentTeams.update(team.id, user.id, expect_status=("plan_ready", "start_failed"),
                                 status="starting", error=None)
    if starting is None:
        raise HTTPException(status_code=409, detail="这个计划已经批准过或状态已变化")
    try:
        result = await hermes_call(target, "POST", "", json_body={
            "team_id": team.id, "plan": team.plan, "goal": team.goal, "title": team.title, "chat_id": team.chat_id or "",
        }, timeout=60)
    except TeamsError as exc:
        AgentTeams.update(team.id, user.id, expect_status=("starting",), status="start_failed",
                          error=f"启动失败：{exc.detail}")
        raise HTTPException(status_code=exc.status_code if exc.status_code < 500 else 502, detail=f"启动失败：{exc.detail}")
    import time as _time

    updated = AgentTeams.update(team.id, user.id, expect_status=("starting",), status="running", phase="running",
                                board=(result or {}).get("board"), approved_at=int(_time.time()), error=None)
    return public_team(updated or team)


@router.post("/{team_id}/cancel", dependencies=[Depends(_enabled)])
async def cancel(team_id: str, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    updated = AgentTeams.update(team.id, user.id, expect_status=("planning", "plan_ready", "plan_failed", "start_failed"),
                                status="cancelled")
    if updated is None:
        raise HTTPException(status_code=409, detail="已经开始执行的协作任务请用「停止」")
    return public_team(updated)


async def _running_target(request: Request, team_id: str, user):
    team = _own(team_id, user)
    if team.status != "running":
        raise HTTPException(status_code=409, detail="这个协作任务还没有开始执行")
    try:
        return team, await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)


@router.get("/{team_id}/events", dependencies=[Depends(_enabled)])
async def events(request: Request, team_id: str, after: int = 0, limit: int = 500, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if team.status != "running":
        return {"events": [], "next_after": 0, "has_more": False, "latest_seq": 0, "reconcile": []}
    try:
        target = await hermes_target(request, user)
        return await hermes_call(target, "GET", f"/{team.id}/events",
                                 params={"after": max(0, int(after)), "limit": max(1, min(int(limit), 2000))})
    except TeamsError as exc:
        _raise(exc)


@router.get("/{team_id}/tasks/{task_id}", dependencies=[Depends(_enabled)])
async def task_detail(request: Request, team_id: str, task_id: str, log: bool = False,
                      user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "GET", f"/{team.id}/tasks/{_task_id(task_id)}",
                                 params={"log": "1" if log else "0"})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/tasks/{task_id}/messages", dependencies=[Depends(_enabled)])
async def send_message(request: Request, team_id: str, task_id: str, form: MessageForm,
                       user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/tasks/{_task_id(task_id)}/messages",
                                 json_body={"body": form.body, "author_name": user.name or "用户"})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/tasks/{task_id}/retry", dependencies=[Depends(_enabled)])
async def retry_task(request: Request, team_id: str, task_id: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/tasks/{_task_id(task_id)}/retry",
                                 json_body={"actor": user.name or ""})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/control", dependencies=[Depends(_enabled)])
async def control(request: Request, team_id: str, form: ControlForm, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        result = await hermes_call(target, "POST", f"/{team.id}/control",
                                   json_body={"action": form.action, "actor": user.name or ""})
    except TeamsError as exc:
        _raise(exc)
    if form.action == "stop":
        import time as _time

        AgentTeams.update(team.id, user.id, phase="stopped", finished_at=team.finished_at or int(_time.time()))
    elif form.action in ("pause", "resume"):
        AgentTeams.update(team.id, user.id, phase="paused" if form.action == "pause" else "running")
    return result


def _task_id(task_id: str) -> str:
    import re

    if not re.match(r"^t_[0-9a-f]{4,32}$", task_id or ""):
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_id
