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


def test_edit_plan_changes_a_members_model_without_touching_its_runner(hermes):
    client = _client("u1")
    team_id = _ready_team(client, hermes)
    members = [{**PLAN["members"][0], "model": "claude-chat", "model_source": "lead", "model_recommended": "claude-chat"},
               {**PLAN["members"][1], "executor_source": "goal", "model": "gpt-chat", "model_source": "default",
                "model_recommended": "gpt-chat"}]
    AgentTeams.update(team_id, "u1", plan={**PLAN, "members": members})
    resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "spec-writer", "model": "deepseek-chat"}]})
    assert resp.status_code == 200, resp.text
    sent = next(c for c in hermes.calls if c[2] == "/plan/resolve")[3]["plan"]["members"]
    assert (sent[0]["model"], sent[0]["model_source"], sent[0]["model_recommended"]) == ("deepseek-chat", "user", "claude-chat")
    assert sent[0]["executor"] == "hermes" and "executor_source" not in PLAN["members"][0]  # runner untouched
    assert sent[1]["executor_source"] == "goal" and sent[1]["model"] == "gpt-chat"
    stored = AgentTeams.get(team_id, "u1").plan["members"][0]
    assert stored["model"] == "deepseek-chat" and stored["model_source"] == "user"
    # back to the lead's recommendation
    resp = client.put(f"/api/v1/teams/{team_id}/plan", json={"members": [{"name": "spec-writer", "model_source": "auto"}]})
    stored = AgentTeams.get(team_id, "u1").plan["members"][0]
    assert (stored["model"], stored["model_source"]) == ("claude-chat", "lead")
    assert client.put(f"/api/v1/teams/{team_id}/plan",
                      json={"members": [{"name": "spec-writer", "model": "x" * 81}]}).status_code == 422


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

    # Finished teams are not asked again once the lead is done with them (result written and checked).
    del hermes.fail[("GET", team_id)]
    hermes.responses[("GET", team_id)] = {"team": {"phase": "completed", "conclusion": {
        "status": "ready", "acceptance": {"status": "ready", "verdict": "met"}}}, "tasks": [
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


def test_auto_start_skips_approval_only_when_every_member_can_run(hermes, monkeypatch):
    client = _client("u1")
    created = client.post("/api/v1/teams/", json={"goal": "直接开始的目标", "auto_start": True}).json()
    assert created["auto_start"] is True
    team = AgentTeams.get(created["id"], "u1")
    target = teams_utils.HermesTarget("http://hermes", {}, "u1")
    runnable = {**PLAN, "members": [{**m, "runner": "hermes"} for m in PLAN["members"]]}
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": runnable}
    hermes.responses[("POST", "")] = {"board": "halo-auto", "created": True, "tasks": {}}
    asyncio.run(teams_utils._plan_job(team, target, "", None))
    row = AgentTeams.get(team.id, "u1")
    assert row.status == "running" and row.board == "halo-auto" and row.approved_at
    assert any(c[1] == "POST" and c[2] == "" and c[3]["team_id"] == team.id for c in hermes.calls)

    # a member with no runner available: the plan waits for the user, as without auto-start
    team2 = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "目标二", "auto_start": True}).json()["id"], "u1")
    down = {**PLAN, "members": [{**PLAN["members"][0], "runner": None}, {**PLAN["members"][1], "runner": "hermes"}]}
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": down}
    asyncio.run(teams_utils._plan_job(team2, target, "", None))
    assert AgentTeams.get(team2.id, "u1").status == "plan_ready"

    # without auto_start nothing starts on its own
    team3 = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "目标三"}).json()["id"], "u1")
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": runnable}
    asyncio.run(teams_utils._plan_job(team3, target, "", None))
    assert AgentTeams.get(team3.id, "u1").status == "plan_ready"

    # a start that fails is recorded, not a fake running state; Telegram gets the outcome
    team4 = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "目标四", "auto_start": True}).json()["id"], "u1")
    AgentTeams.update(team4.id, "u1", meta={**(team4.meta or {}), "origin": {"platform": "telegram", "chat_id": "5"}})
    team4 = AgentTeams.get(team4.id, "u1")
    hermes.fail[("POST", "")] = (502, "Hermes 不可用")
    asyncio.run(teams_utils._plan_job(team4, target, "", None))
    row4 = AgentTeams.get(team4.id, "u1")
    assert row4.status == "start_failed" and "启动失败" in row4.error
    notice = [c for c in hermes.calls if c[2] == "/notify"][-1]
    assert notice[3]["event"] == "start_failed"


