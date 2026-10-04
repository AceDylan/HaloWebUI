"""讨论台 API on an in-memory chat table with fake model streams."""

import asyncio
import json
import pathlib
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.models import chats as chats_mod  # noqa: E402
from open_webui.routers import discussions as api  # noqa: E402
from open_webui.utils import chat as chat_utils  # noqa: E402
from open_webui.utils import discussion_room as room  # noqa: E402

USER = SimpleNamespace(id="u1", role="admin")
OTHER = SimpleNamespace(id="u2", role="admin")
MODELS = {m: {"id": m, "name": m} for m in ("a", "b", "c", "hermes-agent")}
ORIGINAL_AFTER_DONE = api._after_done


class _Stream:
    def __init__(self, text, delay=0.0):
        self.text = text
        self.delay = delay

    @property
    def body_iterator(self):
        async def gen():
            for ch in [self.text[i : i + 3] for i in range(0, len(self.text), 3)]:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield f'data: {json.dumps({"choices": [{"delta": {"content": ch}}]}, ensure_ascii=False)}\n\n'
            yield "data: [DONE]\n\n"

        return gen()


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats_mod.Chat.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(chats_mod, "get_db", get_db)
    monkeypatch.setattr(chats_mod.ChatMessages, "upsert_message", lambda **_kwargs: None)

    calls, events, after = [], [], []
    state = {"delay": 0.0, "fail": set()}

    async def fake_completion(request, payload, user, bypass_filter=False):
        model = payload["model"]
        calls.append((model, payload["messages"]))
        if model in state["fail"]:
            raise RuntimeError(f"{model} is down")
        system = payload["messages"][0]["content"]
        if system.startswith("You moderated"):
            return _Stream("## 结论\n用 Postgres。\n## 共识\n- 要备份", state["delay"])
        return _Stream(f"{model} 的观点", state["delay"])

    monkeypatch.setattr(chat_utils, "generate_chat_completion", fake_completion)

    def emitter(user, chat_id, message_id):
        async def emit(event):
            events.append(event)

        return emit

    monkeypatch.setattr(api, "_emitter", emitter)

    async def fake_after_done(request, user, chat_id, ask):
        after.append((chat_id, ask["id"], ask["status"]))

    monkeypatch.setattr(api, "_after_done", fake_after_done)
    # the excluded-model check needs the real helpers; keep them but make hermes recognisable
    request = SimpleNamespace(
        state=SimpleNamespace(MODELS=MODELS, MODELS_AMBIGUOUS=set()),
        app=SimpleNamespace(state=SimpleNamespace(MODELS=MODELS, config=SimpleNamespace())),
    )
    room.LIVE.clear()
    yield SimpleNamespace(request=request, calls=calls, events=events, after=after, state=state)
    room.LIVE.clear()
    engine.dispose()


def _create(env, **overrides):
    research = overrides.pop("research", False)
    form = api.CreateForm(
        research=research,
        question=overrides.pop("question", "如何选数据库？"),
        mode=overrides.pop("mode", "roundtable"),
        seats=[api.SeatForm(model=m) for m in overrides.pop("seats", ["a", "b"])],
        rounds=overrides.pop("rounds", 1),
        moderator=overrides.pop("moderator", "c"),
    )
    return api.create_discussion(env.request, form, USER)


async def _settle(chat_id):
    live = room.LIVE.get(chat_id)
    if live and live.task:
        await live.task
    await asyncio.sleep(0)


