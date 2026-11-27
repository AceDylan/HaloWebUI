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


def test_work_config_forwards_get_and_put(monkeypatch):
    config = {"plan_review": True, "steps": {
        "plan": {"runner": "offiagy", "fallback": ["agy"]},
        "plan_review": {"runner": "officlaude", "fallback": ["codex"]},
        "dev": {"runner": "codex", "fallback": []},
        "review": {"runner": "officlaude", "fallback": ["cchclaude"]},
    }}
    response = {"config": config, "defaults": {}, "runners": [], "steps_meta": []}
    calls = _world(monkeypatch, (200, response))
    assert asyncio.run(hermes_routing.get_work_config(None, USER)) == response
    assert asyncio.run(hermes_routing.save_work_config(None, USER, config)) == response
    path = "http://hermes.test/v1/halo-teams/work-config"
    assert calls == [("GET", path, None), ("PUT", path, config)]


@pytest.mark.parametrize("status, body, expected, message", [
    (400, {"error": {"message": "开发的兜底不能包含首选执行器"}}, 400, "不能包含首选执行器"),
    (403, {}, 403, "HTTP 403"),
    (409, {}, 409, "HTTP 409"),
    (404, {}, 501, "网页配置 /work"),
    (500, {"error": {"message": "upstream error"}}, 502, "upstream error"),
])
def test_work_config_keeps_gateway_error_semantics(monkeypatch, status, body, expected, message):
    _world(monkeypatch, (status, body))
    with pytest.raises(HermesSessionsError) as error:
        asyncio.run(hermes_routing.save_work_config(None, USER, {}))
    assert error.value.status_code == expected
    assert message in error.value.detail


def test_work_config_routes_require_an_admin(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from open_webui.routers.hermes import router
    from open_webui.utils.auth import get_current_user

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = {
        "plan_review": True,
        "dual_plan": False,
        "plan_approval": False,
        "ui_review": False,
        "split_dev": False,
        "steps": {
            step: {"runner": "codex", "fallback": []}
            for step in ("plan", "plan_review", "dev", "review")
        },
    }
    calls = []

    async def get_config(_request, user):
        calls.append(("GET", user.role))
        return {"config": payload}

    async def save_config(_request, user, config):
        calls.append(("PUT", user.role, config))
        return {"config": config}

    monkeypatch.setattr(hermes_routing, "get_work_config", get_config)
    monkeypatch.setattr(hermes_routing, "save_work_config", save_config)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="user")
    assert client.get("/work-config").status_code in (401, 403)
    assert client.put("/work-config", json=payload).status_code in (401, 403)
    assert not calls
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="admin")
    assert client.get("/work-config").json() == {"config": payload}
    assert client.put("/work-config", json=payload).json() == {"config": payload}
    assert client.put("/work-config", json={**payload, "plan_review": "true"}).status_code == 422
    assert client.put("/work-config", json={**payload, "dual_plan": "yes"}).status_code == 422
    assert calls == [("GET", "admin"), ("PUT", "admin", payload)]


# ---- AGY 优先 ----


class _Card:
    def __init__(self, value):
        self.value, self.config_value, self.saved = value, None, 0

    def save(self):
        self.saved += 1
        self.config_value = self.value


def _card(monkeypatch, value="gemini-4-argon-high"):
    import open_webui.config as config

    card = _Card(value)
    monkeypatch.setattr(config, "HTML_VISUAL_AGY_CARD_MODEL", card, raising=False)
    monkeypatch.setenv("HALOWEBUI_AGY_OAUTH_TOKEN_FILE", "/x/token")
    return card


def test_agy_prefs_combines_card_and_teams(monkeypatch):
    calls = _world(monkeypatch, (200, {"ui_runner": "offiagy", "offiagy_models": []}))
    _card(monkeypatch)
    out = asyncio.run(hermes_routing.get_agy_prefs(None, USER))
    assert out["card"] == {"model": "gemini-4-argon-high", "default": "gemini-4-argon-high", "signed_in": True}
    assert out["teams"]["ui_runner"] == "offiagy"
    assert calls == [("GET", "http://hermes.test/v1/halo-teams/agy-prefs", None)]
    calls.clear()
    asyncio.run(hermes_routing.get_agy_prefs(None, USER, refresh=True))
    assert calls == [("GET", "http://hermes.test/v1/halo-teams/agy-prefs?refresh=1", None)]