# --- where the conclusion goes: the chat, a follow-up chat, the knowledge base ------------------------

CONCLUSION = {
    "status": "ready",
    "markdown": "# 结论\n\n见图：\n![走势](charts/a.png)\n\n/root/work/agent-teams/halo-x/charts/b.png\n\n"
                "[外链](https://example.com/x) [报告](report.md#part)\n\n```\n![原样](raw.png)\n```",
    "entry": {"status": "ready", "generated_at": 1700000123, "model": "gpt-chat",
              "acceptance": {"status": "ready", "verdict": "partial", "summary": "少一张图",
                             "gaps": [{"title": "补图", "detail": "缺月度图"}]}},
    "workspace": "/root/work/agent-teams/halo-x",
    "files": [{"path": "charts/a.png"}, {"path": "charts/b.png"}, {"path": "report.md"}],
    "tasks": [],
}


def _finished_team(client, hermes, user_id="u1", chat_id=None):
    team_id = _ready_team(client, hermes, user_id)
    AgentTeams.update(team_id, user_id, status="running", phase="completed", finished_at=int(time.time()),
                      chat_id=chat_id)
    hermes.responses[("GET", "/conclusion")] = CONCLUSION
    hermes.responses[("GET", team_id)] = {"team": {"phase": "completed"}, "tasks": []}
    return team_id


def test_the_conclusion_goes_into_the_chat_the_team_came_from(hermes, monkeypatch):
    from open_webui.utils import hermes_notify

    shown = []

    async def show(request, **kwargs):
        shown.append(kwargs)
        return {"status": True, "chat_id": kwargs["chat_id"], "duplicate": len(shown) > 1}

    monkeypatch.setattr(hermes_notify, "show_notification_report", show)
    monkeypatch.setattr(teams_router.Chats, "get_chat_by_id_and_user_id",
                        lambda chat_id, user_id: object() if chat_id == "chat-1" and user_id == "u1" else None)
    from open_webui.utils import agent_team_outputs as outputs

    monkeypatch.setattr(outputs.Chats, "get_chat_by_id_and_user_id",
                        lambda chat_id, user_id: object() if chat_id == "chat-1" and user_id == "u1" else None)
    client = _client("u1")
    team_id = _finished_team(client, hermes, chat_id="chat-1")
    bare = _hermes_client(monkeypatch)
    h = {"X-Hermes-Key": "k", "X-Halo-Owner": "u1"}
    out = bare.post(f"/api/v1/teams/hermes/teams/{team_id}/concluded", headers=h, json={"telegram": True})
    assert out.status_code == 200 and out.json() == {"posted": True, "chat_id": "chat-1", "duplicate": False}
    call = shown[0]
    assert call["chat_id"] == "chat-1" and call["source"] == "team" and call["run_id"] == f"team:{team_id}:1700000123"
    assert call["push"] is False and call["design"] is False and call["quiet"] is False  # Telegram already told them
    assert call["max_chars"] >= 60000  # the complete result, not a 20000-char report
    content = call["content"]
    assert f"](/api/v1/teams/{team_id}/files/charts/a.png)" in content
    assert f"![charts/b.png](/api/v1/teams/{team_id}/files/charts/b.png)" in content  # a bare path of a known image
    assert "(https://example.com/x)" in content and f"(/api/v1/teams/{team_id}/files/report.md#part)" in content
    assert "![原样](raw.png)" in content  # code blocks stay as written
    assert "负责人验收：部分达成" in content and "**补图**：缺月度图" in content
    assert f"(/teams/{team_id}/conclusion)" in content
    assert "/root/work/agent-teams/halo-x" in call["notice"] and "计算器设计" in call["notice"]
    team = client.get(f"/api/v1/teams/{team_id}").json()["team"]
    assert team["outputs"]["chat_posted"] == {"generated_at": 1700000123}
    # the same version again: the chat dedups it; without Telegram the away push may go out
    bare.post(f"/api/v1/teams/hermes/teams/{team_id}/concluded", headers=h, json={})
    assert shown[1]["push"] is True
    # a team with no chat, or whose chat is gone: nothing to post
    lone = _finished_team(client, hermes)
    assert bare.post(f"/api/v1/teams/hermes/teams/{lone}/concluded", headers=h, json={}).json()["posted"] is False
    gone = _finished_team(client, hermes, chat_id="deleted-chat")
    assert bare.post(f"/api/v1/teams/hermes/teams/{gone}/concluded", headers=h, json={}).json()["reason"] == "chat gone"
    assert len(shown) == 2
    # not the owner's team: 404; a busy chat: 409 so Hermes tries again later
    other = _hermes_client(monkeypatch, owners=("u1", "u2"))
    assert other.post(f"/api/v1/teams/hermes/teams/{team_id}/concluded",
                      headers={"X-Hermes-Key": "k", "X-Halo-Owner": "u2"}, json={}).status_code == 404

    async def busy(request, **kwargs):
        raise hermes_notify.HermesNotifyError(409, "chat is busy with another run; retry later")

    monkeypatch.setattr(hermes_notify, "show_notification_report", busy)
    assert bare.post(f"/api/v1/teams/hermes/teams/{team_id}/concluded", headers=h, json={}).status_code == 409