def test_create_runs_to_a_conclusion_and_is_listed(env):
    async def scenario():
        detail = await _create(env)
        chat_id = detail["id"]
        assert detail["running"] is True
        assert detail["title"] == "新讨论"
        assert detail["asks"][0]["status"] == "running"
        assert [s["model"] for s in detail["setup"]["seats"]] == ["a", "b"]
        await _settle(chat_id)
        return chat_id

    chat_id = asyncio.run(scenario())
    detail = asyncio.run(api.get_discussion(chat_id, USER))
    ask = detail["asks"][0]
    assert detail["running"] is False
    assert ask["status"] == "done"
    assert [t["content"] for t in ask["turns"]] == ["a 的观点", "b 的观点"]
    assert ask["conclusion"]["content"].startswith("## 结论\n用 Postgres")

    chat = chats_mod.ChatTable().get_chat_by_id(chat_id)
    message = chat.chat["history"]["messages"][ask["id"]]
    assert message["content"] == ask["conclusion"]["content"]  # what the normal chat view shows
    assert message["done"] is True
    assert chat.meta[room.META_KEY]["status"] == "done"
    assert chat.meta[room.META_KEY]["preview"].startswith("用 Postgres")
    assert chat.meta["title_generation"]["auto_generated"] is True
    assert env.after == [(chat_id, ask["id"], "done")]

    listed = asyncio.run(api.list_discussions(USER))
    assert [item["id"] for item in listed] == [chat_id]
    assert listed[0]["status"] == "done" and listed[0]["mode"] == "roundtable"
    assert asyncio.run(api.list_discussions(OTHER)) == []
    with pytest.raises(HTTPException) as other:
        asyncio.run(api.get_discussion(chat_id, OTHER))
    assert other.value.status_code == 404


def test_hermes_and_bad_setups_are_refused(env):
    with pytest.raises(HTTPException) as hermes:
        asyncio.run(_create(env, seats=["a", "hermes-agent"]))
    assert hermes.value.status_code == 400 and "Hermes" in hermes.value.detail
    with pytest.raises(HTTPException):
        asyncio.run(_create(env, seats=["a"]))
    with pytest.raises(HTTPException):
        asyncio.run(_create(env, question="   "))
    assert chats_mod.ChatTable().get_chats_with_meta_key_by_user_id("u1", room.META_KEY) == []


def test_follow_up_questions_carry_the_earlier_conclusion(env):
    async def scenario():
        detail = await _create(env)
        await _settle(detail["id"])
        env.calls.clear()
        second = await api.ask_again(env.request, detail["id"], api.AskForm(question="那备份呢？"), USER)
        assert [a["status"] for a in second["asks"]] == ["done", "running"]
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    first_turn_prompt = env.calls[0][1][1]["content"]
    assert "Earlier question: 如何选数据库？" in first_turn_prompt and "用 Postgres" in first_turn_prompt
    detail = asyncio.run(api.get_discussion(chat_id, USER))
    first, second = detail["asks"]
    assert second["question"] == "那备份呢？" and second["status"] == "done"
    messages = chats_mod.ChatTable().get_chat_by_id(chat_id).chat["history"]["messages"]
    assert messages[second["userMessageId"]]["parentId"] == first["id"]
    assert second["userMessageId"] in messages[first["id"]]["childrenIds"]
    assert chats_mod.ChatTable().get_chat_by_id(chat_id).chat["history"]["currentId"] == second["id"]


def test_one_question_at_a_time_and_a_cap_per_user(env):
    env.state["delay"] = 0.02

    async def scenario():
        first = await _create(env)
        with pytest.raises(HTTPException) as busy:
            await api.ask_again(env.request, first["id"], api.AskForm(question="再问"), USER)
        assert busy.value.status_code == 409
        second = await _create(env)
        with pytest.raises(HTTPException) as cap:
            await _create(env)
        assert cap.value.status_code == 429
        await api.stop(first["id"], USER)
        await api.stop(second["id"], USER)

    asyncio.run(scenario())


def test_interject_stop_then_conclude_and_continue(env):
    env.state["delay"] = 0.03

    async def scenario():
        detail = await _create(env, rounds=2)
        chat_id = detail["id"]
        live = room.LIVE[chat_id]
        for _ in range(200):  # wait for round 2 to be under way
            if live.ask["round"] == 2:
                break
            await asyncio.sleep(0.01)
        assert live.ask["round"] == 2
        said = await api.interject(chat_id, api.InterjectForm(text="预算只有 100 元"), USER)
        assert said["interjections"][0]["text"] == "预算只有 100 元"
        stopped = await api.stop(chat_id, USER)
        assert stopped["stopped"] is True
        assert stopped["asks"][0]["status"] == "stopped"
        with pytest.raises(HTTPException):
            await api.interject(chat_id, api.InterjectForm(text="晚了"), USER)
        return chat_id

    chat_id = asyncio.run(scenario())
    env.state["delay"] = 0.0
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert [t["status"] for t in ask["turns"] if t["round"] == 1] == ["done", "done"]
    assert {t["status"] for t in ask["turns"] if t["round"] == 2} == {"stopped"}

    async def conclude():
        await api.conclude_now(env.request, chat_id, USER)
        await _settle(chat_id)

    asyncio.run(conclude())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["status"] == "done" and ask["conclusion"]["content"].startswith("## 结论")
    moderator_prompt = env.calls[-1][1][1]["content"]
    assert "预算只有 100 元" in moderator_prompt

    async def more():
        await api.continue_discussion(env.request, chat_id, USER)
        await _settle(chat_id)

    asyncio.run(more())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["status"] == "done"
    # the stopped round 2 is run again in full, then a fresh conclusion
    assert [(t["round"], t["status"]) for t in ask["turns"]] == [(1, "done"), (1, "done"), (2, "done"), (2, "done")]
    assert ask["previousConclusions"]


