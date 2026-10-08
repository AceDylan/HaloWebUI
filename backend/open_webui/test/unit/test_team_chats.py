"""Every 协作台 team in the chat history: its own chat (or a card in the chat it came from), the
earlier teams' chats in their place, the lead's name for it, and the sidebar's 协作 mark.

Runs against a throwaway SQLite database (the app's migrations create the schema)."""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-team-chats-test-"))
os.environ.setdefault("DATA_DIR", str(_TMP))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/webui.db")
os.environ.setdefault("WEBUI_SECRET_KEY", "team-chats-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.models.agent_teams import AgentTeams  # noqa: E402
from open_webui.models.chats import ChatForm, Chats  # noqa: E402
from open_webui.routers import teams as teams_router  # noqa: E402
from open_webui.utils import agent_teams as teams_utils  # noqa: E402
from open_webui.utils import team_chats  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402
from open_webui.utils.chat_kinds import chat_kinds  # noqa: E402

MODEL = {"model": "modelref::hermes::hermes-agent", "modelName": "Hermes", "modelIdx": 0}


class _User:
    def __init__(self, id: str):
        self.id = id
        self.name = "Ace"
        self.role = "admin"


@pytest.fixture
def env(monkeypatch):
    events = []
    planned = []

    async def target(request, user):
        return teams_utils.HermesTarget("http://hermes", {"Authorization": "Bearer k"}, str(user.id))

    async def model_info(request, user):
        await asyncio.sleep(0)  # a real lookup yields to the loop: other requests run meanwhile
        return dict(MODEL)

    async def emit(user_id, chat_id, kind, data=None):
        events.append((chat_id, kind))

    async def no_hermes(*args, **kwargs):
        return {}

    monkeypatch.setattr(teams_router, "hermes_target", target)
    monkeypatch.setattr(teams_router, "hermes_call", no_hermes)
    monkeypatch.setattr(teams_utils, "hermes_call", no_hermes)
    monkeypatch.setattr(teams_router, "start_planning",
                        lambda team, target, feedback="", previous=None, access=None: planned.append(team))
    monkeypatch.setattr(team_chats, "hermes_model_info", model_info)
    monkeypatch.setattr(team_chats, "emit_chat_event", emit)
    team_chats._backfill_tried.clear()
    return {"events": events, "planned": planned}


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(teams_router.router, prefix="/api/v1/teams")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def _messages(chat_id: str, user_id: str) -> tuple[dict, list[dict]]:
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    history = chat.chat["history"]
    chain, current = [], history["currentId"]
    while current:
        chain.append(history["messages"][current])
        current = history["messages"][current].get("parentId")
    return chat, list(reversed(chain))


def test_the_users_words_without_the_background_they_came_with():
    assert team_chats.ask_of("做计划\n\n背景（来自对话「出游」）：\n用户：去哪玩？") == "做计划"
    assert team_chats.ask_of("帮我写\n\n（这是在对话里交给协作台的；对话里之前说的，供参考）\n用户：x") == "帮我写"
    assert team_chats.ask_of("  只有目标  ") == "只有目标"
    assert len(team_chats.ask_of("长" * 9000)) == team_chats.ASK_MAX_CHARS + 1


def test_a_team_started_on_its_own_gets_a_chat_in_the_history(env):
    client = _client("tc-1")
    team = client.post("/api/v1/teams/", json={"goal": "调研三个看板工具\n\n背景（来自讨论「选型」）：\n很长的背景"}).json()
    assert team["chat_id"], "the team is linked to its chat at once"
    assert env["planned"][0].chat_id == team["chat_id"]  # planning starts with the chat known
    chat, chain = _messages(team["chat_id"], "tc-1")
    assert chat.title == team["title"] and chat.meta[team_chats.CHAT_META_KEY] == {"team_id": team["id"]}
    ask, card = chain
    assert ask["role"] == "user" and ask["content"] == "调研三个看板工具"
    assert card["role"] == "assistant" and card["done"] is True and card["team_dispatch"] == {"team_id": team["id"]}
    assert card["model"] == MODEL["model"] and "等你批准" in card["content"]
    assert (team["chat_id"], "chat:title") in env["events"]  # the sidebar shows it now
    assert chat_kinds("tc-1", [team["chat_id"]]) == {team["chat_id"]: "team"}
    # a chat of its own, opened by the user later, is the team's: the conclusion goes there
    assert AgentTeams.get(team["id"], "tc-1").chat_id == team["chat_id"]


def test_a_team_started_for_a_chat_shows_up_in_that_chat(env):
    leaf = {"id": "m1", "parentId": None, "childrenIds": ["m2"], "role": "user", "content": "我们聊到这"}
    reply = {"id": "m2", "parentId": "m1", "childrenIds": [], "role": "assistant", "content": "好的",
             "model": "gpt-x", "modelName": "GPT X", "modelIdx": 0, "done": True}
    chat = Chats.insert_new_chat("tc-2", ChatForm(chat={"title": "旧对话", "models": ["gpt-x"],
                                                        "history": {"messages": {"m1": leaf, "m2": reply},
                                                                    "currentId": "m2"}}))
    team = _client("tc-2").post("/api/v1/teams/", json={"goal": "把刚才的方案做出来", "chat_id": chat.id}).json()
    assert team["chat_id"] == chat.id
    stored, chain = _messages(chat.id, "tc-2")
    assert [m["id"] for m in chain[:2]] == ["m1", "m2"] and len(chain) == 4
    assert chain[2]["content"] == "把刚才的方案做出来" and chain[3]["team_dispatch"] == {"team_id": team["id"]}
    assert chain[3]["model"] == "gpt-x"  # signed by the chat's own model
    assert stored.title == "旧对话"
    assert (chat.id, "chat:reload") in env["events"]
    # the same team is not carded twice
    assert team_chats.add_card_to_chat(AgentTeams.get(team["id"], "tc-2"), chat.id) is True
    assert len(_messages(chat.id, "tc-2")[1]) == 4


def test_a_busy_chat_gets_no_card_but_keeps_the_team(env, monkeypatch):
    chat = Chats.insert_new_chat("tc-3", ChatForm(chat={"title": "忙着的对话", "history": {"messages": {}, "currentId": None}}))
    monkeypatch.setattr("open_webui.tasks.list_task_ids_by_chat_id", lambda chat_id, blocks_completion_only=False: ["t1"])
    team = _client("tc-3").post("/api/v1/teams/", json={"goal": "做个东西", "chat_id": chat.id}).json()
    assert team["chat_id"] == chat.id
    assert Chats.get_chat_by_id_and_user_id(chat.id, "tc-3").chat["history"]["messages"] == {}


def test_earlier_teams_get_their_chats_in_their_place(env):
    old = AgentTeams.insert("tc-4", "很久以前的目标", None, "以前的团队")
    AgentTeams.update(old.id, "tc-4", status="running", phase="completed", finished_at=int(time.time()) - 3000)
    created_at = int(time.time()) - 86400 * 3
    from open_webui.internal.db import get_db
    from open_webui.models.agent_teams import AgentTeam

    with get_db() as db:
        db.query(AgentTeam).filter_by(id=old.id).update({"created_at": created_at})
        db.commit()
    client = _client("tc-4")
    listed = client.get("/api/v1/teams/").json()["teams"]
    chat_id = listed[0]["chat_id"]
    assert chat_id and AgentTeams.get(old.id, "tc-4").chat_id == chat_id
    chat, chain = _messages(chat_id, "tc-4")
    assert chat.created_at == created_at and chat.updated_at < int(time.time()) - 1000
    assert chain[0]["content"] == "很久以前的目标" and chain[1]["team_dispatch"] == {"team_id": old.id}
    assert "结果页" in chain[1]["content"]  # not "负责人在制定计划" for a team long done
    # read again: no second chat
    again = client.get("/api/v1/teams/").json()["teams"]
    assert again[0]["chat_id"] == chat_id
    assert len([c for c in Chats.get_chat_title_id_list_by_user_id("tc-4", include_folders=True)]) == 1


def test_a_deleted_chat_stays_deleted(env):
    client = _client("tc-5")
    team = client.post("/api/v1/teams/", json={"goal": "写报告"}).json()
    Chats.delete_chat_by_id(team["chat_id"])
    assert client.get(f"/api/v1/teams/{team['id']}").json()["team"]["chat_id"] is None
    client.get("/api/v1/teams/")
    assert Chats.get_chat_title_id_list_by_user_id("tc-5", include_folders=True) == []


def test_the_chat_takes_the_leads_name_unless_renamed(env, monkeypatch):
    client = _client("tc-6")
    team = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "设计一个计算器"}).json()["id"], "tc-6")
    target = teams_utils.HermesTarget("http://hermes", {}, "tc-6")

    async def plan(*args, **kwargs):
        return {"ok": True, "plan": {"title": "计算器设计", "members": [], "tasks": []}}

    monkeypatch.setattr(teams_utils, "hermes_call", plan)
    asyncio.run(teams_utils._plan_job(team, target, "", None))
    assert Chats.get_chat_title_by_id(team.chat_id) == "计算器设计"

    other = AgentTeams.get(client.post("/api/v1/teams/", json={"goal": "做一个日历"}).json()["id"], "tc-6")
    Chats.update_chat_title_by_id(other.chat_id, "我自己起的名字")
    asyncio.run(teams_utils._plan_job(other, target, "", None))
    assert Chats.get_chat_title_by_id(other.chat_id) == "我自己起的名字"


