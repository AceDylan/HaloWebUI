"""Automatic workbench: one durable request, at most one dispatch attempt."""

import asyncio
import hashlib
import json
import logging
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from open_webui.models.auto_routes import AutoRoutes
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.utils.auth import get_verified_user
from open_webui.utils.auto_routing import PATHS, normalize_selection, selection_messages, preferred_routing_model

router = APIRouter()
log = logging.getLogger(__name__)
_jobs: dict[str, asyncio.Task] = {}


class CreateForm(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    client_key: str = Field(min_length=1, max_length=128)
    files: list[str] = Field(default_factory=list, max_length=4)
    context: str = Field(default="", max_length=12000)
    research: bool = True
    preference: Literal["standard", "economy"] = "standard"
    mode: Literal["auto", "answer", "discuss", "team"] = "auto"
    auto_start: bool = False


def _own(id, user):
    row = AutoRoutes.get(id, user.id)
    if row is None:
        raise HTTPException(404, "这条分流记录不存在")
    return _settle(row, user)


def _settle(row, user):
    id = row["id"]
    # A crashed process must never silently repeat an uncertain dispatch.
    if row["status"] in ("routing", "dispatching") and row["updated_at"] < time.time() - 600:
        row = AutoRoutes.update(id, user.id, expect=(row["status"],), status="interrupted",
            data={**row["data"], "error": "分流已中断；如已创建任务，请打开原任务查看，勿重复提交"}) or row
    return row


def public(row, user, targets=None):
    data = row["data"]
    mode, target = row.get("mode"), row.get("target_id")
    result = {"id": row["id"], "question": data["input"]["question"], "status": row["status"],
        "mode": mode, "target_id": target, "reason": data.get("reason", ""),
        "error": data.get("error", ""), "created_at": row["created_at"],
        "href": PATHS[mode] + target if mode in PATHS and target else None,
        "auto_start": bool(data.get("auto_start")), "target_status": None,
        "title": data["input"]["question"][:80], "routing_model": data.get("routing_model")}
    if targets is not None:
        info = targets.get((mode, target)) if target else None
        if target:
            result.update(info or {"target_status": "deleted"})
        return result
    if target and mode == "team":
        from open_webui.models.agent_teams import AgentTeams
        team = AgentTeams.get(target, user.id)
        result["target_status"] = team.status if team else "deleted"
        if team:
            result["title"] = team.title or result["title"]
        if team and team.phase:
            result["target_status"] = team.phase
    elif target and mode in ("answer", "discuss"):
        chat = Chats.get_chat_by_id_and_user_id(target, user.id)
        key = "answer_desk" if mode == "answer" else "discussion_room"
        if chat:
            result["title"] = chat.title if chat.title != "New Chat" else result["title"]
        result["target_status"] = (chat.meta or {}).get(key, {}).get("status") if chat else "deleted"
    return result


def _files(ids, user):
    items = []
    for id in dict.fromkeys(ids):
        file = Files.get_file_by_id(id)
        if file is None or file.user_id != user.id:
            raise HTTPException(404, "有附件不存在或不属于你")
        items.append({"name": file.filename[:200], "type": (file.meta or {}).get("content_type", "")})
    return items


async def select(request, user, form, file_info):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library as lib
    from open_webui.utils.agent_teams import ENABLE_AGENT_TEAMS, TeamsError, hermes_target
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.answer_desk import iterate_completion, parse_json_object

    models, ambiguous = await answers._models(request, user)
    _, bases = lib.library(models, user)
    preferred = preferred_routing_model(bases, models)
    planner = answers._resolve_planner(preferred, models, ambiguous, user)
    from open_webui.utils.task import get_task_model_id
    routing_model = preferred or get_task_model_id(planner["model"], "",
        getattr(request.app.state.config, "TASK_MODEL_EXTERNAL", ""), models, ambiguous)
    if not any(base["id"] == routing_model for base in bases):
        routing_model = planner["model"]
    teams_available = bool(ENABLE_AGENT_TEAMS)
    if form.mode != "auto":
        raw = {"mode": form.mode, "reason": "你指定了处理方式", "execution_requested": form.mode == "team"}
    else:
        async def classify():
            payload = {"model": routing_model, "stream": True,
                "messages": selection_messages(form.question, form.context, file_info, teams_available=teams_available),
                "metadata": {"task": "auto_routing"}, "max_tokens": 400}
            text = ""
            async for kind, part in iterate_completion(await generate_chat_completion(request, payload, user)):
                if kind == "content":
                    text += part
                    if len(text) > 6000:
                        raise ValueError("route response too long")
            return parse_json_object(text)
        try:
            raw = await asyncio.wait_for(classify(), timeout=25)
        except Exception:
            log.info("automatic selection unavailable; using answer")
            raw = {"mode": "answer", "reason": "自动判断暂不可用，已按默认方式交给精答"}
    if isinstance(raw, dict) and raw.get("mode") == "team" and teams_available:
        try:
            await hermes_target(request, user)
        except TeamsError:
            teams_available = False
    try:
        decision = normalize_selection(raw, question=form.question, context=form.context,
            teams_available=teams_available, discussion_available=len(bases) >= 2)
    except ValueError:
        decision = {"mode": "answer", "reason": "自动判断结果不可用，已交给精答", "execution_requested": False}
    # An explicit manual choice should explain an unavailable capability rather than change mode.
    if form.mode != "auto" and decision["mode"] != form.mode:
        raise HTTPException(400, decision["reason"] + "；可改选精答")
    decision["routing_model"] = routing_model if form.mode == "auto" else None
    return decision, models, ambiguous, bases, planner


async def dispatch(request, user, row, form, decision, models, ambiguous, bases, planner):
    from open_webui.routers import answers, discussions, teams
    from open_webui.utils import discussion_room as room
    from open_webui.utils.agent_teams import AssistantAccess, GOAL_MAX_CHARS, hermes_target, input_files

    mode = decision["mode"]
    origin = row["data"].get("origin")
    context = {"text": form.context} if form.context else None
    data = {**row["data"], **decision, "auto_start": bool(form.auto_start and decision["execution_requested"])}
    claimed = AutoRoutes.update(row["id"], user.id, expect=("routing",), status="dispatching", mode=mode, data=data)
    if not claimed:  # cancelled while the model was selecting
        return

    def bind(target_id):
        AutoRoutes.update(row["id"], user.id, target_id=target_id)

    if mode == "team":
        teams._enabled()
        target = await hermes_target(request, user)
        inputs = input_files(form.files, user)
        if len(inputs) < len(set(form.files)):
            raise HTTPException(400, "协作台无法读取部分附件，请重新上传或改用精答")
        goal = form.question
        if form.context:
            goal += "\n\n对话背景（供参考，遵守用户当前要求）：\n" + form.context
        if not form.research:
            goal += "\n\n用户约束：不要联网检索，只使用提供的资料和工作区。"
        if len(goal) > GOAL_MAX_CHARS:
            raise HTTPException(400, "协作目标与背景合计过长，请精简到 8000 字以内后重试")
        if origin:
            # A chat dispatch already owns its reply; attach() would insert a second card.
            from open_webui.models.agent_teams import AgentTeams
            from open_webui.utils.agent_teams import default_title, start_planning
            team = AgentTeams.insert(user.id, goal, origin["chatId"], default_title(form.question),
                meta={"auto_start": data["auto_start"], "from_chat": True, "inputs": inputs})
            bind(team.id)
            start_planning(team, target, access=AssistantAccess(request, user))
        else:
            await teams._start(request, user, goal, target, inputs=inputs, auto_start=data["auto_start"],
                access=AssistantAccess(request, user), on_created=bind)
    else:
        loaded = await asyncio.to_thread(discussions._load_files, form.files, user)
        web = form.research and bool(getattr(request.app.state.config, "ENABLE_WEB_SEARCH", True))
        if mode == "answer":
            answers._check_capacity(user)
            answers._open(request, user, question=form.question, planner=planner, web_allowed=web,
                context=context, origin=origin, files=loaded, on_created=bind)
        else:
            discussions._check_capacity(user)
            chosen = discussions._diverse(bases, 2 if form.preference == "economy" else 3)
            setup = room.normalize_setup({"mode": "compare", "rounds": 1,
                "seats": [{"model": b["id"]} for b in chosen], "moderator": planner["model"],
                "research": web, "autoMatch": True}, models, ambiguous, user)
            discussions._open(request, user, question=form.question, setup=setup, files=loaded,
                context=context, origin=origin, on_created=bind)
        if origin:
            from open_webui.utils.mode_dispatch import mark_chat
            mark_chat(origin["chatId"], mode)
    AutoRoutes.update(row["id"], user.id, status="dispatched")
    if origin:
        Chats.set_chat_meta_value_by_id(origin["chatId"], "auto_route", {"id": row["id"], "mode": mode})
        from open_webui.utils.team_chats import emit_chat_event
        await emit_chat_event(user.id, origin["chatId"], "chat:title", Chats.get_chat_title_by_id(origin["chatId"]))


async def _run(request, user, row, form, file_info):
    try:
        selection = await asyncio.wait_for(select(request, user, form, file_info), timeout=60)
        await asyncio.wait_for(dispatch(request, user, row, form, *selection), timeout=180)
    except Exception as exc:
        # Never persist provider messages, credentials, or raw model output in a receipt.
        message = exc.detail if isinstance(exc, HTTPException) else "未能完成派发，请查看原任务或调整后重试"
        current = AutoRoutes.get(row["id"], user.id)
        if current and current["status"] != "cancelled":
            AutoRoutes.update(row["id"], user.id, status="error", data={**current["data"], "error": str(message)[:300]})
        log.info("auto dispatch failed (%s)", type(exc).__name__)


async def start(request, user, form, origin=None):
    form = form.model_copy(update={"question": form.question.strip()})
    if not form.question:
        raise HTTPException(400, "请写下问题或任务")
    if origin and not Chats.get_chat_by_id_and_user_id(origin["chatId"], user.id):
        raise HTTPException(404, "来源对话不存在")
    payload = form.model_dump(exclude={"client_key"})
    fingerprint = hashlib.sha256(json.dumps({"input": payload, "origin": origin}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # Existing keys remain usable even when capacity is full.
    existing = AutoRoutes.by_key(user.id, form.client_key)
    if existing:
        if existing["fingerprint"] != fingerprint:
            raise HTTPException(409, "这次提交的内容已改变，请重新开始")
        return public(_own(existing["id"], user), user)
    file_info = _files(form.files, user)
    if AutoRoutes.count_active(user.id) >= 3:
        raise HTTPException(429, "已有 3 个问题正在分流，请稍后再试")
    row, created = AutoRoutes.create(user.id, form.client_key, fingerprint, {"input": payload, "origin": origin})
    if row["fingerprint"] != fingerprint:
        raise HTTPException(409, "这次提交的内容已改变，请重新开始")
    if created:
        task = asyncio.create_task(_run(request, user, row, form, file_info))
        _jobs[row["id"]] = task
        task.add_done_callback(lambda _: _jobs.pop(row["id"], None))
    return public(_own(row["id"], user), user)


@router.post("/")
async def create(request: Request, form: CreateForm, user=Depends(get_verified_user)):
    return await start(request, user, form)


def _target_summaries(rows, user):
    # Read only list metadata, never whole chat transcripts, in two bounded queries.
    from open_webui.internal.db import get_db
    from open_webui.models.chats import Chat
    from open_webui.models.agent_teams import AgentTeam
    ids = [r["target_id"] for r in rows if r.get("target_id")]
    result = {}
    if not ids:
        return result
    with get_db() as db:
        for id, title, meta in db.query(Chat.id, Chat.title, Chat.meta).filter(Chat.user_id == user.id, Chat.id.in_(ids)):
            for mode, key in (("answer", "answer_desk"), ("discuss", "discussion_room")):
                info = {"target_status": (meta or {}).get(key, {}).get("status")}
                if title and title != "New Chat":
                    info["title"] = title
                result[(mode, id)] = info
        for id, title, status, phase in db.query(AgentTeam.id, AgentTeam.title, AgentTeam.status, AgentTeam.phase).filter(
                AgentTeam.user_id == user.id, AgentTeam.id.in_(ids)):
            result[("team", id)] = {"title": title, "target_status": phase or status}
    return result


@router.get("/")
async def history(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=50),
                  before: Optional[str] = None, q: str = Query("", max_length=200),
                  mode: Optional[Literal["answer", "discuss", "team"]] = None,
                  user=Depends(get_verified_user)):
    cursor = None
    if before:
        try:
            stamp, id = before.split(":", 1)
            cursor = (int(stamp), id)
            if not id:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "历史游标无效，请刷新后重试")
    rows = AutoRoutes.page(user.id, offset, limit + 1, before=cursor, query=q, mode=mode)
    page = [_settle(row, user) for row in rows[:limit]]
    targets = _target_summaries(page, user)
    items = [public(row, user, targets) for row in page]
    for item in items:
        item["question"] = item["question"][:300]
    return {"items": items, "more": len(rows) > limit,
            "next": f"{page[-1]['created_at']}:{page[-1]['id']}" if len(rows) > limit and page else None}


@router.get("/target/{mode}/{target_id}")
async def target_route(mode: Literal["answer", "discuss", "team"], target_id: str, user=Depends(get_verified_user)):
    row = AutoRoutes.for_target(user.id, mode, target_id)
    return public(_own(row["id"], user), user) if row else None


@router.get("/{id}")
async def detail(id: str, user=Depends(get_verified_user), request: Request = None):
    row = _own(id, user)
    # Repair older chat dispatches on opening their card; never scan all chat histories.
    origin = row["data"].get("origin") or {}
    if request and origin.get("chatId"):
        chat = Chats.get_chat_by_id_and_user_id(origin["chatId"], user.id)
        if chat and not (chat.meta or {}).get("auto_route"):
            Chats.set_chat_meta_value_by_id(chat.id, "auto_route", {"id": row["id"], "mode": row.get("mode")})
            from open_webui.utils.mode_chats import schedule_chat_metadata
            history = (chat.chat or {}).get("history") or {}
            messages = list((history.get("messages") or {}).values())
            count = sum(1 for m in messages if m.get("role") == "user" and not m.get("hermes_notice"))
            schedule_chat_metadata(request, user, chat.id, model_id=((chat.chat or {}).get("models") or ["hermes-agent"])[0],
                messages=[{"role": "user", "content": row["data"]["input"]["question"]}],
                message_id=origin.get("messageId"), user_message_count=max(1, count))
    return public(row, user)


class RetryForm(BaseModel):
    mode: Literal["auto", "answer", "discuss", "team"] = "auto"


RETRYABLE = ("error", "interrupted", "cancelled")


@router.post("/{id}/retry")
async def retry(request: Request, id: str, form: RetryForm, user=Depends(get_verified_user)):
    """Route a failed, interrupted or cancelled request again (optionally in a chosen mode), from
    the card where it failed: same input and chat of origin, a new receipt. Two presses of the
    same retry share one receipt (the key is derived from this one)."""
    row = _own(id, user)
    if row["status"] not in RETRYABLE:
        raise HTTPException(409, "这次分流没有失败，不需要重试")
    data = row["data"]
    previous = AutoRoutes.get(data["retried_as"], user.id) if data.get("retried_as") else None
    if previous and previous["status"] not in RETRYABLE:
        return public(_own(previous["id"], user), user)  # retried already: that one is under way
    attempt = int(data.get("retries") or 0) + 1
    inputs = {**data["input"], "mode": form.mode, "client_key": f"retry:{id}:{attempt}"}
    created = await start(request, user, CreateForm(**inputs), origin=data.get("origin"))
    AutoRoutes.update(id, user.id, data={**data, "retries": attempt, "retried_as": created["id"]})
    origin = data.get("origin") or {}
    if origin.get("chatId") and origin.get("messageId"):
        # the chat's card follows the new receipt (also after a reload)
        Chats.upsert_message_to_chat_by_id_and_message_id(origin["chatId"], origin["messageId"],
            {"auto_route": {"id": created["id"]}})
    return created


@router.post("/{id}/cancel")
async def cancel(id: str, user=Depends(get_verified_user)):
    _own(id, user)
    row = AutoRoutes.update(id, user.id, expect=("routing",), status="cancelled")
    if row is None:
        raise HTTPException(409, "已经开始派发，请打开目标工作台停止任务")
    return public(row, user)
