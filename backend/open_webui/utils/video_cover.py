"""视频封面: once a finished video is in the library, gpt-image draws its cover from its first frame.

A video that lands in the library (utils/video_library.record_video, whichever way it came: a
Hermes reply, a runner's report, a run started from Telegram) gets one cover, in the background:

1. its first frame with something on it (a fade from black or white is stepped past, up to
   ``SCAN_SECONDS``) is read with OpenCV;
2. the app's image generation, on the owner's gpt-image model (the one their image templates use;
   ``HALO_VIDEO_COVER_MODEL`` overrides), redraws that frame as a cover: same characters, palette
   and style, a stronger composition and the video's name as its only text;
3. the picture is cut to the video's own aspect ratio and stored as one of the owner's files.

The library row keeps where it stands: ``coverStatus`` generating | ready | failed, ``cover``
(the URL, used as the players' poster), ``coverModel``, ``coverError``. A video filed again keeps
its cover; ``start(..., force=True)`` (the library's 重新生成封面) draws a new one.
HALO_VIDEO_COVER=0 turns it off; so does image generation being off or not allowed for the user.
"""

import asyncio
import base64
import io
import logging
import os
import re
from typing import Optional

from open_webui.utils.mode_illustrate import IllustrateError, later, may_illustrate, now_ms

log = logging.getLogger(__name__)

ENV = "HALO_VIDEO_COVER"
MODEL_ENV = "HALO_VIDEO_COVER_MODEL"
TIMEOUT_SECONDS = 420
# A cover still "generating" after this was lost (a restart): it may be drawn again.
STALE_MS = 15 * 60 * 1000
SCAN_SECONDS = 5.0
SCAN_STEP_SECONDS = 0.25
REFERENCE_MAX_SIDE = 1280
COVER_MAX_SIDE = 1920
TITLE_MAX_CHARS = 40
# The template whose model a cover is drawn with first (the one 结论配图 uses), then any gpt-image one.
PREFERRED_TEMPLATE_ID = "halo_hand_v1_auto_style"
COVER_PROMPT = """参考图是一支视频的第一帧画面。请把它重新绘制成这支视频的封面（缩略图）：
- 保持参考图里的主角、场景、画风和配色，让人一眼认出是同一支视频；不要换成别的风格；
- 构图更集中、更有冲击力，主体清晰、光影更精致，适合在视频列表里小尺寸显示；
- 封面上只写一个标题：「{title}」，字大、醒目、清晰，不要错别字，不要写任何其他文字、logo、水印或播放按钮；
- 画幅是 {orientation}，主体和标题放在中间区域，四周留出安全边距（边缘会被裁掉一点）；
- 画面不透明，不要留白边框。{extra}"""
_NAME_NOISE = re.compile(r"[_\-]+")


def may_cover(request, user) -> bool:
    return may_illustrate(request, user, env=ENV)


def cover_model(user_id: str) -> Optional[str]:
    """The gpt-image model the owner draws with: ``HALO_VIDEO_COVER_MODEL``, else the model of
    their 手绘万能图 template when it is a gpt-image one, else of any template that is; None
    (the default image model) when none is."""
    override = os.environ.get(MODEL_ENV, "").strip()
    if override:
        return override
    from open_webui.models.image_studio import ImageStudioItems

    try:
        items = ImageStudioItems.get_items_by_user_id(user_id, kind="template", limit=200)
    except Exception:  # noqa: BLE001
        log.warning("video cover: could not read the image templates of %s", user_id, exc_info=True)
        return None
    found = None
    for item in items:
        config = (item.data or {}).get("config") if isinstance((item.data or {}).get("config"), dict) else {}
        model = str(config.get("model") or "").strip()
        if "gpt-image" not in model.lower():
            continue
        if item.id == PREFERRED_TEMPLATE_ID:
            return model
        found = found or model
    return found


def cover_title(name: str, chat_title: str = "") -> str:
    """The cover's one line of text: the video's file name without its extension and separators."""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    title = " ".join(_NAME_NOISE.sub(" ", stem).split()) or " ".join(str(chat_title or "").split())
    return title[:TITLE_MAX_CHARS] or "视频"


def _blank(frame) -> bool:
    """A frame of one color (black or white during a fade, a solid card)."""
    small = frame[::8, ::8]
    return float(small.std()) < 6.0


