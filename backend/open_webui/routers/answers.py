"""精答工作台 API: /api/v1/answers.

A run is one of the user's chats (see utils/answer_desk.py): created, listed and driven here,
deleted like any chat. Every route is per user.
"""

import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.models.chats import ChatForm, Chats
from open_webui.socket.main import get_event_emitter
from open_webui.utils.auth import get_verified_user
from open_webui.utils import answer_desk as desk
from open_webui.utils.answer_desk import CHAT_KEY, LIVE, MESSAGE_KEY, META_KEY, AnswerError
from open_webui.utils.discussion_room import clean_context

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_TITLE = "新精答"
RECENT_SECONDS = 120


class CreateForm(BaseModel):
    question: str
    # the model that picks (and writes) the assistant; the strongest text model by default
    planner: Optional[str] = None
    # may the dispatcher look things up on the web (it decides whether the question needs it)
    research: bool = True
    # the conversation it was asked from (text, title, chat_id): background for the dispatcher
    # and the assistant
    context: Optional[dict] = None
    # set once per question by the page and sent again when it retries
    client_key: Optional[str] = None


# Recently created runs, so a retry after a dropped response (same key) or a double tap (same
# question) never becomes a second run.
_recent: dict[str, list[dict]] = {}


def _recent_duplicate(user, key: Optional[str], question: str) -> Optional[str]:
    now = time.time()
    entries = [e for e in _recent.get(user.id, []) if now - e["at"] < RECENT_SECONDS or e["chat_id"] in LIVE]
    _recent[user.id] = entries
    for entry in reversed(entries):
        same_request = bool(key) and entry["key"] == key
        if not same_request and entry["question"] != question:
            continue
        chat = Chats.get_chat_by_id_and_user_id(entry["chat_id"], user.id)
        if chat is None or not isinstance((chat.chat or {}).get(CHAT_KEY), dict):
            continue
        status = ((chat.meta or {}).get(META_KEY) or {}).get("status")
        if same_request or chat.id in LIVE or status not in {"error", "stopped", "interrupted"}:
            return chat.id
    return None


def _raise(exc: AnswerError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


async def _models(request: Request, user, refresh: bool = False) -> tuple[dict, set]:
    from open_webui.utils.models import get_all_models

    if refresh or not getattr(request.state, "MODELS", None):
        await get_all_models(request, user=user)
    return (
        getattr(request.state, "MODELS", None) or {},
        getattr(request.state, "MODELS_AMBIGUOUS", set()) or set(),
    )


def _may_write_library(request: Request, user) -> bool:
    from open_webui.utils.access_control import has_permission

    if getattr(user, "role", None) == "admin":
        return True
    return has_permission(user.id, "workspace.models", request.app.state.config.USER_PERMISSIONS)


def _own(chat_id: str, user):
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None or not isinstance((chat.chat or {}).get(CHAT_KEY), dict):
        raise HTTPException(status_code=404, detail="这条精答不存在")
    return chat


def _run_of(chat) -> Optional[dict]:
    data = (chat.chat or {}).get(CHAT_KEY) or {}
    live = LIVE.get(chat.id)
    if live:
        return desk.public_run(live.run)
    message = (((chat.chat or {}).get("history") or {}).get("messages") or {}).get(data.get("messageId")) or {}
    run = message.get(MESSAGE_KEY)
    return desk.public_run(run) if isinstance(run, dict) else None


def _stored_run(chat) -> Optional[dict]:
    """The run as written (with the private parts the page never sees)."""
    data = (chat.chat or {}).get(CHAT_KEY) or {}
    message = (((chat.chat or {}).get("history") or {}).get("messages") or {}).get(data.get("messageId")) or {}
    run = message.get(MESSAGE_KEY)
    return run if isinstance(run, dict) else None


def _settle_interrupted(chat) -> None:
    """A run still marked going with no live task was cut off by a restart."""
    if chat.id in LIVE:
        return
    run = _stored_run(chat)
    if run and run.get("status") in desk.RUNNING_STATUSES:
        run["status"] = "interrupted"
        run["endedAt"] = run.get("endedAt") or desk.now_ms()
        for key in ("plan", "answer"):
            part = run.get(key) or {}
            if part.get("status") in {"running", "streaming", "waiting"} and part.get("startedAt"):
                part["status"] = "stopped"
        _persist(chat.id, run)


def _detail(chat_id: str, user) -> dict:
    chat = _own(chat_id, user)
    _settle_interrupted(chat)
    chat = _own(chat_id, user)
    data = (chat.chat or {}).get(CHAT_KEY) or {}
    messages = ((chat.chat or {}).get("history") or {}).get("messages") or {}
    return {
        "id": chat.id,
        "title": chat.title,
        "folder_id": chat.folder_id,
        "updated_at": chat.updated_at,
        "created_at": chat.created_at,
        "run": _run_of(chat),
        "running": chat.id in LIVE,
        # follow-ups asked in the chat afterwards
        "followups": max(0, sum(1 for m in messages.values() if m.get("role") == "user") - 1),
        "messageId": data.get("messageId"),
    }


def _persist(chat_id: str, run: dict) -> None:
    assistant = run.get("assistant") or {}
    terminal = run.get("status") in desk.TERMINAL_STATUSES
    update = {"content": desk.stored_content(run), "done": terminal, MESSAGE_KEY: run}
    if assistant.get("id"):
        update["model"] = assistant["id"]
        update["modelName"] = assistant.get("name") or assistant["id"]
    if terminal:
        update["completedAt"] = int((run.get("endedAt") or desk.now_ms()) / 1000)
    Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, run["id"], update)
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return
    if assistant.get("id") and assistant.get("saved") and (chat.chat or {}).get("models") != [assistant["id"]]:
        # the chat continues with the assistant that answered
        payload = dict(chat.chat or {})
        payload["models"] = [assistant["id"]]
        user_message = (payload.get("history") or {}).get("messages", {}).get(run.get("userMessageId"))
        if isinstance(user_message, dict):
            user_message["models"] = [assistant["id"]]
        Chats.update_chat_by_id(chat_id, payload, update_title=False)
    Chats.set_chat_meta_value_by_id(chat_id, META_KEY, desk.summary_meta(run))


