"""协作台 (agent teams) API: /api/v1/teams.

Every route is per user: a team is only visible to and controllable by the user who created
it (administrators included — the global entry shows only your own teams). See
utils/agent_teams.py for the split between HaloWebUI and Hermes.
"""

import asyncio
import hmac
import logging
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.models.agent_teams import AgentTeams
from open_webui.models.chats import Chats
from open_webui.models.users import Users
from open_webui.utils.agent_teams import (
    ENABLE_AGENT_TEAMS,
    AssistantAccess,
    FEEDBACK_MAX_CHARS,
    GOAL_MAX_CHARS,
    TeamsError,
    default_title,
    deletable,
    hermes_call,
    hermes_file,
    INPUT_FILES_MAX,
    hermes_target,
    image_templates,
    input_files,
    mark_reverted,
    planning_progress,
    preferred_refs,
    public_team,
    reconcile,
    stage_brief,
    stage_of,
    start_planning,
    start_team,
)
from open_webui.utils.agent_team_outputs import concluded, follow_up, save_to_knowledge
from open_webui.utils import team_chats
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
    # One of the models Hermes has configured for the lead (plan + conclusion); empty = Hermes' default.
    lead_model: Optional[str] = Field(default=None, max_length=120)
    # Where the team works: a git repository on the Hermes host (its path), "none" = a fresh
    # directory, empty = the project the goal names, if any (Hermes decides).
    project: Optional[str] = Field(default=None, max_length=500)
    # 「计划好直接开始」: approve the plan as soon as it is ready (when every member can run now).
    auto_start: bool = False
    # Files uploaded for the team (their ids, /api/v1/files): copied into its workspace's inputs/.
    files: list[str] = Field(default_factory=list, max_length=INPUT_FILES_MAX)
    # 「用于协作」 from the assistant library: assistants (model:<id> / builtin:<id>) at least one
    # member must use; the lead staffs them, the plan check assigns them if it did not.
    assistants: list[str] = Field(default_factory=list, max_length=3)


class ReplanForm(BaseModel):
    feedback: str = Field(default="", max_length=FEEDBACK_MAX_CHARS)
    # None = keep the plan's project; "none" = a fresh directory; a path = that repository.
    project: Optional[str] = Field(default=None, max_length=500)


class MemberExecutor(BaseModel):
    name: str = Field(max_length=40)
    # Hermes members, or one of the runners the Hermes teams plugin can drive (see its runners.py).
    # None: the runner stays as it is (only the model changes).
    executor: Optional[Literal["hermes", "reclaude", "cchclaude", "anyclaude", "codex", "agy"]] = None
    # "user": the user picked this runner (the automatic choice never overrides it; it still falls
    # back when the runner is down). "auto": back to the runner the member's task kind defaults to.
    source: Literal["user", "auto"] = "user"
    # The model the member runs on when it runs on Hermes (one Hermes has configured; Hermes checks).
    model: Optional[str] = Field(default=None, max_length=80)
    # "user": the user picked it. "auto": back to what the lead recommended.
    model_source: Literal["user", "auto"] = "user"


class PlanEditForm(BaseModel):
    members: list[MemberExecutor] = Field(max_length=12)


