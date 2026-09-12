"""Server-side storage for workspace image studio templates / gallery / history.

Runs against a throwaway SQLite database: the environment is pointed at a temp
directory before any open_webui module is imported, so the app's own peewee +
Alembic migrations create the schema (which also exercises the new revision).
"""

import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-image-studio-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "image-studio-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.internal.db import engine  # noqa: E402
from open_webui.models.image_studio import (  # noqa: E402
    IMAGE_STUDIO_HISTORY_LIMIT,
    ImageStudioItemForm,
    ImageStudioItems,
)
from open_webui.routers import image_studio  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402


class _User:
    def __init__(self, id: str):
        self.id = id
        self.role = "user"


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(image_studio.router, prefix="/api/v1/image-studio")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def test_migration_created_the_table_with_composite_key():
    inspector = sa.inspect(engine)
    assert "image_studio_item" in inspector.get_table_names()
    pk = inspector.get_pk_constraint("image_studio_item")["constrained_columns"]
    assert set(pk) == {"id", "user_id"}
    index_names = {
        index["name"] for index in inspector.get_indexes("image_studio_item")
    }
    assert "ix_image_studio_item_user_kind_created" in index_names


def test_upsert_list_delete_and_clear_are_scoped_to_the_user():
    alice = _client("alice")
    bob = _client("bob")

    payload = {
        "items": [
            {
                "id": "template_1",
                "kind": "template",
                "data": {
                    "id": "template_1",
                    "name": "Poster",
                    "config": {"prompt": "x"},
                },
            },
            {
                "id": "gallery_1",
                "kind": "gallery",
                "data": {
                    "id": "gallery_1",
                    "url": "/api/v1/files/a/content",
                    "createdAt": 1700000000000,
                },
            },
            {
                "id": "history_1",
                "kind": "history",
                "data": {"id": "history_1", "prompt": "x", "status": "success"},
            },
        ]
    }
    res = alice.post("/api/v1/image-studio/items/upsert", json=payload)
    assert res.status_code == 200, res.text
    assert {item["id"] for item in res.json()} == {
        "template_1",
        "gallery_1",
        "history_1",
    }
    assert all(item["user_id"] == "alice" for item in res.json())
    gallery_row = next(item for item in res.json() if item["id"] == "gallery_1")
    assert gallery_row["created_at"] == 1700000000  # taken from data.createdAt (ms)

    # Bob sees nothing of Alice's and may reuse the same ids for his own rows.
    assert bob.get("/api/v1/image-studio/items").json() == []
    res = bob.post(
        "/api/v1/image-studio/items/upsert",
        json={
            "items": [
                {"id": "template_1", "kind": "template", "data": {"name": "Bob's"}}
            ]
        },
    )
    assert res.status_code == 200, res.text
    assert (
        alice.get("/api/v1/image-studio/items?kind=template").json()[0]["data"]["name"]
        == "Poster"
    )
    assert (
        bob.get("/api/v1/image-studio/items?kind=template").json()[0]["data"]["name"]
        == "Bob's"
    )

    # Upsert replaces data in place and keeps created_at.
    res = alice.post(
        "/api/v1/image-studio/items/upsert",
        json={
            "items": [
                {
                    "id": "gallery_1",
                    "kind": "gallery",
                    "data": {"id": "gallery_1", "url": "/x", "favorite": True},
                }
            ]
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()[0]["data"]["favorite"] is True
    assert res.json()[0]["created_at"] == 1700000000
    assert len(alice.get("/api/v1/image-studio/items?kind=gallery").json()) == 1

    # Deleting through Bob's session cannot touch Alice's rows.
    assert bob.delete("/api/v1/image-studio/items/gallery_1").json() is False
    assert len(alice.get("/api/v1/image-studio/items").json()) == 3
    assert alice.delete("/api/v1/image-studio/items/gallery_1").json() is True
    assert len(alice.get("/api/v1/image-studio/items").json()) == 2

    # Clearing one kind leaves the others alone and is scoped to the caller.
    assert (
        alice.post("/api/v1/image-studio/items/clear", json={"kind": "history"}).json()
        is True
    )
    kinds = sorted(
        item["kind"] for item in alice.get("/api/v1/image-studio/items").json()
    )
    assert kinds == ["template"]
    assert len(bob.get("/api/v1/image-studio/items").json()) == 1

    assert ImageStudioItems.delete_items_by_user_id("alice") is True
    assert ImageStudioItems.delete_items_by_user_id("bob") is True
    assert alice.get("/api/v1/image-studio/items").json() == []


def test_validation_rejects_bad_kind_empty_id_and_oversized_items():
    client = _client("carol")
    res = client.post(
        "/api/v1/image-studio/items/upsert",
        json={"items": [{"id": "x", "kind": "prefs", "data": {}}]},
    )
    assert res.status_code == 422
    res = client.post(
        "/api/v1/image-studio/items/upsert",
        json={"items": [{"id": "", "kind": "template", "data": {}}]},
    )
    assert res.status_code == 422
    res = client.post(
        "/api/v1/image-studio/items/upsert",
        json={
            "items": [
                {"id": "big", "kind": "template", "data": {"prompt": "x" * (70 * 1024)}}
            ]
        },
    )
    assert res.status_code == 413
    assert client.get("/api/v1/image-studio/items?kind=prefs").status_code == 422
    assert (
        client.post("/api/v1/image-studio/items/upsert", json={"items": []}).json()
        == []
    )
    assert client.get("/api/v1/image-studio/items").json() == []


def test_history_is_trimmed_to_the_newest_entries():
    user_id = "dave"
    now_ms = int(time.time() * 1000)
    forms = [
        ImageStudioItemForm(
            id=f"history_{index}",
            kind="history",
            data={"id": f"history_{index}", "createdAt": now_ms - (index * 1000)},
        )
        for index in range(IMAGE_STUDIO_HISTORY_LIMIT + 7)
    ]
    ImageStudioItems.upsert_items(user_id, forms)
    trimmed = ImageStudioItems.trim_items(
        user_id, "history", IMAGE_STUDIO_HISTORY_LIMIT
    )
    assert len(trimmed) == 7
    # The oldest ones (largest index) are the ones that went away.
    assert set(trimmed) == {
        f"history_{index}"
        for index in range(IMAGE_STUDIO_HISTORY_LIMIT, IMAGE_STUDIO_HISTORY_LIMIT + 7)
    }
    remaining = ImageStudioItems.get_items_by_user_id(user_id, kind="history")
    assert len(remaining) == IMAGE_STUDIO_HISTORY_LIMIT
    assert remaining[0].id == "history_0"

    # The router applies the same trim after a history upsert.
    client = _client(user_id)
    res = client.post(
        "/api/v1/image-studio/items/upsert",
        json={
            "items": [
                {
                    "id": "history_new",
                    "kind": "history",
                    "data": {"createdAt": now_ms + 5000},
                }
            ]
        },
    )
    assert res.status_code == 200, res.text
    items = client.get("/api/v1/image-studio/items?kind=history").json()
    assert len(items) == IMAGE_STUDIO_HISTORY_LIMIT
    assert items[0]["id"] == "history_new"
    assert ImageStudioItems.delete_items_by_user_id(user_id) is True
