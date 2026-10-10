"""Real SQLite/files + HTTP import boundary, isolated from the running gallery."""
import base64
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

_TMP = Path(tempfile.mkdtemp(prefix="halo-hermes-gallery-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ["HALO_RUNTIME_MIGRATION_DONE"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import open_webui.config  # noqa: F401
from open_webui.models.files import Files
from open_webui.models.image_studio import ImageStudioItems
from open_webui.routers import teams
from open_webui.utils import hermes_image_gallery as gallery


def payload(event="a", **overrides):
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    return {"event_id": event * 64, "model": "gpt-image-2", "prompt": "灯塔", "size": "8x8",
            "created_at_ms": 1_700_000_000_000,
            "image_base64": base64.b64encode(stream.getvalue()).decode(), **overrides}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(teams, "ENABLE_AGENT_TEAMS", True)
    monkeypatch.setattr(teams.Users, "get_user_by_id", lambda id: SimpleNamespace(id=id) if id in {"alice", "bob"} else None)
    teams._hermes_auth_cache.clear()

    async def target(request, user):
        return SimpleNamespace(headers={"Authorization": "Bearer test-key"})

    monkeypatch.setattr(teams, "hermes_target", target)
    app = FastAPI()
    app.include_router(teams.router, prefix="/api/v1/teams")
    return TestClient(app)


HEADERS = {"X-Hermes-Key": "test-key", "X-Halo-Owner": "alice"}
ENDPOINT = "/api/v1/teams/hermes/images"


def test_authentication_storage_retry_and_deletion(client):
    assert client.post(ENDPOINT, json=payload()).status_code == 401
    assert client.post(ENDPOINT, headers={**HEADERS, "X-Hermes-Key": "wrong"}, json=payload()).status_code == 401
    first = client.post(ENDPOINT, headers=HEADERS, json=payload())
    assert first.status_code == 200, first.text
    url = first.json()["url"]
    stored = Files.get_file_by_id(url.split("/")[-2])
    assert stored.user_id == "alice" and Path(stored.path).is_file()
    forms = ImageStudioItems.get_items_by_user_id("alice", "gallery")
    assert len(forms) == 1 and forms[0].data["prompt"] == "灯塔"
    assert not ImageStudioItems.get_items_by_user_id("alice", "history")
    forms[0].data["favorite"] = True
    ImageStudioItems.upsert_items("alice", [gallery.ImageStudioItemForm(id=forms[0].id, kind="gallery", data=forms[0].data)])
    assert client.post(ENDPOINT, headers=HEADERS, json=payload()).json()["duplicate"]
    assert ImageStudioItems.get_items_by_user_id("alice", "gallery")[0].data["favorite"]
    ImageStudioItems.delete_item_by_id_and_user_id(forms[0].id, "alice")
    assert client.post(ENDPOINT, headers=HEADERS, json=payload()).json()["stored"]
    assert not ImageStudioItems.get_items_by_user_id("alice", "gallery")


@pytest.mark.parametrize("changes", [{"model": "flux"}, {"image_base64": "bad base64"},
                                    {"image_base64": base64.b64encode(b"not an image").decode()}])
def test_rejects_non_gpt_or_invalid_images(client, changes):
    response = client.post(ENDPOINT, headers=HEADERS, json=payload("b", **changes))
    assert response.status_code == 422


def test_chat_owner_resolved_and_cross_gateway_denied(client, monkeypatch):
    monkeypatch.setattr(teams.Chats, "get_chat_by_id", lambda id: SimpleNamespace(id=id, user_id="bob"))
    body = payload("c", platform="api_server", chat_id="chat-bob")
    result = client.post(ENDPOINT, headers=HEADERS, json=body)
    assert result.status_code == 200, result.text
    forms = ImageStudioItems.get_items_by_user_id("bob", "gallery")
    assert len(forms) == 1 and forms[0].data["chatId"] == "chat-bob"

    async def other_target(request, user):
        return SimpleNamespace(headers={"Authorization": "Bearer other-key"})

    monkeypatch.setattr(teams, "hermes_target", other_target)
    assert client.post(ENDPOINT, headers=HEADERS, json=payload("d", platform="api_server", chat_id="chat-bob")).status_code == 403


def test_db_retry_reuses_file_and_queued_illustration_skips_legacy_import(client, monkeypatch):
    original = gallery.ImageStudioItems.upsert_items
    monkeypatch.setattr(gallery.ImageStudioItems, "upsert_items", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        client.post(ENDPOINT, headers=HEADERS, json=payload("e"))
    monkeypatch.setattr(gallery.ImageStudioItems, "upsert_items", original)
    response = client.post(ENDPOINT, headers=HEADERS, json=payload("e"))
    assert response.status_code == 200
    import asyncio
    from open_webui.utils.agent_team_outputs import illustration_to_gallery
    assert asyncio.run(illustration_to_gallery(None, None, None, {"gallery_queued": True}))["reason"] == "hermes image queue"
