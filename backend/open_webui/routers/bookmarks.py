"""收藏 (models/bookmarks.py): keep a reply, list kept replies, open one again."""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.bookmarks import (
    MessageBookmarkListItem,
    MessageBookmarkModel,
    MessageBookmarks,
)
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

EXCERPT_CHARS = 280

_DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.S | re.I)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>\n]{1,500}>")
_WS_RE = re.compile(r"\s+")


def message_excerpt(content) -> str:
    if isinstance(content, list):
        content = " ".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    text = _DETAILS_RE.sub(" ", str(content or ""))
    text = _IMAGE_RE.sub("[图片]", text)
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rstrip() + "…"


@router.get("/", response_model=list[MessageBookmarkListItem])
async def get_bookmarks(user=Depends(get_verified_user)):
    return MessageBookmarks.get_list(user.id)


@router.get("/chat/{chat_id}", response_model=list[str])
async def get_chat_bookmarks(chat_id: str, user=Depends(get_verified_user)):
    """The message ids kept in one chat, for the marks on its replies."""
    return MessageBookmarks.get_message_ids_by_chat(user.id, chat_id)


class BookmarkForm(BaseModel):
    chat_id: str
    message_id: str


@router.post("/", response_model=Optional[MessageBookmarkModel])
async def add_bookmark(form_data: BookmarkForm, user=Depends(get_verified_user)):
    chat = Chats.get_chat_by_id_and_user_id(form_data.chat_id, user.id)
    history = (chat.chat or {}).get("history") if chat else None
    messages = history.get("messages") if isinstance(history, dict) else None
    message = messages.get(form_data.message_id) if isinstance(messages, dict) else None
    if not isinstance(message, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    return MessageBookmarks.get_or_create(
        user.id,
        chat.id,
        form_data.message_id,
        message.get("role"),
        message_excerpt(message.get("content")),
    )


@router.delete("/chat/{chat_id}/{message_id}", response_model=bool)
async def delete_bookmark_by_message(
    chat_id: str, message_id: str, user=Depends(get_verified_user)
):
    return MessageBookmarks.delete_by_message(user.id, chat_id, message_id)


@router.delete("/{id}", response_model=bool)
async def delete_bookmark(id: str, user=Depends(get_verified_user)):
    return MessageBookmarks.delete_by_id(user.id, id)
