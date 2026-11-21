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
COVR_SCAN_BYTES = 8 * 1024 * 1024
FRAME_ZERO_MODEL = "视频第 0 帧"
COVER_PROMPT = """参考图是一支视频的第一帧画面。请把它重新绘制成这支视频的封面（缩略图）：
- 保持参考图里的主角、场景、画风和配色，让人一眼认出是同一支视频；不要换成别的风格；
- 构图更集中、更有冲击力，主体清晰、光影更精致，适合在视频列表里小尺寸显示；
- 封面上只写一个标题：「{title}」，字大、醒目、清晰，不要错别字，不要写任何其他文字、logo、水印或播放按钮；
- 画幅是 {orientation}，主体和标题放在中间区域，四周留出安全边距（边缘会被裁掉一点）；
- 画面不透明，不要留白边框。{extra}"""
VERTICAL_COVER_EXTRA = (
    "\n- 这是竖屏短视频（抖音风格）动画封面：严格保持参考帧的卡通/插画动画美术风格与主角神态，强化光影层次与构图张力，"
    "不要做成纯黑底大字海报；标题干净醒目、高对比配色（纯白或暖亮色配柔和深描边），不遮挡主角脸部与核心画面，"
    "主体与标题集中在黄金安全区（避开顶部状态栏、右侧互动按钮列和底部文案栏，四周留足约 15% 安全边距），"
    "确保手机信息流小图 0.5 秒一眼看出动画质感与主题。"
)
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


def first_frame(path: str, max_side: int = REFERENCE_MAX_SIDE, quality: int = 90) -> tuple[bytes, int, int]:
    """The first frame with something on it, as JPEG bytes (at most *max_side*), and the
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
        scale = min(1.0, max_side / max(chosen.shape[0], chosen.shape[1]))
        if scale < 1.0:
            chosen = cv2.resize(chosen, (int(chosen.shape[1] * scale), int(chosen.shape[0] * scale)),
                                interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", chosen, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise IllustrateError("首帧转图片失败")
        return encoded.tobytes(), width, height
    finally:
        capture.release()


# 缩略图: a video without a cover (older than the covers, or its cover failed) shows its first
# frame as a small JPEG in the library and as the players' poster, instead of each <video> tile
# buffering megabytes of the video over a slow link. Made once per file, kept in the cache.
THUMB_MAX_SIDE = 480
THUMB_QUALITY = 80
_thumb_slots: Optional[asyncio.Semaphore] = None


def thumb_path(file_id: str) -> str:
    from open_webui.config import CACHE_DIR

    return os.path.join(str(CACHE_DIR), "video-thumbs", f"{file_id}.jpg")


def drop_thumb(file_id: str) -> None:
    try:
        os.remove(thumb_path(file_id))
    except OSError:
        pass


async def thumbnail(file_id: str, video_path: str) -> bytes:
    """The cached first-frame JPEG of *file_id* (made from *video_path* the first time; two at a
    time, a page of tiles asks at once)."""
    global _thumb_slots
    target = thumb_path(file_id)
    try:
        with open(target, "rb") as f:
            return f.read()
    except OSError:
        pass
    if _thumb_slots is None:
        _thumb_slots = asyncio.Semaphore(2)
    async with _thumb_slots:
        if os.path.isfile(target):
            with open(target, "rb") as f:
                return f.read()
        jpeg, _, _ = await asyncio.to_thread(first_frame, video_path, THUMB_MAX_SIDE, THUMB_QUALITY)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        partial = f"{target}.{os.getpid()}.part"
        with open(partial, "wb") as f:
            f.write(jpeg)
        os.replace(partial, target)
        return jpeg


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


def has_cover_art(path: str) -> bool:
    """The MP4 carries cover art (a ``covr`` atom): the video studio pipeline put its cover there
    and in frame 0 (skill video-studio ``scripts/cover.py``), so that frame is the cover."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(COVR_SCAN_BYTES)
            f.seek(max(0, size - COVR_SCAN_BYTES))
            tail = f.read(COVR_SCAN_BYTES)
        return b"covr" in head or b"covr" in tail
    except OSError:
        return False


def frame_zero(path: str) -> tuple[bytes, int, int]:
    """Frame 0 as a JPEG at full size, and the video's width and height."""
    import cv2

    capture = cv2.VideoCapture(path)
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            raise IllustrateError("视频里读不出画面")
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            raise IllustrateError("首帧转图片失败")
        return encoded.tobytes(), frame.shape[1], frame.shape[0]
    finally:
        capture.release()


async def draw_from_frame(request, user, frame: bytes, width: int, height: int, title: str) -> tuple[bytes, str]:
    """gpt-image redraws *frame* as the cover titled *title*, cut to width:height; (JPEG, model).
    The uncut picture image generation stored as a file of the user's is removed again."""
    from open_webui.routers.images import GenerateImageForm, image_generations
    from open_webui.utils.chat_image_refs import extract_chat_image_file_id, resolve_chat_image_url_to_bytes

    size, orientation = canvas_for(width, height)
    model = cover_model(user.id)
    extra = VERTICAL_COVER_EXTRA if height > width * 1.1 else ""
    form = GenerateImageForm(
        prompt=COVER_PROMPT.format(title=title, orientation=orientation, extra=extra),
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
    if not drawn:
        raise IllustrateError("读不到生成的图片")
    cover = await asyncio.to_thread(fit_to, drawn[1], width, height)
    _remove_file(extract_chat_image_file_id(url))
    return cover, (model or "").rsplit("::", 1)[-1]


def _remove_file(file_id: Optional[str]) -> None:
    if not file_id:
        return
    try:
        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage

        file = Files.get_file_by_id(file_id)
        if file is not None and file.path:
            Storage.delete_file(file.path)
        Files.delete_file_by_id(file_id)
    except Exception:  # noqa: BLE001 — only a leftover picture
        log.warning("video cover: could not remove the uncut picture %s", file_id, exc_info=True)


async def draw_cover(request, user, video: dict) -> dict:
    """The cover of a library video (its data); ``{"url", "fileId", "model"}``. A video whose
    frame 0 already is its cover (cover art in the MP4) gets that frame, without drawing."""
    from open_webui.routers.images import upload_image
    from open_webui.utils.chat_image_refs import extract_chat_image_file_id

    path = _local_path(str(video.get("fileId") or ""))
    if await asyncio.to_thread(has_cover_art, path):
        frame, width, height = await asyncio.to_thread(frame_zero, path)
        cover, model = await asyncio.to_thread(fit_to, frame, width, height), FRAME_ZERO_MODEL
    else:
        frame, width, height = await asyncio.to_thread(first_frame, path)
        title = cover_title(str(video.get("name") or ""), _chat_title(video.get("chatId")))
        cover, model = await draw_from_frame(request, user, frame, width, height, title)
    url = upload_image(request, {"video_cover": video.get("id"), "chat_id": video.get("chatId")}, cover, "image/jpeg", user)
    return {"url": url, "fileId": extract_chat_image_file_id(url) or "", "model": model}


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