def test_agy_prefs_card_still_shows_when_hermes_is_down(monkeypatch):
    _world(monkeypatch, (500, {"error": {"message": "boom"}}))
    _card(monkeypatch, "")
    out = asyncio.run(hermes_routing.get_agy_prefs(None, USER))
    assert out["card"]["model"] == "" and "boom" in out["teams"]["error"]


def test_agy_prefs_save_card_locally_and_teams_on_hermes(monkeypatch):
    calls = _world(monkeypatch, (200, {"ui_runner": "agy"}))
    card = _card(monkeypatch)
    asyncio.run(
        hermes_routing.save_agy_prefs(
            None, USER, {"card_model": "", "ui_runner": "agy", "offiagy_model": "gemini-4-neon-high"}
        )
    )
    assert card.value == "" and card.saved == 1
    assert calls[0] == (
        "PUT", "http://hermes.test/v1/halo-teams/agy-prefs",
        {"ui_runner": "agy", "offiagy_model": "gemini-4-neon-high"},
    )
    # only the card: nothing goes to hermes but the re-read
    calls.clear()
    asyncio.run(hermes_routing.save_agy_prefs(None, USER, {"card_model": "gemini-4-neon-low"}))
    assert card.value == "gemini-4-neon-low" and [c[0] for c in calls] == ["GET"]
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_routing.save_agy_prefs(None, USER, {"card_model": "--evil flag"}))
    assert e.value.status_code == 400 and card.value == "gemini-4-neon-low"


def test_html_card_prefers_the_model_saved_on_the_page(monkeypatch):
    from open_webui.utils import html_visual_prompt

    card = _card(monkeypatch)
    monkeypatch.setenv("HALOWEBUI_AGY_PREFERRED_MODEL", "from-env")
    assert html_visual_prompt._agy_preferred_model() == "from-env"  # nothing saved yet
    card.value = "gemini-4-neon-high"
    card.save()
    assert html_visual_prompt._agy_preferred_model() == "gemini-4-neon-high"
    card.value = ""
    card.save()
    assert html_visual_prompt._agy_preferred_model() is None  # switched off on the page


def test_get_routing_supports_refresh_and_attaches_halo_reasoning_effort(monkeypatch):
    import open_webui.haloclaw.config as hc

    effort_cfg = _Card("high")
    monkeypatch.setattr(hc, "HALOCLAW_DEFAULT_REASONING_EFFORT", effort_cfg, raising=False)
    calls = _world(monkeypatch, (200, {"models": [], "routing": {"main": "gpt-chat"}}))
    _MODEL_OPTIONS_CACHE["u1"] = (0, {})
    out = asyncio.run(hermes_routing.get_routing(None, USER, refresh=True))
    assert calls == [("GET", "http://hermes.test/api/admin/routing?refresh=1", None)]
    assert out["halo_reasoning_effort"] == "high"
    assert _MODEL_OPTIONS_CACHE == {}


def test_save_and_rollback_routing_sync_halo_reasoning_effort(monkeypatch):
    import open_webui.haloclaw.config as hc

    effort_cfg = _Card("medium")
    monkeypatch.setattr(hc, "HALOCLAW_DEFAULT_REASONING_EFFORT", effort_cfg, raising=False)
    _world(
        monkeypatch,
        (200, {"routing": {"main": "gpt-chat", "reasoning_effort": "high"}, "changes": []}),
    )
    out = asyncio.run(
        hermes_routing.save_routing(
            None, USER, {"main": "gpt-chat", "reasoning_effort": "high"}, "rev"
        )
    )
    assert effort_cfg.value == "high" and effort_cfg.saved == 1
    assert out["halo_reasoning_effort"] == "high"
    assert out["changes"] == [{"path": "reasoning_effort", "before": "medium", "after": "high"}]

    _world(
        monkeypatch,
        (
            200,
            {
                "routing": {"main": "gpt-chat", "reasoning_effort": "low"},
                "changes": [{"path": "reasoning_effort", "before": "high", "after": "low"}],
            },
        ),
    )
    rolled = asyncio.run(hermes_routing.rollback_routing(None, USER, "20261125-1", "rev"))
    assert effort_cfg.value == "low" and effort_cfg.saved == 2
    assert rolled["halo_reasoning_effort"] == "low"
