"""The video library: every video Hermes hands over, in a chat reply or a runner's report.

Hermes and the runners make videos on the host and name them with ``MEDIA:<path>``;
hermes_media fetches each one into the user's files (hermes_agent._store_generated_file).
A video stored there is also written here, as one row of the studio item table
(models/image_studio.py) with kind ``video``, so the video studio (/workspace/videos) lists
them a page at a time however many pile up. The file stays where the chat shows it: taking
a video out of the library leaves the chat alone.

One row per video, not per stored copy: a reply recovered after a reconnect fetches the
same file again, so the id comes from the file's name and size.
"""

import hashlib
import logging
import os
import time
from typing import Optional

from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems

log = logging.getLogger(__name__)

VIDEO_KIND = "video"
# Where a video came from: Hermes' own reply, or a runner's report (codex, reclaude, …).
VIDEO_ORIGINS = ("hermes", "runner")


def video_item_id(name: str, size: int) -> str:
    digest = hashlib.sha1(f"{name}\0{int(size or 0)}".encode("utf-8")).hexdigest()
    return f"video_{digest[:24]}"


def video_form(
    *,
    file_id: str,
    name: str,
    size: int,
    content_type: str,
    chat_id: Optional[str] = None,
    origin: str = "hermes",
    created_at_ms: Optional[int] = None,
) -> ImageStudioItemForm:
    name = os.path.basename(str(name or "").strip()) or "video.mp4"
    item_id = video_item_id(name, size)
    data = {
        "id": item_id,
        "fileId": file_id,
        "url": f"/api/v1/files/{file_id}/content",
        "name": name,
        "title": os.path.splitext(name)[0] or name,
        "size": int(size or 0),
        "contentType": content_type or "video/mp4",
        "origin": origin if origin in VIDEO_ORIGINS else "hermes",
        "createdAt": int(created_at_ms or time.time() * 1000),
    }
    chat_id = str(chat_id or "").strip()
    if chat_id and not chat_id.startswith("local:"):
        data["chatId"] = chat_id
    return ImageStudioItemForm(id=item_id, kind=VIDEO_KIND, data=data)


def record_video(user_id: str, **kwargs) -> bool:
    """Adds a stored video to the user's library; never fails the reply or report it came in."""
    if not user_id:
        return False
    try:
        ImageStudioItems.upsert_items(user_id, [video_form(**kwargs)])
        return True
    except Exception as e:  # noqa: BLE001 — the video is already in the chat
        log.warning("Could not add a video to the video library: %s", e)
        return False