def test_a_long_complete_result_goes_into_the_chat_whole(hermes):
    from open_webui.utils import agent_team_outputs as outputs

    client = _client("u1")
    team = AgentTeams.get(_finished_team(client, hermes, chat_id="chat-1"), "u1")
    body = "# 科学戒烟行动指南\n\n" + "完整的一句话。" * 6000  # ~42 000 characters
    content = outputs.chat_content(team, {**CONCLUSION, "markdown": body})
    assert content.count("完整的一句话。") == 6000 and "结果较长" not in content
    assert len(content) <= outputs.CHAT_POST_MAX_CHARS
    huge = outputs.chat_content(team, {**CONCLUSION, "markdown": "长" * 90000})
    assert "结果较长" in huge and len(huge) <= outputs.CHAT_POST_MAX_CHARS
    assert "完整结果" in outputs.notice_text(team, CONCLUSION)


def test_follow_up_opens_a_new_chat_with_the_conclusion_for_a_team_without_one(hermes, monkeypatch):
    from open_webui.models.chats import Chats
    from open_webui.utils import hermes_sessions

    async def model(request, user, model_id=None):
        return {"id": "conn.hermes-agent", "selection_id": "modelref::openai::personal::id:conn::hermes-agent",
                "name": "Hermes", "model_ref": {"provider": "openai", "connection_id": "conn"}}

    monkeypatch.setattr(hermes_sessions, "resolve_hermes_model", model)
    from open_webui.utils import hermes_notify

    monkeypatch.setattr(hermes_notify.Users, "get_user_by_id", lambda uid: _User(uid))
    client = _client("u1")
    team_id = _finished_team(client, hermes)
    out = client.post(f"/api/v1/teams/{team_id}/conclusion/chat")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["created"] is True and body["posted"] is True
    chat = Chats.get_chat_by_id_and_user_id(body["chat_id"], "u1")
    assert chat is not None and chat.title == "计算器设计"
    history = chat.chat["history"]
    reply = history["messages"][history["currentId"]]
    notice = history["messages"][reply["parentId"]]
    assert notice["role"] == "user" and notice["hermes_notice"] == {"source": "team", "run_id": f"team:{team_id}:1700000123"}
    assert "/root/work/agent-teams/halo-x" in notice["content"]
    assert reply["role"] == "assistant" and reply["done"] is True
    assert reply["model"] == "modelref::openai::personal::id:conn::hermes-agent"
    assert chat.chat["models"] == [reply["model"]] and notice["models"] == [reply["model"]]
    assert reply["model_ref"] == {"provider": "openai", "connection_id": "conn"} and "# 结论" in reply["content"]
    row = AgentTeams.get(team_id, "u1")
    assert row.chat_id == body["chat_id"] and row.meta["chat_posted"]["generated_at"] == 1700000123
    # again: back to the same chat, the conclusion is already there
    again = client.post(f"/api/v1/teams/{team_id}/conclusion/chat").json()
    assert again == {"chat_id": body["chat_id"], "created": False, "posted": False}
    assert len(Chats.get_chat_by_id(body["chat_id"]).chat["history"]["messages"]) == 2
    # no conclusion yet / someone else's team
    hermes.responses[("GET", "/conclusion")] = {"status": "generating", "markdown": "", "entry": {}}
    assert client.post(f"/api/v1/teams/{_finished_team(client, hermes)}/conclusion/chat").status_code == 200
    hermes.responses[("GET", "/conclusion")] = {"status": "none", "markdown": "", "entry": {}}
    fresh = _ready_team(client, hermes)
    AgentTeams.update(fresh, "u1", status="running", phase="completed")
    assert client.post(f"/api/v1/teams/{fresh}/conclusion/chat").status_code == 409
    assert _client("u2").post(f"/api/v1/teams/{team_id}/conclusion/chat").status_code == 404


