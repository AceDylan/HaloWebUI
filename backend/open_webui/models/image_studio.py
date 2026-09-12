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
from sqlalchemy import JSON, BigInteger, Column, Index, Integer, String
from sqlalchemy.exc import IntegrityError

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


class ImageStudioMigration(Base):
    """Marks that an account may no longer receive automatic uploads of
    browser-local (legacy localStorage) image studio data.

    Browsers keep their own "already migrated" marker, but a browser that never
    wrote one (another device, cleared site data, an old injected copy) would
    otherwise re-upload whatever it still holds, including items the user has
    since deleted on the server. The row's existence is the gate; ``source``
    records why it was closed.
    """

    __tablename__ = "image_studio_migration"

    user_id = Column(String, primary_key=True)
    # "legacy-upload": a browser's local data was accepted (once per account).
    # "existing-data": the account already held server items, nothing uploaded.
    # "curated": the user deleted or cleared server items.
    source = Column(String, nullable=False)
    uploaded = Column(Integer, nullable=False, default=0)
    migrated_at = Column(BigInteger, nullable=False)  # epoch seconds


class ImageStudioMigrationModel(BaseModel):
    user_id: str
    source: str
    uploaded: int
    migrated_at: int

    model_config = ConfigDict(from_attributes=True)


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


def _dedupe_forms(forms: list[ImageStudioItemForm]) -> list[ImageStudioItemForm]:
    """Last occurrence of an id wins inside one request."""
    deduped: dict[str, ImageStudioItemForm] = {}
    for form in forms:
        deduped[form.id] = form
    return list(deduped.values())


def _upsert_rows(
    db, user_id: str, forms: list[ImageStudioItemForm], now: int
) -> list[ImageStudioItem]:
    """Adds or updates the caller's rows inside ``db`` without committing."""
    rows: list[ImageStudioItem] = []
    for form in forms:
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
    return rows


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
        forms = _dedupe_forms(forms)
        if not forms:
            return []

        now = int(time.time())
        with get_db() as db:
            rows = _upsert_rows(db, user_id, forms, now)
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


class ImageStudioMigrationsTable:
    def get_by_user_id(self, user_id: str) -> Optional[ImageStudioMigrationModel]:
        with get_db() as db:
            row = db.get(ImageStudioMigration, user_id)
            return ImageStudioMigrationModel.model_validate(row) if row else None

    def close(
        self, user_id: str, source: str, uploaded: int = 0
    ) -> ImageStudioMigrationModel:
        """Records that legacy uploads are over for this account.

        Idempotent: an existing row, including one inserted by a concurrent
        request, is kept as it is.
        """
        with get_db() as db:
            row = db.get(ImageStudioMigration, user_id)
            if row is None:
                row = ImageStudioMigration(
                    user_id=user_id,
                    source=source,
                    uploaded=uploaded,
                    migrated_at=int(time.time()),
                )
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    row = db.get(ImageStudioMigration, user_id)
            return ImageStudioMigrationModel.model_validate(row)

    def close_if_account_has_data(
        self, user_id: str
    ) -> Optional[ImageStudioMigrationModel]:
        """Closes accounts that already hold server items (nothing to migrate)."""
        with get_db() as db:
            row = db.get(ImageStudioMigration, user_id)
            if row is not None:
                return ImageStudioMigrationModel.model_validate(row)
            has_items = (
                db.query(ImageStudioItem.id).filter_by(user_id=user_id).first()
                is not None
            )
        if not has_items:
            return None
        return self.close(user_id, "existing-data")

    def import_legacy_items(
        self, user_id: str, forms: list[ImageStudioItemForm]
    ) -> tuple[Optional[ImageStudioMigrationModel], list[ImageStudioItemModel]]:
        """Claims the account's single legacy upload and stores ``forms`` with it.

        Everything happens in one transaction, so either the claim and all
        items are stored or nothing is. Returns the migration row and the
        stored items; the list is empty whenever the upload was not accepted
        (the account was already closed, holds server data, or another request
        won the claim at the same moment).
        """
        forms = _dedupe_forms(forms)
        now = int(time.time())
        with get_db() as db:
            existing = db.get(ImageStudioMigration, user_id)
            if existing is not None:
                return ImageStudioMigrationModel.model_validate(existing), []

            has_items = (
                db.query(ImageStudioItem.id).filter_by(user_id=user_id).first()
                is not None
            )
            record = ImageStudioMigration(
                user_id=user_id,
                source="existing-data" if has_items else "legacy-upload",
                uploaded=0 if has_items else len(forms),
                migrated_at=now,
            )
            db.add(record)
            rows = [] if has_items else _upsert_rows(db, user_id, forms, now)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                winner = db.get(ImageStudioMigration, user_id)
                if winner is None:
                    # Not a lost claim but a clash on an item row; let the caller retry.
                    raise
                return ImageStudioMigrationModel.model_validate(winner), []
            db.refresh(record)
            for item in rows:
                db.refresh(item)
            return (
                ImageStudioMigrationModel.model_validate(record),
                [ImageStudioItemModel.model_validate(item) for item in rows],
            )

    def delete_by_user_id(self, user_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(ImageStudioMigration).filter_by(user_id=user_id).delete()
                db.commit()
                return True
        except Exception:
            return False


ImageStudioMigrations = ImageStudioMigrationsTable()
