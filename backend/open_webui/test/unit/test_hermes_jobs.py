"""定时任务 page: the pass-through to hermes /api/jobs (utils/hermes_jobs.py)."""

import asyncio
from types import SimpleNamespace

import aiohttp
import pytest

from open_webui.utils import hermes_jobs
from open_webui.utils.hermes_sessions import HermesSessionsError

JOB = {
    "id": "c5a0e24a8ec9",
    "name": "每周更新",
    "prompt": "",
    "script": "weekly.sh",
    "no_agent": True,
    "schedule": {"kind": "cron", "expr": "0 7 * * 1", "display": "0 7 * * 1"},
    "enabled": True,
    "state": "scheduled",
    "next_run_at": "2026-10-12T07:00:00+08:00",
    "deliver": "telegram:1",
    "fire_claim": {"owner": "x"},
    "origin": {"platform": "telegram"},
    "latest_execution": {"status": "completed", "pid": 1, "error": None, "delivery_outcome": "delivered"},
}


class _Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, content_type=None):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class _Session:
    def __init__(self, answer, calls):
        self.answer, self.calls = answer, calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("json"), kwargs.get("params")))
        return _Response(*self.answer)


def _world(monkeypatch, answer, *, session_class=_Session):
    calls = []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    monkeypatch.setattr(hermes_jobs, "resolve_hermes_model", resolve)
    monkeypatch.setattr(hermes_jobs, "_connection", lambda *_a: ("http://hermes.test", {}))
    monkeypatch.setattr(hermes_jobs.aiohttp, "ClientSession", lambda **_kw: session_class(answer, calls))
    return calls


USER = SimpleNamespace(id="u1")


def test_list_trims_scheduler_bookkeeping(monkeypatch):
    calls = _world(monkeypatch, (200, {"jobs": [JOB]}))
    jobs = asyncio.run(hermes_jobs.list_jobs(None, USER))
    assert calls == [("GET", "http://hermes.test/api/jobs", None, {"include_disabled": "true"})]
    assert jobs[0]["name"] == "每周更新" and jobs[0]["script"] == "weekly.sh"
    assert "fire_claim" not in jobs[0] and "origin" not in jobs[0]
    assert jobs[0]["latest_execution"] == {
        "status": "completed",
        "started_at": None,
        "finished_at": None,
        "error": None,
        "delivery_outcome": "delivered",
    }


def test_create_and_actions_hit_the_job_routes(monkeypatch):
    calls = _world(monkeypatch, (200, {"job": JOB}))
    fields = {"name": "早报", "schedule": "0 9 * * *", "prompt": "汇总新闻", "deliver": "local"}
    assert asyncio.run(hermes_jobs.create_job(None, USER, fields))["id"] == JOB["id"]
    asyncio.run(hermes_jobs.job_action(None, USER, JOB["id"], "pause"))
    asyncio.run(hermes_jobs.update_job(None, USER, JOB["id"], {"schedule": "0 8 * * *"}))
    asyncio.run(hermes_jobs.delete_job(None, USER, JOB["id"]))
    assert [(c[0], c[1], c[2]) for c in calls] == [
        ("POST", "http://hermes.test/api/jobs", fields),
        ("POST", f"http://hermes.test/api/jobs/{JOB['id']}/pause", None),
        ("PATCH", f"http://hermes.test/api/jobs/{JOB['id']}", {"schedule": "0 8 * * *"}),
        ("DELETE", f"http://hermes.test/api/jobs/{JOB['id']}", None),
    ]


def test_bad_ids_and_actions_never_reach_hermes(monkeypatch):
    calls = _world(monkeypatch, (200, {}))
    for job_id in ("../etc", "C5A0E24A8EC9", "abc"):
        with pytest.raises(HermesSessionsError) as e:
            asyncio.run(hermes_jobs.job_action(None, USER, job_id, "run"))
        assert e.value.status_code == 400
    with pytest.raises(HermesSessionsError):
        asyncio.run(hermes_jobs.job_action(None, USER, JOB["id"], "explode"))
    assert calls == []


def test_outputs_limit_is_clamped(monkeypatch):
    calls = _world(monkeypatch, (200, {"outputs": [{"name": "a.md", "content": "x"}, "junk"]}))
    outputs = asyncio.run(hermes_jobs.job_outputs(None, USER, JOB["id"], 50))
    assert outputs == [{"name": "a.md", "content": "x"}]
    assert calls[0][3] == {"limit": "10"}


@pytest.mark.parametrize(
    "answer,status,words",
    [
        ((400, {"error": "Invalid schedule 'soon'"}), 400, "Invalid schedule"),
        ((404, {"error": "Job not found"}), 404, "Job not found"),
        ((404, {}), 501, "更新 Hermes"),
        ((500, {"error": "boom"}), 502, "boom"),
    ],
)
def test_hermes_errors_keep_their_meaning(monkeypatch, answer, status, words):
    _world(monkeypatch, answer)
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_jobs.job_outputs(None, USER, JOB["id"]))
    assert e.value.status_code == status and words in e.value.detail