def test_saving_the_conclusion_to_the_knowledge_base(hermes, monkeypatch):
    from open_webui.models.knowledge import Knowledges
    from open_webui.routers import files as files_router
    from open_webui.routers import knowledge as knowledge_router

    uploads, removed = [], []

    class Stored:
        def __init__(self, id):
            self.id = id

    def upload(request, file, user=None, file_metadata=None, process=True, processing_mode=None):
        uploads.append((file.filename, file.content_type, file.file.read().decode(), file_metadata, process))
        return Stored(f"file-{len(uploads)}")

    def add(request, id, form_data, user=None):
        kb = Knowledges.get_knowledge_by_id(id)
        data = dict(kb.data or {})
        data["file_ids"] = [*(data.get("file_ids") or []), form_data.file_id]
        Knowledges.update_knowledge_data_by_id(id=id, data=data)

    def remove(id, form_data, user=None):
        removed.append(form_data.file_id)
        kb = Knowledges.get_knowledge_by_id(id)
        data = dict(kb.data or {})
        data["file_ids"] = [f for f in data.get("file_ids") or [] if f != form_data.file_id]
        Knowledges.update_knowledge_data_by_id(id=id, data=data)

    monkeypatch.setattr(files_router, "upload_file", upload)
    monkeypatch.setattr(knowledge_router, "add_file_to_knowledge_by_id", add)
    monkeypatch.setattr(knowledge_router, "remove_file_from_knowledge_by_id", remove)
    client = _client("u-kb")
    team_id = _finished_team(client, hermes, "u-kb")
    out = client.post(f"/api/v1/teams/{team_id}/conclusion/knowledge")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["knowledge_name"] == "协作结论" and body["file_id"] == "file-1" and body["duplicate"] is False
    kb = Knowledges.get_knowledge_by_id(body["knowledge_id"])
    assert kb.user_id == "u-kb" and kb.access_control == {}  # private, not shared
    name, ctype, text, meta, process = uploads[0]
    assert name == "计算器设计 · 结论.md" and ctype == "text/markdown" and meta == {"agent_team": team_id} and not process
    assert text.startswith("# 计算器设计 · 结论") and "设计一个计算器" in text and "# 结论" in text
    assert client.get(f"/api/v1/teams/{team_id}").json()["team"]["outputs"]["knowledge"] == {
        "id": kb.id, "generated_at": 1700000123}
    # the same version again: nothing new
    again = client.post(f"/api/v1/teams/{team_id}/conclusion/knowledge").json()
    assert again["duplicate"] is True and len(uploads) == 1
    # a rewritten conclusion replaces the team's file in the same base
    hermes.responses[("GET", "/conclusion")] = {**CONCLUSION, "entry": {**CONCLUSION["entry"], "generated_at": 1700000999}}
    newer = client.post(f"/api/v1/teams/{team_id}/conclusion/knowledge").json()
    assert newer["knowledge_id"] == kb.id and newer["file_id"] == "file-2" and newer["replaced"] is True
    assert removed == ["file-1"] and Knowledges.get_knowledge_by_id(kb.id).data["file_ids"] == ["file-2"]
    # another team of the same user goes into the same base; from Telegram too
    other = _finished_team(client, hermes, "u-kb")
    bare = _hermes_client(monkeypatch, owners=("u-kb",))
    tg = bare.post(f"/api/v1/teams/hermes/teams/{other}/knowledge", headers={"X-Hermes-Key": "k", "X-Halo-Owner": "u-kb"})
    assert tg.status_code == 200 and tg.json()["knowledge_id"] == kb.id
    assert Knowledges.get_knowledge_by_id(kb.id).data["file_ids"] == ["file-2", "file-3"]


# --- stage: where the team is, what happens now, how long it may still take ----------------------

