"""讨论台 API: /api/v1/discussions.

A discussion is one of the user's chats (see utils/discussion_room.py): created, listed and
driven here, deleted like any chat. Every route is per user.
"""

import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.models.chats import (
    ChatForm,
    Chats,
    can_auto_generate_chat_title,
)
from open_webui.socket.main import get_event_emitter
from open_webui.utils.auth import get_verified_user
from open_webui.utils import discussion_room as room
from open_webui.utils.discussion_room import (
    CHAT_KEY,
    LIVE,
    MESSAGE_KEY,
    META_KEY,
    DiscussError,
)

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_TITLE = "新讨论"


class SeatForm(BaseModel):
    model: str
    role: Optional[str] = ""


class CreateForm(BaseModel):
    question: str
    mode: Optional[str] = "roundtable"
    seats: list[SeatForm]
    rounds: Optional[int] = None
    moderator: Optional[str] = None
    research: bool = False
    files: list[str] = []


class AskForm(BaseModel):
    question: str
    rounds: Optional[int] = None
    files: list[str] = []


class InterjectForm(BaseModel):
    text: str


class RetryForm(BaseModel):
    turn: str


def _raise(exc: DiscussError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


async def _models(request: Request, user) -> tuple[dict, set]:
    from open_webui.utils.models import get_all_models

    if not getattr(request.state, "MODELS", None):
        await get_all_models(request, user=user)
    return (
        getattr(request.state, "MODELS", None) or {},
        getattr(request.state, "MODELS_AMBIGUOUS", set()) or set(),
    )


def _own(chat_id: str, user):
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None or not isinstance((chat.chat or {}).get(CHAT_KEY), dict):
        raise HTTPException(status_code=404, detail="讨论不存在")
    return chat


def _setup_of(chat) -> dict:
    data = (chat.chat or {}).get(CHAT_KEY) or {}
    setup = {key: data.get(key) for key in ("mode", "rounds", "seats", "moderator")}
    setup["research"] = bool(data.get("research"))
    return setup


def _asks_of(chat) -> list[dict]:
    """The questions asked in this discussion, oldest first; the running one from memory."""
    data = (chat.chat or {}).get(CHAT_KEY) or {}
    messages = ((chat.chat or {}).get("history") or {}).get("messages") or {}
    live = LIVE.get(chat.id)
    asks = []
    for message_id in data.get("asks") or []:
        if live and live.ask.get("id") == message_id:
            asks.append(room.public_ask(live.ask))
            continue
        message = messages.get(message_id) or {}
        ask = message.get(MESSAGE_KEY)
        if isinstance(ask, dict):
            asks.append(ask)
    return asks


def _settle_interrupted(chat) -> None:
    """A question still marked running with no live task was cut off by a restart."""
    if chat.id in LIVE:
        return
    for ask in _asks_of(chat):
        if ask.get("status") in room.RUNNING_STATUSES:
            ask["status"] = "interrupted"
            ask["endedAt"] = ask.get("endedAt") or room.now_ms()
            for turn in ask.get("turns") or []:
                if turn.get("status") in {"waiting", "streaming"}:
                    turn["status"] = "stopped"
            if (ask.get("conclusion") or {}).get("status") in {"waiting", "streaming"}:
                ask["conclusion"]["status"] = "stopped" if ask["conclusion"].get("content") else "waiting"
            _persist_ask(chat.id, ask, _setup_of(chat))


def _detail(chat_id: str, user) -> dict:
    chat = _own(chat_id, user)
    _settle_interrupted(chat)
    chat = _own(chat_id, user)
    return {
        "id": chat.id,
        "title": chat.title,
        "folder_id": chat.folder_id,
        "updated_at": chat.updated_at,
        "created_at": chat.created_at,
        "setup": _setup_of(chat),
        "asks": _asks_of(chat),
        "running": chat.id in LIVE,
    }


def _persist_ask(chat_id: str, ask: dict, setup: dict) -> None:
    conclusion = ask.get("conclusion") or {}
    terminal = ask.get("status") in room.TERMINAL_STATUSES
    update = {
        "content": conclusion.get("content") or "",
        "done": terminal,
        MESSAGE_KEY: room.public_ask(ask),
    }
    if terminal:
        update["completedAt"] = int((ask.get("endedAt") or room.now_ms()) / 1000)
    Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, ask["id"], update)
    chat = Chats.get_chat_by_id(chat_id)
    if chat is not None:
        Chats.set_chat_meta_value_by_id(chat_id, META_KEY, room.summary_meta(setup, _asks_of(chat)))