class _GetSession(_Session):
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, None, kwargs.get("params")))
        return _Response(*self.answer)


def test_runner_stats_clamps_days_and_keeps_rows(monkeypatch):
    calls = []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    monkeypatch.setattr(hermes_jobs, "resolve_hermes_model", resolve)
    monkeypatch.setattr(hermes_jobs, "_connection", lambda *_a: ("http://hermes.test", {}))
    monkeypatch.setattr(
        hermes_jobs.aiohttp,
        "ClientSession",
        lambda **_kw: _GetSession((200, {"days": 90, "runs": [{"run_id": "r1"}, "junk"]}), calls),
    )
    out = asyncio.run(hermes_jobs.runner_stats(None, USER, 365))
    assert out == {"days": 90, "runs": [{"run_id": "r1"}]}
    assert calls == [("GET", "http://hermes.test/v1/runners/stats", None, {"days": "90"})]

    monkeypatch.setattr(
        hermes_jobs.aiohttp, "ClientSession", lambda **_kw: _GetSession((404, {}), calls)
    )
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_jobs.runner_stats(None, USER, 7))
    assert e.value.status_code == 501


def test_runner_stats_preserves_quota_and_rejects_malformed_data(monkeypatch):
    calls = _world(monkeypatch, (200, {}))
    quota = {"available": True, "windows": [{"utilization": 95}]}
    monkeypatch.setattr(
        hermes_jobs.aiohttp, "ClientSession",
        lambda **_kw: _GetSession((200, {"days": 7, "runs": [], "quota": quota}), calls),
    )
    assert asyncio.run(hermes_jobs.runner_stats(None, USER, 7))["quota"] == quota
    offiagy = {"runner": "offiagy", "label": "offiagy", "available": True, "windows": []}
    codex = {"runner": "openai-codex", "label": "Hermes Codex", "plan": "Plus", "banked_resets": 2,
             "available": True, "windows": [{"key": "weekly", "label": "每周", "utilization": 83, "resets_at": None}]}
    monkeypatch.setattr(
        hermes_jobs.aiohttp, "ClientSession",
        lambda **_kw: _GetSession((200, {"days": 7, "runs": [], "quota": quota,
                                          "quotas": [quota, offiagy, codex, "junk"]}), calls),
    )
    assert asyncio.run(hermes_jobs.runner_stats(None, USER, 7))["quotas"] == [quota, offiagy, codex]
    monkeypatch.setattr(
        hermes_jobs.aiohttp, "ClientSession", lambda **_kw: _GetSession((200, []), calls)
    )
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_jobs.runner_stats(None, USER, 7))
    assert e.value.status_code == 502


def test_official_quotas_returns_only_the_three_accounts_and_public_fields(monkeypatch):
    claude = {
        "runner": "officlaude",
        "label": "官方 Claude",
        "available": True,
        "checked_at": 100.1,
        "windows": [
            {"key": "five_hour", "label": "5 小时", "utilization": 18.0, "resets_at": None},
            {"key": "seven_day", "label": "每周", "utilization": 42.0, "resets_at": None},
        ],
    }
    agy = {
        "runner": "offiagy",
        "label": "offiagy",
        "available": True,
        "checked_at": 100.2,
        "windows": [
            {"key": "gemini_five_hour", "label": "Gemini 5 小时", "utilization": 5.0, "resets_at": None},
            {"key": "gemini_weekly", "label": "Gemini 每周", "utilization": 12.0, "resets_at": None},
            {"key": "argon_weekly", "label": "Argon 每周", "utilization": 8.0, "resets_at": None},
        ],
    }
    codex = {
        "runner": "openai-codex",
        "label": "Hermes Codex",
        "available": True,
        "checked_at": 100.3,
        "windows": [
            {"key": "five_hour", "label": "5 小时", "utilization": 10.0,
             "resets_at": "2026-11-28T11:45:00+00:00"},
            {"key": "weekly", "label": "每周", "utilization": 65.0, "resets_at": None},
        ],
        "plan": "Plus",
        "banked_resets": 2,
    }
    body = {
        "days": 1,
        "runs": [{"run_id": "r1", "cwd": "/private"}],
        "quota": claude,
        "quotas": [
            {
                **claude,
                "api_key": "test-only",
                "windows": [
                    {**claude["windows"][0], "access_token": "test-only"},
                    claude["windows"][1],
                ],
            },
            agy,
            codex,
            {"runner": "other"},
            "junk",
        ],
    }
    calls = _world(monkeypatch, (200, body), session_class=_GetSession)
    monkeypatch.setattr(hermes_jobs, "time", SimpleNamespace(time=lambda: 101.0))

    assert asyncio.run(hermes_jobs.official_quotas(None, USER)) == {
        "quotas": [claude, agy, codex],
        "fetched_at": 101.0,
        "cache_ttl_seconds": 60,
    }
    assert calls == [("GET", "http://hermes.test/v1/runners/stats", None, {"days": "1"})]


