"""The video library: videos Hermes or a runner hands over are listed in the video studio.

Throwaway SQLite database, schema from the app's own migrations (as test_image_studio_items).
"""

import io
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-video-library-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "video-library-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.internal.db import get_db  # noqa: E402
from open_webui.models.chats import Chat  # noqa: E402
from open_webui.models.image_studio import ImageStudioItems  # noqa: E402
from open_webui.routers import video_studio  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402
from open_webui.utils.video_library import record_video, video_item_id  # noqa: E402


class _User:
    def __init__(self, id: str):
        self.id = id
        self.role = "user"


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def _add_chat(chat_id: str, user_id: str, title: str):
    with get_db() as db:
        db.add(Chat(id=chat_id, user_id=user_id, title=title, chat={}, created_at=1, updated_at=1, meta={}))
        db.commit()


def test_a_video_fetched_twice_is_listed_once_with_its_latest_copy():
    for file_id in ("f-1", "f-2"):
        assert record_video(
            "vid-ann", file_id=file_id, name="/root/out/片头.mp4", size=1234,
            content_type="video/mp4", chat_id="chat-a", origin="runner",
        )
    rows = ImageStudioItems.get_items_by_user_id("vid-ann", kind="video")
    assert len(rows) == 1
    data = rows[0].data
    assert rows[0].id == video_item_id("片头.mp4", 1234)
    assert data["fileId"] == "f-2" and data["url"] == "/api/v1/files/f-2/content"
    assert data["name"] == "片头.mp4" and data["title"] == "片头"
    assert data["origin"] == "runner" and data["chatId"] == "chat-a"


def test_the_library_comes_a_page_at_a_time_with_titles_and_search():
    _add_chat("chat-b", "vid-bob", "电脑的历史")
    for index in range(5):
        record_video(
            "vid-bob", file_id=f"b{index}", name=f"clip-{index}.mp4", size=index + 1,
            content_type="video/mp4", chat_id="chat-b" if index != 3 else "gone",
            created_at_ms=1_700_000_000_000 + index * 1000,
        )
    client = _client("vid-bob")
    first = client.get("/api/v1/video-studio/items?limit=2").json()
    assert [item["data"]["name"] for item in first["items"]] == ["clip-4.mp4", "clip-3.mp4"]
    assert first["items"][0]["data"]["chatTitle"] == "电脑的历史"
    # a chat deleted since: no way back, the video stays
    assert "chatId" not in first["items"][1]["data"]
    assert first["next"]
    second = client.get(f"/api/v1/video-studio/items?limit=2&before={first['next']}").json()
    assert [item["data"]["name"] for item in second["items"]] == ["clip-2.mp4", "clip-1.mp4"]
    found = client.get("/api/v1/video-studio/items?q=CLIP-0").json()
    assert [item["data"]["name"] for item in found["items"]] == ["clip-0.mp4"]
    assert found["next"] is None
    # someone else's library is their own
    assert _client("vid-eve").get("/api/v1/video-studio/items").json()["items"] == []


def test_taking_a_video_out_touches_only_the_library():
    record_video("vid-cat", file_id="c1", name="a.mp4", size=9, content_type="video/mp4")
    item_id = video_item_id("a.mp4", 9)
    assert _client("vid-eve").delete(f"/api/v1/video-studio/items/{item_id}").json() is False
    assert _client("vid-cat").delete("/api/v1/video-studio/items/gallery_x").status_code == 404
    assert _client("vid-cat").delete(f"/api/v1/video-studio/items/{item_id}").json() is True
    assert ImageStudioItems.get_items_by_user_id("vid-cat", kind="video") == []


def test_hermes_files_record_videos_but_not_other_files(monkeypatch):
    from open_webui.storage.provider import Storage
    from open_webui.utils import hermes_agent

    monkeypatch.setattr(Storage, "upload_file", lambda stream, name: (len(stream.read()), f"/tmp/{name}"))
    user = _User("vid-dan")
    url = hermes_agent._store_generated_file(
        None, user, {"chat_id": "chat-d", "media_origin": "runner"}, "成片.mp4", b"x" * 10, "video/mp4"
    )
    hermes_agent._store_generated_file(None, user, {"chat_id": "chat-d"}, "封面.png", io.BytesIO(b"png"), "image/png")
    rows = ImageStudioItems.get_items_by_user_id("vid-dan", kind="video")
    assert len(rows) == 1
    assert rows[0].data["url"] == url
    assert rows[0].data["origin"] == "runner" and rows[0].data["chatId"] == "chat-d"