def test_every_stage_says_where_the_team_is_and_how_long_it_may_take(hermes):
    client = _client("u1")
    team_id = client.post("/api/v1/teams/", json={"goal": "调研三个看板工具"}).json()["id"]

    def listed():
        return next(t for t in client.get("/api/v1/teams/").json()["teams"] if t["id"] == team_id)

    # planning: the lead's current step on Hermes and how long plans take there
    hermes.responses[("GET", "/plan/progress")] = {
        "progress": {"step": "model", "text": "负责人（gpt-chat）在理解目标、挑选成员、拆分带依赖的任务",
                     "model": "gpt-chat", "attempt": 1},
        "typical": {"median": 40, "p75": 70, "basis": "本机最近 12 次"}}
    stage = client.get(f"/api/v1/teams/{team_id}").json()["stage"]
    assert stage["key"] == "planning" and "gpt-chat" in stage["now"] and stage["model"] == "gpt-chat"
    assert 0 < stage["eta"]["seconds"] <= 40 and stage["eta"]["high"] >= stage["eta"]["seconds"]
    assert "本机最近 12 次" in stage["eta"]["basis"]
    assert [s["state"] for s in stage["steps"]] == ["active", "pending", "pending", "pending", "pending"]
    assert [c for c in hermes.calls if c[2] == "/plan/progress"][-1][4] == {"team_id": team_id}
    assert listed()["stage"]["key"] == "planning"
    # Hermes does not answer: the stage still says what is going on, on typical numbers
    hermes.fail[("GET", "/plan/progress")] = (502, "x")
    stage = client.get(f"/api/v1/teams/{team_id}").json()["stage"]
    assert stage["key"] == "planning" and stage["now"] and stage["eta"]["seconds"] > 0
    hermes.fail.clear()

    # plan ready: waiting for you, and how long it takes once approved
    AgentTeams.update(team_id, "u1", status="plan_ready",
                      plan={**PLAN, "estimate": {"seconds": 540, "high": 760, "basis": "按本机最近 8 次 hermes 调研任务的用时估算"}})
    stage = client.get(f"/api/v1/teams/{team_id}").json()["stage"]
    assert stage["key"] == "approval" and stage["after_approval"]["seconds"] == 540
    assert [s["state"] for s in stage["steps"]][:2] == ["done", "active"]
    assert listed()["stage"]["after_approval"] == 540 and listed()["stage"]["after_approval_high"] == 760

    # running: Hermes' own stage, stamped with the snapshot's time so the page can count down
    AgentTeams.update(team_id, "u1", status="running", phase="running")
    hermes.responses[("GET", team_id)] = {
        "team": {"phase": "running", "stage": {"key": "running", "label": "成员执行中", "now": "#T1 researcher：搜索 · 看板工具",
                                               "eta": {"seconds": 300, "high": 420, "basis": "按…"}}},
        "tasks": [], "generated_at": 1790000000}
    stage = client.get(f"/api/v1/teams/{team_id}").json()["stage"]
    assert stage["key"] == "running" and stage["at"] == 1790000000 and stage["eta"]["seconds"] == 300
    brief = listed()["stage"]
    assert brief["now"].startswith("#T1") and brief["eta"] == 300 and brief["eta_high"] == 420

    # just finished: the list still reads it while the lead writes and checks the result
    hermes.responses[("GET", team_id)] = {
        "team": {"phase": "completed", "conclusion": {"status": "generating"},
                 "stage": {"key": "concluding", "label": "整理完整结果", "now": "负责人在整合",
                           "eta": {"seconds": 30, "high": 50}}},
        "tasks": [], "generated_at": 1790000100}
    AgentTeams.update(team_id, "u1", phase="completed", finished_at=int(time.time()))
    assert listed()["stage"]["key"] == "concluding" and listed()["stage"]["key"] == "concluding"
    hermes.responses[("GET", team_id)] = {
        "team": {"phase": "completed", "conclusion": {"status": "ready", "acceptance": {"status": "ready"}},
                 "stage": {"key": "done", "label": "已完成", "now": "完整结果已经整理好"}},
        "tasks": [], "generated_at": 1790000200}
    assert listed()["stage"]["key"] == "done"
    mine = lambda: sum(1 for c in hermes.calls if c[2] == f"/{team_id}")  # noqa: E731
    calls = mine()
    assert "stage" not in listed() and mine() == calls  # settled: not asked again


