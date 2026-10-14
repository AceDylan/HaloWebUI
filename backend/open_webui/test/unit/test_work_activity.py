"""运行中 beyond Hermes: chat replies, 精答, 讨论台, 协作台, 自动分流 and 生图 rows."""
import asyncio
from types import SimpleNamespace

from open_webui import tasks
from open_webui.models import agent_teams, auto_routes
from open_webui.routers import images
from open_webui.utils import answer_desk, discussion_room, work_activity


def test_every_mode_at_work_is_listed_once(monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(tasks, "task_metadata", {
        "t-chat": {"chat_id": "chat-1", "owner_id": "u1", "kind": None, "started_at": now - 30},
        "t-title": {"chat_id": "chat-1", "owner_id": "u1", "kind": None, "blocks_completion": False},
        "t-img": {"chat_id": "chat-2", "owner_id": "u1", "kind": "image", "started_at": now - 20},
        "t-hermes": {"chat_id": "chat-h", "owner_id": "u1", "kind": None, "started_at": now - 50},
        "t-dispatch": {"chat_id": "chat-3", "owner_id": "u1", "kind": "dispatch", "started_at": now},
        "t-temp": {"chat_id": "local", "owner_id": "u1", "kind": None, "started_at": now},
        "t-other": {"chat_id": "chat-9", "owner_id": "u2", "kind": None, "started_at": now},
        "t-answer": {"chat_id": "answer-a1", "owner_id": "u1", "kind": "answer", "started_at": now},
    })
    monkeypatch.setattr(answer_desk, "LIVE", {
        "a1": SimpleNamespace(user_id="u1", run={"question": "押金多久退？", "startedAt": (now - 40) * 1000}),
        "a2": SimpleNamespace(user_id="u2", run={"question": "别人的", "startedAt": now * 1000}),
    })
    monkeypatch.setattr(discussion_room, "LIVE", {
        "d1": SimpleNamespace(user_id="u1", ask={"question": "选哪个库", "startedAt": (now - 10) * 1000}),
    })
    teams = [
        SimpleNamespace(id="team-1", chat_id="chat-3", title="重构登录", status="plan_ready", phase=None,
                        approved_at=None, created_at=now - 60),
        SimpleNamespace(id="team-2", chat_id=None, title="迁移", status="running", phase="attention",
                        approved_at=now - 45, created_at=now - 100),
    ]
    monkeypatch.setattr(agent_teams.AgentTeams, "list_working_for_user", lambda user_id, limit: teams)
    monkeypatch.setattr(agent_teams.AgentTeams, "list_finishing_for_user", lambda user_id, since, limit: [])
    monkeypatch.setattr(auto_routes.AutoRoutes, "active_for_user", lambda user_id, since: [
        {"id": "r1", "created_at": now - 5, "data": {"input": {"question": "解释\n报错"}, "origin": None}},
    ])
    monkeypatch.setattr(images, "active_image_runs", lambda user_id: [
        {"id": "img-1", "prompt": "一只猫", "started_at": now - 15},
    ])
    monkeypatch.setattr(work_activity, "_titles", lambda ids: {"chat-1": "周报", "a1": "押金"})

    rows = work_activity.list_work("u1", {"chat-h"})
    by = {row["id"]: row for row in rows}
    assert [row["id"] for row in rows] == ["team-1", "team-2", "a1", "chat-1", "chat-2", "studio:img-1", "d1", "r1"]
    assert by["chat-1"] == {"kind": "chat", "id": "chat-1", "chat_id": "chat-1", "href": "/c/chat-1",
                            "started_at": now - 30, "state": "running", "title": "周报"}
    assert by["chat-2"]["kind"] == "image"
    assert by["a1"]["href"] == "/answer/a1" and by["a1"]["title"] == "押金"
    assert by["d1"]["href"] == "/discuss/d1" and by["d1"]["title"] == "选哪个库"
    assert by["team-1"]["state"] == "waiting" and by["team-1"]["note"] == "等你批准"
    assert by["team-2"]["state"] == "waiting" and by["team-2"]["started_at"] == now - 45
    assert by["r1"]["href"] == "/auto?request=r1" and by["r1"]["title"] == "解释 报错"
    assert by["studio:img-1"]["href"] == "/workspace/images?tab=workbench"
    # the chat that handed its message to the team shows the team, not itself
    assert "chat-3" not in by and "chat-h" not in by and "chat-9" not in by and "local" not in by


def test_a_part_that_fails_does_not_hide_the_rest(monkeypatch):
    monkeypatch.setattr(tasks, "task_metadata", {})
    monkeypatch.setattr(answer_desk, "LIVE", {})
    monkeypatch.setattr(discussion_room, "LIVE", {})
    def broken(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(agent_teams.AgentTeams, "list_working_for_user", broken)
    monkeypatch.setattr(auto_routes.AutoRoutes, "active_for_user", broken)
    monkeypatch.setattr(images, "active_image_runs", lambda user_id: [{"id": "x", "prompt": "猫"}])
    monkeypatch.setattr(work_activity, "_titles", lambda ids: {})
    assert [row["kind"] for row in work_activity.list_work("u1", set())] == ["image"]


def test_studio_runs_are_listed_while_they_are_made(monkeypatch):
    monkeypatch.setattr(images, "_image_runs", {})
    monkeypatch.setattr(images, "_image_run_info", {})

    async def run():
        gate = asyncio.Event()

        async def start():
            await gate.wait()
            return {"ok": True}

        job = asyncio.ensure_future(images._run_image_generation_once(("u1", "req-1"), start, {"prompt": "一只猫"}))
        await asyncio.sleep(0)
        listed = images.active_image_runs("u1")
        assert [r["id"] for r in listed] == ["req-1"] and listed[0]["prompt"] == "一只猫"
        assert images.active_image_runs("u2") == []
        gate.set()
        await job
        assert images.active_image_runs("u1") == []

    asyncio.run(run())


def test_tasks_record_their_kind_and_start(monkeypatch):
    async def run():
        async def work():
            await asyncio.sleep(0)

        task_id, task = tasks.create_task(work(), id="chat-1", owner_id="u1", kind="image")
        meta = dict(tasks.task_metadata[task_id])
        await task
        return meta

    meta = asyncio.run(run())
    assert meta["kind"] == "image" and meta["owner_id"] == "u1" and meta["started_at"] > 0


def test_placeholder_titles_give_way_to_the_question(monkeypatch):
    from contextlib import contextmanager
    from open_webui.internal import db as db_module

    class Query:
        def filter(self, *a):
            return self
        def all(self):
            return [("a1", "新精答"), ("c1", "周报"), ("c2", "New Chat")]

    @contextmanager
    def fake_db():
        yield SimpleNamespace(query=lambda *cols: Query())

    monkeypatch.setattr(db_module, "get_db", fake_db)
    assert work_activity._titles({"a1", "c1", "c2"}) == {"c1": "周报"}


def test_work_whose_last_step_is_still_going_stays_listed(monkeypatch):
    """A finished 精答 / 讨论 whose picture is being drawn, a team whose result is being written,
    checked or drawn: still at work, on the clock they started on."""
    from open_webui.utils import mode_illustrate

    now = 1_000_000.0
    monkeypatch.setattr(tasks, "task_metadata", {})
    monkeypatch.setattr(answer_desk, "LIVE", {
        "a2": SimpleNamespace(user_id="u1", run={"question": "又问了一次", "startedAt": now * 1000}),
    })
    monkeypatch.setattr(discussion_room, "LIVE", {})
    monkeypatch.setattr(mode_illustrate, "DRAWING", {
        "a1": {"kind": "answer", "title": "押金\n多久退", "started_at": now - 90, "user_id": "u1"},
        "d1": {"kind": "discuss", "title": "选哪个库", "started_at": now - 200, "user_id": "u1"},
        "a2": {"kind": "answer", "title": "上一次", "started_at": now - 300, "user_id": "u1"},
        "x1": {"kind": "answer", "title": "别人的", "started_at": now, "user_id": "u2"},
    })
    monkeypatch.setattr(agent_teams.AgentTeams, "list_working_for_user", lambda user_id, limit: [])
    finishing = [SimpleNamespace(id="team-9", chat_id="chat-9", title="调研", status="running", phase="completed",
                                 approved_at=now - 500, created_at=now - 600)]
    monkeypatch.setattr(agent_teams.AgentTeams, "list_finishing_for_user", lambda user_id, since, limit: finishing)
    monkeypatch.setattr(auto_routes.AutoRoutes, "active_for_user", lambda user_id, since: [])
    monkeypatch.setattr(images, "active_image_runs", lambda user_id: [])
    monkeypatch.setattr(work_activity, "_titles", lambda ids: {})

    by = {row["id"]: row for row in work_activity.list_work("u1", set())}
    assert sorted(by) == ["a1", "a2", "d1", "team-9"]
    assert by["a1"] == {"kind": "answer", "id": "a1", "chat_id": "a1", "href": "/answer/a1", "title": "押金 多久退",
                        "started_at": now - 90, "state": "running", "note": "配图中"}
    assert by["d1"]["href"] == "/discuss/d1" and by["d1"]["note"] == "配图中"
    # asked again while the last picture is drawn: the new run is what is at work
    assert by["a2"]["title"] == "又问了一次" and "note" not in by["a2"]
    assert by["team-9"]["note"] == "收尾中" and by["team-9"]["started_at"] == now - 500


def test_finishing_teams_are_those_not_settled_yet():
    import time as _time
    from open_webui.models.agent_teams import AgentTeams

    now = int(_time.time())
    for name, finished, meta in (("fresh", now - 30, {}), ("settled", now - 30, {"settled": True}),
                                 ("old", now - 5000, {})):
        team = AgentTeams.insert("u-finishing", name, None, name)
        AgentTeams.update(team.id, "u-finishing", status="running", phase="completed", finished_at=finished, meta=meta)
    found = AgentTeams.list_finishing_for_user("u-finishing", now - 600)
    assert [team.title for team in found] == ["fresh"]
