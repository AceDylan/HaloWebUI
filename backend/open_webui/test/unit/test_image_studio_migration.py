"""Server-side gate for the one-time upload of browser-local image studio data.

Runs against a throwaway SQLite database (same bootstrap as
test_image_studio_items.py) so the Alembic revision that adds
``image_studio_migration`` is exercised too.
"""

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-image-studio-migration-test-"))
os.environ.setdefault("DATA_DIR", str(_TMP))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/webui.db")
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
    IMAGE_STUDIO_MAX_ITEM_BYTES,
    ImageStudioItemForm,
    ImageStudioItems,
    ImageStudioMigrations,
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


def _template(id: str, name: str = "Poster") -> dict:
    return {
        "id": id,
        "kind": "template",
        "data": {"id": id, "name": name, "config": {"prompt": f"prompt for {name}"}},
    }


def _ids(client: TestClient, kind: str = "template") -> set[str]:
    res = client.get(f"/api/v1/image-studio/items?kind={kind}")
    assert res.status_code == 200, res.text
    return {item["id"] for item in res.json()}


def test_migration_created_the_table_keyed_by_user():
    inspector = sa.inspect(engine)
    assert "image_studio_migration" in inspector.get_table_names()
    pk = inspector.get_pk_constraint("image_studio_migration")["constrained_columns"]
    assert pk == ["user_id"]


def test_fresh_account_accepts_one_legacy_upload_then_refuses_the_next_browser():
    client = _client("mig-alice")
    assert client.get("/api/v1/image-studio/legacy-migration").json() is None
    # Listing an empty account keeps it open for a legacy upload.
    assert client.get("/api/v1/image-studio/items").json() == []
    assert client.get("/api/v1/image-studio/legacy-migration").json() is None

    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={
            "items": [
                _template("template_1"),
                {
                    "id": "gallery_1",
                    "kind": "gallery",
                    "data": {"id": "gallery_1", "url": "/api/v1/files/a/content"},
                },
            ]
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] is True
    assert body["uploaded"] == 2
    assert body["migration"]["source"] == "legacy-upload"
    assert body["migration"]["uploaded"] == 2
    assert _ids(client) == {"template_1"}
    assert _ids(client, "gallery") == {"gallery_1"}

    # A second browser of the same account (no local marker) is refused and
    # nothing of its copy is stored.
    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={"items": [_template("template_1"), _template("template_2", "Other")]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] is False
    assert res.json()["uploaded"] == 0
    assert res.json()["migration"]["source"] == "legacy-upload"
    assert _ids(client) == {"template_1"}


def test_account_with_server_data_is_closed_on_listing():
    client = _client("mig-bob")
    res = client.post(
        "/api/v1/image-studio/items/upsert", json={"items": [_template("template_1")]}
    )
    assert res.status_code == 200, res.text
    # The studio always lists before it migrates; listing closes the account.
    assert _ids(client) == {"template_1"}
    assert client.get("/api/v1/image-studio/legacy-migration").json()["source"] == (
        "existing-data"
    )

    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={"items": [_template("template_9", "Stale")]},
    )
    assert res.json()["accepted"] is False
    assert _ids(client) == {"template_1"}


def test_legacy_upload_checks_server_data_even_without_a_prior_listing():
    ImageStudioItems.upsert_items(
        "mig-carol",
        [ImageStudioItemForm(id="template_1", kind="template", data={"name": "x"})],
    )
    client = _client("mig-carol")
    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={"items": [_template("template_2", "Stale")]},
    )
    assert res.json()["accepted"] is False
    assert res.json()["migration"]["source"] == "existing-data"
    assert _ids(client) == {"template_1"}


