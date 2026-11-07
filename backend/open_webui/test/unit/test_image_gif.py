"""GIF requests against the OpenAI images routes: payload, verification, stored type."""
import asyncio
import base64
import io
import json
import pathlib
import sys

import pytest
from fastapi import HTTPException
from PIL import Image

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import images as images_router  # noqa: E402


def _gif() -> bytes:
    frames = [Image.new("RGB", (8, 8), color) for color in ("red", "blue")]
    out = io.BytesIO()
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:], duration=100)
    return out.getvalue()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def upstream(monkeypatch):
    """Answers every image request with ``upstream.reply``; records the bodies and uploads."""

    class Upstream:
        reply = _gif()
        images = 1
        bodies: list = []
        uploads: list = []

    state = Upstream()
    state.bodies, state.uploads = [], []

    async def send(**kwargs):
        state.bodies.append(kwargs.get("json_body") or kwargs.get("form_fields"))
        image = {"b64_json": base64.b64encode(state.reply).decode()}
        body = {"data": [image] * state.images}
        return {"status": 200, "response_body": json.dumps(body), "headers": {}}, {}

    monkeypatch.setattr(images_router, "_send_openai_image_request_with_key_pool", send)
    monkeypatch.setattr(
        images_router,
        "upload_file",
        lambda request, file, user, file_metadata=None: state.uploads.append(file)
        or type("Stored", (), {"id": "file-id"})(),
    )
    return state


class _Request:
    class app:
        @staticmethod
        def url_path_for(_name, id):
            return f"/files/{id}/content"


COMMON = dict(
    model_id="gpt-image",
    prompt="a waving cat",
    size="auto",
    background=None,
    source={"base_url": "https://relay.example/v1", "key": "k", "api_config": {}},
)


def test_generation_sends_gif_without_streaming_and_stores_it_as_gif(upstream):
    result = asyncio.run(
        images_router._generate_via_openai_images_endpoint(
            _Request(), None, stream=True, n=1, output_format="gif", **COMMON
        )
    )
    body = upstream.bodies[0]
    assert body["output_format"] == "gif" and body["size"] == "auto"
    # Without this the relay answers output_format=gif with a PNG.
    assert body["prompt"].startswith("a waving cat") and "animated GIF" in body["prompt"]
    assert "stream" not in body and "partial_images" not in body
    assert result[0]["url"] == "/files/file-id/content"
    assert upstream.uploads[0].filename.endswith(".gif")
    assert upstream.uploads[0].headers["content-type"] == "image/gif"
    assert upstream.uploads[0].file.read() == upstream.reply


def test_each_image_of_a_batch_keeps_the_gif_request(upstream):
    result = asyncio.run(
        images_router._generate_via_openai_images_endpoint(
            _Request(), None, n=2, output_format="gif", **COMMON
        )
    )
    assert len(result) == 2
    assert [body["output_format"] for body in upstream.bodies] == ["gif", "gif"]


def test_a_relay_that_ignores_the_request_is_an_error_not_a_still(upstream):
    upstream.reply = _png()
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            images_router._generate_via_openai_images_endpoint(
                _Request(), None, n=1, output_format="gif", **COMMON
            )
        )
    assert failure.value.status_code == 502
    assert len(upstream.bodies) == 1 and not upstream.uploads


def test_a_still_request_is_unchanged(upstream):
    upstream.reply = _png()
    asyncio.run(images_router._generate_via_openai_images_endpoint(_Request(), None, n=1, **COMMON))
    assert "output_format" not in upstream.bodies[0]
    assert upstream.bodies[0]["prompt"] == "a waving cat"
    assert upstream.uploads[0].headers["content-type"] == "image/png"


def test_edit_sends_gif_and_a_stored_gif_source_goes_up_as_png(upstream, monkeypatch):
    monkeypatch.setattr(
        images_router, "_resolve_image_edit_input", lambda *_: ("image/gif", _gif())
    )
    seen = {}
    original = images_router._send_openai_image_request_with_key_pool

    async def send(**kwargs):
        seen["files"] = kwargs.get("files")
        return await original(**kwargs)

    monkeypatch.setattr(images_router, "_send_openai_image_request_with_key_pool", send)
    asyncio.run(
        images_router._generate_via_openai_image_edits_endpoint(
            _Request(), None, image_url="/files/x/content", n=1, output_format="gif", **COMMON
        )
    )
    assert upstream.bodies[0]["output_format"] == "gif"
    assert "animated GIF" in upstream.bodies[0]["prompt"]
    assert seen["files"][0]["mime"] == "image/png"


def test_a_relay_answering_with_extra_images_yields_only_what_was_asked(upstream):
    upstream.images = 2
    result = asyncio.run(
        images_router._generate_via_openai_images_endpoint(
            _Request(), None, n=1, output_format="gif", **COMMON
        )
    )
    assert len(result) == 1 and len(upstream.uploads) == 1