def test_a_plan_that_draws_takes_the_users_own_image_templates_along(hermes):
    from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems

    ImageStudioItems.upsert_items("u-img", [
        ImageStudioItemForm(id="halo_hand_v1_auto_style", kind="template", data={
            "name": "手绘万能图 · 自动选画风与画幅", "tags": ["图解"],
            "config": {"prompt": "请把下面的内容画成一张手绘信息图。\n\n内容：", "aspectRatio": "3:2", "size": "1536x1024"}}),
        ImageStudioItemForm(id="no-prompt", kind="template", data={"name": "空模板", "config": {}}),
        ImageStudioItemForm(id="g1", kind="gallery", data={"name": "一张旧图", "config": {"prompt": "x"}}),
    ])
    ImageStudioItems.upsert_items("u-other", [ImageStudioItemForm(id="theirs", kind="template", data={
        "name": "别人的模板", "config": {"prompt": "y"}})])
    client = _client("u-img")
    drawing = {**PLAN, "members": [*PLAN["members"], {"name": "illustrator", "role": "插画师", "kind": "image",
                                                    "executor": "hermes"}]}
    hermes.responses[("POST", "")] = {"board": "halo-img", "created": True, "tasks": {}}
    team_id = client.post("/api/v1/teams/", json={"goal": "画一张图解"}).json()["id"]
    AgentTeams.update(team_id, "u-img", status="plan_ready", plan=drawing, title="图解")
    assert client.post(f"/api/v1/teams/{team_id}/approve").status_code == 200
    body = [c for c in hermes.calls if c[1] == "POST" and c[2] == ""][-1][3]
    assert [t["name"] for t in body["image_templates"]] == ["手绘万能图 · 自动选画风与画幅"]
    assert body["image_templates"][0]["prompt"].endswith("内容：") and body["image_templates"][0]["aspect"] == "3:2"
    # a plan that does not draw sends none
    plain = client.post("/api/v1/teams/", json={"goal": "写个说明"}).json()["id"]
    AgentTeams.update(plain, "u-img", status="plan_ready", plan=PLAN, title="说明")
    assert client.post(f"/api/v1/teams/{plain}/approve").status_code == 200
    body = [c for c in hermes.calls if c[1] == "POST" and c[2] == ""][-1][3]
    assert "image_templates" not in body
    # every team takes the template its result is drawn in on its own once written: 「手绘万能图」
    assert body["conclusion_template"]["id"] == "halo_hand_v1_auto_style"
    assert body["conclusion_template"]["prompt"].endswith("内容：") and body["conclusion_template"]["aspect"] == "3:2"


def test_the_result_picture_template_is_found_by_name_and_left_out_without_one(hermes):
    from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems

    ImageStudioItems.upsert_items("u-pic", [
        ImageStudioItemForm(id="把结论生成图片", kind="template", data={
            "name": "把结论生成图片", "config": {"prompt": "结论图。\n\n内容：", "aspectRatio": "1:1"}}),
        ImageStudioItemForm(id="copy-1", kind="template", data={
            "name": "手绘万能图（我的副本）", "config": {"prompt": "手绘。\n\n内容：", "aspectRatio": "3:2"}}),
    ])
    hermes.responses[("POST", "")] = {"board": "halo-pic", "created": True, "tasks": {}}
    for user, expected in (("u-pic", "手绘万能图（我的副本）"), ("u-none", None)):
        client = _client(user)
        team_id = client.post("/api/v1/teams/", json={"goal": "写个说明"}).json()["id"]
        AgentTeams.update(team_id, user, status="plan_ready", plan=PLAN, title="说明")
        assert client.post(f"/api/v1/teams/{team_id}/approve").status_code == 200
        body = [c for c in hermes.calls if c[1] == "POST" and c[2] == ""][-1][3]
        assert (body.get("conclusion_template") or {}).get("name") == expected


def test_the_result_can_be_drawn_in_one_of_the_users_image_templates(hermes):
    from open_webui.models.image_studio import ImageStudioItemForm, ImageStudioItems

    ImageStudioItems.upsert_items("u-draw", [ImageStudioItemForm(id="halo_daily_v2_knowledge_card", kind="template", data={
        "name": "知识卡片 · 小红书封面", "tags": ["社交媒体"],
        "config": {"prompt": "做成一张竖版知识卡片。\n\n内容：", "aspectRatio": "2:3", "size": "1024x1536"}})])
    client = _client("u-draw")
    hermes.responses[("GET", "/meta")] = {"lead": {"model": "gpt-chat"}}
    meta = client.get("/api/v1/teams/meta").json()
    assert meta["image_templates"] == [{"id": "halo_daily_v2_knowledge_card", "name": "知识卡片 · 小红书封面",
                                        "tags": ["社交媒体"], "aspect": "2:3"}]  # names only, no prompts
    team_id = _ready_team(client, hermes, "u-draw")
    AgentTeams.update(team_id, "u-draw", status="running", phase="completed")
    hermes.responses[("POST", "/conclusion/illustrate")] = {"status": "generating", "template": "知识卡片 · 小红书封面"}
    out = client.post(f"/api/v1/teams/{team_id}/conclusion/illustrate", json={"template_id": "halo_daily_v2_knowledge_card"})
    assert out.status_code == 200 and out.json()["status"] == "generating"
    call = [c for c in hermes.calls if c[2] == f"/{team_id}/conclusion/illustrate"][-1]
    assert call[3]["template"]["prompt"].endswith("内容：") and call[3]["template"]["aspect"] == "2:3"
    # no template: Hermes' own hand-drawn infographic; someone else's / unknown template: 404
    client.post(f"/api/v1/teams/{team_id}/conclusion/illustrate", json={})
    assert [c for c in hermes.calls if c[2] == f"/{team_id}/conclusion/illustrate"][-1][3] == {}
    assert client.post(f"/api/v1/teams/{team_id}/conclusion/illustrate", json={"template_id": "theirs"}).status_code == 404


