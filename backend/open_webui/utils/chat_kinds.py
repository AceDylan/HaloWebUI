"""What kind of work a chat in the sidebar list is: a 讨论台 discussion, a 精答 answer, a chat a
协作台 team works for, or a chat that made images. The list marks them so the chat and its modes
read as one list (instead of separate places)."""

import logging
from typing import Iterable

from sqlalchemy import String, cast

from open_webui.internal.db import get_db

log = logging.getLogger(__name__)

# newest chat-made gallery entries looked at for the 生图 mark
IMAGE_SCAN_LIMIT = 800


def chat_kinds(user_id: str, chat_ids: Iterable[str]) -> dict[str, str]:
    """``{chat_id: 'discuss' | 'answer' | 'team' | 'image'}`` for the given chats (others are plain
    chats). A discussion wins over an answer, an answer over a team, a team over images. Never
    raises: no marks on failure."""
    ids = [chat_id for chat_id in dict.fromkeys(chat_ids) if chat_id]
    if not ids:
        return {}
    from open_webui.models.agent_teams import AgentTeam
    from open_webui.models.chats import Chat
    from open_webui.models.image_studio import ImageStudioItem

    wanted = set(ids)
    kinds: dict[str, str] = {}
    try:
        with get_db() as db:
            rows = (
                db.query(ImageStudioItem.data)
                .filter(
                    ImageStudioItem.user_id == user_id,
                    ImageStudioItem.kind == "gallery",
                    ImageStudioItem.id.like("gallery_chat_%"),
                )
                .order_by(ImageStudioItem.created_at.desc())
                .limit(IMAGE_SCAN_LIMIT)
                .all()
            )
            for (data,) in rows:
                chat_id = (data or {}).get("chatId") if isinstance(data, dict) else None
                if chat_id in wanted:
                    kinds[chat_id] = "image"
            for (chat_id,) in (
                db.query(AgentTeam.chat_id)
                .filter(AgentTeam.user_id == user_id, AgentTeam.chat_id.in_(ids))
                .all()
            ):
                if chat_id:
                    kinds[chat_id] = "team"
            for (chat_id,) in (
                db.query(Chat.id)
                .filter(
                    Chat.user_id == user_id,
                    Chat.id.in_(ids),
                    cast(Chat.meta, String).like('%"answer_desk"%'),
                )
                .all()
            ):
                kinds[chat_id] = "answer"
            for (chat_id,) in (
                db.query(Chat.id)
                .filter(
                    Chat.user_id == user_id,
                    Chat.id.in_(ids),
                    cast(Chat.meta, String).like('%"discussion_room"%'),
                )
                .all()
            ):
                kinds[chat_id] = "discuss"
    except Exception:
        log.exception("chat kinds")
        return {}
    return kinds


def with_kinds(user_id: str, items: list) -> list:
    """The list rows (ChatTitleIdResponse and kin) with their ``kind`` filled in."""
    kinds = chat_kinds(user_id, [getattr(item, "id", None) for item in items])
    for item in items:
        kind = kinds.get(getattr(item, "id", None))
        if kind:
            item.kind = kind
    return items
