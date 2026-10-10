"""Images made outside the image studio, in its gallery.

The studio's gallery (models/image_studio.py) only knew the workbench's own
runs; images made in a chat lived in that message alone, a team's result
picture only in its workspace. Each of them is now also written into the
gallery, in the item shape the studio already reads
(src/lib/utils/image-studio-storage.ts), so the gallery holds every image the
person made in HaloWebUI. ``chatId`` / ``teamId`` let the studio link back to
where it was made. The history stays the workbench's own runs.
"""

import logging
from typing import Any, Optional

from open_webui.models.image_studio import (
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


def _short_id(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")[:80]


def _gallery_form(item_id: str, data: dict) -> Optional[ImageStudioItemForm]:
    form = ImageStudioItemForm(id=item_id, kind="gallery", data={"id": item_id, **data})
    return form if image_studio_item_size(form.data) <= IMAGE_STUDIO_MAX_ITEM_BYTES else None


def chat_image_studio_items(
    *,
    chat_id: Optional[str],
    message_id: Optional[str],
    prompt: str,
    options: dict[str, Any],
    images: list[Any],
    completed_at_ms: int,
) -> list[ImageStudioItemForm]:
    """The gallery entries for one chat generation.

    Nothing for a temporary chat (``local:`` ids are never saved) or a run
    without a successful image.
    """
    chat_id = str(chat_id or "").strip()
    urls = _image_urls(images)
    if not chat_id or chat_id.startswith("local:") or not urls:
        return []

    prompt = str(prompt or "").strip()[:_PROMPT_MAX_CHARS]
    model = str(options.get("model") or "").strip()
    size = str(options.get("size") or "").strip() or "auto"
    run_id = _short_id(message_id) or str(completed_at_ms)
    forms = [
        _gallery_form(
            f"gallery_chat_{run_id}_{index}",
            {
                "url": url,
                "prompt": prompt,
                "model": model,
                "size": size,
                "createdAt": completed_at_ms,
                "chatId": chat_id,
            },
        )
        for index, url in enumerate(urls)
    ]
    return [form for form in forms if form is not None]


def team_image_studio_item(
    *, team_id: str, picture_id: str, url: str, prompt: str, model: str, created_at_ms: int
) -> Optional[ImageStudioItemForm]:
    """The gallery entry for a team's result picture (one per drawn picture)."""
    if not team_id or not url:
        return None
    return _gallery_form(
        f"gallery_team_{_short_id(team_id)}_{_short_id(picture_id)}",
        {
            "url": url,
            "prompt": str(prompt or "").strip()[:_PROMPT_MAX_CHARS],
            "model": model,
            "size": "auto",
            "createdAt": created_at_ms,
            "teamId": team_id,
        },
    )


def record_in_studio(user_id: str, forms: list[Optional[ImageStudioItemForm]]) -> bool:
    """Writes gallery entries into the user's studio; never fails the caller."""
    forms = [form for form in forms if form is not None]
    if not forms or not user_id:
        return False
    try:
        ImageStudioItems.upsert_items(user_id, forms)
        return True
    except Exception as e:  # noqa: BLE001 — the image is already where it was made
        log.warning("Could not add images to the image studio gallery: %s", e)
        return False


def record_chat_images_in_studio(user_id: str, **kwargs: Any) -> None:
    """Writes a chat generation into the user's studio gallery; never fails the reply."""
    try:
        forms = chat_image_studio_items(**kwargs)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not add chat images to the image studio: %s", e)
        return
    record_in_studio(user_id, forms)
