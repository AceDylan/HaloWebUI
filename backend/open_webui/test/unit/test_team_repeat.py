"""协作台「再来一次」与定时 (utils/team_repeat.py, the routes in routers/teams.py)."""

import asyncio
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

_TMP = Path(tempfile.mkdtemp(prefix="halo-team-repeat-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "team-repeat-test-secret")
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
from open_webui.models.agent_team_schedules import AgentTeamSchedules  # noqa: E402
from open_webui.models.agent_teams import AgentTeams  # noqa: E402
from open_webui.routers import teams as teams_router  # noqa: E402
from open_webui.utils import agent_teams as teams_utils  # noqa: E402
from open_webui.utils import team_chats  # noqa: E402
from open_webui.utils import team_repeat  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402

PLAN = {
    "title": "每周新闻汇总",
    "members": [{"name": "writer", "role": "编辑", "executor": "hermes", "runner": "hermes"}],
    "tasks": [{"key": "T1", "title": "汇总", "member": "writer", "depends_on": []}],
    "executors": ["hermes"],
    "assistants_applied": {"run_ref": "team:old", "members": {}},
}
SHANGHAI = ZoneInfo("Asia/Shanghai")


class _User:
    def __init__(self, id: str):
        self.id = id
        self.name = "Ace"
        self.role = "admin"


@pytest.fixture
def hermes(monkeypatch):
    calls = []

    async def call(target, method, path, *, json_body=None, params=None, timeout=30):
        calls.append((method, path, json_body))
        if method == "POST" and path == "":
            return {"board": f"halo-{json_body['team_id'][:8]}", "created": True, "tasks": {"T1": "t_1"}}
        return {}

    async def target(request, user):
        return teams_utils.HermesTarget("http://hermes", {}, str(user.id))

    async def attach(request, user, team):
        return team

    monkeypatch.setattr(teams_utils, "hermes_call", call)
    monkeypatch.setattr(team_repeat, "hermes_target", target)
    monkeypatch.setattr(team_chats, "attach", attach)
    monkeypatch.setattr(team_repeat, "_background_request", lambda app: SimpleNamespace(app=app))
    monkeypatch.setattr("open_webui.models.users.Users.get_user_by_id", lambda uid: _User(uid))
    return calls


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(teams_router.router, prefix="/api/v1/teams")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def _source(user_id="u1", **meta):
    team = AgentTeams.insert(user_id, "汇总本周 AI 新闻", None, "新闻", meta={"lead_model": "gpt-chat", **meta})
    return AgentTeams.update(team.id, user_id, status="running", phase="completed", plan=PLAN, title="每周新闻汇总")


def test_migration_created_the_table():
    assert "agent_team_schedule" in sa.inspect(engine).get_table_names()


def test_repeat_makes_a_new_team_with_the_same_plan(hermes):
    source = _source(project="/root/work/x", progress={"done": 1}, chat_posted={"at": 1})
    resp = _client("u1").post(f"/api/v1/teams/{source.id}/repeat", json={})
    assert resp.status_code == 200
    team = resp.json()
    assert team["id"] != source.id and team["status"] == "plan_ready" and team["goal"] == source.goal
    assert team["repeat_of"] == source.id and team["lead_model"] == "gpt-chat"
    stored = AgentTeams.get(team["id"], "u1")
    assert stored.plan["tasks"] == PLAN["tasks"] and stored.plan["assistants_applied"]["run_ref"] == "team:old"
    assert stored.meta["project"] == "/root/work/x" and "progress" not in stored.meta and "chat_posted" not in stored.meta
    assert not [c for c in hermes if c[1] == "/plan"]  # no new planning


def test_repeat_can_start_at_once(hermes):
    source = _source()
    team = _client("u1").post(f"/api/v1/teams/{source.id}/repeat", json={"auto_start": True}).json()
    assert team["status"] == "running" and team["board"].startswith("halo-")
    sent = next(c for c in hermes if c[1] == "")[2]
    assert sent["team_id"] == team["id"] and sent["goal"] == source.goal


def test_repeat_needs_a_plan_and_an_owner(hermes):
    planning = AgentTeams.insert("u1", "x", None, "x")
    assert _client("u1").post(f"/api/v1/teams/{planning.id}/repeat", json={}).status_code == 409
    assert _client("u2").post(f"/api/v1/teams/{_source().id}/repeat", json={}).status_code == 404


def test_next_run_at_daily_weekly_monthly():
    def at(*args):
        return datetime(*args, tzinfo=SHANGHAI).timestamp()

    now = at(2026, 10, 10, 23, 30)  # a Saturday
    daily = SimpleNamespace(freq="daily", time="09:00", weekday=None, day=None, tz="Asia/Shanghai")
    assert team_repeat.next_run_at(daily, now) == at(2026, 10, 11, 9, 0)
    assert team_repeat.next_run_at(daily, at(2026, 10, 11, 8, 59)) == at(2026, 10, 11, 9, 0)
    assert team_repeat.next_run_at(daily, at(2026, 10, 11, 9, 0)) == at(2026, 10, 12, 9, 0)
    monday = SimpleNamespace(freq="weekly", time="09:00", weekday=0, day=None, tz="Asia/Shanghai")
    assert team_repeat.next_run_at(monday, now) == at(2026, 10, 12, 9, 0)
    first = SimpleNamespace(freq="monthly", time="07:30", weekday=None, day=1, tz="Asia/Shanghai")
    assert team_repeat.next_run_at(first, now) == at(2026, 11, 1, 7, 30)
    assert team_repeat.describe(monday) == "每周一 09:00" and team_repeat.describe(first) == "每月 1 号 07:30"


def test_schedule_routes_validate_list_and_go_with_the_team(hermes):
    client = _client("u1")
    source = _source()
    bad = client.put(f"/api/v1/teams/{source.id}/schedule", json={"freq": "weekly", "time": "09:00"})
    assert bad.status_code == 400 and "星期" in bad.json()["detail"]
    assert client.put(f"/api/v1/teams/{source.id}/schedule",
                      json={"freq": "daily", "time": "25:00"}).status_code == 400
    ok = client.put(f"/api/v1/teams/{source.id}/schedule",
                    json={"freq": "weekly", "time": "09:00", "weekday": 0, "tz": "Asia/Shanghai"})
    assert ok.status_code == 200
    schedule = ok.json()["schedule"]
    assert schedule["label"] == "每周一 09:00" and schedule["enabled"] and schedule["next_run_at"]
    assert datetime.fromtimestamp(schedule["next_run_at"], SHANGHAI).weekday() == 0
    listed = client.get("/api/v1/teams/schedules").json()["schedules"]
    assert [s["team"]["id"] for s in listed] == [source.id]
    assert _client("u2").get("/api/v1/teams/schedules").json()["schedules"] == []
    paused = client.put(f"/api/v1/teams/{source.id}/schedule",
                        json={"freq": "weekly", "time": "09:00", "weekday": 0, "enabled": False}).json()["schedule"]
    assert paused["enabled"] is False and paused["next_run_at"] is None
    assert client.delete(f"/api/v1/teams/{source.id}").status_code == 200
    assert AgentTeamSchedules.get_for_team(source.id, "u1") is None


def test_a_due_schedule_starts_one_run_and_skips_while_it_is_at_work(hermes):
    source = _source()
    schedule = AgentTeamSchedules.upsert("u1", source.id, freq="daily", time="09:00", weekday=None, day=None,
                                         tz="Asia/Shanghai", enabled=True, next_run_at=1000)
    started = asyncio.run(team_repeat.run_due_schedules(app=None, now=2000))
    assert started == 1
    after = AgentTeamSchedules.get_for_team(source.id, "u1")
    assert after.next_run_at > 2000 and after.last_run_at == 2000 and after.last_error is None
    run = AgentTeams.get(after.last_team_id, "u1")
    assert run.status == "running" and run.meta["schedule_id"] == schedule.id and run.meta["repeat_of"] == source.id
    # nothing more is due
    assert asyncio.run(team_repeat.run_due_schedules(app=None, now=2001)) == 0
    # the next occurrence comes while that run is still at work: skipped, not piled up
    AgentTeamSchedules.record(schedule.id, next_run_at=3000)
    assert asyncio.run(team_repeat.run_due_schedules(app=None, now=3001)) == 0
    skipped = AgentTeamSchedules.get_for_team(source.id, "u1")
    assert "跳过" in skipped.last_error and skipped.last_team_id == run.id and skipped.next_run_at > 3001
    # once it finished, the next occurrence runs again
    AgentTeams.update(run.id, "u1", phase="completed")
    AgentTeamSchedules.record(schedule.id, next_run_at=4000)
    assert asyncio.run(team_repeat.run_due_schedules(app=None, now=4001)) == 1


def test_a_schedule_whose_team_is_gone_turns_itself_off(hermes):
    source = _source()
    AgentTeamSchedules.upsert("u1", source.id, freq="daily", time="09:00", weekday=None, day=None,
                              tz="Asia/Shanghai", enabled=True, next_run_at=1000)
    AgentTeams.delete(source.id, "u1")
    assert asyncio.run(team_repeat.run_due_schedules(app=None, now=2000)) == 0
    left = AgentTeamSchedules.get_for_team(source.id, "u1")
    assert left.enabled is False and "已删除" in left.last_error


def test_a_repeat_chat_says_it_reuses_the_plan():
    team = AgentTeams.insert("u1", "目标", None, "每周新闻汇总", meta={"repeat_of": "x", "schedule_id": "s", "auto_start": True})
    assert team_chats.card_text(team) == (
        "🤝 协作台「每周新闻汇总」定时：用上次的目标和成员，直接开始。"
        "进度在下面的卡片里实时更新，做完后完整结果会发回这个对话。")
    again = AgentTeams.insert("u1", "目标", None, "新闻", meta={"repeat_of": "x"})
    assert "再来一次" in team_chats.card_text(again) and "等你批准后开始" in team_chats.card_text(again)
    fresh = AgentTeams.insert("u1", "目标", None, "新闻")
    assert "负责人在制定计划" in team_chats.card_text(fresh)