def test_a_question_cut_off_by_a_restart_reads_as_interrupted(env):
    async def scenario():
        detail = await _create(env)
        await _settle(detail["id"])
        return detail

    detail = asyncio.run(scenario())
    chat_id, ask_id = detail["id"], detail["asks"][0]["id"]
    table = chats_mod.ChatTable()
    message = table.get_chat_by_id(chat_id).chat["history"]["messages"][ask_id]
    ask = message[room.MESSAGE_KEY]
    ask["status"] = "running"
    ask["turns"][0]["status"] = "streaming"
    table.upsert_message_to_chat_by_id_and_message_id(chat_id, ask_id, {room.MESSAGE_KEY: ask})
    again = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert again["status"] == "interrupted"
    assert again["turns"][0]["status"] == "stopped"


def test_delete(env):
    async def scenario():
        detail = await _create(env)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    assert asyncio.run(api.delete_discussion(chat_id, USER)) == {"ok": True}
    assert chats_mod.ChatTable().get_chat_by_id(chat_id) is None


def test_after_done_titles_and_files_the_discussion(env, monkeypatch):
    from open_webui.routers import tasks as tasks_router
    from open_webui.utils import folder_assignment

    titles, folders, emitted = [], [], []

    async def fake_title(request, form, user):
        titles.append(form)
        return {"choices": [{"message": {"content": '{"title": "数据库选型讨论"}'}}]}

    async def fake_assign(**kwargs):
        folders.append(kwargs)
        return folder_assignment.FolderAssignmentResult("assigned", changed=True, folder_id="f1", folder_name="技术")

    monkeypatch.setattr(tasks_router, "generate_title", fake_title)
    monkeypatch.setattr(folder_assignment, "assign_chat_folder", fake_assign)

    def emitter(user, chat_id, message_id):
        async def emit(event):
            emitted.append(event)

        return emit

    monkeypatch.setattr(api, "_emitter", emitter)
    # the fixture replaced _after_done for the run itself; call the original afterwards
    env.request.app.state.config = SimpleNamespace(ENABLE_TITLE_GENERATION=True, ENABLE_FOLDER_AUTO_ASSIGNMENT=True)

    async def scenario():
        detail = await _create(env)
        await _settle(detail["id"])
        ask = (await api.get_discussion(detail["id"], USER))["asks"][0]
        await ORIGINAL_AFTER_DONE(env.request, USER, detail["id"], ask)
        return detail["id"]

    chat_id = asyncio.run(scenario())
    assert titles and titles[0]["model"] == "c"
    assert titles[0]["messages"][0] == {"role": "user", "content": "如何选数据库？"}
    assert titles[0]["messages"][1]["content"] == "用 Postgres。"
    assert chats_mod.ChatTable().get_chat_by_id(chat_id).title == "数据库选型讨论"
    assert folders and folders[0]["user_message_count"] == 1 and folders[0]["title"] == "数据库选型讨论"
    kinds = [e["type"] for e in emitted]
    assert "chat:title" in kinds
    meta = next(e for e in emitted if e["type"] == "discuss" and e["data"]["kind"] == "meta")
    assert meta["data"]["folderId"] == "f1" and meta["data"]["title"] == "数据库选型讨论"


