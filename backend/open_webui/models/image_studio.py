"""Server-side storage for the workspace image studio.

Prompt templates, the gallery and the generation history used to live only in
the browser's localStorage. Each row here is one of those items, owned by a
single user. ``data`` keeps the exact item shape the frontend already uses, so
existing browser data can be uploaded as-is and the UI keeps working unchanged.
"""

import json
import math
import time
from typing import Literal, Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, BigInteger, Column, Index, String

ImageStudioKind = Literal["template", "gallery", "history"]
IMAGE_STUDIO_KINDS: tuple[str, ...] = ("template", "gallery", "history")

# Newest history rows kept per user; older ones are trimmed on write.
IMAGE_STUDIO_HISTORY_LIMIT = 200
IMAGE_STUDIO_MAX_ITEMS_PER_REQUEST = 500
IMAGE_STUDIO_MAX_ITEM_BYTES = 64 * 1024
IMAGE_STUDIO_ID_MAX_CHARS = 128


####################
# Image studio DB schema
####################


class ImageStudioItem(Base):
    __tablename__ = "image_studio_item"

    # Ids are generated client-side (and may travel between users through
    # template export files), so the primary key is (id, user_id).
    id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    kind = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(BigInteger, nullable=False)  # epoch seconds
    updated_at = Column(BigInteger, nullable=False)  # epoch seconds

    __table_args__ = (
        Index(
            "ix_image_studio_item_user_kind_created",
            "user_id",
            "kind",
            "created_at",
        ),
    )


class ImageStudioItemModel(BaseModel):
    id: str
    user_id: str
    kind: ImageStudioKind
    data: dict
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class ImageStudioItemForm(BaseModel):
    id: str = Field(min_length=1, max_length=IMAGE_STUDIO_ID_MAX_CHARS)
    kind: ImageStudioKind
    data: dict


def image_studio_item_size(data: dict) -> int:
    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _created_at_from_data(data: dict, now: int) -> int:
    """Use the item's own createdAt (ms or s) so migrated items keep their order."""
    raw = data.get("createdAt", data.get("created_at"))
    if isinstance(raw, bool):
        return now
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return now
    if not math.isfinite(value) or value <= 0:
        return now
    if value > 1e11:  # milliseconds
        value = value / 1000
    return int(value)


class ImageStudioItemsTable:
    def get_items_by_user_id(
        self,
        user_id: str,
        kind: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[ImageStudioItemModel]:
        with get_db() as db:
            query = db.query(ImageStudioItem).filter_by(user_id=user_id)
            if kind:
                query = query.filter_by(kind=kind)
            query = query.order_by(
                ImageStudioItem.created_at.desc(), ImageStudioItem.id.desc()
            )
            if limit:
                query = query.limit(limit)
            return [ImageStudioItemModel.model_validate(item) for item in query.all()]

    def upsert_items(
        self, user_id: str, forms: list[ImageStudioItemForm]
    ) -> list[ImageStudioItemModel]:
        # Last occurrence of an id wins inside one request.
        deduped: dict[str, ImageStudioItemForm] = {}
        for form in forms:
            deduped[form.id] = form
        if not deduped:
            return []

        now = int(time.time())
        with get_db() as db:
            rows: list[ImageStudioItem] = []
            for form in deduped.values():
                item = db.get(ImageStudioItem, {"id": form.id, "user_id": user_id})
                if item:
                    item.kind = form.kind
                    item.data = form.data
                    item.updated_at = now
                else:
                    item = ImageStudioItem(
                        id=form.id,
                        user_id=user_id,
                        kind=form.kind,
                        data=form.data,
                        created_at=_created_at_from_data(form.data, now),
                        updated_at=now,
                    )
                    db.add(item)
                rows.append(item)
            db.commit()
            for item in rows:
                db.refresh(item)
            return [ImageStudioItemModel.model_validate(item) for item in rows]

    def trim_items(self, user_id: str, kind: str, keep: int) -> list[str]:
        """Delete everything but the newest ``keep`` items of ``kind``; returns deleted ids."""
        keep = max(0, int(keep))
        with get_db() as db:
            stale = (
                db.query(ImageStudioItem.id)
                .filter_by(user_id=user_id, kind=kind)
                .order_by(ImageStudioItem.created_at.desc(), ImageStudioItem.id.desc())
                .offset(keep)
                .all()
            )
            ids = [row.id for row in stale]
            if ids:
                db.query(ImageStudioItem).filter(
                    ImageStudioItem.user_id == user_id,
                    ImageStudioItem.kind == kind,
                    ImageStudioItem.id.in_(ids),
                ).delete(synchronize_session=False)
                db.commit()
            return ids

    def delete_item_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        with get_db() as db:
            deleted = (
                db.query(ImageStudioItem).filter_by(id=id, user_id=user_id).delete()
            )
            db.commit()
            return deleted > 0

    def delete_items_by_user_id_and_kind(self, user_id: str, kind: str) -> bool:
        try:
            with get_db() as db:
                db.query(ImageStudioItem).filter_by(user_id=user_id, kind=kind).delete()
                db.commit()
                return True
        except Exception:
            return False

    def delete_items_by_user_id(self, user_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(ImageStudioItem).filter_by(user_id=user_id).delete()
                db.commit()
                return True
        except Exception:
            return False


ImageStudioItems = ImageStudioItemsTable()