def test_two_reads_at_once_write_one_chat(env):
    old = AgentTeams.insert("tc-7", "以前的目标", None, "以前的")
    teams = [AgentTeams.get(old.id, "tc-7")]

    async def both():
        return await asyncio.gather(team_chats.backfill(None, _User("tc-7"), teams),
                                    team_chats.backfill(None, _User("tc-7"), teams))

    first, second = asyncio.run(both())
    assert len(Chats.get_chat_title_id_list_by_user_id("tc-7", include_folders=True)) == 1
    assert AgentTeams.get(old.id, "tc-7").chat_id in (first[0].chat_id, second[0].chat_id)


def test_the_team_list_comes_a_page_at_a_time_with_server_filters_and_counts(env):
    from open_webui.internal.db import get_db as _db
    from open_webui.models.agent_teams import AgentTeam

    user = "tc-page"
    made = []
    for n, (status, phase) in enumerate([("plan_ready", None), ("running", "running"), ("running", "completed"),
                                         ("running", "completed"), ("plan_failed", None), ("running", "stopped"),
                                         ("planning", None)]):
        team = AgentTeams.insert(user, f"目标 {n}：{'看板' if n % 2 else '周报'}", None, f"任务 {n}")
        with _db() as db:
            db.query(AgentTeam).filter_by(id=team.id).update(
                {"status": status, "phase": phase, "updated_at": 1_700_000_000 + n, "chat_id": f"chat-{n}"})
            db.commit()
        made.append(team.id)
    client = _client(user)

    first = client.get("/api/v1/teams/?limit=3").json()
    assert [t["id"] for t in first["teams"]] == made[::-1][:3]  # newest first
    assert first["next"] and first["counts"] == {"all": 7, "active": 2, "review": 1, "done": 2, "ended": 2}
    second = client.get(f"/api/v1/teams/?limit=3&before={first['next']}").json()
    third = client.get(f"/api/v1/teams/?limit=3&before={second['next']}").json()
    assert third["next"] is None and second["counts"] is None  # counts come with the first page
    assert [t["id"] for t in first["teams"] + second["teams"] + third["teams"]] == made[::-1]

    done = client.get("/api/v1/teams/?bucket=done").json()
    assert {t["id"] for t in done["teams"]} == {made[2], made[3]} and done["total"] == 2
    ended = client.get("/api/v1/teams/?bucket=ended").json()
    assert {t["id"] for t in ended["teams"]} == {made[4], made[5]}
    searched = client.get("/api/v1/teams/", params={"q": "看板"}).json()
    assert {t["id"] for t in searched["teams"]} == {made[1], made[3], made[5]} and searched["counts"]["all"] == 3

    # the sidebar badge: at work or waiting, plus what changed lately — not the whole history
    with _db() as db:
        db.query(AgentTeam).filter(AgentTeam.id.in_([made[2], made[4]])).update(
            {"updated_at": int(time.time())}, synchronize_session=False)
        db.commit()
    current = client.get("/api/v1/teams/?scope=current").json()
    assert {t["id"] for t in current["teams"]} == {made[0], made[1], made[6], made[2], made[4]}