def first_frame(path: str) -> tuple[bytes, int, int]:
    """The first frame with something on it, as JPEG bytes (at most REFERENCE_MAX_SIDE), and the
    video's width and height."""
    import cv2

    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise IllustrateError("读不了这个视频")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise IllustrateError("视频里读不出画面")
        chosen = frame
        at = SCAN_STEP_SECONDS
        while _blank(chosen) and at <= SCAN_SECONDS:
            capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            chosen = frame
            at += SCAN_STEP_SECONDS
        height = height or chosen.shape[0]
        width = width or chosen.shape[1]
        scale = min(1.0, REFERENCE_MAX_SIDE / max(chosen.shape[0], chosen.shape[1]))
        if scale < 1.0:
            chosen = cv2.resize(chosen, (int(chosen.shape[1] * scale), int(chosen.shape[0] * scale)),
                                interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", chosen, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise IllustrateError("首帧转图片失败")
        return encoded.tobytes(), width, height
    finally:
        capture.release()


def canvas_for(width: int, height: int) -> tuple[str, str]:
    """The gpt-image size closest to the video's shape, and how the prompt names it."""
    if width > height * 1.1:
        return "1536x1024", "横版（最终裁成 16:9）" if abs(width / height - 16 / 9) < 0.05 else "横版"
    if height > width * 1.1:
        return "1024x1536", "竖版（最终裁成 9:16）" if abs(height / width - 16 / 9) < 0.05 else "竖版"
    return "1024x1024", "方形"


def fit_to(image_bytes: bytes, width: int, height: int) -> bytes:
    """The picture center-cut to width:height (the video's shape), at most COVER_MAX_SIDE, as JPEG."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as source:
        picture = source.convert("RGB")
    if width > 0 and height > 0:
        target = width / height
        w, h = picture.size
        if w / h > target:
            cut = int(round(h * target))
            left = (w - cut) // 2
            picture = picture.crop((left, 0, left + cut, h))
        elif w / h < target:
            cut = int(round(w / target))
            top = (h - cut) // 2
            picture = picture.crop((0, top, w, top + cut))
    longest = max(picture.size)
    if longest > COVER_MAX_SIDE:
        scale = COVER_MAX_SIDE / longest
        picture = picture.resize((int(picture.size[0] * scale), int(picture.size[1] * scale)), Image.LANCZOS)
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


def _local_path(file_id: str) -> str:
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage

    file = Files.get_file_by_id(file_id)
    if file is None or not file.path:
        raise IllustrateError("找不到视频文件")
    return Storage.get_file(file.path)


def _chat_title(chat_id: Optional[str]) -> str:
    if not chat_id:
        return ""
    try:
        from open_webui.models.chats import Chats

        chat = Chats.get_chat_by_id(chat_id)
        return str(getattr(chat, "title", "") or "") if chat else ""
    except Exception:  # noqa: BLE001
        return ""


async def draw_cover(request, user, video: dict) -> dict:
    """Draws one cover for a library video (its data); ``{"url", "fileId", "model"}``."""
    from open_webui.routers.images import GenerateImageForm, image_generations, upload_image
    from open_webui.utils.chat_image_refs import extract_chat_image_file_id, resolve_chat_image_url_to_bytes

    path = _local_path(str(video.get("fileId") or ""))
    frame, width, height = await asyncio.to_thread(first_frame, path)
    size, orientation = canvas_for(width, height)
    title = cover_title(str(video.get("name") or ""), _chat_title(video.get("chatId")))
    model = cover_model(user.id)
    form = GenerateImageForm(
        prompt=COVER_PROMPT.format(title=title, orientation=orientation, extra=""),
        model=model,
        size=size,
        image_url="data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii"),
        n=1,
    )
    images = await image_generations(request, form, user=user)
    url = next((str(i.get("url") or "") for i in images or [] if isinstance(i, dict) and i.get("url")), "")
    if not url:
        raise IllustrateError("生图没有返回图片")
    drawn = resolve_chat_image_url_to_bytes(url, user_id=user.id, is_admin=getattr(user, "role", "") == "admin")
    if drawn:
        try:
            cover = await asyncio.to_thread(fit_to, drawn[1], width, height)
            url = upload_image(request, {"video_cover": video.get("id"), "chat_id": video.get("chatId")},
                               cover, "image/jpeg", user)
        except Exception:  # noqa: BLE001 — the uncut picture is still a cover
            log.warning("video cover: could not cut the cover of %s; keeping it as drawn", video.get("id"), exc_info=True)
    return {"url": url, "fileId": extract_chat_image_file_id(url) or "",
            "model": (model or "").rsplit("::", 1)[-1]}


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "封面生成超时"
    detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
    return str(detail)[:300]


def busy(video: dict, force: bool = False) -> bool:
    """Whether this video's cover is being drawn (or is there and not asked again)."""
    status = video.get("coverStatus")
    if status == "generating":
        return now_ms() - int(video.get("coverStartedAt") or 0) < STALE_MS
    return status == "ready" and not force


async def make(request, user, item_id: str, force: bool = False) -> Optional[dict]:
    """Draws the cover of library video *item_id* and records it; returns the row's data
    (None when it is not in the library or its cover is already there / being drawn)."""
    from open_webui.utils.video_library import _get_video, set_video_fields

    row = _get_video(user.id, item_id)
    if row is None or busy(row.data or {}, force):
        return None
    started = now_ms()
    set_video_fields(user.id, item_id, {"coverStatus": "generating", "coverStartedAt": started, "coverError": None})
    try:
        cover = await asyncio.wait_for(draw_cover(request, user, {**(row.data or {}), "id": item_id}), TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        set_video_fields(user.id, item_id, {"coverStatus": "failed", "coverError": "已取消"})
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("video cover for %s failed: %r", item_id, exc)
        return set_video_fields(user.id, item_id, {"coverStatus": "failed", "coverError": _error_text(exc)})
    log.info("video cover for %s ready in %.1fs", item_id, (now_ms() - started) / 1000)
    return set_video_fields(user.id, item_id, {
        "coverStatus": "ready", "cover": cover["url"], "coverFileId": cover["fileId"] or None,
        "coverModel": cover["model"] or None, "coverAt": now_ms(), "coverError": None,
    })


def start(request, user, item_id: Optional[str], force: bool = False) -> bool:
    """Draws the cover in the background (a video was just filed). Returns whether it started."""
    if not item_id or request is None or not may_cover(request, user):
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    later(make(request, user, item_id, force))
    return True
