"""协作台 (agent teams) API: ownership, the plan → approve → running lifecycle, honest failure
states, reconciliation after a restart, and the Hermes proxy (faked here).

Runs against a throwaway SQLite database; the app's Alembic migrations create the schema
(which also exercises the new agent_team revision)."""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-agent-teams-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "agent-teams-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.internal.db import engine  # noqa: E402
from open_webui.models.agent_teams import AgentTeams  # noqa: E402
from open_webui.routers import teams as teams_router  # noqa: E402
from open_webui.utils import agent_teams as teams_utils  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402

PLAN = {
    "title": "计算器设计",
    "members": [
        {"name": "spec-writer", "role": "说明", "executor": "hermes"},
        {"name": "reviewer", "role": "评审", "executor": "hermes"},
    ],
    "tasks": [
        {"key": "T1", "title": "写说明", "member": "spec-writer", "depends_on": []},
        {"key": "T2", "title": "评审", "member": "reviewer", "depends_on": ["T1"]},
    ],
    "executors": ["hermes"],
}


class _User:
    def __init__(self, id: str, name: str = "Ace"):
        self.id = id
        self.name = name
        self.role = "admin"


class FakeHermes:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.fail = {}

    async def call(self, target, method, path, *, json_body=None, params=None, timeout=30):
        self.calls.append((target.headers.get("X-Halo-Owner"), method, path, json_body, params))

        def hit(key):
            m, suffix = key
            return m == method and (path.endswith(suffix) if suffix else path == "")

        for key, err in self.fail.items():
            if hit(key):
                raise teams_utils.TeamsError(*err)
        for key, value in self.responses.items():
            if hit(key):
                return value
        return {}


@pytest.fixture
def hermes(monkeypatch):
    fake = FakeHermes()

    async def target(request, user):
        return teams_utils.HermesTarget("http://hermes", {"Authorization": "Bearer k"}, str(user.id))

    monkeypatch.setattr(teams_router, "hermes_target", target)
    monkeypatch.setattr(teams_router, "hermes_call", fake.call)
    monkeypatch.setattr(teams_utils, "hermes_call", fake.call)
    planned = []
    monkeypatch.setattr(teams_router, "start_planning", lambda team, target, feedback="", previous=None:
                        planned.append((team.id, feedback, previous)))
    fake.planned = planned
    return fake


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(teams_router.router, prefix="/api/v1/teams")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def _ready_team(client, hermes, user_id="u1"):
    team = client.post("/api/v1/teams/", json={"goal": "设计一个计算器"}).json()
    AgentTeams.update(team["id"], user_id, status="plan_ready", plan=PLAN, title="计算器设计")
    return team["id"]


def test_migration_created_the_table():
    assert "agent_team" in sa.inspect(engine).get_table_names()


def test_create_lists_only_own_teams_and_hides_others(hermes):
    a, b = _client("u1"), _client("u2")
    created = a.post("/api/v1/teams/", json={"goal": "  写一份调研报告  "})
    assert created.status_code == 200
    team = created.json()
    assert team["status"] == "planning" and team["goal"] == "写一份调研报告" and "user_id" not in team
    assert hermes.planned[-1][0] == team["id"]
    assert [t["id"] for t in a.get("/api/v1/teams/").json()["teams"]] == [team["id"]]
    assert b.get("/api/v1/teams/").json()["teams"] == []
    for method, path in (("get", ""), ("post", "/approve"), ("post", "/cancel"), ("get", "/events")):
        resp = getattr(b, method)(f"/api/v1/teams/{team['id']}{path}")
        assert resp.status_code == 404, (method, path)


def test_chat_must_belong_to_the_user(hermes, monkeypatch):
    monkeypatch.setattr(teams_router.Chats, "get_chat_by_id_and_user_id", lambda chat_id, user_id: None)
    resp = _client("u1").post("/api/v1/teams/", json={"goal": "x", "chat_id": "someone-elses-chat"})
    assert resp.status_code == 404


