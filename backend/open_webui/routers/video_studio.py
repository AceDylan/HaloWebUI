"""The video studio's library (/workspace/videos): the videos Hermes and the runners made.

Rows are written by utils/video_library.py when a reply or a report hands a video over;
this lists them a page at a time (newest first, the same cursor as the image gallery) and
takes one out of the library. The workbench itself starts its work in a chat (Hermes or a
runner does the making), so there is nothing to generate here.

A runner started from Telegram reports there and never reaches a HaloWebUI chat: its notifier
(integrations/hermes-runner/reclaude-notify.py) posts the run's videos to ``/runner-videos``
with the notification token, and they are filed in the Hermes owner's library.

The workbench's 背景音乐 is an MP3 the user uploads (an ordinary file upload, not processed)
or picks again from their earlier ones: ``/music`` lists those.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat
from open_webui.models.files import File
from open_webui.models.image_studio import ImageStudioItemModel, ImageStudioItems
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from open_webui.utils.hermes_notify import notify_token_configured, verify_notify_token
from open_webui.utils.video_library import RUN_VIDEOS_MAX, VIDEO_KIND, import_run_videos

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


class MusicFile(BaseModel):
    id: str
    name: str
    size: int = 0
    createdAt: int = 0


@router.get("/music", response_model=list[MusicFile])
async def get_music(limit: int = Query(default=12, ge=1, le=50), user=Depends(get_verified_user)):
    """The user's own MP3 uploads, newest first (an admin too sees only theirs): the music the
    workbench can pick again. The same name and size uploaded twice is listed once."""
    with get_db() as db:
        rows = (
            db.query(File.id, File.filename, File.meta, File.created_at)
            .filter(File.user_id == user.id, File.path.isnot(None), File.filename.ilike("%.mp3"))
            .order_by(File.created_at.desc(), File.id.desc())
            .limit(limit * 3)
            .all()
        )
    music, seen = [], set()
    for row in rows:
        meta = row.meta if isinstance(row.meta, dict) else {}
        name = str(meta.get("name") or row.filename)
        size = int(meta.get("size") or 0)
        if (name, size) in seen:
            continue
        seen.add((name, size))
        music.append(MusicFile(id=row.id, name=name, size=size, createdAt=int(row.created_at or 0) * 1000))
        if len(music) >= limit:
            break
    return music


@router.delete("/items/{item_id}", response_model=bool)
async def delete_video(item_id: str, user=Depends(get_verified_user)):
    """Takes a video out of the library; the file stays in the chat that shows it."""
    if not item_id.startswith("video_"):
        raise HTTPException(404, "视频不存在")
    return ImageStudioItems.delete_item_by_id_and_user_id(item_id, user.id)


class RunnerVideosForm(BaseModel):
    run_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    runner: str = Field(default="", max_length=32)
    platform: str = Field(default="", max_length=32)
    title: str = Field(default="", max_length=400)
    paths: list[str] = Field(min_length=1, max_length=RUN_VIDEOS_MAX * 2)


@router.post("/runner-videos")
async def file_runner_videos(request: Request, form: RunnerVideosForm):
    """A background run's videos, from its notifier, into the library of the account that
    owns Hermes (the first user, the admin): the run reported to Telegram, not to a chat here.
    Each path is fetched from Hermes like a report's MEDIA tag; a run filed before is skipped."""
    if not notify_token_configured():
        raise HTTPException(503, "HERMES_AGENT_NOTIFY_TOKEN is not set")
    if not verify_notify_token(request.headers.get("Authorization")):
        raise HTTPException(401, "invalid notification token")
    owner = Users.get_first_user()
    if owner is None:
        raise HTTPException(503, "no account to file the videos for")
    run = {"run_id": form.run_id, "runner": form.runner, "platform": form.platform, "title": form.title}
    result = await import_run_videos(request, owner, paths=form.paths, run=run)
    log.info(
        "run %s videos: %d stored, %d already filed, %d failed",
        form.run_id, len(result["stored"]), len(result["skipped"]), len(result["failed"]),
    )
    return result