def _emitter(user, chat_id: str, message_id: str):
    return get_event_emitter(
        {"user_id": user.id, "chat_id": chat_id, "message_id": message_id, "session_id": None},
        update_db=False,
    )


async def _after_done(request: Request, user, chat_id: str, run: dict) -> None:
    from open_webui.utils.mode_chats import auto_title_and_folder

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        return
    answer = (run.get("answer") or {}).get("content") or ""
    messages = [{"role": "user", "content": run["question"]}, {"role": "assistant", "content": answer}]
    title, folder_id = await auto_title_and_folder(
        request,
        user,
        chat,
        messages=messages,
        model_id=run["planner"]["model"],
        message_id=run["id"],
        user_message_count=1,
        label="answer",
    )
    emit = _emitter(user, chat_id, run["id"])
    try:
        await emit({"type": "answer", "data": {"kind": "meta", "chatId": chat_id, "title": title, "folderId": folder_id}})
        await emit({"type": "chat:title", "data": title})
        await emit({"type": "chat:completion", "data": {"done": True, "title": title, "content": answer[:400], "answer_desk": True}})
    except Exception:
        pass


def _resolve_planner(requested: Optional[str], models_map: dict, ambiguous: set, user) -> dict:
    """The dispatcher's model: the one asked for, else a strong text model."""
    from open_webui.utils.discussion_room import DiscussError, resolve_seat_model

    if requested:
        try:
            return resolve_seat_model(requested, models_map, ambiguous, user)
        except DiscussError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    _, bases = desk.library(models_map, user)
    if not bases:
        raise HTTPException(status_code=400, detail="没有可用的文本模型")
    strong = next((b for b in bases if re.search(r"claude|gpt", b["name"], re.I)), bases[0])
    return resolve_seat_model(strong["id"], models_map, ambiguous, user)