def test_planning_job_records_plan_or_real_error(hermes):
    client = _client("u1")
    team = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "目标"}).json()["id"], "u1")
    target = teams_utils.HermesTarget("http://hermes", {}, "u1")
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": PLAN}
    asyncio.run(teams_utils._plan_job(team, target, "", None))
    done = AgentTeams.get(team.id, "u1")
    assert done.status == "plan_ready" and done.title == "计算器设计" and done.plan["tasks"][1]["depends_on"] == ["T1"]
    assert hermes.calls[-1][0] == "u1" and hermes.calls[-1][3]["team_id"] == team.id

    team2 = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "目标2"}).json()["id"], "u1")
    hermes.fail[("POST", "/plan")] = (502, "模型调用失败：401")
    asyncio.run(teams_utils._plan_job(team2, target, "", None))
    failed = AgentTeams.get(team2.id, "u1")
    assert failed.status == "plan_failed" and "401" in failed.error


def test_approve_starts_once_and_failure_is_not_a_fake_running_state(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    hermes.fail[("POST", "")] = (502, "Hermes 上没有协作台插件")
    resp = client.post(f"/api/v1/teams/{team_id}/approve")
    assert resp.status_code == 502 and "启动失败" in resp.json()["detail"]
    row = AgentTeams.get(team_id, "u1")
    assert row.status == "start_failed" and "没有协作台插件" in row.error
    del hermes.fail[("POST", "")]
    hermes.responses[("POST", "")] = {"board": "halo-abc", "created": True, "tasks": {"T1": "t_1", "T2": "t_2"}}
    resp = client.post(f"/api/v1/teams/{team_id}/approve")
    assert resp.status_code == 200 and resp.json()["status"] == "running" and resp.json()["board"] == "halo-abc"
    body = next(c for c in hermes.calls if c[1] == "POST" and c[2] == "")[3]
    assert body["plan"]["title"] == "计算器设计" and body["team_id"] == team_id
    again = client.post(f"/api/v1/teams/{team_id}/approve")
    assert again.status_code == 409
    assert client.post(f"/api/v1/teams/{team_id}/cancel").status_code == 409


def test_edit_plan_executors_only_before_approval(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "reviewer", "executor": "reclaude"}]})
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    assert [m["executor"] for m in plan["members"]] == ["hermes", "reclaude"] and plan["executors"] == ["hermes", "reclaude"]
    for runner in ("cchclaude", "anyclaude", "codex", "agy"):
        resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "reviewer", "executor": runner}]})
        assert resp.status_code == 200 and resp.json()["plan"]["executors"] == sorted(["hermes", runner])
    bad = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "reviewer", "executor": "gpt"}]})
    assert bad.status_code == 422


def test_edit_plan_records_the_users_choice_and_lets_hermes_resolve_the_runner(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    resolved = {**PLAN, "members": [
        {**PLAN["members"][0]},
        {**PLAN["members"][1], "executor": "codex", "executor_source": "user", "runner": "agy",
         "runner_note": "codex 没有登录"}]}
    hermes.responses[("POST", "/plan/resolve")] = {"ok": True, "plan": resolved}
    resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "reviewer", "executor": "codex"}]})
    assert resp.status_code == 200
    sent = next(c for c in hermes.calls if c[2] == "/plan/resolve")[3]["plan"]
    assert sent["members"][1]["executor"] == "codex" and sent["members"][1]["executor_source"] == "user"
    member = resp.json()["plan"]["members"][1]
    assert member["runner"] == "agy" and "没有登录" in member["runner_note"]
    assert resp.json()["plan"]["executors"] == ["agy", "hermes"]
    # "auto" goes back to the kind's recommendation.
    AgentTeams.update(team_id, "u1", plan={**PLAN, "members": [PLAN["members"][0], {**PLAN["members"][1], "recommended": "cchclaude"}]})
    hermes.responses.pop(("POST", "/plan/resolve"))
    resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "reviewer", "executor": "codex", "source": "auto"}]})
    member = resp.json()["plan"]["members"][1]
    assert member["executor"] == "cchclaude" and member["executor_source"] == "auto" and member["runner"] == "cchclaude"


