"""Authenticated Hermes image imports; permanent files and idempotent gallery rows."""
import base64
import binascii
import io
import time
import uuid

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from open_webui.models.files import FileForm, Files
from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems
from open_webui.storage.provider import Storage
from open_webui.utils.image_output import compact_generated_image

MAX_BYTES = 32 * 1024 * 1024


class HermesImageForm(BaseModel):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=120)
    prompt: str = Field(default="", max_length=8000)
    size: str = Field(default="auto", max_length=80)
    created_at_ms: int = Field(gt=0, le=32_503_680_000_000)
    platform: str = Field(default="", max_length=80)
    session_id: str = Field(default="", max_length=256)
    chat_id: str = Field(default="", max_length=256)
    team_id: str = Field(default="", max_length=64)
    image_base64: str = Field(min_length=1, max_length=4 * ((MAX_BYTES + 2) // 3))


def store_image(form: HermesImageForm, user_id: str, *, chat_id: str = "", team_id: str = "") -> dict:
    model = form.model.lower().split("/")[-1]
    if not (model.startswith("gpt-image") or model == "chatgpt-image-latest"):
        raise HTTPException(422, "Only GPT Image results may be imported")
    file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hermes-image:{user_id}:{form.event_id}"))
    item_id = f"gallery_hermes_{form.event_id}"
    url = f"/api/v1/files/{file_id}/content"
    existing = Files.get_file_by_id(file_id)
    if existing and (existing.data or {}).get("gallery_recorded"):
        return {"stored": True, "duplicate": True, "url": url}
    if existing is None:
        try:
            raw = base64.b64decode(form.image_base64, validate=True)
            if len(raw) > MAX_BYTES:
                raise ValueError("image too large")
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("unsupported image")
                content_type = Image.MIME[picture.format]
                picture.verify()
        except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            raise HTTPException(422, "Invalid PNG, JPEG or WebP image") from None
        raw, content_type = compact_generated_image(raw, content_type)
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[content_type]
        name = f"{file_id}.{extension}"
        size, path = Storage.upload_file(io.BytesIO(raw), name)
        existing = Files.insert_new_file(user_id, FileForm(
            id=file_id, filename=name, path=path,
            meta={"name": name, "content_type": content_type, "size": size,
                  "hermes_event_id": form.event_id},
        ))
        if existing is None:
            raise HTTPException(503, "Could not persist image file")
    data = {"id": item_id, "url": url, "prompt": form.prompt, "model": form.model,
            "size": form.size, "createdAt": min(form.created_at_ms, int(time.time() * 1000)),
            "source": "hermes", "hermesSessionId": form.session_id,
            **({"chatId": chat_id} if chat_id else {}), **({"teamId": team_id} if team_id else {})}
    ImageStudioItems.upsert_items(user_id, [ImageStudioItemForm(id=item_id, kind="gallery", data=data)])
    if Files.update_file_data_by_id(file_id, {"gallery_recorded": True}) is None:
        raise HTTPException(503, "Could not acknowledge gallery import")
    return {"stored": True, "duplicate": False, "url": url}