def _start(request: Request, user, chat, run: dict) -> desk.LiveAnswer:
    chat_id = chat.id
    question = run["question"]
    may_write = _may_write_library(request, user)

    async def call_model(model_id: str, messages: list[dict]):
        from open_webui.utils.chat import generate_chat_completion

        payload = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            "metadata": {"chat_id": chat_id, "message_id": run["id"], "task": "answer_desk"},
        }
        return await generate_chat_completion(request, payload, user)

    async def route(current: dict) -> tuple[dict, dict]:
        models_map, _ = await _models(request, user, refresh=True)
        assistants, bases = desk.library(models_map, user)
        planner = current["planner"]["model"]
        default_base = planner if any(b["id"] == planner for b in bases) else (bases[0]["id"] if bases else "")
        options = {"default_base": default_base, "may_create": may_write, "web_allowed": bool(current.get("webAllowed"))}
        messages = desk.plan_messages(question, assistants, bases, background=(current.get("context") or {}).get("text") or "", **options)
        text = ""
        async for kind, part in desk.iterate_completion(await call_model(planner, messages)):
            if kind == "content":
                text += part
        plan = desk.normalize_plan(desk.parse_json_object(text), assistants, bases, **options)
        return plan_public(plan), await carry_out(plan, bases)

    def plan_public(plan: dict) -> dict:
        return {k: plan[k] for k in ("action", "reason", "change", "webSearch", "note")}

    async def carry_out(plan: dict, bases: list[dict]) -> dict:
        action, target, spec = plan["action"], plan["target"], plan["spec"]
        if action == "use":
            return {
                "id": target["id"],
                "name": target["name"],
                "emoji": target["emoji"],
                "description": target["description"],
                "action": "use",
                "saved": True,
                "base": target["base"],
                "baseName": desk.base_name(bases, target["base"]),
            }
        if action == "update":
            row, before = desk.update_assistant(user, target["id"], spec, chat_id=chat_id, change=plan["change"])
            await _models(request, user, refresh=True)
            return {
                "id": row.id,
                "name": row.name,
                "emoji": target["emoji"],
                "description": (row.meta.description or ""),
                "action": "update",
                "saved": True,
                "base": row.base_model_id,
                "baseName": desk.base_name(bases, row.base_model_id or ""),
                "system": spec["system"],
                "before": before,
            }
        common = {
            "name": spec["name"],
            "emoji": spec["emoji"],
            "description": spec["description"],
            "base": spec["base"],
            "baseName": desk.base_name(bases, spec["base"]),
            "system": spec["system"],
        }
        if not may_write:
            # not allowed to keep it: answer once with the assistant it would have been
            return {**common, "id": spec["base"], "action": "temporary", "saved": False}
        row = desk.create_assistant(user, spec, chat_id=chat_id, question=question)
        await _models(request, user, refresh=True)
        return {**common, "id": row.id, "action": "create", "saved": True}

    async def search(text: str):
        # the discussion room's evidence pack: 1-2 queries through the app's own web search
        from open_webui.routers import discussions

        return await discussions._search(request, user, run["planner"]["model"], text, [])

    async def after_done(done: dict):
        await _after_done(request, user, chat_id, done)

    live = desk.LiveAnswer(
        chat_id=chat_id,
        user_id=user.id,
        run=run,
        emit=_emitter(user, chat_id, run["id"]),
        call_model=call_model,
        route=route,
        persist=lambda current: _persist(chat_id, current),
        after_done=after_done,
        search=search,
    )
    desk.start_live(live)
    return live


def _check_capacity(user):
    if desk.running_for_user(user.id) >= desk.MAX_RUNNING_PER_USER:
        raise HTTPException(status_code=429, detail=f"已有 {desk.MAX_RUNNING_PER_USER} 个精答在进行，等它们答完再问")


############################
# Routes
############################


@router.get("/assistants")
async def list_assistants(request: Request, user=Depends(get_verified_user)):
    """The library the dispatcher picks from (what the page shows), and whether it may grow."""
    models_map, _ = await _models(request, user)
    assistants, bases = desk.library(models_map, user)
    return {
        "assistants": [{**desk.public_assistant(a), "baseName": desk.base_name(bases, a["base"])} for a in assistants],
        "may_create": _may_write_library(request, user),
    }


@router.get("/")
async def list_answers(user=Depends(get_verified_user), archived: bool = False):
    rows = Chats.get_chats_with_meta_key_by_user_id(user.id, META_KEY, include_archived=archived)
    out = []
    for row in rows:
        summary = dict(row["meta"].get(META_KEY) or {})
        if row["id"] in LIVE:
            summary["status"] = LIVE[row["id"]].run.get("status")
        elif summary.get("status") in desk.RUNNING_STATUSES:
            summary["status"] = "interrupted"
        out.append(
            {
                "id": row["id"],
                "title": row["title"],
                "updated_at": row["updated_at"],
                "created_at": row["created_at"],
                "folder_id": row["folder_id"],
                "archived": row["archived"],
                "running": row["id"] in LIVE,
                **summary,
            }
        )
    return out


