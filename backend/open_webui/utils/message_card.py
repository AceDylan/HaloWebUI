"""「生成 HTML 卡片」 / 「生成配图」 asked for under a reply in the chat.

Nothing makes a reply's HTML card (or a result's picture) on its own any more: the person asks for
it. A reply in the chat gets its card here; the results of 精答, 讨论台 and 协作台 keep theirs where
they always did (the run's ``card`` / the team's ``result_card``), so a reply of theirs is handed to
its own mode. The design itself is unchanged: AGY designs the card from the finished text
(utils/html_visual_prompt.py, via utils/mode_card.py) and it replaces any HTML the model wrote.

While it is designed the reply carries ``htmlCard`` ({status: designing|ready|failed, reason,
startedAt, endedAt}); the page is told with a ``chat:message:html_card`` event, and gets the new
content as a ``chat:completion`` (content only) once the card is in.
"""

import logging
from typing import Any, Optional

from fastapi import HTTPException

from open_webui.models.chats import Chats
from open_webui.socket.main import get_event_emitter
from open_webui.utils import mode_card

log = logging.getLogger(__name__)

EVENT = "chat:message:html_card"
STATE_KEY = "htmlCard"
TEAM_RUN_PREFIX = "team:"


def _emitter(user_id: str, chat_id: str, message_id: str):
    return get_event_emitter(
        {"user_id": user_id, "chat_id": chat_id, "message_id": message_id, "session_id": None},
        update_db=False,
    )


async def tell(user_id: str, chat_id: str, message_id: str, entry: Optional[dict], content: Optional[str] = None) -> None:
    """The page: where the reply's card stands, and its content once the card is in."""
    emit = _emitter(user_id, chat_id, message_id)
    try:
        if entry is not None:
            await emit({"type": EVENT, "data": public(entry)})
        if content is not None:
            await emit({"type": "chat:completion", "data": {"content": content}})
    except Exception:  # noqa: BLE001 — saved; the chat shows it on next open
        log.debug("message card: event for %s/%s failed", chat_id, message_id, exc_info=True)


def public(entry: Optional[dict]) -> Optional[dict]:
    """The card entry as the page reads it (without its HTML, which is in the content)."""
    if not isinstance(entry, dict):
        return None
    return {k: entry[k] for k in ("status", "reason", "startedAt", "endedAt") if k in entry}


def _messages(chat) -> dict:
    return (((chat.chat or {}).get("history") or {}).get("messages") or {}) if chat is not None else {}


def _reply(user, chat_id: str, message_id: str) -> tuple[Any, dict, dict]:
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = _messages(chat)
    message = messages.get(message_id)
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise HTTPException(status_code=404, detail="没有这条回复")
    if message.get("done") is False:
        raise HTTPException(status_code=409, detail="回复还没写完，写完再生成")
    if not str(message.get("content") or "").strip():
        raise HTTPException(status_code=409, detail="这条回复没有内容")
    return chat, messages, message


def team_of(messages: dict, message: dict) -> Optional[str]:
    """The team whose conclusion this reply is (its notice carries ``team:<id>:<version>``)."""
    notice = (messages.get(message.get("parentId") or "") or {}).get("hermes_notice") or {}
    run_id = str(notice.get("run_id") or "")
    if not run_id.startswith(TEAM_RUN_PREFIX):
        return None
    return run_id[len(TEAM_RUN_PREFIX):].split(":", 1)[0] or None


