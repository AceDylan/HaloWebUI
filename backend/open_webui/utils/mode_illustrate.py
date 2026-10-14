"""结论配图 for the modes that write their own chats (精答, 讨论台), like a team's result picture.

Once an answer or a conclusion is done, it gets one picture on its own: the run's model condenses
it into what fits on one picture (a title, a subtitle, 3–6 short points), then the app's own image
generation draws it in the owner's 「手绘万能图 · 自动选画风与画幅」 image template (its prompt,
model and canvas; without it the default image model and a plain hand-drawn infographic prompt).
The picture is a file of the owner's like any generated image; it goes into the image studio
gallery (linked back to the chat) and into the chat's message under the answer's title.

The run keeps where it stands as ``illustration`` ({status: generating|ready|failed, url, ...});
the caller stores it and tells the page. The picture is the work's last step: while it is drawn the
work stays in 运行中 (``DRAWING``), and its "done" notice goes out once the picture is there.
HALO_MODES_AUTO_ILLUSTRATE=0 turns it off; so does image generation being off or not allowed for the user (then nothing is shown at all).
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

AUTO_ENV = "HALO_MODES_AUTO_ILLUSTRATE"
TIMEOUT_SECONDS = 420
CONDENSE_TIMEOUT_SECONDS = 120
TEXT_MAX_CHARS = 30000
CONDENSE_SYSTEM = """你要把一份结果提炼成一张图上放的内容。只输出这些内容本身，不要解释、不要代码块：
标题：不超过 16 个字
副标题：一句话（可省略）
要点：3 到 6 条，每条不超过 14 个字，可在前面加一个贴切的 emoji
用和结果相同的语言，只用结果里有的信息，数字和专有名词照抄。"""
FALLBACK_PROMPT = (
    "请把下面的内容画成一张手绘风格的信息图：一个醒目的标题，3–6 个要点配简单的图标和箭头，"
    "选择合适的不透明底色，确保文字和插图有足够对比度；中文清晰可读、不要错别字、不要拼凑的假文字。\n\n内容："
)
FALLBACK_NAME = "手绘信息图"
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)

OnChange = Callable[[dict], Awaitable[None]]
_background: set = set()
# chat id -> the 运行中 row of a finished answer / conclusion whose picture is being drawn
DRAWING: dict[str, dict] = {}


class IllustrateError(Exception):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def may_illustrate(request, user) -> bool:
    """Automatic pictures are on, and this user may generate images at all."""
    if os.environ.get(AUTO_ENV, "1") == "0":
        return False
    try:
        from open_webui.routers.images import _can_use_image_generation

        enabled = getattr(request.app.state.config, "ENABLE_IMAGE_GENERATION", False)
        return bool(enabled) and _can_use_image_generation(request, user)
    except Exception:  # noqa: BLE001 — no picture rather than a failed answer
        log.warning("illustrate: could not tell whether images may be generated", exc_info=True)
        return False


def picture_template(user_id: str) -> Optional[dict]:
    """The owner's 「手绘万能图」 image template (by id, else by name) as drawing needs it, the same
    one a team's result is drawn in; None when there is none."""
    from open_webui.models.image_studio import ImageStudioItems
    from open_webui.utils.agent_teams import CONCLUSION_TEMPLATE_ID, CONCLUSION_TEMPLATE_NAME

    try:
        items = ImageStudioItems.get_items_by_user_id(user_id, kind="template", limit=200)
    except Exception:  # noqa: BLE001
        log.warning("illustrate: could not read the image templates of %s", user_id, exc_info=True)
        return None
    found = None
    for item in items:
        data = item.data if isinstance(item.data, dict) else {}
        if item.id == CONCLUSION_TEMPLATE_ID:
            found = data
            break
        if found is None and CONCLUSION_TEMPLATE_NAME in str(data.get("name") or ""):
            found = data
    config = (found or {}).get("config") if isinstance((found or {}).get("config"), dict) else {}
    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        return None
    return {
        "name": str(found.get("name") or "模板")[:60],
        "prompt": prompt[:6000],
        "model": str(config.get("model") or "").strip() or None,
        "size": str(config.get("size") or "").strip() or None,
        "aspect": str(config.get("aspectRatio") or "").strip() or None,
    }


def _content_of(res: Any) -> str:
    if hasattr(res, "body") and not isinstance(res, dict):
        try:
            res = json.loads(res.body)
        except Exception:  # noqa: BLE001
            return ""
    if not isinstance(res, dict):
        return ""
    choices = res.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    text = str((choices[0].get("message") or {}).get("content") or "")
    return _THINK_RE.sub("", text).strip()


async def condense(request, user, model_id: str, text: str, metadata: dict) -> str:
    """What goes on the picture, written by the run's own model."""
    from open_webui.utils.chat import generate_chat_completion

    payload = {
        "model": model_id,
        "messages": [{"role": "system", "content": CONDENSE_SYSTEM}, {"role": "user", "content": text[:TEXT_MAX_CHARS]}],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 800,
        "metadata": metadata,
    }
    res = await asyncio.wait_for(generate_chat_completion(request, payload, user), CONDENSE_TIMEOUT_SECONDS)
    content = _content_of(res)
    if not content:
        raise IllustrateError("没能提炼出图上的内容")
    return content


