"""自动分流「交给 Hermes」: Hermes answers in a chat, as if the question had been sent to it there.

Three ways in: the chat's own message (utils/auto_dispatch.py keeps its request and calls
``run_turn``), a retry from a chat's card (``answer_in_chat`` on that reply, rebuilt from the saved
chat), and the /auto page (``open_chat`` makes a Hermes chat for the question first).
"""

import asyncio
import logging
import time
import uuid

from fastapi import HTTPException

from open_webui.models.chats import ChatForm, Chats

log = logging.getLogger(__name__)


def without_dispatch(form_data: dict) -> dict:
    """The request as a plain Hermes turn: the composer's model choice stays, the 派发方式 goes."""
    options = form_data.get("hermes_options")
    options = {k: v for k, v in options.items() if k != "dispatch"} if isinstance(options, dict) else None
    return {**form_data, "hermes_options": options}


async def run_turn(request, form_data, user, metadata, model, events=None, *, wait=False):
    """Hermes' normal run on ``metadata``'s reply (it streams and finishes that message). ``wait``:
    until the run is over, so stopping the caller's task stops the run with it."""
    from open_webui import tasks
    from open_webui.utils.hermes_agent import run_hermes_agent

    result = await run_hermes_agent(request, without_dispatch(form_data), user, metadata, model, events or [])
    task = tasks.tasks.get((result or {}).get("task_id") or "")
    if wait and task is not None:
        await task
    return result


async def _hermes_model(request, user, model_id=None):
    from open_webui.utils.hermes_sessions import HermesSessionsError, resolve_hermes_model

    try:
        return await resolve_hermes_model(request, user, model_id or None)
    except HermesSessionsError:
        if model_id:  # the chat's model is gone: the user's Hermes
            return await _hermes_model(request, user)
        raise HTTPException(403, "你的账号没有可用的 Hermes，请改选精答、讨论或协作台")


def _branch(messages: dict, reply_id: str) -> list[dict]:
    """The messages before ``reply_id`` on its branch, oldest first (ends with its question)."""
    chain, seen = [], set()
    cursor = messages.get((messages.get(reply_id) or {}).get("parentId") or "")
    while isinstance(cursor, dict) and cursor.get("id") not in seen:
        seen.add(cursor.get("id"))
        chain.append(cursor)
        cursor = messages.get(cursor.get("parentId") or "")
    return chain[::-1]


async def answer_in_chat(request, user, chat_id: str, message_id: str, route_id: str):
    """Hermes answers the question of reply ``message_id`` into that reply (its card stays on top)."""
    from open_webui.socket.main import get_event_emitter

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        raise HTTPException(404, "来源对话不存在")
    content = chat.chat or {}
    messages = (content.get("history") or {}).get("messages") or {}
    reply = messages.get(message_id)
    branch = _branch(messages, message_id)
    if not reply or not branch or branch[-1].get("role") != "user":
        raise HTTPException(400, "找不到这条回复对应的问题")
    model = await _hermes_model(request, user, reply.get("model") or ((content.get("models") or [None])[0]))
    system = str((content.get("params") or {}).get("system") or "").strip()
    form_data = {
        "model": model["id"],
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": m["role"], "content": m.get("content") or "", **({"stopped": True} if m.get("stopped") else {})}
           for m in branch if m.get("role") in ("user", "assistant")],
    }
    # pictures go as files too: Hermes is told where they are and looks at them itself
    files = [{**f, "type": "file"} if isinstance(f, dict) and f.get("type") == "image" else f
             for f in branch[-1].get("files") or []]
    metadata = {"user_id": user.id, "chat_id": chat_id, "message_id": message_id,
                "session_id": f"auto-route:{route_id}", "files": files}
    # a reply stopped earlier would refuse Hermes' writes (guard_stopped): this is a new answer
    fresh = {"content": "", "done": False, "error": None, "stopped": False, "stoppedByUser": False,
             "model": model["id"], "auto_route": {"id": route_id, "mode": "hermes"}}
    Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, fresh, set_current=False)
    try:
        await get_event_emitter(metadata, update_db=False)({"type": "chat:completion", "data": fresh})
    except Exception:  # an open page reads it on its next refresh
        log.debug("hermes route: could not tell the page", exc_info=True)
    result = await run_turn(request, form_data, user, metadata, model)
    if not result:
        raise HTTPException(503, "Hermes 现在连不上，请稍后重试或改选精答")
    return result


async def open_chat(request, user, form, route_id: str, *, on_created=None) -> tuple[str, str]:
    """A Hermes chat for a question asked on /auto: the question (and its files), Hermes' reply
    streaming under it. Background typed there becomes the chat's system prompt, so later turns
    keep it. Returns (chat id, reply id)."""
    from open_webui.routers import discussions
    from open_webui.utils.mode_chats import schedule_chat_metadata

    model = await _hermes_model(request, user)
    loaded = await asyncio.to_thread(discussions._load_files, form.files, user)
    ask, reply = str(uuid.uuid4()), str(uuid.uuid4())
    now = int(time.time())
    messages = {
        ask: {"id": ask, "parentId": None, "childrenIds": [reply], "role": "user", "content": form.question,
              "files": discussions._message_files(loaded), "timestamp": now, "models": [model["id"]]},
        reply: {"id": reply, "parentId": ask, "childrenIds": [], "role": "assistant", "content": "",
                "model": model["id"], "modelName": model.get("name") or "Hermes", "modelIdx": 0, "timestamp": now,
                "done": False, "auto_route": {"id": route_id, "mode": "hermes"}},
    }
    system = "\n\n".join(part for part in (
        f"对话背景（供参考，遵守用户当前要求）：\n{form.context}" if form.context else "",
        "" if form.research else "用户约束：不要联网检索，只使用提供的资料和本机内容。",
    ) if part)
    payload = {"title": "New Chat", "models": [model["id"]], "params": {"system": system} if system else {},
               "history": {"messages": messages, "currentId": reply}, "messages": [messages[ask], messages[reply]],
               "tags": [], "timestamp": int(time.time() * 1000)}
    chat = Chats.insert_new_chat(user.id, ChatForm(chat=payload))
    if chat is None:
        raise HTTPException(500, "创建 Hermes 对话失败")
    if on_created:
        on_created(chat.id)
    Chats.set_chat_meta_value_by_id(chat.id, "auto_route", {"id": route_id, "mode": "hermes"})
    schedule_chat_metadata(request, user, chat.id, model_id=model["id"],
                           messages=[{"role": "user", "content": form.question}], message_id=reply)
    await answer_in_chat(request, user, chat.id, reply, route_id)
    return chat.id, reply