def test_meta_conclusion_and_files_are_proxied_per_owner(hermes, monkeypatch):
    client, other = _client("u1"), _client("u2")
    hermes.responses[("GET", "/meta")] = {"lead_model": {"model": "gpt-chat"}}
    assert client.get("/api/v1/teams/meta").json()["lead_model"]["model"] == "gpt-chat"
    team_id = _ready_team(client, hermes)
    assert client.get(f"/api/v1/teams/{team_id}/conclusion").json()["status"] == "none"  # not started: no call
    AgentTeams.update(team_id, "u1", status="running", board="halo-x")
    hermes.responses[("GET", "/conclusion")] = {"status": "ready", "markdown": "# 结论"}
    assert client.get(f"/api/v1/teams/{team_id}/conclusion").json()["markdown"] == "# 结论"
    assert hermes.calls[-1][:3] == ("u1", "GET", f"/{team_id}/conclusion")
    hermes.responses[("POST", "/conclusion")] = {"status": "generating"}
    assert client.post(f"/api/v1/teams/{team_id}/conclusion").json()["status"] == "generating"
    fetched = []

    async def fake_file(target, path, timeout=60):
        fetched.append((target.headers["X-Halo-Owner"], path))
        return b"\x89PNG", {"Content-Type": "image/png", "Content-Disposition": "inline", "Server": "x"}

    monkeypatch.setattr(teams_router, "hermes_file", fake_file)
    resp = client.get(f"/api/v1/teams/{team_id}/files/shots/home%20page.png")
    assert resp.status_code == 200 and resp.content == b"\x89PNG" and resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff" and "server" not in resp.headers
    assert fetched == [("u1", f"/{team_id}/files/shots/home%20page.png")]
    for path in ("/conclusion", "/files", "/files/a.png"):
        assert other.get(f"/api/v1/teams/{team_id}{path}").status_code == 404


def test_a_team_can_ask_for_another_lead_model(hermes):
    client = _client("u1")
    created = client.post("/api/v1/teams/", json={"goal": "写一份报告", "lead_model": "claude-chat"}).json()
    assert created["lead_model"] == "claude-chat"
    team = AgentTeams.get(created["id"], "u1")
    target = teams_utils.HermesTarget("http://hermes", {}, "u1")
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": PLAN}
    asyncio.run(teams_utils._plan_job(team, target, "", None))
    sent = [c for c in hermes.calls if c[2] == "/plan"][-1][3]
    assert sent["lead_model"] == "claude-chat"
    plain = client.post("/api/v1/teams/", json={"goal": "x"}).json()
    assert plain["lead_model"] is None


def test_replan_sends_feedback_and_previous_plan(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    resp = client.post(f"/api/v1/teams/{team_id}/replan", json={"feedback": "再加一个测试成员"})
    assert resp.status_code == 200 and resp.json()["status"] == "planning"
    assert hermes.planned[-1] == (team_id, "再加一个测试成员", PLAN)


def test_reconcile_fixes_rows_left_behind_by_a_restart(hermes):
    client = _client("u1")
    team_id = client.post("/api/v1/teams/", json={"goal": "x"}).json()["id"]
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE agent_team SET updated_at = :t WHERE id = :id"),
                     {"t": int(time.time()) - 3600, "id": team_id})
    data = client.get(f"/api/v1/teams/{team_id}").json()
    assert data["team"]["status"] == "plan_failed" and "中断" in data["team"]["error"]

    team_id = _ready_team(client, hermes)
    AgentTeams.update(team_id, "u1", status="starting")
    hermes.responses[("GET", team_id)] = {"team": {"phase": "completed", "board": "halo-x"}, "tasks": []}
    data = client.get(f"/api/v1/teams/{team_id}").json()
    assert data["team"]["status"] == "running" and data["team"]["phase"] == "completed"
    assert data["team"]["finished_at"] and data["live"]["team"]["board"] == "halo-x"


