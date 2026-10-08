"""收藏: replies a person keeps, wherever they are in the history.

One row per (user, chat, message) with a short excerpt taken when it was
saved, so the list reads without loading every chat. The chat's title is read
live; a bookmark whose chat is gone is dropped the next time the list loads.
"""

import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.chats import Chat
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, String, Text

####################
# Bookmark DB Schema
####################


class MessageBookmark(Base):
    __tablename__ = "message_bookmark"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    role = Column(String, nullable=True)
    excerpt = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_message_bookmark_user_created", "user_id", "created_at"),
        Index("ix_message_bookmark_user_chat_message", "user_id", "chat_id", "message_id", unique=True),
    )


class MessageBookmarkModel(BaseModel):
    id: str
    user_id: str
    chat_id: str
    message_id: str
    role: Optional[str] = None
    excerpt: Optional[str] = None
    created_at: int

    model_config = ConfigDict(from_attributes=True)


class MessageBookmarkListItem(MessageBookmarkModel):
    chat_title: str = ""
    chat_archived: bool = False


class MessageBookmarksTable:
    def get_or_create(
        self,
        user_id: str,
        chat_id: str,
        message_id: str,
        role: Optional[str],
        excerpt: Optional[str],
    ) -> MessageBookmarkModel:
        with get_db() as db:
            existing = (
                db.query(MessageBookmark)
                .filter_by(user_id=user_id, chat_id=chat_id, message_id=message_id)
                .first()
            )
            if existing:
                return MessageBookmarkModel.model_validate(existing)

            row = MessageBookmark(
                id=str(uuid.uuid4()),
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                role=role,
                excerpt=excerpt,
                created_at=int(time.time()),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return MessageBookmarkModel.model_validate(row)

    def get_message_ids_by_chat(self, user_id: str, chat_id: str) -> list[str]:
        with get_db() as db:
            return [
                message_id
                for (message_id,) in db.query(MessageBookmark.message_id)
                .filter_by(user_id=user_id, chat_id=chat_id)
                .all()
            ]

    def get_list(self, user_id: str) -> list[MessageBookmarkListItem]:
        """Newest first, with the chat's current title; bookmarks of chats
        that no longer exist are removed on the way."""
        with get_db() as db:
            rows = (
                db.query(MessageBookmark, Chat.title, Chat.archived)
                .outerjoin(
                    Chat,
                    (Chat.id == MessageBookmark.chat_id) & (Chat.user_id == MessageBookmark.user_id),
                )
                .filter(MessageBookmark.user_id == user_id)
                .order_by(MessageBookmark.created_at.desc())
                .all()
            )
            orphans = [bookmark.id for bookmark, title, _ in rows if title is None]
            if orphans:
                db.query(MessageBookmark).filter(MessageBookmark.id.in_(orphans)).delete(
                    synchronize_session=False
                )
                db.commit()
            return [
                MessageBookmarkListItem(
                    **MessageBookmarkModel.model_validate(bookmark).model_dump(),
                    chat_title=title,
                    chat_archived=bool(archived),
                )
                for bookmark, title, archived in rows
                if title is not None
            ]

    def delete_by_id(self, user_id: str, id: str) -> bool:
        with get_db() as db:
            count = db.query(MessageBookmark).filter_by(user_id=user_id, id=id).delete()
            db.commit()
            return count > 0

    def delete_by_message(self, user_id: str, chat_id: str, message_id: str) -> bool:
        with get_db() as db:
            count = (
                db.query(MessageBookmark)
                .filter_by(user_id=user_id, chat_id=chat_id, message_id=message_id)
                .delete()
            )
            db.commit()
            return count > 0

    def delete_by_user_id(self, user_id: str) -> bool:
        with get_db() as db:
            db.query(MessageBookmark).filter_by(user_id=user_id).delete()
            db.commit()
            return True


MessageBookmarks = MessageBookmarksTable()
