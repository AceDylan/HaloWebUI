"""视频封面: a video filed in the library gets a cover gpt-image draws from its first frame.

Throwaway SQLite database, schema from the app's own migrations (as test_video_library).
"""

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="halo-video-cover-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "video-cover-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems  # noqa: E402
from open_webui.routers import video_studio  # noqa: E402
from open_webui.utils import video_cover  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402
from open_webui.utils.video_library import record_video, video_item_id  # noqa: E402


class _User:
    def __init__(self, id: str):
        self.id = id
        self.role = "user"


def _file(user_id: str, name: str = "笑一笑_歌词MV.mp4", size: int = 100) -> str:
    item_id = record_video(user_id, file_id="f1", name=name, size=size, content_type="video/mp4", chat_id="c1")
    assert item_id == video_item_id(name, size)
    return item_id


def _data(user_id: str, item_id: str) -> dict:
    return ImageStudioItems.get_item(user_id, item_id, kind="video").data


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, format="PNG")
    return out.getvalue()


def test_the_cover_is_cut_to_the_video_shape():
    from PIL import Image

    landscape = Image.open(io.BytesIO(video_cover.fit_to(_png(1536, 1024), 1920, 1080)))
    assert landscape.format == "JPEG" and landscape.size == (1536, 864)
    portrait = Image.open(io.BytesIO(video_cover.fit_to(_png(1024, 1536), 1080, 1920)))
    assert portrait.size == (864, 1536)
    big = Image.open(io.BytesIO(video_cover.fit_to(_png(3000, 2000), 0, 0)))
    assert max(big.size) == video_cover.COVER_MAX_SIDE


def test_canvas_and_title_follow_the_video():
    assert video_cover.canvas_for(1920, 1080)[0] == "1536x1024"
    assert video_cover.canvas_for(1080, 1920)[0] == "1024x1536"
    assert video_cover.canvas_for(1080, 1080)[0] == "1024x1024"
    assert video_cover.cover_title("/out/笑一笑_歌词-MV.mp4") == "笑一笑 歌词 MV"
    assert video_cover.cover_title("", "我的对话") == "我的对话"


def test_the_first_frame_skips_a_fade_from_black(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = str(tmp_path / "fade.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    assert writer.isOpened()
    for index in range(30):
        frame = np.zeros((180, 320, 3), np.uint8)
        if index >= 8:  # 0.8 s of black, then a picture
            frame[:, :160] = (0, 200, 0)
            frame[40:140, 200:300] = (255, 255, 255)
        writer.write(frame)
    writer.release()

    jpeg, width, height = video_cover.first_frame(path)
    assert (width, height) == (320, 180)
    picture = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert picture.std() > 20  # not the black opening frame


def test_a_cover_is_drawn_once_and_kept_when_the_video_is_filed_again(monkeypatch):
    item_id = _file("vc-ann")
    calls = []

    async def draw(request, user, video):
        calls.append(video["id"])
        return {"url": "/api/v1/files/cover1/content", "fileId": "cover1", "model": "gpt-image"}

    monkeypatch.setattr(video_cover, "draw_cover", draw)
    user = _User("vc-ann")
    data = asyncio.run(video_cover.make(None, user, item_id))
    assert data["coverStatus"] == "ready" and data["cover"] == "/api/v1/files/cover1/content"
    assert data["coverModel"] == "gpt-image" and "coverError" not in data
    # ready: not drawn again unless asked
    assert asyncio.run(video_cover.make(None, user, item_id)) is None
    assert calls == [item_id]
    # the same video fetched again (a reconnect) keeps its cover, with the newest file
    record_video("vc-ann", file_id="f2", name="笑一笑_歌词MV.mp4", size=100, content_type="video/mp4", chat_id="c1")
    data = _data("vc-ann", item_id)
    assert data["fileId"] == "f2" and data["cover"] == "/api/v1/files/cover1/content"
    # 重新生成封面
    assert asyncio.run(video_cover.make(None, user, item_id, force=True))["coverStatus"] == "ready"
    assert calls == [item_id, item_id]


def test_a_failed_cover_says_why_and_a_lost_one_may_be_drawn_again(monkeypatch):
    item_id = _file("vc-bob")

    async def broken(request, user, video):
        raise video_cover.IllustrateError("生图没有返回图片")

    monkeypatch.setattr(video_cover, "draw_cover", broken)
    data = asyncio.run(video_cover.make(None, _User("vc-bob"), item_id))
    assert data["coverStatus"] == "failed" and data["coverError"] == "生图没有返回图片"
    assert "cover" not in data

    from open_webui.utils.video_library import set_video_fields

    set_video_fields("vc-bob", item_id, {"coverStatus": "generating", "coverStartedAt": video_cover.now_ms()})
    assert video_cover.busy(_data("vc-bob", item_id))
    set_video_fields("vc-bob", item_id, {"coverStartedAt": video_cover.now_ms() - video_cover.STALE_MS - 1})
    assert not video_cover.busy(_data("vc-bob", item_id))


def test_the_cover_model_is_the_owners_gpt_image_one(monkeypatch):
    monkeypatch.delenv(video_cover.MODEL_ENV, raising=False)
    assert video_cover.cover_model("vc-none") is None
    ImageStudioItems.upsert_items("vc-tpl", [
        ImageStudioItemForm(id="t1", kind="template", data={"config": {"model": "modelref::x::dall-e-3"}}),
        ImageStudioItemForm(id="t2", kind="template", data={"config": {"model": "modelref::x::gpt-image"}}),
    ])
    assert video_cover.cover_model("vc-tpl") == "modelref::x::gpt-image"
    monkeypatch.setenv(video_cover.MODEL_ENV, "gpt-image-2")
    assert video_cover.cover_model("vc-tpl") == "gpt-image-2"


def test_redraw_endpoint(monkeypatch):
    item_id = _file("vc-cat")
    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    app.dependency_overrides[get_verified_user] = lambda: _User("vc-cat")
    client = TestClient(app)
    started = []
    monkeypatch.setattr(video_cover, "may_cover", lambda request, user: True)
    monkeypatch.setattr(video_cover, "start", lambda request, user, item, force=False: started.append((item, force)) or True)

    assert client.post("/api/v1/video-studio/items/video_nope/cover").status_code == 404
    res = client.post(f"/api/v1/video-studio/items/{item_id}/cover")
    assert res.status_code == 200 and res.json()["data"]["coverStatus"] == "generating"
    assert started == [(item_id, True)]

    from open_webui.utils.video_library import set_video_fields

    set_video_fields("vc-cat", item_id, {"coverStatus": "generating", "coverStartedAt": video_cover.now_ms()})
    assert client.post(f"/api/v1/video-studio/items/{item_id}/cover").status_code == 409
    monkeypatch.setattr(video_cover, "may_cover", lambda request, user: False)
    set_video_fields("vc-cat", item_id, {"coverStatus": None})
    assert client.post(f"/api/v1/video-studio/items/{item_id}/cover").status_code == 403


def test_start_needs_a_request_and_a_loop(monkeypatch):
    monkeypatch.setattr(video_cover, "may_cover", lambda request, user: True)
    assert video_cover.start(None, _User("x"), "video_1") is False
    assert video_cover.start(object(), _User("x"), "video_1") is False  # no running loop
    assert video_cover.start(object(), _User("x"), None) is False
