"""定时任务 page: the pass-through to hermes /api/jobs (utils/hermes_jobs.py)."""

import asyncio
from types import SimpleNamespace

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


def _world(monkeypatch, answer):
    calls = []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    monkeypatch.setattr(hermes_jobs, "resolve_hermes_model", resolve)
    monkeypatch.setattr(hermes_jobs, "_connection", lambda *_a: ("http://hermes.test", {}))
    monkeypatch.setattr(hermes_jobs.aiohttp, "ClientSession", lambda **_kw: _Session(answer, calls))
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
    monkeypatch.setattr(
        hermes_jobs.aiohttp, "ClientSession", lambda **_kw: _GetSession((200, []), calls)
    )
    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(hermes_jobs.runner_stats(None, USER, 7))
    assert e.value.status_code == 502
