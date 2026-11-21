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


def test_vertical_cover_prompt_adds_douyin_safe_zone_guidance(monkeypatch):
    import open_webui.routers.images as images
    import open_webui.utils.chat_image_refs as refs

    prompts = []

    async def fake_generate(request, form, user=None):
        prompts.append(form.prompt)
        return [{"url": "/api/v1/files/tmp1/content"}]

    monkeypatch.setattr(images, "image_generations", fake_generate)
    monkeypatch.setattr(refs, "resolve_chat_image_url_to_bytes", lambda *a, **k: ("image/png", _png(1024, 1536)))
    monkeypatch.setattr(video_cover, "_remove_file", lambda _fid: None)
    monkeypatch.setattr(video_cover, "cover_model", lambda _uid: "gpt-image")

    asyncio.run(video_cover.draw_from_frame(None, _User("vc-dy"), _png(1080, 1920), 1080, 1920, "别再内耗了"))
    asyncio.run(video_cover.draw_from_frame(None, _User("vc-dy"), _png(1920, 1080), 1920, 1080, "横屏测试"))
    assert "抖音风格" in prompts[0] and "15% 安全边距" in prompts[0] and "不要做成纯黑底大字海报" in prompts[0]
    assert "抖音风格" not in prompts[1]


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


def test_a_video_with_cover_art_uses_its_frame_zero(tmp_path, monkeypatch):
    plain = tmp_path / "plain.mp4"
    plain.write_bytes(b"\x00" * 1000 + b"moov" + b"\x00" * 1000)
    covered = tmp_path / "covered.mp4"
    covered.write_bytes(b"\x00" * 1000 + b"moovudtametailstcovr" + b"\x00" * 1000)
    assert not video_cover.has_cover_art(str(plain))
    assert video_cover.has_cover_art(str(covered))

    calls = []
    monkeypatch.setattr(video_cover, "_local_path", lambda file_id: str(covered))
    monkeypatch.setattr(video_cover, "frame_zero", lambda path: (_png(1280, 720), 1280, 720))

    async def draw(*a, **k):
        calls.append(a)
        return b"x", "gpt-image"

    monkeypatch.setattr(video_cover, "draw_from_frame", draw)
    import open_webui.routers.images as images

    monkeypatch.setattr(images, "upload_image", lambda request, meta, data, kind, user: "/api/v1/files/fz/content")
    out = asyncio.run(video_cover.draw_cover(None, _User("vc-fz"), {"id": "video_1", "fileId": "f"}))
    assert out == {"url": "/api/v1/files/fz/content", "fileId": "fz", "model": video_cover.FRAME_ZERO_MODEL}
    assert calls == []  # no drawing: frame 0 already is the cover


def test_the_pipeline_cover_endpoint_needs_the_notification_token(monkeypatch):
    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    client = TestClient(app)
    body = {"frame": "A" * 200, "width": 1920, "height": 1080, "title": "笑一笑"}
    monkeypatch.delenv("HERMES_AGENT_NOTIFY_TOKEN", raising=False)
    assert client.post("/api/v1/video-studio/cover-image", json=body).status_code == 503
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_TOKEN", "tok-1")
    assert client.post("/api/v1/video-studio/cover-image", json=body).status_code == 401
    assert client.post("/api/v1/video-studio/cover-image", json=body,
                       headers={"Authorization": "Bearer nope"}).status_code == 401


def test_the_thumb_endpoint_cuts_the_first_frame_once_and_only_for_the_owner(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from open_webui.models.files import FileForm, Files

    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (1280, 720))
    assert writer.isOpened()
    for _ in range(5):
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:, :640] = (0, 200, 0)
        writer.write(frame)
    writer.release()
    Files.insert_new_file("vt-owner", FileForm(id="vt-f1", filename="clip.mp4", path=path,
                                                meta={"content_type": "video/mp4"}))
    Files.insert_new_file("vt-owner", FileForm(id="vt-doc", filename="a.pdf", path=path,
                                                meta={"content_type": "application/pdf"}))

    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    who = {"user": _User("vt-owner")}
    app.dependency_overrides[get_verified_user] = lambda: who["user"]
    client = TestClient(app)

    res = client.get("/api/v1/video-studio/thumb/vt-f1")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    assert "max-age" in res.headers["cache-control"]
    picture = cv2.imdecode(np.frombuffer(res.content, np.uint8), cv2.IMREAD_COLOR)
    assert max(picture.shape[:2]) == video_cover.THUMB_MAX_SIDE
    assert os.path.isfile(video_cover.thumb_path("vt-f1"))

    # cut once: the cached picture is served even when the video can no longer be read
    monkeypatch.setattr(video_cover, "first_frame", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cut again")))
    assert client.get("/api/v1/video-studio/thumb/vt-f1").content == res.content

    assert client.get("/api/v1/video-studio/thumb/vt-doc").status_code == 404
    assert client.get("/api/v1/video-studio/thumb/nope").status_code == 404
    who["user"] = _User("vt-other")
    assert client.get("/api/v1/video-studio/thumb/vt-f1").status_code == 404

    from open_webui.utils.video_library import delete_owned_file

    delete_owned_file("vt-owner", "vt-f1")
    assert not os.path.exists(video_cover.thumb_path("vt-f1"))
