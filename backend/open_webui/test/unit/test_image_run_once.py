import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import images as images_router  # noqa: E402
from open_webui.routers.images import (  # noqa: E402
    GenerateImageForm,
    _image_run_key,
    _run_image_generation_once,
)


@pytest.fixture(autouse=True)
def _fresh_runs(monkeypatch):
    monkeypatch.setattr(images_router, "_image_runs", {})


def _user(user_id="u1"):
    return SimpleNamespace(id=user_id)


def test_run_key_needs_an_id_and_belongs_to_the_user():
    assert _image_run_key(_user(), None) is None
    assert _image_run_key(_user(), "  ") is None
    assert _image_run_key(_user(), "a1-b2_c3") == ("u1", "a1-b2_c3")
    # Only a plain token is kept.
    assert _image_run_key(_user(), "x/../y z") == ("u1", "xyz")
    assert _image_run_key(_user("u2"), "a1") != _image_run_key(_user(), "a1")


def test_a_resent_request_joins_the_running_generation():
    # The 10-05 phone case: the browser re-sent the POST while the first one
    # was still generating; the upstream must be called once.
    calls = []

    async def scenario():
        release = asyncio.Event()

        async def start():
            calls.append(1)
            await release.wait()
            return [{"url": "/api/v1/files/f1/content"}]

        key = ("u1", "run-1")
        first = asyncio.ensure_future(_run_image_generation_once(key, start))
        await asyncio.sleep(0)
        second = asyncio.ensure_future(_run_image_generation_once(key, start))
        await asyncio.sleep(0)
        release.set()
        return await first, await second

    first, second = asyncio.run(scenario())
    assert calls == [1]
    assert first == second == [{"url": "/api/v1/files/f1/content"}]


def test_a_dropped_connection_does_not_stop_the_generation_and_a_retry_gets_it():
    calls = []

    async def scenario():
        release = asyncio.Event()

        async def start():
            calls.append(1)
            await release.wait()
            return ["image"]

        key = ("u1", "run-2")
        dropped = asyncio.ensure_future(_run_image_generation_once(key, start))
        await asyncio.sleep(0)
        dropped.cancel()  # the client went away
        await asyncio.sleep(0)
        release.set()
        await asyncio.sleep(0)
        return await _run_image_generation_once(key, start)

    assert asyncio.run(scenario()) == ["image"]
    assert calls == [1]


def test_a_failed_run_reports_its_error_to_the_resend_and_other_ids_run_apart():
    calls = []

    async def scenario():
        async def fail():
            calls.append("fail")
            raise RuntimeError("upstream said no")

        async def succeed():
            calls.append("ok")
            return ["image"]

        with pytest.raises(RuntimeError):
            await _run_image_generation_once(("u1", "bad"), fail)
        with pytest.raises(RuntimeError):
            await _run_image_generation_once(("u1", "bad"), fail)
        return await _run_image_generation_once(("u1", "good"), succeed)

    assert asyncio.run(scenario()) == ["image"]
    assert calls == ["fail", "ok"]


def test_finished_runs_are_forgotten_after_the_keep_window():
    calls = []

    async def scenario():
        async def start():
            calls.append(1)
            return ["image"]

        await _run_image_generation_once(("u1", "old"), start)
        started_at, run = images_router._image_runs[("u1", "old")]
        images_router._image_runs[("u1", "old")] = (
            started_at - images_router._IMAGE_RUN_KEEP_SECONDS - 1,
            run,
        )
        await _run_image_generation_once(("u1", "new"), start)
        assert ("u1", "old") not in images_router._image_runs
        await _run_image_generation_once(("u1", "old"), start)

    asyncio.run(scenario())
    assert calls == [1, 1, 1]


def test_the_route_runs_once_per_client_request_id(monkeypatch):
    calls = []

    async def fake_generations(request, form_data, user):
        calls.append(form_data.prompt)
        return [{"url": "/x"}]

    monkeypatch.setattr(images_router, "_image_generations", fake_generations)

    async def scenario():
        user = _user()
        tagged = GenerateImageForm(prompt="a cat", client_request_id="r1")
        untagged = GenerateImageForm(prompt="a dog")
        await images_router.image_generations(None, tagged, user=user)
        await images_router.image_generations(None, tagged, user=user)
        await images_router.image_generations(None, untagged, user=user)
        await images_router.image_generations(None, untagged, user=user)

    asyncio.run(scenario())
    assert calls == ["a cat", "a dog", "a dog"]
