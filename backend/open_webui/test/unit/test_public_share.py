"""A shared-chat link opens without signing in and shows that conversation only:
the snapshot taken at share time, stripped of private fields, with its images
served through a share-scoped route."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from open_webui.models import chats as chats_mod
from open_webui.routers import chats as chats_router
from open_webui.utils.public_share import build_public_shared_chat

IMG = "11111111-2222-3333-4444-555555555555"
SVG = "66666666-7777-8888-9999-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


def _payload(extra_text=""):
    return {
        "title": "Trip plan",
        "models": ["gpt-x"],
        "timestamp": 1,
        "system": "secret system prompt",
        "params": {"system": "secret system prompt"},
        "composer_state": {"draft": "half-typed"},
        "files": [{"id": "doc"}],
        "history": {
            "currentId": "a",
            "messages": {
                "u": {
                    "id": "u",
                    "role": "user",
                    "content": "draw it",
                    "parentId": None,
                    "childrenIds": ["a"],
                    "timestamp": 1,
                    "userContext": {"memory": "private"},
                    "files": [
                        {
                            "type": "image",
                            "id": IMG,
                            "url": f"/api/v1/files/{IMG}/content",
                            "file": {"path": "/app/backend/data/uploads/x.png"},
                            "context": "full",
                        }
                    ],
                },
                "a": {
                    "id": "a",
                    "role": "assistant",
                    "content": f"Here ![p](https://halo.example/api/v1/files/{IMG}/content) "
                    f"and ![s](/api/v1/files/{SVG}/content){extra_text}",
                    "parentId": "u",
                    "childrenIds": [],
                    "model": "gpt-x",
                    "done": True,
                    "timestamp": 2,
                    "hermes_run": {"run_id": "r1", "runner_run_id": "rr"},
                    "hermesOptions": {"dispatch": "x"},
                    "model_ref": {"connection_id": "c"},
                    "mode_dispatch": {"kind": "team", "chat_id": "other"},
                },
            },
        },
    }


def test_public_view_keeps_the_conversation_and_drops_private_fields():
    payload, file_ids = build_public_shared_chat(_payload(), "share-1")

    assert set(payload) == {"title", "models", "timestamp", "history"}
    assert "secret" not in str(payload) and "half-typed" not in str(payload)
    user, answer = payload["history"]["messages"]["u"], payload["history"]["messages"]["a"]
    assert "userContext" not in user
    assert user["files"] == [
        {
            "type": "image",
            "id": IMG,
            "url": f"/api/v1/chats/public/share/share-1/files/{IMG}/content",
        }
    ]
    for key in ("hermes_run", "hermesOptions", "model_ref", "mode_dispatch"):
        assert key not in answer
    assert f"(/api/v1/chats/public/share/share-1/files/{IMG}/content)" in answer["content"]
    assert "halo.example" not in answer["content"]
    assert file_ids == {IMG, SVG}


@pytest.fixture
def app(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    chats_mod.Chat.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(chats_mod, "get_db", get_db)
    monkeypatch.setattr(chats_mod.ChatMessages, "upsert_message", lambda **_kwargs: None)
    with get_db() as db:
        db.add(
            chats_mod.Chat(
                id="chat",
                user_id="owner",
                title="Trip plan",
                created_at=1,
                updated_at=1,
                chat=_payload(),
            )
        )
        db.commit()

    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    files = {
        IMG: SimpleNamespace(id=IMG, user_id="owner", path="x", meta={"content_type": "image/png"}),
        SVG: SimpleNamespace(
            id=SVG, user_id="owner", path="x", meta={"content_type": "image/svg+xml"}
        ),
        OTHER: SimpleNamespace(
            id=OTHER, user_id="owner", path="x", meta={"content_type": "image/png"}
        ),
    }
    monkeypatch.setattr(chats_router.Files, "get_file_by_id", lambda fid: files.get(fid))
    monkeypatch.setattr(chats_router.Storage, "get_file", lambda _path: str(png))
    monkeypatch.setattr(
        chats_router.Users, "get_user_by_id", lambda uid: SimpleNamespace(name="Dylan", email="d@x")
    )

    web = FastAPI()
    web.include_router(chats_router.router, prefix="/api/v1/chats")
    return TestClient(web)


def _share():
    return chats_mod.Chats.insert_shared_chat_by_chat_id("chat").id


def test_a_shared_link_opens_without_signing_in(app):
    share_id = _share()
    res = app.get(f"/api/v1/chats/public/share/{share_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == share_id
    assert body["user"] == {"name": "Dylan"}
    assert body["chat"]["history"]["currentId"] == "a"
    assert "secret" not in res.text and "d@x" not in res.text and "owner" not in res.text


def test_messages_sent_after_sharing_stay_private(app):
    share_id = _share()
    with chats_mod.get_db() as db:
        chat = db.get(chats_mod.Chat, "chat")
        chat.chat = _payload(" LATER MESSAGE")
        db.commit()
    assert "LATER MESSAGE" not in app.get(f"/api/v1/chats/public/share/{share_id}").text

    chats_mod.Chats.update_shared_chat_by_chat_id("chat")
    assert "LATER MESSAGE" in app.get(f"/api/v1/chats/public/share/{share_id}").text


def test_unknown_live_or_deleted_links_are_not_found(app):
    share_id = _share()
    assert app.get("/api/v1/chats/public/share/nope").status_code == 404
    # The original chat's own id is not a share link.
    assert app.get("/api/v1/chats/public/share/chat").status_code == 404
    chats_mod.Chats.delete_shared_chat_by_chat_id("chat")
    chats_mod.Chats.update_chat_share_id_by_id("chat", None)
    assert app.get(f"/api/v1/chats/public/share/{share_id}").status_code == 404


def test_only_referenced_bitmap_images_are_served(app):
    share_id = _share()
    base = f"/api/v1/chats/public/share/{share_id}/files"
    res = app.get(f"{base}/{IMG}/content")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert app.get(f"{base}/{IMG}").status_code == 200
    # SVG runs script when opened directly; unreferenced files are not part of the share.
    assert app.get(f"{base}/{SVG}/content").status_code == 404
    assert app.get(f"{base}/{OTHER}/content").status_code == 404
    assert app.get(f"/api/v1/chats/public/share/nope/files/{IMG}").status_code == 404