@router.post("/")
async def create_answer(request: Request, form: CreateForm, user=Depends(get_verified_user)):
    question = desk.clean_text(form.question, desk.QUESTION_MAX_CHARS)
    if not question:
        raise HTTPException(status_code=400, detail="先写下要问的问题")
    key = str(form.client_key or "").strip()[:64] or None
    if key:
        existing = _recent_duplicate(user, key, "")
        if existing:
            return {**_detail(existing, user), "deduplicated": True}
    _check_capacity(user)
    models_map, ambiguous = await _models(request, user)
    planner = _resolve_planner(form.planner, models_map, ambiguous, user)
    web_allowed = bool(form.research) and bool(getattr(request.app.state.config, "ENABLE_WEB_SEARCH", True))
    # checked again after the awaits above (none from here to the insert)
    existing = _recent_duplicate(user, key, question)
    if existing:
        return {**_detail(existing, user), "deduplicated": True}

    user_message_id, message_id = desk.new_id(), desk.new_id()
    run = desk.new_run(
        question=question,
        planner={"model": planner["model"], "name": planner["name"]},
        user_message_id=user_message_id,
        message_id=message_id,
        web_allowed=web_allowed,
        context=clean_context(form.context),
    )
    messages = {
        user_message_id: {
            "id": user_message_id,
            "parentId": None,
            "childrenIds": [message_id],
            "role": "user",
            "content": question,
            "timestamp": int(time.time()),
            "models": [planner["model"]],
        },
        message_id: {
            "id": message_id,
            "parentId": user_message_id,
            "childrenIds": [],
            "role": "assistant",
            "content": "",
            "model": planner["model"],
            "modelName": "精答",
            "modelIdx": 0,
            "timestamp": int(time.time()),
            "done": False,
            MESSAGE_KEY: run,
        },
    }
    payload = {
        "title": DEFAULT_TITLE,
        "models": [planner["model"]],
        "params": {},
        "history": {"messages": messages, "currentId": message_id},
        "tags": [],
        "timestamp": desk.now_ms(),
        CHAT_KEY: {"v": 1, "messageId": message_id},
    }
    chat = Chats.insert_new_chat(user.id, ChatForm(chat=payload, title_auto_generated=True))
    if chat is None:
        raise HTTPException(status_code=500, detail="创建精答失败")
    for mid in (user_message_id, message_id):
        Chats.upsert_message_to_chat_by_id_and_message_id(chat.id, mid, messages[mid])
    Chats.set_chat_meta_value_by_id(chat.id, META_KEY, desk.summary_meta(run))
    _recent.setdefault(user.id, []).append({"key": key, "question": question, "chat_id": chat.id, "at": time.time()})
    _start(request, user, chat, run)
    return _detail(chat.id, user)


@router.get("/{chat_id}")
async def get_answer(chat_id: str, user=Depends(get_verified_user)):
    return _detail(chat_id, user)


@router.post("/{chat_id}/stop")
async def stop_answer(chat_id: str, user=Depends(get_verified_user)):
    _own(chat_id, user)
    stopped = await desk.stop_live(chat_id)
    return {"ok": True, "stopped": stopped, **_detail(chat_id, user)}


@router.post("/{chat_id}/retry")
async def retry_answer(request: Request, chat_id: str, user=Depends(get_verified_user)):
    """Run it again from where it failed, stopped or was cut off: the dispatcher if it never
    decided, else the same assistant answers again."""
    chat = _own(chat_id, user)
    if chat_id in LIVE:
        raise HTTPException(status_code=409, detail="还在回答")
    _settle_interrupted(chat)
    chat = _own(chat_id, user)
    run = _stored_run(chat)
    if run is None:
        raise HTTPException(status_code=404, detail="这条精答没有记录")
    if run.get("status") == "done":
        raise HTTPException(status_code=400, detail="已经答完；可以到对话里继续追问")
    _check_capacity(user)
    await _models(request, user)
    run = dict(run)
    if (run.get("plan") or {}).get("status") != "done":
        run["assistant"] = None
    run["answer"] = {**(run.get("answer") or {}), "status": "waiting", "content": "", "error": None, "retry": None, "startedAt": None, "endedAt": None}
    run.update({"status": "routing" if not run.get("assistant") else "answering", "endedAt": None, "error": None})
    _start(request, user, chat, run)
    return _detail(chat_id, user)


@router.post("/{chat_id}/revert")
async def revert_upgrade(request: Request, chat_id: str, user=Depends(get_verified_user)):
    """Undo the upgrade this run made to an assistant (if nothing changed it since)."""
    chat = _own(chat_id, user)
    if chat_id in LIVE:
        raise HTTPException(status_code=409, detail="还在回答，等答完再撤销")
    run = _stored_run(chat)
    assistant = (run or {}).get("assistant") or {}
    if assistant.get("action") != "update" or assistant.get("reverted"):
        raise HTTPException(status_code=400, detail="这次没有升级助手")
    try:
        desk.revert_assistant(user, assistant["id"], chat_id=chat_id, after_system=assistant.get("system") or "")
    except AnswerError as exc:
        _raise(exc)
    run = dict(run)
    run["assistant"] = {**assistant, "reverted": True}
    _persist(chat_id, run)
    return _detail(chat_id, user)


@router.delete("/{chat_id}")
async def delete_answer(chat_id: str, user=Depends(get_verified_user)):
    _own(chat_id, user)
    await desk.stop_live(chat_id)
    return {"ok": bool(Chats.delete_chat_by_id_and_user_id(chat_id, user.id))}