# --- 派发方式「协作台」: a chat message becomes a team ------------------------------------------------

def test_a_chat_message_becomes_a_team_with_what_was_said_before(hermes, monkeypatch):
    from open_webui.utils import agent_team_dispatch as dispatch

    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "我在考虑戒烟"},
        {"role": "assistant", "content": [{"type": "text", "text": "可以先定一个戒烟日。"}]},
        {"role": "user", "content": "帮我做一份完整的戒烟计划，配一张激励海报"},
    ]
    goal, ask = dispatch.goal_from(messages)
    assert ask == "帮我做一份完整的戒烟计划，配一张激励海报"
    assert goal.startswith(ask) and "用户：我在考虑戒烟" in goal and "Hermes：可以先定一个戒烟日。" in goal
    assert goal.index("我在考虑戒烟") < goal.index("可以先定一个戒烟日")  # oldest first
    long = [{"role": "user", "content": "旧" * 5000}, {"role": "user", "content": "新问题"}]
    assert len(dispatch.goal_from(long)[0]) < 1400  # one earlier turn is cut, not the whole goal
    assert dispatch.goal_from([{"role": "assistant", "content": "x"}]) == ("", "")

    emitted, saved, titles, planned = [], [], {"chat-9": "新对话"}, []
    jobs = []

    async def emitter(event):
        emitted.append(event)

    monkeypatch.setattr("open_webui.socket.main.get_event_emitter", lambda metadata: emitter)
    monkeypatch.setattr("open_webui.tasks.create_task", lambda coro, id=None, owner_id=None: (jobs.append(coro) or "task-1", None))
    monkeypatch.setattr(dispatch, "start_planning", lambda team, target: planned.append(team))
    monkeypatch.setattr(dispatch, "hermes_target", teams_router.hermes_target)
    monkeypatch.setattr(dispatch.Chats, "upsert_message_to_chat_by_id_and_message_id",
                        lambda chat_id, message_id, fields: saved.append((chat_id, message_id, fields)))
    monkeypatch.setattr(dispatch.Chats, "get_chat_title_by_id", lambda chat_id: titles.get(chat_id))
    monkeypatch.setattr(dispatch.Chats, "update_chat_title_by_id",
                        lambda chat_id, title: titles.__setitem__(chat_id, title))
    monkeypatch.setattr(dispatch, "attachments", lambda metadata, user: [{"name": "体检报告.pdf", "path": "/data/uploads/a.pdf"}])
    user = _User("u-chat")
    out = asyncio.run(dispatch.run_team_dispatch(None, {"messages": messages}, user,
                                                 {"chat_id": "chat-9", "message_id": "m-2"}, "hermes-agent"))
    assert out == {"status": True, "task_id": "task-1"}
    asyncio.run(jobs[0])
    team = planned[0]
    assert team.chat_id == "chat-9" and team.goal.startswith("帮我做一份完整的戒烟计划")
    assert team.meta["auto_start"] is True and team.meta["inputs"] == [{"name": "体检报告.pdf", "path": "/data/uploads/a.pdf"}]
    chat_id, message_id, fields = saved[0]
    assert (chat_id, message_id) == ("chat-9", "m-2") and fields["done"] is True
    assert fields["team_dispatch"] == {"team_id": team.id} and "已交给协作台" in fields["content"]
    assert "附带的 1 个文件" in fields["content"]
    assert titles["chat-9"] == team.title  # a new chat is named after its team
    event = emitted[0]
    assert event["type"] == "chat:completion" and event["data"]["team_dispatch"] == {"team_id": team.id}
    assert event["data"]["title"] == team.title

    # no Hermes connection: the reply says so, no team
    async def no_target(request, user):
        raise teams_utils.TeamsError(403, "你的账号没有可用的 Hermes 连接，不能使用协作台")

    monkeypatch.setattr(dispatch, "hermes_target", no_target)
    saved.clear()
    jobs.clear()
    asyncio.run(dispatch.run_team_dispatch(None, {"messages": messages}, user,
                                           {"chat_id": "chat-9", "message_id": "m-3"}, "hermes-agent"))
    asyncio.run(jobs[0])
    fields = saved[0][2]
    assert "team_dispatch" not in fields and "没有可用的 Hermes 连接" in fields["content"] and fields["error"]