def _history(chat, before_ask_id: Optional[str] = None) -> list[dict]:
    out = []
    for ask in _asks_of(chat):
        if ask.get("id") == before_ask_id:
            break
        content = (ask.get("conclusion") or {}).get("content") or ""
        if content:
            out.append({"question": ask.get("question"), "conclusion": content})
    return out


def _load_files(file_ids: list[str], user) -> list[dict]:
    """The user's own uploaded files for a question: images by reference, documents with their text."""
    from open_webui.models.files import Files

    out = []
    for file_id in list(dict.fromkeys(str(f or "").strip() for f in file_ids or []))[: room.MAX_FILES + 1]:
        if not file_id:
            continue
        item = Files.get_file_by_id(file_id)
        if item is None or (item.user_id != user.id and getattr(user, "role", None) != "admin"):
            raise HTTPException(status_code=404, detail="附件不存在")
        meta = item.meta or {}
        content_type = str(meta.get("content_type") or "")
        is_image = content_type.startswith("image/")
        entry = {
            "id": item.id,
            "name": str(meta.get("name") or item.filename or "附件")[:200],
            "type": "image" if is_image else "file",
            "content_type": content_type,
            "size": meta.get("size"),
        }
        if not is_image:
            entry["text"] = str((item.data or {}).get("content") or "")[: room.FILE_TEXT_CHARS]
        out.append(entry)
    if len(out) > room.MAX_FILES:
        raise HTTPException(status_code=400, detail=f"最多 {room.MAX_FILES} 个附件")
    return out


def _ask_images(ask: dict, user) -> list[str]:
    """Data URLs of the question's images (what the providers accept)."""
    from open_webui.utils.chat_image_refs import build_chat_image_content_url, materialize_image_url_for_openai

    urls = []
    for item in ask.get("files") or []:
        if item.get("type") != "image":
            continue
        try:
            url = materialize_image_url_for_openai(
                build_chat_image_content_url(item["id"]),
                user_id=user.id,
                is_admin=getattr(user, "role", None) == "admin",
            )
            if isinstance(url, str) and url.startswith("data:"):
                urls.append(url)
        except Exception as exc:
            log.warning("discussion: image %s not readable: %s", item.get("id"), exc)
    return urls


def _message_files(files: list[dict]) -> list[dict]:
    """The same attachments as the chat view lists them on a user message."""
    out = []
    for item in files:
        if item.get("type") == "image":
            out.append({"type": "image", "id": item["id"], "name": item["name"], "url": f"/api/v1/files/{item['id']}/content"})
        else:
            out.append({"type": "file", "id": item["id"], "name": item["name"], "url": f"/api/v1/files/{item['id']}", "size": item.get("size")})
    return out


def _emitter(user, chat_id: str, message_id: str):
    return get_event_emitter(
        {"user_id": user.id, "chat_id": chat_id, "message_id": message_id, "session_id": None},
        update_db=False,
    )


def _title_from(res: Any) -> str:
    if isinstance(res, dict):
        choices = res.get("choices") or []
        if len(choices) == 1 and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "").strip()
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end > start:
                try:
                    title = str(json.loads(content[start : end + 1]).get("title") or "").strip()
                    if title:
                        return title[:80]
                except Exception:
                    pass
            content = content.strip(" \"'`#*")
            if content and "\n" not in content and len(content) <= 80:
                return content
    return ""


