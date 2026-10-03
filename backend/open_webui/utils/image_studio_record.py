"""Chat images in the image studio.

The studio's gallery and history (models/image_studio.py) only knew the
workbench's own runs; images made in a chat lived in that message alone. Each
image generated in a chat is now also written there, in the item shapes the
studio already reads (src/lib/utils/image-studio-storage.ts), so the gallery
and history hold every image the person made in HaloWebUI. ``chatId`` lets the
studio link back to the conversation.
"""

import logging
from typing import Any, Optional

from open_webui.utils.chat_image_refs import (
    OPENWEBUI_FILE_URL_SCHEME,
    build_chat_image_content_url,
)
from open_webui.models.image_studio import (
    IMAGE_STUDIO_HISTORY_LIMIT,
    IMAGE_STUDIO_MAX_ITEM_BYTES,
    ImageStudioItemForm,
    ImageStudioItems,
    image_studio_item_size,
)

log = logging.getLogger(__name__)

_PROMPT_MAX_CHARS = 8000


def _image_urls(images: list[Any]) -> list[str]:
    urls: list[str] = []
    for image in images or []:
        url = str((image or {}).get("url") or "").strip() if isinstance(image, dict) else ""
        if url and url not in urls:
            urls.append(url)
    return urls


def _reference_urls(source_urls: list[str]) -> list[str]:
    # The studio shows and re-sends these, so they must be addresses a page
    # can load: the chat's internal openwebui-file:// form becomes the file's
    # content address, and inline data: images are too big to keep.
    urls: list[str] = []
    for url in source_urls or []:
        url = str(url or "").strip()
        if url.startswith(OPENWEBUI_FILE_URL_SCHEME):
            url = build_chat_image_content_url(url[len(OPENWEBUI_FILE_URL_SCHEME) :])
        if url and not url.startswith("data:") and url not in urls:
            urls.append(url)
    return urls[:4]


def _short_id(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")[:80]


def chat_image_studio_items(
    *,
    chat_id: Optional[str],
    message_id: Optional[str],
    prompt: str,
    options: dict[str, Any],
    images: list[Any],
    source_urls: list[str],
    started_at_ms: int,
    completed_at_ms: int,
) -> list[ImageStudioItemForm]:
    """The gallery entries and the history entry for one chat generation.

    Nothing for a temporary chat (``local:`` ids are never saved) or a run
    without a successful image.
    """
    chat_id = str(chat_id or "").strip()
    urls = _image_urls(images)
    if not chat_id or chat_id.startswith("local:") or not urls:
        return []

    prompt = str(prompt or "").strip()[:_PROMPT_MAX_CHARS]
    model = str(options.get("model") or "").strip()
    size = str(options.get("size") or "").strip()
    run_id = _short_id(message_id) or str(started_at_ms)

    parameters = {
        key: value
        for key, value in {
            "modelId": model or None,
            "size": size or None,
            "aspectRatio": options.get("aspect_ratio") or None,
            "resolution": options.get("resolution") or None,
            "quality": options.get("quality") or None,
            "numberOfImages": options.get("n") or None,
            "background": options.get("background") or None,
            "references": _reference_urls(source_urls) or None,
            "origin": "chat",
            "chatId": chat_id,
            "messageId": str(message_id or "") or None,
        }.items()
        if value is not None
    }

    forms = [
        ImageStudioItemForm(
            id=f"gallery_chat_{run_id}_{index}",
            kind="gallery",
            data={
                "id": f"gallery_chat_{run_id}_{index}",
                "url": url,
                "prompt": prompt,
                "model": model,
                "size": size or "auto",
                "createdAt": completed_at_ms,
                "chatId": chat_id,
            },
        )
        for index, url in enumerate(urls)
    ]
    forms.append(
        ImageStudioItemForm(
            id=f"history_chat_{run_id}",
            kind="history",
            data={
                "id": f"history_chat_{run_id}",
                "prompt": prompt,
                "model": model,
                "parameters": parameters,
                "status": "success",
                "images": urls,
                "createdAt": started_at_ms,
                "completedAt": completed_at_ms,
            },
        )
    )
    return [
        form
        for form in forms
        if image_studio_item_size(form.data) <= IMAGE_STUDIO_MAX_ITEM_BYTES
    ]


def record_chat_images_in_studio(user_id: str, **kwargs: Any) -> None:
    """Writes a chat generation into the user's studio; never fails the reply."""
    try:
        forms = chat_image_studio_items(**kwargs)
        if not forms or not user_id:
            return
        ImageStudioItems.upsert_items(user_id, forms)
        ImageStudioItems.trim_items(user_id, "history", IMAGE_STUDIO_HISTORY_LIMIT)
    except Exception as e:  # noqa: BLE001 — the image is already in the chat
        log.warning("Could not add chat images to the image studio: %s", e)
