"""Obsidian archive permissions, completion state and the existing chat reply."""

import asyncio

import pytest
from test_agent_teams import (
    CONCLUSION,
    PLAN,
    AgentTeams,
    _client,
    _finished_team,
    _hermes_client,
    _User,
    get_verified_user,
    hermes,
    teams_router,
    teams_utils,
)

from open_webui.models.chats import Chats
from open_webui.utils import agent_team_outputs as outputs
from open_webui.utils import hermes_notify, hermes_sessions, message_card


@pytest.mark.parametrize("platform", ["web", "telegram", "qqbot"])
@pytest.mark.parametrize("workflow", ["auto", "work"])
@pytest.mark.parametrize("role", ["admin", "user"])
def test_only_admins_can_enable_vault_archive(hermes, monkeypatch, platform, workflow, role):
    owner = _User("u1")
    owner.role = role
    body = {"goal": "验证发布流程", "workflow": workflow, "vault_archive": True}
    if platform == "web":
        client = _client(owner.id)
        client.app.dependency_overrides[get_verified_user] = lambda: owner
        path, headers = "/api/v1/teams", {}
    else:
        client = _hermes_client(monkeypatch)
        monkeypatch.setattr(teams_router.Users, "get_user_by_id", lambda _uid: owner)
        path, headers = "/api/v1/teams/hermes/teams", {"X-Hermes-Key": "k", "X-Halo-Owner": owner.id}
        body["origin"] = {"platform": platform, "chat_id": "test"}
    created = client.post(path + ("/" if platform == "web" else ""), headers=headers, json=body)
    assert created.status_code == 200
    team_id = created.json()["id"]
    AgentTeams.update(team_id, owner.id, status="plan_ready", plan=PLAN)
    approved = client.post(f"{path}/{team_id}/approve", headers=headers)
    assert approved.status_code == 200
    start = next(call[3] for call in hermes.calls if call[1:3] == ("POST", ""))
    assert start["vault_archive"] is (role == "admin")


def test_start_without_assistant_access_looks_up_owner(hermes, monkeypatch):
    client = _client("u1")
    created = client.post("/api/v1/teams/", json={"goal": "检查归档权限"}).json()
    team = AgentTeams.update(created["id"], "u1", status="plan_ready", plan=PLAN)
    monkeypatch.setattr(teams_utils.Users, "get_user_by_id", lambda uid: _User(uid))
    asyncio.run(teams_utils.start_team(team, teams_utils.HermesTarget("http://hermes", {}, "u1")))
    assert hermes.calls[-1][3]["vault_archive"] is True


@pytest.mark.parametrize("status,expected", [("pending", False), ("running", False), ("saved", True),
                                             ("skipped", True), ("failed", True), (None, True)])
def test_settled_waits_for_vault_archive(status, expected):
    assert teams_utils.result_settled({
        "conclusion": {"status": "ready", "vault_archive": {"status": status} if status else None},
        "deploy": {"status": "succeeded"},
    }) is expected


@pytest.mark.parametrize("entry,line", [
    ({"status": "saved", "action": "append", "path": "项目/发布.md", "reason": "已验证"}, "已追加 项目/发布.md（已验证）"),
    ({"status": "skipped", "reason": "已有记录"}, "未写入知识库（已有记录）"),
    ({"status": "failed", "error": "校验拒绝"}, "自动归档失败（校验拒绝）"),
])
def test_chat_formats_obsidian_status(hermes, entry, line):
    team_id = _finished_team(_client("u1"), hermes)
    team = AgentTeams.get(team_id, "u1")
    content = outputs.chat_content(team, {**CONCLUSION, "entry": {**CONCLUSION["entry"], "vault_archive": entry}})
    assert content.index("负责人验收") < content.index(line) < content.index("在协作台看")


def test_vault_callback_refreshes_the_existing_reply_in_place(hermes, monkeypatch):
    async def model(request, user, model_id=None):
        return {"id": "conn.hermes-agent", "selection_id": "conn.hermes-agent", "name": "Hermes"}

    events = []

    async def tell(*args):
        events.append(args)

    monkeypatch.setattr(hermes_sessions, "resolve_hermes_model", model)
    monkeypatch.setattr(hermes_notify.Users, "get_user_by_id", lambda uid: _User(uid))
    monkeypatch.setattr(message_card, "tell", tell)
    client = _client("u1")
    team_id = _finished_team(client, hermes)
    chat_id = client.post(f"/api/v1/teams/{team_id}/conclusion/chat").json()["chat_id"]
    before = Chats.get_chat_by_id(chat_id).chat["history"]
    reply_id = before["currentId"]

    entry = {**CONCLUSION["entry"], "vault_archive": {
        "status": "saved", "action": "update", "path": "项目/发布.md", "reason": "已验证"}}
    hermes.responses[("GET", "/conclusion")] = {**CONCLUSION, "entry": entry}
    bare = _hermes_client(monkeypatch)
    path = f"/api/v1/teams/hermes/teams/{team_id}/vault-archived"
    assert bare.post(path).status_code == 401
    headers = {"X-Hermes-Key": "k", "X-Halo-Owner": "u1"}
    assert bare.post(path, headers=headers).json() == {"refreshed": True}
    assert bare.post(path, headers=headers).json() == {"refreshed": False}
    history = Chats.get_chat_by_id(chat_id).chat["history"]
    assert history["messages"].keys() == before["messages"].keys()
    assert history["currentId"] == reply_id and len(events) == 1
    assert "Obsidian：已更新 项目/发布.md" in history["messages"][reply_id]["content"]