@pytest.mark.parametrize("legacy_envelope", [{}, {"quotas": "bad"}])
def test_official_quotas_supports_legacy_quota(monkeypatch, legacy_envelope):
    body = {
        **legacy_envelope,
        "quota": {
            "available": True,
            "windows": [{"key": "five_hour", "label": "5 小时", "utilization": 0}],
        },
    }
    _world(monkeypatch, (200, body), session_class=_GetSession)
    out = asyncio.run(hermes_jobs.official_quotas(None, USER))

    assert out["quotas"] == [
        {
            "runner": "officlaude",
            "label": "官方 Claude",
            "available": True,
            "checked_at": out["fetched_at"],
            "windows": [{"key": "five_hour", "label": "5 小时", "utilization": 0.0, "resets_at": None}],
        }
    ]


def test_official_quotas_filters_malformed_windows_and_preserves_partial_results(monkeypatch):
    valid = {"key": "weekly", "label": "每周", "utilization": 120, "resets_at": 100}
    invalid = [
        "junk",
        {**valid, "key": 2},
        {**valid, "label": None},
        {**valid, "utilization": float("nan")},
        {**valid, "utilization": float("inf")},
        {**valid, "utilization": -1},
        {**valid, "utilization": True},
        {**valid, "utilization": "junk"},
    ]
    body = {
        "quotas": [
            {"runner": "officlaude", "available": True, "windows": [*invalid, valid]},
            {"runner": "offiagy", "available": False, "checked_at": 90,
             "notice": "暂时无法获取 offiagy 的实时额度"},
            {"runner": "openai-codex", "label": " ", "available": True, "checked_at": float("inf"),
             "windows": invalid, "plan": " ", "banked_resets": True, "notice": {"error": "test-only"}},
        ]
    }
    _world(monkeypatch, (200, body), session_class=_GetSession)
    out = asyncio.run(hermes_jobs.official_quotas(None, USER))

    assert out["quotas"] == [
        {
            "runner": "officlaude", "label": "官方 Claude", "available": True, "checked_at": out["fetched_at"],
            "windows": [{"key": "weekly", "label": "每周", "utilization": 100.0, "resets_at": None}],
        },
        {
            "runner": "offiagy", "label": "offiagy", "available": False, "checked_at": 90.0, "windows": [],
            "notice": "暂时无法获取 offiagy 的实时额度",
        },
        {
            "runner": "openai-codex", "label": "Hermes Codex", "available": False,
            "checked_at": out["fetched_at"], "windows": [],
        },
    ]


@pytest.mark.parametrize(
    "body",
    [{"runs": [{"run_id": "r1"}]}, {"quotas": {}, "quota": []}, {"quotas": [], "quota": {"available": True}}],
)
def test_official_quotas_returns_empty_list_when_no_quotas_are_reported(monkeypatch, body):
    _world(monkeypatch, (200, body), session_class=_GetSession)
    assert asyncio.run(hermes_jobs.official_quotas(None, USER))["quotas"] == []


@pytest.mark.parametrize(
    "answer,status,detail",
    [
        ((404, {"error": "test-only"}), 501, "这个 Hermes 还不支持额度查询，更新 Hermes 并重启网关后再试"),
        ((401, {"error": {"message": "Invalid gateway API key (API_SERVER_KEY)"}}), 502,
         "Hermes 返回 401：Invalid gateway API key (API_SERVER_KEY)"),
        ((500, {"error": {"message": "Bearer test-only"}}), 502, "Hermes 返回 500：HTTP 500"),
        ((500, ValueError("upstream raw body")), 502, "Hermes 返回 500：HTTP 500"),
        ((200, TimeoutError("test-only")), 502, "连不上 Hermes：请求超时"),
        ((200, aiohttp.ClientConnectionError("test-only")), 502, "连不上 Hermes：连接失败"),
        ((200, ValueError("upstream raw body")), 502, "Hermes 额度查询返回格式异常"),
        ((200, []), 502, "Hermes 额度查询返回格式异常"),
    ],
)
def test_official_quotas_maps_gateway_errors_without_exposing_private_details(monkeypatch, answer, status, detail):
    _world(monkeypatch, answer, session_class=_GetSession)
    with pytest.raises(HermesSessionsError) as error:
        asyncio.run(hermes_jobs.official_quotas(None, USER))

    assert error.value.status_code == status
    assert error.value.detail == detail


def test_official_quotas_reports_missing_gateway_configuration(monkeypatch):
    calls = _world(monkeypatch, (200, {}), session_class=_GetSession)

    def missing_connection(*_args):
        raise HermesSessionsError(503, "test-only")

    monkeypatch.setattr(hermes_jobs, "_connection", missing_connection)
    with pytest.raises(HermesSessionsError) as error:
        asyncio.run(hermes_jobs.official_quotas(None, USER))

    assert error.value.status_code == 502
    assert error.value.detail == "连不上 Hermes：未配置可用的 Hermes 网关"
    assert calls == []
