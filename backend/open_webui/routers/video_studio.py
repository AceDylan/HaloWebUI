"""The video studio's library (/workspace/videos): the videos Hermes and the runners made.

Rows are written by utils/video_library.py when a reply or a report hands a video over;
this lists them a page at a time (newest first, the same cursor as the image gallery) and
takes one out of the library. The workbench itself starts its work in a chat (Hermes or a
runner does the making), so there is nothing to generate here.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat
from open_webui.models.image_studio import ImageStudioItemModel, ImageStudioItems
from open_webui.utils.auth import get_verified_user
from open_webui.utils.video_library import VIDEO_KIND

log = logging.getLogger(__name__)

router = APIRouter()


class VideoPage(BaseModel):
    items: list[ImageStudioItemModel]
    # the cursor of the page after (pass it as ``before``), null at the end
    next: Optional[str] = None


def _chat_titles(user_id: str, chat_ids: set[str]) -> dict[str, str]:
    """The current titles of the user's chats the videos were made in (a chat named after
    its first reply has no title yet when the video arrives)."""
    if not chat_ids:
        return {}
    try:
        with get_db() as db:
            rows = (
                db.query(Chat.id, Chat.title)
                .filter(Chat.user_id == user_id, Chat.id.in_(list(chat_ids)))
                .all()
            )
        return {row.id: row.title or "" for row in rows}
    except Exception as e:  # noqa: BLE001 — titles are a nicety
        log.warning("video library chat titles unavailable: %s", e)
        return {}


@router.get("/items", response_model=VideoPage)
async def get_video_page(
    limit: int = Query(default=24, ge=1, le=100),
    before: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """One page of the library, newest first; ``q`` searches the video's name. Each item
    carries ``chatTitle`` (the chat it came from, as it is called now) when that chat is
    still there; a chat deleted since leaves the video without a way back."""
    at, _, last_id = str(before or "").partition(":")
    try:
        cursor = (int(at), last_id) if last_id else None
    except ValueError:
        cursor = None
    items, more = ImageStudioItems.page_items(
        user.id, VIDEO_KIND, limit=limit, before=cursor, query=q
    )
    titles = _chat_titles(
        user.id, {str(item.data.get("chatId")) for item in items if item.data.get("chatId")}
    )
    shown = []
    for item in items:
        data = dict(item.data)
        chat_id = data.get("chatId")
        if chat_id and chat_id in titles:
            data["chatTitle"] = titles[chat_id]
        elif chat_id:
            data.pop("chatId", None)
        shown.append(item.model_copy(update={"data": data}))
    return {
        "items": shown,
        "next": f"{items[-1].created_at}:{items[-1].id}" if more and items else None,
    }


@router.delete("/items/{item_id}", response_model=bool)
async def delete_video(item_id: str, user=Depends(get_verified_user)):
    """Takes a video out of the library; the file stays in the chat that shows it."""
    if not item_id.startswith("video_"):
        raise HTTPException(404, "视频不存在")
    return ImageStudioItems.delete_item_by_id_and_user_id(item_id, user.id)