async def draw(request, user, template: Optional[dict], content: str) -> dict:
    """One picture through the app's image generation; ``{"url", "model", "template", "prompt"}``."""
    from open_webui.routers.images import GenerateImageForm, image_generations

    template = template or {}
    prompt = (str(template.get("prompt") or FALLBACK_PROMPT).rstrip() + "\n" + content.strip()).strip()
    form = GenerateImageForm(
        prompt=prompt,
        model=template.get("model"),
        size=template.get("size"),
        aspect_ratio=template.get("aspect"),
        n=1,
    )
    images = await image_generations(request, form, user=user)
    url = next(
        (str(i.get("url") or "") for i in images or [] if isinstance(i, dict) and str(i.get("url") or "").strip()),
        "",
    )
    if not url:
        raise IllustrateError("生图没有返回图片")
    model = str(template.get("model") or "")
    return {
        "url": url,
        "model": model.rsplit("::", 1)[-1] if model else "",
        "template": template.get("name") or FALLBACK_NAME,
        "prompt": prompt,
        "size": template.get("size") or "auto",
    }


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "配图超时"
    detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
    return str(detail)[:300]


async def illustrate(
    request,
    user,
    *,
    chat_id: str,
    message_id: str,
    text: str,
    model_id: str,
    task: str,
    on_change: OnChange,
    held: Optional[dict] = None,
) -> Optional[dict]:
    """Draw the picture for a finished answer / conclusion. ``on_change`` gets the illustration
    entry as it moves (generating, then ready or failed). ``held``: the work's 运行中 row from
    ``hold``, let go once the picture is there (or none is drawn). Never raises; None when no
    picture is drawn for this user at all."""
    try:
        if not text.strip() or not may_illustrate(request, user):
            return None
        return await _illustrate(request, user, chat_id, message_id, text, model_id, task, on_change)
    finally:
        release(chat_id, held)


def hold(request, user, chat_id: str, activity: dict) -> Optional[dict]:
    """Keep a just-finished answer / conclusion in 运行中 ({kind, title, started_at}) until its
    picture is drawn: from the moment its text is done, so it does not drop out while it is named.
    None when no picture will be drawn. Hand the row to ``illustrate`` (or ``release`` it)."""
    if not may_illustrate(request, user):
        return None
    row = {**activity, "user_id": user.id}
    DRAWING[chat_id] = row
    return row


def release(chat_id: str, row: Optional[dict]) -> None:
    if row is not None and DRAWING.get(chat_id) is row:
        DRAWING.pop(chat_id, None)


async def _illustrate(request, user, chat_id, message_id, text, model_id, task, on_change) -> dict:
    template = picture_template(user.id)
    started = now_ms()
    entry: dict = {"status": "generating", "startedAt": started, "template": (template or {}).get("name") or FALLBACK_NAME}

    async def change(fields: dict) -> None:
        entry.update(fields)
        try:
            await on_change(dict(entry))
        except Exception:  # noqa: BLE001
            log.warning("illustrate: could not record the picture of %s", chat_id, exc_info=True)

    await change({"step": "condense"})

    async def run() -> dict:
        content = await condense(request, user, model_id, text, {"chat_id": chat_id, "message_id": message_id, "task": task})
        await change({"step": "draw"})
        return await draw(request, user, template, content)

    try:
        picture = await asyncio.wait_for(run(), TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.info("illustrate: %s picture for %s failed: %s", task, chat_id, exc)
        await change({"status": "failed", "error": _error_text(exc), "step": "", "endedAt": now_ms()})
        return dict(entry)

    from open_webui.utils.image_studio_record import record_chat_images_in_studio

    ended = now_ms()
    record_chat_images_in_studio(
        user.id,
        chat_id=chat_id,
        message_id=message_id,
        prompt=picture["prompt"],
        options={"model": picture["model"], "size": picture["size"]},
        images=[{"url": picture["url"]}],
        completed_at_ms=ended,
    )
    await change(
        {
            "status": "ready",
            "url": picture["url"],
            "model": picture["model"],
            "template": picture["template"],
            "step": "",
            "error": "",
            "endedAt": ended,
            "seconds": round((ended - started) / 1000, 1),
        }
    )
    return dict(entry)


def later(job: Awaitable[Any]) -> None:
    """Run *job* on its own, outside the run's task (a chat task of that id would read as a reply
    still being written, and its stop button would cancel the picture)."""

    async def guarded() -> None:
        try:
            await job
        except Exception:  # noqa: BLE001
            log.exception("illustrate: background job failed")

    task = asyncio.create_task(guarded())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def settle() -> None:
    """Wait for the background jobs started so far (tests)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


def picture_summary(illustration: Optional[dict]) -> Optional[dict]:
    """What a list row keeps of the picture: whether it is still being drawn (结论配图中)."""
    if not isinstance(illustration, dict) or not illustration.get("status"):
        return None
    return {"status": illustration["status"], "startedAt": illustration.get("startedAt")}


def with_picture(markdown: str, illustration: Optional[dict], title: str = "配图") -> str:
    """*markdown* with its ready picture under its leading ``# title`` (on top when it has none),
    the way the chat view and a report back show it."""
    illustration = illustration or {}
    markdown = markdown or ""
    if illustration.get("status") != "ready" or not illustration.get("url") or not markdown.strip():
        return markdown
    alt = re.sub(r"[\[\]\n]", " ", title or "配图").strip()[:40] or "配图"
    block = f"![{alt}]({illustration['url']})"
    lines = markdown.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if lines[first].startswith("# "):
        head, tail = lines[: first + 1], lines[first + 1 :]
        while tail and not tail[0].strip():
            tail = tail[1:]
        return "\n".join(head + ["", block, ""] + tail)
    return f"{block}\n\n{markdown.lstrip()}"