def test_proxy_routes_pass_owner_and_validate_task_ids(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    assert client.get(f"/api/v1/teams/{team_id}/events").json()["events"] == []  # not running yet
    hermes.responses[("POST", "")] = {"board": "halo-abc"}
    client.post(f"/api/v1/teams/{team_id}/approve")
    hermes.responses[("GET", "/events")] = {"events": [{"seq": 1}], "next_after": 1}
    out = client.get(f"/api/v1/teams/{team_id}/events", params={"after": 0, "limit": 99999}).json()
    assert out["events"] == [{"seq": 1}]
    assert hermes.calls[-1][4] == {"after": 0, "limit": 2000} and hermes.calls[-1][0] == "u1"
    assert client.get(f"/api/v1/teams/{team_id}/tasks/..%2F..%2Fetc").status_code == 404
    assert client.post(f"/api/v1/teams/{team_id}/tasks/t_bad!/messages", json={"body": "x"}).status_code in (404, 422)
    hermes.responses[("POST", "/messages")] = {"comment_id": 3, "delivery": "queued"}
    msg = client.post(f"/api/v1/teams/{team_id}/tasks/t_1a2b3c4d/messages", json={"body": "加上错误处理"})
    assert msg.status_code == 200 and hermes.calls[-1][3] == {"body": "加上错误处理", "author_name": "Ace"}
    hermes.responses[("POST", "/control")] = {"state": "stopped"}
    assert client.post(f"/api/v1/teams/{team_id}/control", json={"action": "stop"}).status_code == 200
    row = AgentTeams.get(team_id, "u1")
    assert row.phase == "stopped" and row.finished_at
    assert client.post(f"/api/v1/teams/{team_id}/control", json={"action": "explode"}).status_code == 422


def test_feature_flag_off_hides_every_route(hermes, monkeypatch):
    monkeypatch.setattr(teams_router, "ENABLE_AGENT_TEAMS", False)
    client = _client("u1")
    assert client.get("/api/v1/teams/").status_code == 404
    assert client.post("/api/v1/teams/", json={"goal": "x"}).status_code == 404


def test_list_reads_running_teams_live_and_carries_progress_and_roster(hermes):
    client = _client("u-list")
    team_id = _ready_team(client, hermes, "u-list")
    hermes.responses[("POST", "")] = {"board": "halo-abc"}
    client.post(f"/api/v1/teams/{team_id}/approve")
    hermes.responses[("GET", team_id)] = {
        "team": {"phase": "running"},
        "tasks": [
            {"id": "t_1", "status": "done", "sub_status": "done"},
            {"id": "t_2", "status": "running", "sub_status": "running"},
        ],
    }
    listed = {t["id"]: t for t in client.get("/api/v1/teams/").json()["teams"]}[team_id]
    assert listed["progress"] == {"done": 1, "running": 1, "attention": 0, "total": 2}
    assert [m["name"] for m in listed["roster"]] == ["spec-writer", "reviewer"]
    assert listed["deletable"] is False and "plan" not in listed

    # Hermes down: the list still loads with the last recorded progress.
    hermes.fail[("GET", team_id)] = (502, "Hermes 不可用")
    listed = {t["id"]: t for t in client.get("/api/v1/teams/").json()["teams"]}[team_id]
    assert listed["progress"]["done"] == 1

    # Finished teams are not asked again.
    del hermes.fail[("GET", team_id)]
    hermes.responses[("GET", team_id)] = {"team": {"phase": "completed"}, "tasks": [
        {"id": "t_1", "status": "done"}, {"id": "t_2", "status": "done"}]}
    client.get("/api/v1/teams/")
    calls = len(hermes.calls)
    listed = {t["id"]: t for t in client.get("/api/v1/teams/").json()["teams"]}[team_id]
    assert listed["phase"] == "completed" and listed["deletable"] is True and len(hermes.calls) == calls


def test_delete_only_when_nothing_runs_and_only_your_own(hermes):
    a, b = _client("u-del"), _client("u2")
    planning = a.post("/api/v1/teams/", json={"goal": "x"}).json()["id"]
    assert a.delete(f"/api/v1/teams/{planning}").status_code == 409

    ready = _ready_team(a, hermes, "u-del")
    assert b.delete(f"/api/v1/teams/{ready}").status_code == 404
    assert a.delete(f"/api/v1/teams/{ready}").json() == {"ok": True, "id": ready}
    assert a.get(f"/api/v1/teams/{ready}").status_code == 404

    running = _ready_team(a, hermes, "u-del")
    hermes.responses[("POST", "")] = {"board": "halo-abc"}
    a.post(f"/api/v1/teams/{running}/approve")
    resp = a.delete(f"/api/v1/teams/{running}")
    assert resp.status_code == 409 and "停止" in resp.json()["detail"]
    AgentTeams.update(running, "u-del", phase="stopped")
    assert a.delete(f"/api/v1/teams/{running}").status_code == 200


# --- Hermes calling back (Telegram) -----------------------------------------------------------------

def _hermes_client(monkeypatch, owners=("u1",)):
    known = {o: _User(o) for o in owners}
    monkeypatch.setattr(teams_router.Users, "get_user_by_id", lambda uid: known.get(uid))
    teams_router._hermes_auth_cache.clear()
    app = FastAPI()
    app.include_router(teams_router.router, prefix="/api/v1/teams")
    return TestClient(app)


def test_hermes_routes_need_the_users_own_hermes_key(hermes, monkeypatch):
    client = _hermes_client(monkeypatch)
    base = "/api/v1/teams/hermes/teams"
    assert client.get(base).status_code == 401
    assert client.get(base, headers={"X-Hermes-Key": "k", "X-Halo-Owner": "nobody"}).status_code == 401
    assert client.get(base, headers={"X-Hermes-Key": "wrong", "X-Halo-Owner": "u1"}).status_code == 401
    ok = client.get(base, headers={"X-Hermes-Key": "k", "X-Halo-Owner": "u1"})
    assert ok.status_code == 200 and isinstance(ok.json()["teams"], list)
    # the browser session is not accepted on these routes, nor the Hermes key on the browser ones
    assert _client("u1").get(base).status_code == 401


def test_telegram_team_runs_the_same_plan_and_approve_flow(hermes, monkeypatch):
    client = _hermes_client(monkeypatch)
    h = {"X-Hermes-Key": "k", "X-Halo-Owner": "u1"}
    created = client.post("/api/v1/teams/hermes/teams", headers=h,
                          json={"goal": "研究下雨天山上的云", "origin": {"platform": "telegram", "chat_id": "5550001",
                                                                   "user_id": "5550001", "junk": "x"}})
    assert created.status_code == 200
    team = created.json()
    assert team["status"] == "planning" and team["origin"] == "telegram" and hermes.planned[-1][0] == team["id"]
    row = AgentTeams.get(team["id"], "u1")
    assert row.meta["origin"] == {"platform": "telegram", "chat_id": "5550001", "user_id": "5550001"}
    # the owner sees it in the browser list too, marked as started from Telegram
    listed = _client("u1").get("/api/v1/teams/").json()["teams"]
    assert any(t["id"] == team["id"] and t["origin"] == "telegram" for t in listed)
    # plan ready → Hermes gets the plan card for the chat
    target = teams_utils.HermesTarget("http://hermes", {}, "u1")
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": PLAN}
    asyncio.run(teams_utils._plan_job(row, target, "", None))
    notice = next(c for c in hermes.calls if c[2] == "/notify")
    assert notice[3]["event"] == "plan_ready" and notice[3]["team"]["plan"]["title"] == "计算器设计"
    assert notice[3]["origin"]["chat_id"] == "5550001"
    got = client.get(f"/api/v1/teams/hermes/teams/{team['id']}", headers=h).json()
    assert got["status"] == "plan_ready" and got["plan"]["tasks"][0]["key"] == "T1"
    # approve from Telegram: same start, origin handed to Hermes for the team's notices
    hermes.responses[("POST", "")] = {"board": "halo-tg", "created": True, "tasks": {}}
    approved = client.post(f"/api/v1/teams/hermes/teams/{team['id']}/approve", headers=h)
    assert approved.status_code == 200 and approved.json()["status"] == "running"
    start = next(c for c in hermes.calls if c[1] == "POST" and c[2] == "")
    assert start[3]["origin"]["platform"] == "telegram"
    assert client.post(f"/api/v1/teams/hermes/teams/{team['id']}/approve", headers=h).status_code == 409
    assert client.post(f"/api/v1/teams/hermes/teams/{team['id']}/cancel", headers=h).status_code == 409


def test_browser_teams_do_not_notify_hermes_about_plans(hermes):
    client = _client("u1")
    team = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "网页里发起"}).json()["id"], "u1")
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": PLAN}
    asyncio.run(teams_utils._plan_job(team, teams_utils.HermesTarget("http://hermes", {}, "u1"), "", None))
    assert not any(c[2] == "/notify" for c in hermes.calls)