def test_files_given_with_the_goal_reach_the_lead_and_the_team(hermes, monkeypatch):
    from open_webui.env import DATA_DIR
    from open_webui.models.files import FileForm, Files
    from open_webui.utils import hermes_agent

    monkeypatch.setenv("HERMES_AGENT_HOST_DATA_DIR", "/srv/halowebui/data")
    hermes_agent._HOST_DATA_DIR_CACHE.clear()
    data_dir = str(DATA_DIR).rstrip("/")
    Files.insert_new_file("u-files", FileForm(id="f-pdf", filename="体检报告.pdf", path=f"{data_dir}/uploads/f-pdf_体检报告.pdf",
                                              meta={"content_type": "application/pdf"}))
    Files.insert_new_file("u-files", FileForm(id="f-img", filename="舌苔.png", path=f"{data_dir}/uploads/f-img_舌苔.png",
                                              meta={"content_type": "image/png"}))
    Files.insert_new_file("u-other", FileForm(id="f-theirs", filename="x.txt", path=f"{data_dir}/uploads/x.txt"))
    client = _client("u-files")
    # a file that is not there is refused (404), nothing is created (another user's file is refused the
    # same way for non-admins, see _attachment_host_paths)
    before = len(AgentTeams.list_for_user("u-files"))
    assert client.post("/api/v1/teams/", json={"goal": "看看", "files": ["f-missing"]}).status_code == 404
    assert len(AgentTeams.list_for_user("u-files")) == before
    team = client.post("/api/v1/teams/", json={"goal": "根据体检报告和照片给饮食建议", "files": ["f-pdf", "f-img"]}).json()
    assert team["inputs"] == ["体检报告.pdf", "舌苔.png"]  # images too
    row = AgentTeams.get(team["id"], "u-files")
    assert row.meta["inputs"] == [{"name": "体检报告.pdf", "path": "/srv/halowebui/data/uploads/f-pdf_体检报告.pdf"},
                                  {"name": "舌苔.png", "path": "/srv/halowebui/data/uploads/f-img_舌苔.png"}]
    # the lead plans knowing their names; the start hands Hermes the files to copy
    hermes.responses[("POST", "/plan")] = {"ok": True, "plan": PLAN}
    asyncio.run(teams_utils._plan_job(row, teams_utils.HermesTarget("http://h", {}, "u-files"), "", None))
    plan_call = [c for c in hermes.calls if c[2] == "/plan"][-1]
    assert plan_call[3]["inputs"] == ["体检报告.pdf", "舌苔.png"]
    hermes.responses[("POST", "")] = {"board": "halo-f", "created": True, "tasks": {}}
    assert client.post(f"/api/v1/teams/{team['id']}/approve").status_code == 200
    body = [c for c in hermes.calls if c[1] == "POST" and c[2] == ""][-1][3]
    assert [i["name"] for i in body["inputs"]] == ["体检报告.pdf", "舌苔.png"]
    hermes_agent._HOST_DATA_DIR_CACHE.clear()


def test_a_big_workspace_file_comes_through_whole():
    """A conclusion's picture (megabytes) used to arrive as its first chunk only: a broken image."""
    from aiohttp import web

    body = bytes(range(256)) * (3 * 4096)  # 3 MB

    async def serve_file(request):
        resp = web.StreamResponse(headers={"Content-Type": "image/png"})
        await resp.prepare(request)
        for i in range(0, len(body), 50_000):  # in pieces, like a real network
            await resp.write(body[i:i + 50_000])
            await asyncio.sleep(0)
        await resp.write_eof()
        return resp

    async def run():
        app = web.Application()
        app.router.add_get("/v1/halo-teams/team-1/files/images/big.png", serve_file)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            target = teams_utils.HermesTarget(f"http://127.0.0.1:{port}", {}, "u1")
            return await teams_utils.hermes_file(target, "/team-1/files/images/big.png")
        finally:
            await runner.cleanup()

    data, headers = asyncio.run(run())
    assert len(data) == len(body) and data == body and headers["Content-Type"] == "image/png"