async def _after_done(request: Request, user, chat_id: str, ask: dict) -> None:
    """Automatic title and folder, on the same cadence as ordinary chats."""
    from open_webui.routers.tasks import generate_folder_assignment, generate_title
    from open_webui.utils.folder_assignment import assign_chat_folder, build_default_deps
    from open_webui.utils.task import build_fallback_chat_title

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        return
    asks = _asks_of(chat)
    messages = []
    for item in asks:
        messages.append({"role": "user", "content": item.get("question") or ""})
        answer = room.conclusion_answer((item.get("conclusion") or {}).get("content") or "")
        if answer:
            messages.append({"role": "assistant", "content": answer})
    ask_count = len(asks)
    moderator = (ask.get("moderator") or {}).get("model") or ""
    config = request.app.state.config
    emit = _emitter(user, chat_id, ask["id"])

    title = chat.title
    try:
        may_title = getattr(config, "ENABLE_TITLE_GENERATION", True) and can_auto_generate_chat_title(
            chat.title,
            {"title_generation": Chats.get_chat_title_generation_metadata_by_id(chat_id)},
            ask_count,
            ask["id"],
        )
    except Exception:
        may_title = False
    if may_title:
        generated = ""
        try:
            generated = _title_from(
                await generate_title(
                    request,
                    {"model": moderator, "messages": messages, "chat_id": chat_id},
                    user,
                )
            )
        except Exception as exc:
            log.info("discussion %s: title generation failed: %s", chat_id, exc)
        generated = generated or build_fallback_chat_title(messages)
        if generated and Chats.update_chat_title_by_id(
            chat_id,
            generated,
            auto_generated=True,
            last_user_message_count=ask_count,
            source_message_id=ask["id"],
        ):
            title = generated

    folder_id = chat.folder_id
    if getattr(config, "ENABLE_FOLDER_AUTO_ASSIGNMENT", False):

        async def call_model(payload: dict):
            return await generate_folder_assignment(request, payload, user)

        try:
            result = await assign_chat_folder(
                chat_id=chat_id,
                user_id=user.id,
                model_id=moderator,
                messages=messages,
                user_message_count=ask_count,
                message_id=ask["id"],
                title=title,
                deps=build_default_deps(call_model),
            )
            log.info("discussion %s folder assignment: %s %r", chat_id, result.status, result.folder_name)
            if result.changed:
                folder_id = result.folder_id
        except Exception as exc:
            log.warning("discussion %s: folder assignment failed: %s", chat_id, exc)

    try:
        await emit({"type": "discuss", "data": {"kind": "meta", "chatId": chat_id, "title": title, "folderId": folder_id}})
        await emit({"type": "chat:title", "data": title})
        # the app's "reply ready" toast, for when the room is not on screen
        answer = room.conclusion_answer((ask.get("conclusion") or {}).get("content") or "")
        await emit({"type": "chat:completion", "data": {"done": True, "title": title, "content": answer[:400], "discussion_room": True}})
    except Exception:
        pass


def _parse_queries(res: Any) -> list[str]:
    content = ""
    if isinstance(res, dict):
        choices = res.get("choices") or []
        if choices and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "")
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        queries = json.loads(content[start : end + 1]).get("queries") or []
    except Exception:
        return []
    return [str(q).strip()[:200] for q in queries if str(q or "").strip()]


async def _search(request: Request, user, moderator: str, question: str, history: list[dict]) -> dict:
    """One shared evidence pack for a question: 1-2 queries through the app's own web search."""
    import asyncio

    from open_webui.routers.retrieval import SearchForm, process_web_search
    from open_webui.routers.tasks import generate_queries

    if not getattr(request.app.state.config, "ENABLE_WEB_SEARCH", True):
        raise ValueError("管理员关闭了联网搜索")
    messages = []
    for item in history[-2:]:
        messages += [
            {"role": "user", "content": item.get("question") or ""},
            {"role": "assistant", "content": room.conclusion_answer(item.get("conclusion") or "")[:1500]},
        ]
    messages.append({"role": "user", "content": question})
    queries: list[str] = []
    try:
        queries = _parse_queries(
            await generate_queries(
                request,
                {"model": moderator, "messages": messages, "prompt": question, "type": "web_search"},
                user,
            )
        )
    except Exception as exc:
        log.info("discussion search: query generation failed: %s", exc)
    queries = queries[:2] or [question[:200]]
    results = await asyncio.gather(
        *(process_web_search(request, SearchForm(query=query), user=user) for query in queries),
        return_exceptions=True,
    )
    docs = []
    errors = []
    for result in results:
        if isinstance(result, BaseException):
            errors.append(str(getattr(result, "detail", None) or result))
            continue
        for doc in (result or {}).get("docs") or []:
            meta = doc.get("metadata") or {}
            docs.append(
                {
                    "url": meta.get("source") or meta.get("url") or "",
                    "title": meta.get("title") or "",
                    "content": doc.get("content") or "",
                }
            )
    if not docs and errors:
        raise ValueError(errors[0][:200])
    return {"queries": queries, "docs": docs}