def test_after_done_falls_back_to_the_question_when_the_title_model_fails(env, monkeypatch):
    from open_webui.routers import tasks as tasks_router

    async def broken_title(request, form, user):
        raise RuntimeError("External task model required for this session")

    monkeypatch.setattr(tasks_router, "generate_title", broken_title)
    env.request.app.state.config = SimpleNamespace(ENABLE_TITLE_GENERATION=True, ENABLE_FOLDER_AUTO_ASSIGNMENT=False)

    async def scenario():
        detail = await _create(env, question="请帮我比较 Postgres 和 MySQL")
        await _settle(detail["id"])
        ask = (await api.get_discussion(detail["id"], USER))["asks"][0]
        await ORIGINAL_AFTER_DONE(env.request, USER, detail["id"], ask)
        return detail["id"]

    chat_id = asyncio.run(scenario())
    title = chats_mod.ChatTable().get_chat_by_id(chat_id).title
    assert title and title != "新讨论" and "Postgres" in title



def test_research_and_retry_through_the_api(env, monkeypatch):
    async def fake_search(request, user, moderator, question, history):
        return {"queries": ["q1"], "docs": [{"url": "https://x.example", "title": "X", "content": "资料正文" * 40}]}

    monkeypatch.setattr(api, "_search", fake_search)
    env.state["fail"] = {"b"}

    async def scenario():
        detail = await _create(env, research=True)
        assert detail["setup"]["research"] is True
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["research"]["status"] == "done" and ask["research"]["sources"][0]["url"] == "https://x.example"
    assert [t["status"] for t in ask["turns"]] == ["done", "error"]
    assert ask["status"] == "done"
    with pytest.raises(HTTPException):
        asyncio.run(api.retry_turn(env.request, chat_id, api.RetryForm(turn="r1-s1"), USER))  # already done

    env.state["fail"] = set()
    env.calls.clear()

    async def retry():
        await api.retry_turn(env.request, chat_id, api.RetryForm(turn="r1-s2"), USER)
        await _settle(chat_id)

    asyncio.run(retry())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert [t["status"] for t in ask["turns"]] == ["done", "done"]
    assert [model for model, _ in env.calls] == ["b", "c"]  # the seat, then the moderator
    assert "[1] X — https://x.example" in env.calls[0][1][1]["content"]
    assert ask["previousConclusions"]
    listed = asyncio.run(api.list_discussions(USER))
    assert listed[0]["research"] is True


def test_search_builds_one_evidence_pack(env, monkeypatch):
    from open_webui.routers import retrieval, tasks as tasks_router

    searched = []

    async def fake_queries(request, form, user):
        assert form["type"] == "web_search" and form["model"] == "c"
        return {"choices": [{"message": {"content": '{"queries": ["postgres 优缺点", "mongodb 优缺点", "第三个"]}'}}]}

    async def fake_web(request, form, user=None):
        searched.append(form.query)
        if form.query.startswith("mongodb"):
            raise RuntimeError("engine down")
        return {"docs": [{"content": "正文", "metadata": {"source": "https://p.example", "title": "P"}}]}

    monkeypatch.setattr(tasks_router, "generate_queries", fake_queries)
    monkeypatch.setattr(retrieval, "process_web_search", fake_web)
    env.request.app.state.config = SimpleNamespace(ENABLE_WEB_SEARCH=True)
    out = asyncio.run(api._search(env.request, USER, "c", "选数据库", []))
    assert searched == ["postgres 优缺点", "mongodb 优缺点"]  # at most two
    assert out == {"queries": ["postgres 优缺点", "mongodb 优缺点"], "docs": [{"url": "https://p.example", "title": "P", "content": "正文"}]}

    async def broken_queries(request, form, user):
        raise RuntimeError("no task model")

    async def all_down(request, form, user=None):
        searched.append(form.query)
        raise RuntimeError("engine down")

    monkeypatch.setattr(tasks_router, "generate_queries", broken_queries)
    monkeypatch.setattr(retrieval, "process_web_search", all_down)
    searched.clear()
    with pytest.raises(ValueError, match="engine down"):
        asyncio.run(api._search(env.request, USER, "c", "选数据库", []))
    assert searched == ["选数据库"]  # the question itself when no queries could be made
    env.request.app.state.config = SimpleNamespace(ENABLE_WEB_SEARCH=False)
    with pytest.raises(ValueError, match="关闭"):
        asyncio.run(api._search(env.request, USER, "c", "选数据库", []))