def test_hermes_replan_and_cancel_and_other_owners(hermes, monkeypatch):
    client = _hermes_client(monkeypatch, owners=("u1", "u2"))
    team_id = _ready_team(_client("u1"), hermes)
    other = {"X-Hermes-Key": "k", "X-Halo-Owner": "u2"}
    assert client.get(f"/api/v1/teams/hermes/teams/{team_id}", headers=other).status_code == 404
    h = {"X-Hermes-Key": "k", "X-Halo-Owner": "u1"}
    resp = client.post(f"/api/v1/teams/hermes/teams/{team_id}/replan", headers=h, json={"feedback": "加一个评审"})
    assert resp.status_code == 200 and resp.json()["status"] == "planning"
    assert hermes.planned[-1][1] == "加一个评审"
    AgentTeams.update(team_id, "u1", status="plan_ready")
    assert client.post(f"/api/v1/teams/hermes/teams/{team_id}/cancel", headers=h).json()["status"] == "cancelled"


def test_events_pass_the_visible_flag(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    AgentTeams.update(team_id, "u1", status="running", phase="running")
    client.get(f"/api/v1/teams/{team_id}/events?after=3&visible=1")
    client.get(f"/api/v1/teams/{team_id}/events?after=4")
    params = [c[4] for c in hermes.calls if c[2].endswith("/events")]
    assert params[-2] == {"after": 3, "limit": 500, "visible": "1"} and "visible" not in params[-1]


# --- teams on a project ------------------------------------------------------------------------------

def test_project_choice_reaches_the_lead_and_replan_can_change_it(hermes):
    client = _client("u1")
    team = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "给 HaloWebUI 加接口", "project": "/root/HaloWebUI"})
                          .json()["id"], "u1")
    assert team.meta["project"] == "/root/HaloWebUI"
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": {**PLAN, "project": {"path": "/root/HaloWebUI",
                                                                                     "name": "HaloWebUI"}}}
    asyncio.run(teams_utils._plan_job(team, teams_utils.HermesTarget("http://hermes", {}, "u1"), "", None))
    assert next(c for c in hermes.calls if c[2] == "/plan")[3]["project"] == "/root/HaloWebUI"
    got = client.get(f"/api/v1/teams/{team.id}").json()["team"]
    assert got["project"] == {"name": "HaloWebUI", "path": "/root/HaloWebUI"}
    client.post(f"/api/v1/teams/{team.id}/replan", json={"feedback": "", "project": ""})
    assert AgentTeams.get(team.id, "u1").meta["project"] == "none"