def _start(
    request: Request,
    user,
    chat,
    ask: dict,
    *,
    history: list[dict],
    conclude_only=False,
    from_round=1,
    retry_turn: Optional[str] = None,
):
    setup = _setup_of(chat)
    chat_id = chat.id

    async def call_model(model_id: str, messages: list[dict]):
        from open_webui.utils.chat import generate_chat_completion

        payload = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            "metadata": {"chat_id": chat_id, "message_id": ask["id"], "task": "discussion_room"},
        }
        return await generate_chat_completion(request, payload, user)

    async def after_done(done_ask: dict):
        await _after_done(request, user, chat_id, done_ask)

    async def search(question: str, past: list[dict]):
        return await _search(request, user, ask["moderator"]["model"], question, past)

    live = room.LiveDiscussion(
        chat_id=chat_id,
        user_id=user.id,
        setup=setup,
        ask=ask,
        history=history,
        emit=_emitter(user, chat_id, ask["id"]),
        call_model=call_model,
        persist=lambda current: _persist_ask(chat_id, current, setup),
        after_done=after_done,
        conclude_only=conclude_only,
        from_round=from_round,
        search=search,
        retry_turn=retry_turn,
        images=_ask_images(ask, user) if ask.get("files") else [],
    )
    room.start_live(live)
    return live


def _check_capacity(user):
    if room.running_for_user(user.id) >= room.MAX_RUNNING_PER_USER:
        raise HTTPException(status_code=429, detail=f"已有 {room.MAX_RUNNING_PER_USER} 个讨论在进行，等它们结束再开")


def _user_message(
    message_id: str, question: str, parent_id: Optional[str], child_id: str, model: str, files: Optional[list[dict]] = None
) -> dict:
    message = {
        "id": message_id,
        "parentId": parent_id,
        "childrenIds": [child_id],
        "role": "user",
        "content": question,
        "timestamp": int(time.time()),
        "models": [model],
    }
    if files:
        message["files"] = _message_files(files)
    return message


def _assistant_message(message_id: str, parent_id: str, ask: dict) -> dict:
    return {
        "id": message_id,
        "parentId": parent_id,
        "childrenIds": [],
        "role": "assistant",
        "content": "",
        "model": ask["moderator"]["model"],
        "modelName": "讨论台",
        "modelIdx": 0,
        "timestamp": int(time.time()),
        "done": False,
        MESSAGE_KEY: room.public_ask(ask),
    }


############################
# Routes
############################


@router.get("/")
async def list_discussions(user=Depends(get_verified_user), archived: bool = False):
    rows = Chats.get_chats_with_meta_key_by_user_id(user.id, META_KEY, include_archived=archived)
    out = []
    for row in rows:
        summary = dict(row["meta"].get(META_KEY) or {})
        if row["id"] in LIVE:
            live = LIVE[row["id"]]
            summary["status"] = live.ask.get("status")
            summary["round"] = live.ask.get("round")
        elif summary.get("status") in room.RUNNING_STATUSES:
            # marked running with no live task: a restart cut it off (the room settles it on open)
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
async def create_discussion(request: Request, form: CreateForm, user=Depends(get_verified_user)):
    question = room._clean_text(form.question, room.QUESTION_MAX_CHARS)
    if not question:
        raise HTTPException(status_code=400, detail="先写下要讨论的问题")
    _check_capacity(user)
    models_map, ambiguous = await _models(request, user)
    try:
        setup = room.normalize_setup(
            {
                "mode": form.mode,
                "seats": [seat.model_dump() for seat in form.seats],
                "rounds": form.rounds,
                "moderator": form.moderator,
                "research": form.research,
            },
            models_map,
            ambiguous,
            user,
        )
    except DiscussError as exc:
        _raise(exc)

    files = _load_files(form.files, user)
    user_message_id, assistant_message_id = room.new_id(), room.new_id()
    ask = room.new_ask(
        question=question, setup=setup, user_message_id=user_message_id, message_id=assistant_message_id, files=files
    )
    messages = {
        user_message_id: _user_message(user_message_id, question, None, assistant_message_id, ask["moderator"]["model"], files),
        assistant_message_id: _assistant_message(assistant_message_id, user_message_id, ask),
    }
    payload = {
        "title": DEFAULT_TITLE,
        "models": [seat["model"] for seat in setup["seats"]],
        "params": {},
        "history": {"messages": messages, "currentId": assistant_message_id},
        "tags": [],
        "timestamp": room.now_ms(),
        CHAT_KEY: {"v": 1, **setup, "asks": [assistant_message_id]},
    }
    chat = Chats.insert_new_chat(
        user.id, ChatForm(chat=payload, title_auto_generated=True)
    )
    if chat is None:
        raise HTTPException(status_code=500, detail="创建讨论失败")
    # write both messages through the normal path too (it also fills the message table)
    for message_id in (user_message_id, assistant_message_id):
        Chats.upsert_message_to_chat_by_id_and_message_id(chat.id, message_id, messages[message_id])
    Chats.set_chat_meta_value_by_id(chat.id, META_KEY, room.summary_meta(setup, [ask]))
    _start(request, user, chat, ask, history=[])
    return _detail(chat.id, user)