class MessageForm(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ControlForm(BaseModel):
    action: Literal["pause", "resume", "stop"]


class AdjustForm(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class RunnerCheckForm(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=12)


@router.get("/meta", dependencies=[Depends(_enabled)])
async def meta(request: Request, user=Depends(get_verified_user)):
    """The lead's model (Hermes' default), runners with availability, task kinds, assistant templates."""
    try:
        target = await hermes_target(request, user)
        data = await hermes_call(target, "GET", "/meta", timeout=40)
    except TeamsError as exc:
        _raise(exc)
    if isinstance(data, dict):
        # The user's own image templates (names only): the styles 「为结果配图」 can draw in.
        data["image_templates"] = [{k: t[k] for k in ("id", "name", "tags", "aspect")}
                                   for t in image_templates(user.id)]
    return data


@router.post("/runners/check", dependencies=[Depends(_enabled)])
async def check_runners(request: Request, form: RunnerCheckForm, user=Depends(get_verified_user)):
    try:
        target = await hermes_target(request, user)
        return await hermes_call(target, "POST", "/runners/check", json_body={"names": form.names}, timeout=40)
    except TeamsError as exc:
        _raise(exc)


LIST_REFRESH_LIMIT = 6
LIST_REFRESH_SECONDS = 4
RECENT_FINISH_SECONDS = 600


@router.get("/", dependencies=[Depends(_enabled)])
async def list_teams(request: Request, chat_id: Optional[str] = None, user=Depends(get_verified_user)):
    teams, snaps = await _fresh_list(request, user, chat_id)
    if not chat_id:  # every team is in the chat history: earlier ones get their chat now
        teams = await team_chats.backfill(request, user, teams)
    return {"teams": _with_stages(teams, snaps)}


def _with_stages(teams: list, snaps: dict) -> list[dict]:
    out = []
    for team in teams:
        data = public_team(team, with_plan=False)
        stage = stage_brief(stage_of(team, snaps.get(team.id)))
        if stage:
            data["stage"] = stage
        out.append(data)
    return out


def _recently_finished(team, now: int) -> bool:
    """A team that finished in the last minutes: its conclusion / acceptance may still be underway."""
    return (team.status == "running" and team.phase == "completed" and not (team.meta or {}).get("settled")
            and now - int(team.finished_at or 0) < RECENT_FINISH_SECONDS)


async def _fresh_list(request: Request, user, chat_id: Optional[str] = None, target=None):
    """(teams, {team id: live snapshot}) — the user's teams, those at work read from Hermes once."""
    teams = AgentTeams.list_for_user(user.id, chat_id=chat_id)
    snaps: dict = {}
    # Teams still at work are read from Hermes once here, so the list shows where they are now
    # (phase, tasks done, stage, estimate) without opening each one; so are teams that just finished
    # (the lead may still be writing the result). Best effort and bounded: a slow or missing Hermes
    # leaves the last recorded state.
    now = int(time.time())
    live = [t for t in teams if (t.status in ("running", "starting") and t.phase not in ("completed", "stopped"))
            or _recently_finished(t, now)]
    if live:
        if target is None:
            try:
                target = await hermes_target(request, user)
            except TeamsError:
                target = None
        if target is not None:
            async def refresh(team):
                try:
                    fresh, snap, _err = await asyncio.wait_for(reconcile(team, target), LIST_REFRESH_SECONDS)
                    if snap is not None:
                        snaps[team.id] = snap
                    return fresh
                except Exception:  # noqa: BLE001 — the list must load even when Hermes does not answer
                    return team
            fresh = await asyncio.gather(*(refresh(t) for t in live[:LIST_REFRESH_LIMIT]))
            by_id = {t.id: t for t in fresh}
            teams = [by_id.get(t.id, t) for t in teams]
    return teams, snaps


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
    inputs = input_files(form.files, user)
    if form.files and len(inputs) < len(set(form.files)):
        raise HTTPException(status_code=404, detail="有附件找不到（没上传成功，或不是你的文件）")
    return public_team(await _start(request, user, goal, target, chat_id=chat_id, lead_model=form.lead_model,
                                    project=form.project, auto_start=form.auto_start, inputs=inputs,
                                    assistants=preferred_refs(form.assistants), access=AssistantAccess(request, user)))


async def _start(request: Request, user, goal: str, target, *, chat_id: Optional[str] = None,
                 lead_model: Optional[str] = None, origin: Optional[dict] = None, project: Optional[str] = None,
                 auto_start: bool = False, inputs: Optional[list] = None, assistants: Optional[list] = None,
                 access=None):
    meta: dict = {}
    if inputs:
        meta["inputs"] = inputs
    if assistants:
        meta["assistants"] = assistants
    if auto_start:
        meta["auto_start"] = True
    if (lead_model or "").strip():
        meta["lead_model"] = lead_model.strip()
    if (project or "").strip():
        meta["project"] = project.strip()
    if origin:
        meta["origin"] = origin
    team = AgentTeams.insert(user.id, goal, chat_id, default_title(goal), meta=meta or None)
    # in the chat history from the start: its own chat, or the card in the chat it came from
    team = await team_chats.attach(request, user, team)
    start_planning(team, target, access=access)
    return team


@router.get("/{team_id}", dependencies=[Depends(_enabled)])
async def get_team(request: Request, team_id: str, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    target = None
    if team.status in ("running", "starting"):
        try:
            target = await hermes_target(request, user)
        except TeamsError as exc:
            return {"team": public_team(team), "live": None, "live_error": exc.detail}
    planning = None
    if team.status == "planning":
        try:
            planning = await planning_progress(team, await hermes_target(request, user))
        except TeamsError:
            planning = None
    team, snap, live_error = await reconcile(team, target)
    data = public_team(team)
    if team.chat_id and Chats.get_chat_by_id_and_user_id(team.chat_id, user.id) is None:
        data["chat_id"] = None  # the chat was deleted: no way back to it
    return {"team": data, "live": snap, "live_error": live_error, "stage": stage_of(team, snap, planning)}


@router.post("/{team_id}/replan", dependencies=[Depends(_enabled)])
async def replan(request: Request, team_id: str, form: ReplanForm, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    try:
        target = await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)
    return public_team(_replan(team, user, target, form.feedback, form.project, access=AssistantAccess(request, user)))


def _replan(team, user, target, feedback: str, project: Optional[str] = None, access=None):
    """A new plan from the lead. Like the first one it only records assistant decisions; nothing
    is written to the library until the plan is approved."""
    previous = team.plan
    fields: dict = {}
    if project is not None:  # the user picked another place to work: the next plan uses it
        fields["meta"] = {**(team.meta or {}), "project": project.strip() or "none"}
    updated = AgentTeams.update(team.id, user.id, expect_status=("plan_ready", "plan_failed", "start_failed"),
                                status="planning", error=None, **fields)
    if updated is None:
        raise HTTPException(status_code=409, detail="现在不能重新规划（计划已批准或正在规划）")
    start_planning(updated, target, feedback.strip(), previous, access=access)
    return updated


@router.put("/{team_id}/plan", dependencies=[Depends(_enabled)])
async def edit_plan(request: Request, team_id: str, form: PlanEditForm, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if team.status not in ("plan_ready", "start_failed") or not team.plan:
        raise HTTPException(status_code=409, detail="只有待批准的计划可以修改")
    plan = dict(team.plan)
    chosen = {m.name: m for m in form.members}
    members = []
    for member in plan.get("members") or []:
        member = dict(member)
        pick = chosen.get(member.get("name"))
        if pick is not None and pick.executor is not None:
            member["executor"] = pick.executor
            member["executor_source"] = pick.source
            if pick.source == "auto":
                member["executor"] = member.get("recommended") or pick.executor
        if pick is not None and (pick.model is not None or pick.model_source == "auto"):
            if pick.model_source == "auto":
                recommended = member.get("model_recommended") or ""
                member["model"] = recommended
                member["model_source"] = "lead" if recommended else "default"
            else:
                member["model"] = pick.model.strip()
                member["model_source"] = "user"
        members.append(member)
    plan["members"] = members
    # Hermes works out which runner will actually run each member now (availability, fallback).
    resolved = None
    try:
        target = await hermes_target(request, user)
        sent = {k: v for k, v in plan.items() if k != "assistants_applied"}
        resolved = await hermes_call(target, "POST", "/plan/resolve", json_body={"plan": sent}, timeout=40)
    except TeamsError as exc:
        log.info("teams: plan resolve unavailable (%s); keeping the edit as is", exc.detail)
    if isinstance(resolved, dict) and isinstance(resolved.get("plan"), dict):
        fresh = resolved["plan"]
        # what only HaloWebUI keeps (the assistants a failed start already applied) and what an older
        # Hermes may not echo back (the recorded assistant decisions)
        for key in ("assistants_applied", "assistant_proposals", "assistant_library"):
            if key in plan and key not in fresh:
                fresh[key] = plan[key]
        mine = {m.get("name"): m for m in plan["members"]}
        for member in fresh.get("members") or []:
            if isinstance(member, dict) and "assistant" not in member and member.get("name") in mine:
                member["assistant"] = mine[member["name"]].get("assistant")
        plan = fresh
    else:  # Hermes is checked again at approval; until then show the choice as the runner
        for member in plan["members"]:
            member["runner"] = member.get("executor")
            member["runner_note"] = ""
    plan["executors"] = sorted({m.get("runner") or m.get("executor") or "hermes" for m in plan["members"]})
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
    return public_team(await _approve(team, user, target, AssistantAccess(request, user)))


async def _approve(team, user, target, access=None):
    try:
        return await start_team(team, target, access)
    except TeamsError as exc:
        _raise(exc)


class RevertedForm(BaseModel):
    id: str = Field(min_length=1, max_length=200)


@router.post("/{team_id}/assistants/reverted", dependencies=[Depends(_enabled)])
async def assistant_reverted(team_id: str, form: RevertedForm, user=Depends(get_verified_user)):
    """After 「撤销升级」 (POST /api/v1/assistant-library/undo with run_ref team:<id>): record it on
    the team, once the library shows the undo of this team's upgrade as the assistant's last change."""
    from open_webui.models.models import Models
    from open_webui.utils import assistant_library as lib

    team = _own(team_id, user)
    row = Models.get_model_by_id(form.id)
    revisions = lib.lib_meta(row.meta)["revisions"] if row is not None else []
    last = revisions[-1] if revisions else {}
    if last.get("source") != "undo" or last.get("runRef") != f"team:{team.id}":
        raise HTTPException(status_code=409, detail="这次升级还没有撤销")
    updated = mark_reverted(team, form.id)
    if updated is None:
        raise HTTPException(status_code=404, detail="这个协作任务没有升级过这个助手")
    return public_team(updated)


@router.post("/{team_id}/cancel", dependencies=[Depends(_enabled)])
async def cancel(team_id: str, user=Depends(get_verified_user)):
    return public_team(_cancel(_own(team_id, user), user))


def _cancel(team, user):
    updated = AgentTeams.update(team.id, user.id, expect_status=("planning", "plan_ready", "plan_failed", "start_failed"),
                                status="cancelled")
    if updated is None:
        raise HTTPException(status_code=409, detail="已经开始执行的协作任务请用「停止」")
    return updated


@router.delete("/{team_id}", dependencies=[Depends(_enabled)])
async def delete_team(team_id: str, user=Depends(get_verified_user)):
    """Remove a team from your list. Only when nothing runs in it; the files its members wrote
    stay in the workspace on Hermes."""
    team = _own(team_id, user)
    if team.status == "planning":
        raise HTTPException(status_code=409, detail="负责人正在制定计划，等计划出来再删除")
    if not deletable(team):
        raise HTTPException(status_code=409, detail="正在执行的协作任务要先停止才能删除")
    AgentTeams.delete(team.id, user.id)
    return {"ok": True, "id": team.id}


async def _running_target(request: Request, team_id: str, user):
    team = _own(team_id, user)
    if team.status != "running":
        raise HTTPException(status_code=409, detail="这个协作任务还没有开始执行")
    try:
        return team, await hermes_target(request, user)
    except TeamsError as exc:
        _raise(exc)


@router.get("/{team_id}/events", dependencies=[Depends(_enabled)])
async def events(request: Request, team_id: str, after: int = 0, limit: int = 500, visible: int = 0,
                 user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if team.status != "running":
        return {"events": [], "next_after": 0, "has_more": False, "latest_seq": 0, "reconcile": []}
    params = {"after": max(0, int(after)), "limit": max(1, min(int(limit), 2000))}
    if visible:  # the page is in front of the user: Hermes holds back its Telegram notices for this team
        params["visible"] = "1"
    try:
        target = await hermes_target(request, user)
        return await hermes_call(target, "GET", f"/{team.id}/events", params=params)
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
        AgentTeams.update(team.id, user.id, phase="stopped", finished_at=team.finished_at or int(time.time()))
    elif form.action in ("pause", "resume"):
        AgentTeams.update(team.id, user.id, phase="paused" if form.action == "pause" else "running")
    return result


@router.get("/{team_id}/conclusion", dependencies=[Depends(_enabled)])
async def get_conclusion(request: Request, team_id: str, user=Depends(get_verified_user)):
    team = _own(team_id, user)
    if team.status != "running":
        return {"status": "none", "markdown": "", "tasks": [], "files": [], "entry": {}}
    try:
        target = await hermes_target(request, user)
        return await hermes_call(target, "GET", f"/{team.id}/conclusion", timeout=40)
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/conclusion", dependencies=[Depends(_enabled)])
async def make_conclusion(request: Request, team_id: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/conclusion", json_body={})
    except TeamsError as exc:
        _raise(exc)


class IllustrateForm(BaseModel):
    # One of the user's image templates (HaloWebUI 生图模板); empty = Hermes' hand-drawn infographic.
    template_id: Optional[str] = Field(default=None, max_length=120)


@router.post("/{team_id}/conclusion/illustrate", dependencies=[Depends(_enabled)])
async def conclusion_illustrate(request: Request, team_id: str, form: IllustrateForm,
                                user=Depends(get_verified_user)):
    """「为结果配图」: gpt-image draws the result in one of the user's template styles (async)."""
    team, target = await _running_target(request, team_id, user)
    template = None
    if form.template_id:
        template = next((t for t in image_templates(user.id) if t["id"] == form.template_id), None)
        if template is None:
            raise HTTPException(status_code=404, detail="没有这个生图模板")
    try:
        return await hermes_call(target, "POST", f"/{team.id}/conclusion/illustrate",
                                 json_body={"template": template} if template else {})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/conclusion/chat", dependencies=[Depends(_enabled)])
async def conclusion_chat(request: Request, team_id: str, user=Depends(get_verified_user)):
    """「在对话里追问」: the team's chat (or a new one) with the conclusion in it → {chat_id}."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await follow_up(request, user, team, target)
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/conclusion/knowledge", dependencies=[Depends(_enabled)])
async def conclusion_knowledge(request: Request, team_id: str, user=Depends(get_verified_user)):
    """「存入知识库」: the conclusion into the user's own 「协作结论」 knowledge base."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await save_to_knowledge(request, user, team, target)
    except TeamsError as exc:
        _raise(exc)


@router.get("/{team_id}/files", dependencies=[Depends(_enabled)])
async def list_files(request: Request, team_id: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "GET", f"/{team.id}/files")
    except TeamsError as exc:
        _raise(exc)


# --- the lead after approval (对负责人说, failure diagnosis, acceptance gaps; see lead.py in the plugin)


def _reopened(team, result) -> None:
    """New work on a finished team: it runs again (the page and the list follow at once)."""
    if isinstance(result, dict) and result.get("reopened"):
        AgentTeams.update(team.id, team.user_id, phase="running", finished_at=None)


@router.post("/{team_id}/adjust", dependencies=[Depends(_enabled)])
async def adjust(request: Request, team_id: str, form: AdjustForm, user=Depends(get_verified_user)):
    """Say something to the lead; it proposes a plan change in the background (snapshot → team.change)."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/adjust",
                                 json_body={"text": form.text, "actor": user.name or ""})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/adjust/gaps", dependencies=[Depends(_enabled)])
async def fill_gaps(request: Request, team_id: str, user=Depends(get_verified_user)):
    """「让团队补上」: the lead's acceptance gaps as a change request."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/adjust/gaps", json_body={"actor": user.name or ""})
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/change/{change_id}/{action}", dependencies=[Depends(_enabled)])
async def decide_change(request: Request, team_id: str, change_id: str, action: Literal["apply", "discard"],
                        user=Depends(get_verified_user)):
    import re

    if not re.match(r"^[0-9a-f]{8}$", change_id or ""):
        raise HTTPException(status_code=404, detail="提案不存在")
    team, target = await _running_target(request, team_id, user)
    try:
        result = await hermes_call(target, "POST", f"/{team.id}/change/{change_id}/{action}",
                                   json_body={"actor": user.name or ""}, timeout=60)
    except TeamsError as exc:
        _raise(exc)
    _reopened(team, result)
    return result


@router.post("/{team_id}/tasks/{task_id}/diagnosis/{action}", dependencies=[Depends(_enabled)])
async def task_diagnosis(request: Request, team_id: str, task_id: str, action: Literal["apply", "again"],
                         user=Depends(get_verified_user)):
    """Apply the lead's suggestion for a failed task, or have it look again."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/tasks/{_task_id(task_id)}/diagnosis/{action}",
                                 json_body={"actor": user.name or ""}, timeout=60)
    except TeamsError as exc:
        _raise(exc)


class PushForm(BaseModel):
    what: Literal["branch", "base"]


@router.get("/{team_id}/changes", dependencies=[Depends(_enabled)])
async def get_changes(request: Request, team_id: str, user=Depends(get_verified_user)):
    """A team that worked on a project: its branch, commits and changed files."""
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "GET", f"/{team.id}/changes", timeout=40)
    except TeamsError as exc:
        _raise(exc)


@router.get("/{team_id}/changes/diff", dependencies=[Depends(_enabled)])
async def get_change_diff(request: Request, team_id: str, path: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    if not path or len(path) > 1000 or "\x00" in path:
        raise HTTPException(status_code=400, detail="路径不对")
    try:
        return await hermes_call(target, "GET", f"/{team.id}/changes/diff", params={"path": path}, timeout=40)
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/changes/merge", dependencies=[Depends(_enabled)])
async def merge_changes(request: Request, team_id: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/changes/merge", json_body={}, timeout=120)
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/changes/push", dependencies=[Depends(_enabled)])
async def push_changes(request: Request, team_id: str, form: PushForm, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/changes/push", json_body={"what": form.what}, timeout=200)
    except TeamsError as exc:
        _raise(exc)


@router.post("/{team_id}/changes/discard", dependencies=[Depends(_enabled)])
async def discard_changes(request: Request, team_id: str, user=Depends(get_verified_user)):
    team, target = await _running_target(request, team_id, user)
    try:
        return await hermes_call(target, "POST", f"/{team.id}/changes/discard", json_body={}, timeout=120)
    except TeamsError as exc:
        _raise(exc)


_PASS_HEADERS = ("Content-Type", "Content-Disposition", "Cache-Control", "Content-Security-Policy")


@router.get("/{team_id}/files/{path:path}", dependencies=[Depends(_enabled)])
async def get_file(request: Request, team_id: str, path: str, user=Depends(get_verified_user)):
    """A file from the team's workspace (images in the conclusion load through here with the
    session cookie). Confinement to the workspace is enforced by Hermes; HTML comes back as text."""
    from urllib.parse import quote

    from fastapi.responses import Response

    team, target = await _running_target(request, team_id, user)
    if not path or len(path) > 1000 or "\x00" in path:
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        data, headers = await hermes_file(target, f"/{team.id}/files/{quote(path)}")
    except TeamsError as exc:
        _raise(exc)
    out = {k: headers[k] for k in _PASS_HEADERS if headers.get(k)}
    out["X-Content-Type-Options"] = "nosniff"
    media = out.pop("Content-Type", "application/octet-stream")
    return Response(content=data, media_type=media, headers=out)


def _task_id(task_id: str) -> str:
    import re

    if not re.match(r"^t_[0-9a-f]{4,32}$", task_id or ""):
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_id


# --- Hermes calling back --------------------------------------------------------------------------
# Hermes (the halowebui-teams plugin) starts and approves teams for a user from Telegram. It
# proves who it is with the key HaloWebUI itself uses to call that user's Hermes (the API key of
# the user's Hermes connection) and names the user in X-Halo-Owner; the team is then theirs, with
# the same plan / approval flow as in the browser. Only the steps before execution live here:
# once a team runs, Hermes drives it on its own board.

_HERMES_AUTH_TTL = 60
_hermes_auth_cache: dict = {}


class HermesCreateForm(BaseModel):
    goal: str = Field(min_length=1, max_length=GOAL_MAX_CHARS)
    origin: dict = Field(default_factory=dict)
    auto_start: bool = False


async def _hermes_caller(request: Request):
    _enabled()
    key = (request.headers.get("X-Hermes-Key") or "").strip()
    owner = (request.headers.get("X-Halo-Owner") or "").strip()
    denied = HTTPException(status_code=401, detail="unauthorized")
    if not key or not owner or len(owner) > 64 or len(key) > 512:
        raise denied
    user = Users.get_user_by_id(owner)
    if user is None:
        raise denied
    now = time.monotonic()
    cached = _hermes_auth_cache.get(owner)
    if cached and cached[0] > now:
        target = cached[1]
    else:
        try:
            target = await hermes_target(request, user)
        except TeamsError:
            raise denied
        _hermes_auth_cache[owner] = (now + _HERMES_AUTH_TTL, target)
    expected = target.headers.get("Authorization") or ""
    if not expected or not hmac.compare_digest(expected.encode(), f"Bearer {key}".encode()):
        _hermes_auth_cache.pop(owner, None)
        raise denied
    return user, target


def _clean_origin(origin: dict) -> Optional[dict]:
    if not isinstance(origin, dict):
        return None
    out = {k: str(origin.get(k) or "").strip()[:64] for k in ("platform", "chat_id", "user_id", "thread_id")}
    out = {k: v for k, v in out.items() if v}
    return out if out.get("platform") else None


@router.get("/hermes/teams")
async def hermes_list(request: Request, caller=Depends(_hermes_caller)):
    user, target = caller
    return {"teams": _with_stages(*await _fresh_list(request, user, target=target))}


@router.post("/hermes/teams")
async def hermes_create(request: Request, form: HermesCreateForm, caller=Depends(_hermes_caller)):
    user, target = caller
    goal = form.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="请写下要协作完成的目标")
    return public_team(await _start(request, user, goal, target, origin=_clean_origin(form.origin),
                                    auto_start=form.auto_start, access=AssistantAccess(request, user)))


@router.get("/hermes/teams/{team_id}")
async def hermes_get(request: Request, team_id: str, caller=Depends(_hermes_caller)):
    user, target = caller
    team, _snap, _err = await reconcile(_own(team_id, user), None)
    return public_team(team)


@router.post("/hermes/teams/{team_id}/sync")
async def hermes_sync(request: Request, team_id: str, caller=Depends(_hermes_caller)):
    """Hermes changed a running team on its own (a change applied from Telegram reopened it):
    read its live state now, so the list shows it at work again."""
    user, target = caller
    team, _snap, _err = await reconcile(_own(team_id, user), target)
    return public_team(team, with_plan=False)


class ConcludedForm(BaseModel):
    # Hermes tells Telegram about this team's finish itself: no away push from here.
    telegram: bool = False


@router.post("/hermes/teams/{team_id}/concluded")
async def hermes_concluded(request: Request, team_id: str, form: ConcludedForm, caller=Depends(_hermes_caller)):
    """The lead has written the team's conclusion: it goes into the chat the team came from."""
    user, target = caller
    team, _snap, _err = await reconcile(_own(team_id, user), target)
    if team.status != "running":
        return {"posted": False, "reason": "not running"}
    try:
        return await concluded(request, team, target, telegram=form.telegram)
    except TeamsError as exc:
        _raise(exc)


@router.post("/hermes/teams/{team_id}/knowledge")
async def hermes_knowledge(request: Request, team_id: str, caller=Depends(_hermes_caller)):
    """「存入知识库」 from Telegram."""
    user, target = caller
    team = _own(team_id, user)
    if team.status != "running":
        raise HTTPException(status_code=409, detail="这个协作任务还没有开始执行")
    try:
        return await save_to_knowledge(request, user, team, target)
    except TeamsError as exc:
        _raise(exc)


@router.post("/hermes/teams/{team_id}/approve")
async def hermes_approve(request: Request, team_id: str, caller=Depends(_hermes_caller)):
    user, target = caller
    return public_team(await _approve(_own(team_id, user), user, target, AssistantAccess(request, user)))


@router.post("/hermes/teams/{team_id}/cancel")
async def hermes_cancel(request: Request, team_id: str, caller=Depends(_hermes_caller)):
    user, _target = caller
    return public_team(_cancel(_own(team_id, user), user))


@router.post("/hermes/teams/{team_id}/replan")
async def hermes_replan(request: Request, team_id: str, form: ReplanForm, caller=Depends(_hermes_caller)):
    user, target = caller
    return public_team(_replan(_own(team_id, user), user, target, form.feedback, form.project,
                               access=AssistantAccess(request, user)))
