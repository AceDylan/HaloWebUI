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
from open_webui.utils.video_library import is_video_brief, mark_video_chat, record_video, video_item_id  # noqa: E402


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


def test_a_telegram_run_files_its_videos_once_with_where_they_came_from(monkeypatch):
    import asyncio

    from open_webui.storage.provider import Storage
    from open_webui.utils.video_library import import_run_videos

    monkeypatch.setattr(Storage, "upload_file", lambda stream, name: (len(stream.read()), f"/tmp/{name}"))
    fetched = []

    async def fetch(path):
        fetched.append(path)
        if path.endswith("gone.mp4"):
            return None, None, "文件不存在或不允许读取"
        return io.BytesIO(b"v" * 7), "video/mp4", None

    user = _User("vid-tg")
    run = {"run_id": "20261015-224655-9fe3765e", "runner": "codex-runner", "platform": "telegram",
           "title": "生成一段视频，讲述长征"}
    paths = ["/root/output/长征.mp4", "/root/output/gone.mp4", "/root/output/cover.png", "relative.mp4"]
    out = asyncio.run(import_run_videos(None, user, paths=paths, run=run, fetch=fetch))
    assert out["stored"] == ["/root/output/长征.mp4"]
    assert out["failed"] == [{"path": "/root/output/gone.mp4", "reason": "文件不存在或不允许读取"}]
    # pictures and relative paths are never asked for
    assert fetched == ["/root/output/长征.mp4", "/root/output/gone.mp4"]
    rows = ImageStudioItems.get_items_by_user_id("vid-tg", kind="video")
    assert len(rows) == 1
    data = rows[0].data
    assert data["origin"] == "runner" and "chatId" not in data
    assert (data["runId"], data["runner"], data["platform"], data["runTitle"]) == (
        "20261015-224655-9fe3765e", "codex", "telegram", "生成一段视频，讲述长征")
    # the notifier posting again does not fetch or store the same video twice
    again = asyncio.run(import_run_videos(None, user, paths=paths[:1], run=run, fetch=fetch))
    assert again == {"stored": [], "skipped": ["/root/output/长征.mp4"], "failed": []}
    assert len(fetched) == 2


def test_the_runner_videos_endpoint_needs_the_notification_token(monkeypatch):
    from open_webui.routers import video_studio as router_module

    calls = []

    async def fake_import(request, user, *, paths, run):
        calls.append((user.id, paths, run))
        return {"stored": paths, "skipped": [], "failed": []}

    monkeypatch.setattr(router_module, "import_run_videos", fake_import)
    monkeypatch.setattr(router_module.Users, "get_first_user", lambda: _User("vid-owner"))
    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    client = TestClient(app)
    body = {"run_id": "20261016-221115-37da9b06", "runner": "officlaude", "platform": "telegram",
            "title": "帮我生成一个讲述halowebui的视频", "paths": ["/root/work/halo-video/out/a.mp4"]}
    monkeypatch.delenv("HERMES_AGENT_NOTIFY_TOKEN", raising=False)
    assert client.post("/api/v1/video-studio/runner-videos", json=body).status_code == 503
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_TOKEN", "notify-secret")
    assert client.post("/api/v1/video-studio/runner-videos", json=body,
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/v1/video-studio/runner-videos", json={**body, "run_id": "../x"},
                       headers={"Authorization": "Bearer notify-secret"}).status_code == 422
    res = client.post("/api/v1/video-studio/runner-videos", json=body,
                      headers={"Authorization": "Bearer notify-secret"})
    assert res.status_code == 200 and res.json()["stored"] == body["paths"]
    assert calls == [("vid-owner", body["paths"], {"run_id": body["run_id"], "runner": "officlaude",
                                                    "platform": "telegram", "title": body["title"]})]


def _add_file(file_id: str, user_id: str, name: str, size: int, created_at: int, path: str | None = "/data/x"):
    from open_webui.models.files import File

    with get_db() as db:
        db.add(File(id=file_id, user_id=user_id, filename=name, path=path,
                    meta={"name": name, "size": size, "content_type": "audio/mpeg"},
                    created_at=created_at, updated_at=created_at))
        db.commit()


def test_the_workbench_lists_only_the_users_own_mp3_uploads_newest_first():
    _add_file("mus-1", "mus-ann", "旧歌.mp3", 100, 10)
    _add_file("mus-2", "mus-ann", "新歌.MP3", 200, 30)
    _add_file("mus-3", "mus-ann", "新歌.MP3", 200, 20)  # the same song uploaded again: listed once
    _add_file("mus-4", "mus-ann", "notes.pdf", 300, 40)
    _add_file("mus-5", "mus-ann", "lost.mp3", 300, 50, path=None)
    _add_file("mus-6", "mus-bob", "bob.mp3", 400, 60)
    listed = _client("mus-ann").get("/api/v1/video-studio/music").json()
    assert [m["id"] for m in listed] == ["mus-2", "mus-1"]
    assert listed[0] == {"id": "mus-2", "name": "新歌.MP3", "size": 200, "createdAt": 30_000}
    assert [m["id"] for m in _client("mus-ann").get("/api/v1/video-studio/music?limit=1").json()] == ["mus-2"]
    assert _client("mus-ann").get("/api/v1/video-studio/music?limit=500").status_code == 422
    assert [m["id"] for m in _client("mus-bob").get("/api/v1/video-studio/music").json()] == ["mus-6"]


def test_a_chat_sent_from_the_video_studio_is_marked_once():
    from open_webui.models.chats import Chats

    head = "请制作一个视频（来自 HaloWebUI 视频工作台）。\n\n## 想要的视频\n片头"
    assert is_video_brief(head)
    assert is_video_brief("/codex " + head)
    assert is_video_brief([{"type": "text", "text": head}])
    assert not is_video_brief("帮我请制作一个视频（来自 HaloWebUI 视频工作台）")
    assert not is_video_brief("/codex 做个片头")

    _add_chat("vid-chat", "vid-cat", "New Chat")
    _add_chat("plain-chat", "vid-cat", "New Chat")
    earlier = [{"role": "user", "content": head}, {"role": "assistant", "content": "好"}]
    assert not mark_video_chat("plain-chat", earlier + [{"role": "user", "content": "再快一点"}])
    assert mark_video_chat("vid-chat", [{"role": "user", "content": "/reclaude " + head}])
    assert not mark_video_chat("vid-chat", [{"role": "user", "content": head}])  # already marked
    assert not mark_video_chat("missing", [{"role": "user", "content": head}])
    assert Chats.get_chat_by_id("vid-chat").meta.get("video_studio") is True
    assert "video_studio" not in (Chats.get_chat_by_id("plain-chat").meta or {})
