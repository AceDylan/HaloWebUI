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
    ImageStudioMigrationModel,
    ImageStudioMigrations,
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


class ImageStudioLegacyImportForm(BaseModel):
    items: list[ImageStudioItemForm] = Field(
        min_length=1, max_length=IMAGE_STUDIO_MAX_ITEMS_PER_REQUEST
    )


class ImageStudioLegacyImportResult(BaseModel):
    accepted: bool
    uploaded: int
    migration: Optional[ImageStudioMigrationModel] = None


def _reject_oversized(items: list[ImageStudioItemForm]) -> None:
    for item in items:
        if image_studio_item_size(item.data) > IMAGE_STUDIO_MAX_ITEM_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Image studio item '{item.id}' exceeds {IMAGE_STUDIO_MAX_ITEM_BYTES} bytes"
                ),
            )


def _close_legacy_migration(user_id: str, source: str) -> None:
    """Best effort: never let the migration bookkeeping break a data request."""
    try:
        ImageStudioMigrations.close(user_id, source)
    except Exception as exc:
        log.warning("Failed to close image studio legacy migration: %s", exc)


@router.get("/items", response_model=list[ImageStudioItemModel])
async def get_image_studio_items(
    kind: Optional[ImageStudioKind] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=5000),
    user=Depends(get_verified_user),
):
    """List the current user's items, newest first."""
    items = ImageStudioItems.get_items_by_user_id(user.id, kind=kind, limit=limit)
    # An account that already holds server data has nothing left to migrate;
    # closing it here (before any delete can happen) keeps stale browser copies
    # from re-uploading items later.
    try:
        ImageStudioMigrations.close_if_account_has_data(user.id)
    except Exception as exc:
        log.warning("Failed to record image studio migration state: %s", exc)
    return items


@router.post("/items/upsert", response_model=list[ImageStudioItemModel])
async def upsert_image_studio_items(
    form_data: ImageStudioUpsertForm, user=Depends(get_verified_user)
):
    """Create or replace items by id. Only the caller's own rows are touched."""
    _reject_oversized(form_data.items)

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
        deleted = ImageStudioItems.delete_item_by_id_and_user_id(item_id, user.id)
    except Exception as exc:
        log.exception("Failed to delete image studio item: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting image studio item"),
        )
    if deleted:
        _close_legacy_migration(user.id, "curated")
    return deleted


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
    _close_legacy_migration(user.id, "curated")
    return True


@router.get("/legacy-migration", response_model=Optional[ImageStudioMigrationModel])
async def get_image_studio_legacy_migration(user=Depends(get_verified_user)):
    """The account's legacy-upload state; ``null`` while a first upload is still possible."""
    return ImageStudioMigrations.get_by_user_id(user.id)


@router.post("/legacy-migration", response_model=ImageStudioLegacyImportResult)
async def import_image_studio_legacy_items(
    form_data: ImageStudioLegacyImportForm, user=Depends(get_verified_user)
):
    """Upload what a browser still holds only in localStorage, once per account.

    Unlike ``/items/upsert`` this is refused (``accepted: false``, nothing
    stored) as soon as the account has been through its legacy upload, already
    holds server items, or has deleted items on the server. Deliberate imports
    from the templates tab keep using ``/items/upsert``.
    """
    _reject_oversized(form_data.items)

    try:
        migration, items = ImageStudioMigrations.import_legacy_items(
            user.id, form_data.items
        )
    except Exception as exc:
        log.exception("Failed to import legacy image studio items: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error saving image studio items"),
        )

    accepted = bool(items)
    if accepted and any(item.kind == "history" for item in items):
        ImageStudioItems.trim_items(user.id, "history", IMAGE_STUDIO_HISTORY_LIMIT)
    return ImageStudioLegacyImportResult(
        accepted=accepted, uploaded=len(items), migration=migration
    )