@router.get("/{chat_id}")
async def get_discussion(chat_id: str, user=Depends(get_verified_user)):
    return _detail(chat_id, user)


@router.post("/{chat_id}/ask")
async def ask_again(request: Request, chat_id: str, form: AskForm, user=Depends(get_verified_user)):
    question = room._clean_text(form.question, room.QUESTION_MAX_CHARS)
    if not question:
        raise HTTPException(status_code=400, detail="先写下要追问的内容")
    chat = _own(chat_id, user)
    if chat_id in LIVE:
        raise HTTPException(status_code=409, detail="讨论还在进行，等它结束或先停止")
    _check_capacity(user)
    _settle_interrupted(chat)
    chat = _own(chat_id, user)
    setup = _setup_of(chat)
    models_map, ambiguous = await _models(request, user)
    try:  # the models may have gone away since the discussion started
        for seat in setup["seats"]:
            room.resolve_seat_model(seat["model"], models_map, ambiguous, user)
        room.resolve_seat_model(setup["moderator"]["model"], models_map, ambiguous, user)
    except DiscussError as exc:
        _raise(exc)

    files = _load_files(form.files, user)
    data = dict((chat.chat or {}).get(CHAT_KEY) or {})
    previous_id = (data.get("asks") or [None])[-1]
    user_message_id, assistant_message_id = room.new_id(), room.new_id()
    ask = room.new_ask(
        question=question,
        setup=setup,
        user_message_id=user_message_id,
        message_id=assistant_message_id,
        rounds=form.rounds,
        files=files,
    )
    history = _history(chat)
    chat_payload = dict(chat.chat)
    messages = dict((chat_payload.get("history") or {}).get("messages") or {})
    if previous_id and previous_id in messages:
        previous = dict(messages[previous_id])
        previous["childrenIds"] = [*(previous.get("childrenIds") or []), user_message_id]
        messages[previous_id] = previous
    messages[user_message_id] = _user_message(
        user_message_id, question, previous_id, assistant_message_id, ask["moderator"]["model"], files
    )
    messages[assistant_message_id] = _assistant_message(assistant_message_id, user_message_id, ask)
    chat_payload["history"] = {"messages": messages, "currentId": assistant_message_id}
    data["asks"] = [*(data.get("asks") or []), assistant_message_id]
    chat_payload[CHAT_KEY] = data
    Chats.update_chat_by_id(chat_id, chat_payload, update_title=False)
    for message_id in (user_message_id, assistant_message_id):
        Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, messages[message_id])
    chat = _own(chat_id, user)
    _start(request, user, chat, ask, history=history)
    return _detail(chat_id, user)


@router.post("/{chat_id}/interject")
async def interject(chat_id: str, form: InterjectForm, user=Depends(get_verified_user)):
    _own(chat_id, user)
    text = room._clean_text(form.text, room.INTERJECTION_MAX_CHARS)
    if not text:
        raise HTTPException(status_code=400, detail="插话内容是空的")
    live = LIVE.get(chat_id)
    if not live:
        raise HTTPException(status_code=409, detail="讨论已经结束；可以直接追问")
    if live.ask.get("status") == "concluding":
        raise HTTPException(status_code=409, detail="主持人正在总结；结束后可以追问")
    items = live.ask.setdefault("interjections", [])
    if len(items) >= room.MAX_INTERJECTIONS:
        raise HTTPException(status_code=400, detail="这一问的插话已经够多了")
    # said during round N: the participants hear it from round N+1, the moderator always
    items.append({"text": text, "afterRound": int(live.ask.get("round") or 0), "at": room.now_ms()})
    await live.send_state()
    return {"ok": True, "interjections": items}


