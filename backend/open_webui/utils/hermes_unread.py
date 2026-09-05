"""Unread markers for finished hermes runs.

hermes turns run for minutes and are mostly dispatched and left. Notifications
only reach the person when no tab is open, so a run that finishes while they
are in another chat leaves no trace in the sidebar. A finished run marks its
chat unread (``chat.meta.hermes_unread``); opening the chat clears it.
"""

import logging
import time

from sqlalchemy import text

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.chats import Chat

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

UNREAD_KEY = "hermes_unread"
UNREAD_AT_KEY = "hermes_unread_at"
LIST_LIMIT = 200


def _set_flag(chat_id: str, user_id: str, unread: bool) -> bool:
    """Returns False only when the chat does not belong to the user (or the
    write failed); clearing an already-clear chat is a no-op that returns True."""
    try:
        with get_db() as db:
            chat = db.query(Chat).filter_by(id=chat_id, user_id=user_id).first()
            if chat is None:
                return False
            meta = dict(chat.meta or {})
            if unread:
                meta[UNREAD_KEY] = True
                meta[UNREAD_AT_KEY] = int(time.time())
            else:
                if UNREAD_KEY not in meta and UNREAD_AT_KEY not in meta:
                    return True
                meta.pop(UNREAD_KEY, None)
                meta.pop(UNREAD_AT_KEY, None)
            # Reassign (not mutate) so SQLAlchemy sees the JSON column change;
            # updated_at is left alone on purpose — unread must not reorder the list.
            chat.meta = meta
            db.commit()
            return True
    except Exception as e:
        log.warning(f"hermes unread flag update failed for {chat_id}: {e}")
        return False


def mark_unread(chat_id: str, user_id: str) -> bool:
    return _set_flag(chat_id, user_id, True)


def mark_read(chat_id: str, user_id: str) -> bool:
    return _set_flag(chat_id, user_id, False)


def list_unread_chat_ids(user_id: str, limit: int = LIST_LIMIT) -> list[str]:
    try:
        with get_db() as db:
            dialect = db.bind.dialect.name
            if dialect == "sqlite":
                flag = text("json_extract(chat.meta, '$.hermes_unread') = 1")
            elif dialect == "postgresql":
                flag = text("(chat.meta->>'hermes_unread')::boolean IS TRUE")
            else:
                log.warning(f"hermes unread listing not supported on {dialect}")
                return []
            rows = (
                db.query(Chat.id)
                .filter(Chat.user_id == user_id, Chat.archived == False, flag)  # noqa: E712
                .order_by(Chat.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [row[0] for row in rows]
    except Exception as e:
        log.warning(f"hermes unread listing failed for {user_id}: {e}")
        return []