def test_change_routes_are_proxied_only_for_running_teams(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    assert client.get(f"/api/v1/teams/{team_id}/changes").status_code == 409
    AgentTeams.update(team_id, "u1", status="running", phase="completed")
    hermes.responses[("GET", "/changes")] = {"project": {"branch": "halo/x"}, "files": []}
    assert client.get(f"/api/v1/teams/{team_id}/changes").json()["project"]["branch"] == "halo/x"
    client.get(f"/api/v1/teams/{team_id}/changes/diff", params={"path": "src/a.py"})
    assert hermes.calls[-1][2].endswith("/changes/diff") and hermes.calls[-1][4] == {"path": "src/a.py"}
    assert client.post(f"/api/v1/teams/{team_id}/changes/push", json={"what": "main"}).status_code == 422
    client.post(f"/api/v1/teams/{team_id}/changes/push", json={"what": "branch"})
    assert hermes.calls[-1][2].endswith("/changes/push") and hermes.calls[-1][3] == {"what": "branch"}
    client.post(f"/api/v1/teams/{team_id}/changes/merge")
    assert hermes.calls[-1][2].endswith("/changes/merge")
    assert _client("u2").post(f"/api/v1/teams/{team_id}/changes/merge").status_code == 404


def test_lead_routes_are_proxied_and_new_work_reopens_a_finished_team(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    assert client.post(f"/api/v1/teams/{team_id}/adjust", json={"text": "加个测试"}).status_code == 409  # not running
    AgentTeams.update(team_id, "u1", status="running", phase="completed", finished_at=int(time.time()))
    hermes.responses[("POST", "/adjust")] = {"id": "abcd1234", "status": "thinking"}
    out = client.post(f"/api/v1/teams/{team_id}/adjust", json={"text": "加个测试"}).json()
    assert out["status"] == "thinking" and hermes.calls[-1][3] == {"text": "加个测试", "actor": "Ace"}
    assert client.post(f"/api/v1/teams/{team_id}/adjust", json={"text": ""}).status_code == 422
    client.post(f"/api/v1/teams/{team_id}/adjust/gaps")
    assert hermes.calls[-1][2].endswith("/adjust/gaps")
    assert client.post(f"/api/v1/teams/{team_id}/change/../apply").status_code == 404
    assert client.post(f"/api/v1/teams/{team_id}/change/abcd1234/explode").status_code == 422
    hermes.responses[("POST", "/change/abcd1234/apply")] = {"applied": True, "reopened": True, "added": ["T4"]}
    assert client.post(f"/api/v1/teams/{team_id}/change/abcd1234/apply").json()["added"] == ["T4"]
    row = AgentTeams.get(team_id, "u1")
    assert row.phase == "running" and row.finished_at is None  # back at work
    client.post(f"/api/v1/teams/{team_id}/change/abcd1234/discard")
    assert hermes.calls[-1][2].endswith("/change/abcd1234/discard")
    client.post(f"/api/v1/teams/{team_id}/tasks/t_1a2b3c4d/diagnosis/apply")
    assert hermes.calls[-1][2].endswith("/tasks/t_1a2b3c4d/diagnosis/apply") and hermes.calls[-1][3] == {"actor": "Ace"}
    assert client.post(f"/api/v1/teams/{team_id}/tasks/t_bad!/diagnosis/apply").status_code == 404
    assert _client("u2").post(f"/api/v1/teams/{team_id}/adjust", json={"text": "x"}).status_code == 404
    # reopened from elsewhere (Telegram): the page reading the live phase clears finished_at too
    AgentTeams.update(team_id, "u1", phase="completed", finished_at=int(time.time()))
    hermes.responses[("GET", team_id)] = {"team": {"phase": "running"}, "tasks": []}
    data = client.get(f"/api/v1/teams/{team_id}").json()
    assert data["team"]["phase"] == "running" and data["team"]["finished_at"] is None


def test_hermes_sync_reads_the_live_phase_after_a_telegram_change(hermes, monkeypatch):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    AgentTeams.update(team_id, "u1", status="running", phase="completed", finished_at=int(time.time()))
    hermes.responses[("GET", team_id)] = {"team": {"phase": "running"}, "tasks": []}
    bare = _hermes_client(monkeypatch)
    assert bare.post(f"/api/v1/teams/hermes/teams/{team_id}/sync",
                     headers={"X-Hermes-Key": "wrong", "X-Halo-Owner": "u1"}).status_code == 401
    out = bare.post(f"/api/v1/teams/hermes/teams/{team_id}/sync", headers={"X-Hermes-Key": "k", "X-Halo-Owner": "u1"})
    assert out.status_code == 200 and out.json()["phase"] == "running"
    assert AgentTeams.get(team_id, "u1").finished_at is None