@router.post("/{chat_id}/stop")
async def stop(chat_id: str, user=Depends(get_verified_user)):
    _own(chat_id, user)
    stopped = await room.stop_live(chat_id)
    return {"ok": True, "stopped": stopped, **_detail(chat_id, user)}


def _last_settled_ask(chat_id: str, user) -> tuple[Any, dict]:
    chat = _own(chat_id, user)
    if chat_id in LIVE:
        raise HTTPException(status_code=409, detail="讨论还在进行")
    _settle_interrupted(chat)
    chat = _own(chat_id, user)
    asks = _asks_of(chat)
    if not asks:
        raise HTTPException(status_code=404, detail="这个讨论还没有问题")
    return chat, asks[-1]


@router.post("/{chat_id}/conclude")
async def conclude_now(request: Request, chat_id: str, user=Depends(get_verified_user)):
    """Write the conclusion from what was said (after a stop, an error or an interruption)."""
    chat, ask = _last_settled_ask(chat_id, user)
    if not any(turn.get("status") == "done" for turn in ask.get("turns") or []):
        raise HTTPException(status_code=400, detail="还没有任何人发言，没法总结")
    _check_capacity(user)
    await _models(request, user)
    ask = dict(ask)
    ask.update({"status": "concluding", "endedAt": None, "error": None})
    _start(request, user, chat, ask, history=_history(chat, ask["id"]), conclude_only=True)
    return _detail(chat_id, user)


@router.post("/{chat_id}/continue")
async def continue_discussion(request: Request, chat_id: str, user=Depends(get_verified_user)):
    """One more round on the last question, then a fresh conclusion."""
    chat, ask = _last_settled_ask(chat_id, user)
    if ask.get("mode") == "review":
        raise HTTPException(status_code=400, detail="独立评审固定两轮；可以追问")
    done_rounds = max([turn.get("round") or 0 for turn in ask.get("turns") or []] or [0])
    if done_rounds >= room.MAX_ROUNDS + 2:
        raise HTTPException(status_code=400, detail="这一问已经讨论很多轮了；可以追问")
    _check_capacity(user)
    await _models(request, user)
    ask = dict(ask)
    # drop turns of an unfinished round: it is run again from the start
    complete = {
        r
        for r in {turn.get("round") for turn in ask.get("turns") or []}
        if all(t.get("status") in {"done", "error"} for t in ask["turns"] if t.get("round") == r)
    }
    last_complete = max(complete or {0})
    ask["turns"] = [turn for turn in ask.get("turns") or [] if (turn.get("round") or 0) <= last_complete]
    ask.update({"status": "running", "endedAt": None, "error": None, "rounds": last_complete + 1})
    _start(request, user, chat, ask, history=_history(chat, ask["id"]), from_round=last_complete + 1)
    return _detail(chat_id, user)


@router.post("/{chat_id}/retry")
async def retry_turn(request: Request, chat_id: str, form: RetryForm, user=Depends(get_verified_user)):
    """Run one seat's failed or stopped turn again, then a fresh conclusion."""
    chat, ask = _last_settled_ask(chat_id, user)
    turn = next((t for t in ask.get("turns") or [] if t.get("id") == form.turn), None)
    if turn is None:
        raise HTTPException(status_code=404, detail="找不到这段发言")
    if turn.get("status") not in {"error", "stopped"}:
        raise HTTPException(status_code=400, detail="这段发言已经完成")
    _check_capacity(user)
    await _models(request, user)
    ask = dict(ask)
    ask.update({"status": "running", "endedAt": None, "error": None})
    _start(request, user, chat, ask, history=_history(chat, ask["id"]), retry_turn=form.turn)
    return _detail(chat_id, user)


@router.delete("/{chat_id}")
async def delete_discussion(chat_id: str, user=Depends(get_verified_user)):
    _own(chat_id, user)
    await room.stop_live(chat_id)
    return {"ok": bool(Chats.delete_chat_by_id_and_user_id(chat_id, user.id))}
