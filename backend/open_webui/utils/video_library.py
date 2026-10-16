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
import re
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


def _run_fields(run: Optional[dict]) -> dict:
    """Which background run made it (a runner's report): ``runId``, ``runner``, ``platform``
    (where the run was started: ``telegram``, ``api_server`` …), ``runTitle`` (its task)."""
    if not isinstance(run, dict):
        return {}
    fields = {
        "runId": str(run.get("run_id") or "").strip()[:64],
        "runner": re.sub(r"-runner$", "", str(run.get("runner") or "").strip().lower())[:32],
        "platform": str(run.get("platform") or "").strip()[:32],
        "runTitle": " ".join(str(run.get("title") or "").split())[:120],
    }
    return {key: value for key, value in fields.items() if value}


def video_form(
    *,
    file_id: str,
    name: str,
    size: int,
    content_type: str,
    chat_id: Optional[str] = None,
    origin: str = "hermes",
    created_at_ms: Optional[int] = None,
    run: Optional[dict] = None,
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
        **_run_fields(run),
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


VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
RUN_VIDEOS_MAX = 6


def filed_run_videos(user_id: str, run_id: str) -> set[str]:
    """Names of the videos of this run already in the library (a repeated notify is a no-op)."""
    if not run_id:
        return set()
    rows = ImageStudioItems.get_items_by_user_id(user_id, kind=VIDEO_KIND)
    return {str(row.data.get("name") or "") for row in rows if row.data.get("runId") == run_id}


async def import_run_videos(request, user, *, paths: list[str], run: dict, fetch=None) -> dict:
    """Files the videos a background run made into *user*'s library when its report never
    reached a HaloWebUI chat (a run started from Telegram): each path is fetched from Hermes
    (GET /v1/media, as a report's MEDIA tag is) and stored as one of the user's files.
    Returns ``{"stored": [...], "skipped": [...], "failed": [{"path", "reason"}]}``.
    *fetch(path)* replaces the Hermes fetch in tests."""
    from open_webui.utils.hermes_agent import _store_generated_file
    from open_webui.utils.hermes_media import _fetch_from_hermes, hermes_media_url, media_kind

    out = {"stored": [], "skipped": [], "failed": []}
    wanted = []
    for path in paths:
        path = str(path or "").strip()
        if path.startswith("/") and path.lower().endswith(VIDEO_EXTENSIONS) and path not in wanted:
            wanted.append(path)
    already = filed_run_videos(user.id, str(run.get("run_id") or ""))
    out["skipped"] = [p for p in wanted if os.path.basename(p) in already]
    wanted = [p for p in wanted if p not in out["skipped"]]
    if not wanted:
        return out
    if fetch is None:
        from open_webui.utils.hermes_sessions import _connection, resolve_hermes_model

        model = await resolve_hermes_model(request, user)
        api_root, headers = _connection(request, user, model)
        media_url = hermes_media_url(api_root)

        async def fetch(path):
            return await _fetch_from_hermes(media_url, headers, path)

    metadata = {"chat_id": None, "media_origin": "runner", "video_run": run}
    for path in wanted[:RUN_VIDEOS_MAX]:
        name = os.path.basename(path)
        try:
            handle, content_type, problem = await fetch(path)
        except Exception as e:  # noqa: BLE001
            handle, content_type, problem = None, None, f"取回出错：{e}"
        if handle is None:
            out["failed"].append({"path": path, "reason": problem or "取不回"})
            continue
        try:
            if media_kind(content_type or "", name) != "video":
                out["failed"].append({"path": path, "reason": f"不是视频（{content_type}）"})
                continue
            _store_generated_file(request, user, metadata, name, handle, content_type or "video/mp4")
            out["stored"].append(path)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not store run video %s: %s", name, e)
            out["failed"].append({"path": path, "reason": "保存失败"})
        finally:
            handle.close()
    return out
