"""「Hermes 模型」 page: the pass-through to hermes /api/admin/routing (utils/hermes_routing.py)."""

import asyncio
from types import SimpleNamespace

import pytest

from open_webui.utils import hermes_routing
from open_webui.utils.hermes_sessions import _MODEL_OPTIONS_CACHE, HermesSessionsError


class _Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, content_type=None):
        return self.body


class _Session:
    def __init__(self, answer, calls):
        self.answer, self.calls = answer, calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("json")))
        return _Response(*self.answer)


def _world(monkeypatch, answer):
    calls = []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    monkeypatch.setattr(hermes_routing, "resolve_hermes_model", resolve)
    monkeypatch.setattr(hermes_routing, "_connection", lambda *_a: ("http://hermes.test", {}))
    monkeypatch.setattr(
        hermes_routing.aiohttp, "ClientSession", lambda **_kw: _Session(answer, calls)
    )
    return calls


USER = SimpleNamespace(id="u1")


def test_save_forwards_routing_and_revision_and_drops_picker_cache(monkeypatch):
    calls = _world(monkeypatch, (200, {"routing": {"main": "gpt-chat"}, "changes": [{"path": "main"}]}))
    _MODEL_OPTIONS_CACHE["u1"] = (0, {})
    out = asyncio.run(hermes_routing.save_routing(None, USER, {"main": "gpt-chat"}, "rev"))
    assert out["routing"]["main"] == "gpt-chat"
    assert calls == [
        ("PUT", "http://hermes.test/api/admin/routing",
         {"routing": {"main": "gpt-chat"}, "revision": "rev", "source": "halowebui"})
    ]
    assert _MODEL_OPTIONS_CACHE == {}


def test_unchanged_save_keeps_picker_cache(monkeypatch):
    _world(monkeypatch, (200, {"changes": []}))
    _MODEL_OPTIONS_CACHE["u1"] = (0, {})
    asyncio.run(hermes_routing.save_routing(None, USER, {}, None))
    assert "u1" in _MODEL_OPTIONS_CACHE
    _MODEL_OPTIONS_CACHE.clear()


def test_rollback_and_probe_paths(monkeypatch):
    calls = _world(monkeypatch, (200, {"ok": True}))
    asyncio.run(hermes_routing.rollback_routing(None, USER, "20261123-1", "rev"))
    asyncio.run(hermes_routing.probe_model(None, USER, "gemini-chat"))
    assert [c[1] for c in calls] == [
        "http://hermes.test/api/admin/routing/rollback",
        "http://hermes.test/api/admin/routing/probe",
    ]
    assert calls[0][2] == {"id": "20261123-1", "revision": "rev"}


@pytest.mark.parametrize(
    "status, body, expect_status, expect_text",
    [
        (409, {"error": {"message": "配置已被别处修改"}}, 409, "别处修改"),
        (400, {"error": {"message": "主模型：未知模型 x"}}, 400, "未知模型"),
        (403, {"error": {"message": "Routing admin needs API_SERVER_KEY."}}, 403, "API_SERVER_KEY"),
        (404, {}, 501, "更新 Hermes"),
        (500, {"error": {"message": "boom"}}, 502, "boom"),
    ],
)
def test_errors_keep_hermes_message(monkeypatch, status, body, expect_status, expect_text):
    _world(monkeypatch, (status, body))
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_routing.get_routing(None, USER))
    assert e.value.status_code == expect_status
    assert expect_text in e.value.detail