async def start_card(request, user, chat_id: str, message_id: str) -> dict:
    """「生成 HTML 卡片」 under a reply: designs it in the background; the card entry as it stands."""
    from open_webui.utils.answer_desk import MESSAGE_KEY as ANSWER_KEY
    from open_webui.utils.discussion_room import MESSAGE_KEY as DISCUSSION_KEY

    _chat, messages, message = _reply(user, chat_id, message_id)
    if not mode_card.enabled():
        raise HTTPException(status_code=403, detail="HTML 卡片已在服务端关闭")
    if isinstance(message.get(ANSWER_KEY), dict):
        from open_webui.routers.answers import start_card as answer_card

        return public(answer_card(user, chat_id, message_id)) or {}
    if isinstance(message.get(DISCUSSION_KEY), dict):
        from open_webui.routers.discussions import start_card as discussion_card

        return public(discussion_card(user, chat_id, message_id)) or {}
    team_id = team_of(messages, message)
    if team_id:
        from open_webui.utils.agent_team_outputs import start_card as team_card

        return public(await _team_call(request, user, team_id, team_card)) or {}

    current = message.get(STATE_KEY)
    if mode_card.busy(current):
        return public(current) or {}
    entry = {"status": "designing", "startedAt": mode_card.now_ms()}
    _save(chat_id, message_id, {STATE_KEY: entry})
    mode_card.later(_design(user, chat_id, message_id, str(message.get("content") or "")))
    return public(entry) or {}


async def _team_call(request, user, team_id: str, start):
    """*start*(team, target) for the team whose result a reply is; its errors as HTTP ones."""
    from open_webui.utils.agent_team_outputs import team_and_target
    from open_webui.utils.agent_teams import TeamsError

    try:
        team, target = await team_and_target(request, user, team_id)
        return await start(team, target)
    except TeamsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _save(chat_id: str, message_id: str, update: dict) -> None:
    Chats.upsert_message_to_chat_by_id_and_message_id(
        chat_id, message_id, update, guard_stopped=True, set_current=False
    )


async def _design(user, chat_id: str, message_id: str, content: str) -> None:
    from open_webui.utils.hermes_notify import split_report_header

    await tell(user.id, chat_id, message_id, {"status": "designing", "startedAt": mode_card.now_ms()})
    # A runner report's header lines stay outside the card (the chat shows them above it).
    header, body = split_report_header(content)
    merged, entry = await mode_card.design_merged(body)
    entry = {k: v for k, v in entry.items() if k != "html"}
    current = _messages(Chats.get_chat_by_id_and_user_id(chat_id, user.id)).get(message_id) or {}
    if str(current.get("content") or "") != content:
        # edited, regenerated or deleted meanwhile: a card of the old text would not fit
        entry = {**entry, "status": "failed", "reason": "changed"}
        if current:
            _save(chat_id, message_id, {STATE_KEY: entry})
        await tell(user.id, chat_id, message_id, entry)
        return
    if entry.get("status") != "ready":
        _save(chat_id, message_id, {STATE_KEY: entry})
        await tell(user.id, chat_id, message_id, entry)
        return
    designed = f"{header}\n\n{merged}" if header else merged
    _save(chat_id, message_id, {"content": designed, STATE_KEY: entry})
    await tell(user.id, chat_id, message_id, entry, designed)


async def start_picture(request, user, chat_id: str, message_id: str) -> dict:
    """「生成配图」 under a reply of 精答, 讨论台 or 协作台: hands it to its mode."""
    from open_webui.utils.answer_desk import MESSAGE_KEY as ANSWER_KEY
    from open_webui.utils.discussion_room import MESSAGE_KEY as DISCUSSION_KEY

    _chat, messages, message = _reply(user, chat_id, message_id)
    if isinstance(message.get(ANSWER_KEY), dict):
        from open_webui.routers.answers import start_picture as answer_picture

        return answer_picture(request, user, chat_id, message_id).get("illustration") or {}
    if isinstance(message.get(DISCUSSION_KEY), dict):
        from open_webui.routers.discussions import start_picture as discussion_picture

        return discussion_picture(request, user, chat_id, message_id).get("illustration") or {}
    team_id = team_of(messages, message)
    if team_id:
        from open_webui.utils.agent_team_outputs import start_picture as team_picture

        return await _team_call(request, user, team_id, team_picture)
    raise HTTPException(status_code=400, detail="只有精答、讨论台和协作台的结果可以配图")
