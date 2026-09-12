"""Per-user storage API for the workspace image studio (templates, gallery, history)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.image_studio import (
    IMAGE_STUDIO_HISTORY_LIMIT,
    IMAGE_STUDIO_MAX_ITEM_BYTES,
    IMAGE_STUDIO_MAX_ITEMS_PER_REQUEST,
    ImageStudioItemForm,
    ImageStudioItemModel,
    ImageStudioItems,
    ImageStudioKind,
    image_studio_item_size,
)
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


class ImageStudioUpsertForm(BaseModel):
    items: list[ImageStudioItemForm] = Field(
        default_factory=list, max_length=IMAGE_STUDIO_MAX_ITEMS_PER_REQUEST
    )


class ImageStudioClearForm(BaseModel):
    kind: ImageStudioKind


@router.get("/items", response_model=list[ImageStudioItemModel])
async def get_image_studio_items(
    kind: Optional[ImageStudioKind] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=5000),
    user=Depends(get_verified_user),
):
    """List the current user's items, newest first."""
    return ImageStudioItems.get_items_by_user_id(user.id, kind=kind, limit=limit)


@router.post("/items/upsert", response_model=list[ImageStudioItemModel])
async def upsert_image_studio_items(
    form_data: ImageStudioUpsertForm, user=Depends(get_verified_user)
):
    """Create or replace items by id. Only the caller's own rows are touched."""
    for item in form_data.items:
        if image_studio_item_size(item.data) > IMAGE_STUDIO_MAX_ITEM_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Image studio item '{item.id}' exceeds {IMAGE_STUDIO_MAX_ITEM_BYTES} bytes"
                ),
            )

    if not form_data.items:
        return []

    try:
        items = ImageStudioItems.upsert_items(user.id, form_data.items)
        if any(item.kind == "history" for item in items):
            ImageStudioItems.trim_items(user.id, "history", IMAGE_STUDIO_HISTORY_LIMIT)
        return items
    except Exception as exc:
        log.exception("Failed to upsert image studio items: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error saving image studio items"),
        )


@router.delete("/items/{item_id}", response_model=bool)
async def delete_image_studio_item(item_id: str, user=Depends(get_verified_user)):
    try:
        return ImageStudioItems.delete_item_by_id_and_user_id(item_id, user.id)
    except Exception as exc:
        log.exception("Failed to delete image studio item: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting image studio item"),
        )


@router.post("/items/clear", response_model=bool)
async def clear_image_studio_items(
    form_data: ImageStudioClearForm, user=Depends(get_verified_user)
):
    """Remove every item of one kind (e.g. "clear history") for the current user."""
    if not ImageStudioItems.delete_items_by_user_id_and_kind(user.id, form_data.kind):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error clearing image studio items"),
        )
    return True