def test_deleted_templates_do_not_come_back_from_a_stale_browser():
    client = _client("mig-dave")
    client.post(
        "/api/v1/image-studio/items/upsert", json={"items": [_template("t_old")]}
    )
    assert client.delete("/api/v1/image-studio/items/t_old").json() is True
    assert _ids(client) == set()
    assert client.get("/api/v1/image-studio/legacy-migration").json()["source"] in (
        "curated",
        "existing-data",
    )

    # Empty on the server, but the account is closed: the old copy stays out.
    res = client.post(
        "/api/v1/image-studio/legacy-migration", json={"items": [_template("t_old")]}
    )
    assert res.json()["accepted"] is False
    assert _ids(client) == set()

    # Deliberate imports from the templates tab still work through upsert.
    res = client.post(
        "/api/v1/image-studio/items/upsert", json={"items": [_template("t_old")]}
    )
    assert res.status_code == 200
    assert _ids(client) == {"t_old"}


def test_clearing_a_kind_closes_the_account_too():
    client = _client("mig-erin")
    client.post(
        "/api/v1/image-studio/items/upsert",
        json={"items": [{"id": "h1", "kind": "history", "data": {"id": "h1"}}]},
    )
    assert client.post(
        "/api/v1/image-studio/items/clear", json={"kind": "history"}
    ).json()
    assert client.get("/api/v1/image-studio/legacy-migration").json() is not None
    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={"items": [{"id": "h1", "kind": "history", "data": {"id": "h1"}}]},
    )
    assert res.json()["accepted"] is False
    assert _ids(client, "history") == set()


def test_closed_account_is_refused_atomically_at_model_level():
    ImageStudioMigrations.close("mig-frank", "curated")
    record, items = ImageStudioMigrations.import_legacy_items(
        "mig-frank",
        [ImageStudioItemForm(id="template_1", kind="template", data={"name": "x"})],
    )
    assert record is not None and record.source == "curated"
    assert items == []
    assert ImageStudioItems.get_items_by_user_id("mig-frank") == []

    # Closing again keeps the original row.
    again = ImageStudioMigrations.close("mig-frank", "existing-data", uploaded=9)
    assert again.source == "curated" and again.uploaded == 0


def test_legacy_upload_trims_history_and_dedupes_ids():
    client = _client("mig-gina")
    items = [
        {
            "id": f"h{i}",
            "kind": "history",
            "data": {"id": f"h{i}", "createdAt": 1700000000000 + i},
        }
        for i in range(IMAGE_STUDIO_HISTORY_LIMIT + 5)
    ]
    items.append(_template("t1"))
    items.append(_template("t1", "Renamed"))  # last occurrence of an id wins
    res = client.post("/api/v1/image-studio/legacy-migration", json={"items": items})
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] is True
    assert res.json()["uploaded"] == IMAGE_STUDIO_HISTORY_LIMIT + 5 + 1
    assert len(_ids(client, "history")) == IMAGE_STUDIO_HISTORY_LIMIT
    assert "h0" not in _ids(client, "history")  # oldest trimmed
    res = client.get("/api/v1/image-studio/items?kind=template")
    assert res.json()[0]["data"]["name"] == "Renamed"


def test_payload_validation_matches_upsert():
    client = _client("mig-hank")
    assert (
        client.post(
            "/api/v1/image-studio/legacy-migration", json={"items": []}
        ).status_code
        == 422
    )
    res = client.post(
        "/api/v1/image-studio/legacy-migration",
        json={
            "items": [
                {
                    "id": "big",
                    "kind": "template",
                    "data": {"blob": "x" * (IMAGE_STUDIO_MAX_ITEM_BYTES + 1)},
                }
            ]
        },
    )
    assert res.status_code == 413
    # Nothing was claimed by the rejected request.
    assert client.get("/api/v1/image-studio/legacy-migration").json() is None


def test_delete_by_user_id_removes_the_record():
    ImageStudioMigrations.close("mig-ivy", "legacy-upload", uploaded=3)
    assert ImageStudioMigrations.get_by_user_id("mig-ivy").uploaded == 3
    assert ImageStudioMigrations.delete_by_user_id("mig-ivy") is True
    assert ImageStudioMigrations.get_by_user_id("mig-ivy") is None
