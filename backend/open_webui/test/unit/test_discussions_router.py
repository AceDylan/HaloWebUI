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
    api._recent.clear()
    yield SimpleNamespace(request=request, calls=calls, events=events, after=after, state=state)
    room.LIVE.clear()
    api._recent.clear()
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
        context=overrides.pop("context", None),
        client_key=overrides.pop("client_key", None),
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

    listed = asyncio.run(api.list_discussions(USER))["items"]
    assert [item["id"] for item in listed] == [chat_id]
    assert listed[0]["status"] == "done" and listed[0]["mode"] == "roundtable"
    assert asyncio.run(api.list_discussions(OTHER))["items"] == []
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
        second = await _create(env, question="第二个问题")
        with pytest.raises(HTTPException) as cap:
            await _create(env, question="第三个问题")
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
    api._persist_ask(chat_id, ask, api._setup_of(table.get_chat_by_id(chat_id)))
    assert table.get_chat_by_id(chat_id).meta[room.META_KEY]["status"] == "running"
    # the list (and the sidebar count) does not take it for a live one
    listed = asyncio.run(api.list_discussions(USER))["items"][0]
    assert listed["status"] == "interrupted" and listed["running"] is False
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
    listed = asyncio.run(api.list_discussions(USER))["items"]
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


def test_attachments_are_checked_read_and_passed_on(env, monkeypatch):
    from open_webui.models import files as files_mod
    from open_webui.utils import chat_image_refs

    store = {
        "img": SimpleNamespace(id="img", user_id="u1", filename="cat.png", meta={"content_type": "image/png", "name": "cat.png", "size": 10}, data={}),
        "doc": SimpleNamespace(id="doc", user_id="u1", filename="plan.txt", meta={"content_type": "text/plain", "name": "plan.txt"}, data={"content": "预算十万" * 5000}),
        "theirs": SimpleNamespace(id="theirs", user_id="u2", filename="x.txt", meta={}, data={}),
    }
    monkeypatch.setattr(files_mod.Files, "get_file_by_id", lambda file_id: store.get(file_id))
    monkeypatch.setattr(chat_image_refs, "materialize_image_url_for_openai", lambda url, **kw: "data:image/png;base64,QUJD")

    member = SimpleNamespace(id="u1", role="user")
    with pytest.raises(HTTPException) as other:
        api._load_files(["theirs"], member)  # someone else's file (an admin may read any file)
    assert other.value.status_code == 404
    with pytest.raises(HTTPException):
        api._load_files(["img", "doc", "a", "b", "c"], USER)

    async def scenario():
        form = api.CreateForm(question="看看这个方案", seats=[api.SeatForm(model="a"), api.SeatForm(model="b")], rounds=1, moderator="c", files=["img", "doc"])
        detail = await api.create_discussion(env.request, form, USER)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert [(f["id"], f["type"]) for f in ask["files"]] == [("img", "image"), ("doc", "file")]
    assert len(ask["files"][1]["text"]) == room.FILE_TEXT_CHARS
    first = env.calls[0][1][1]["content"]
    assert isinstance(first, list) and first[1]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert "Attached file «plan.txt»" in first[0]["text"]
    message = chats_mod.ChatTable().get_chat_by_id(chat_id).chat["history"]["messages"][ask["userMessageId"]]
    assert [f["type"] for f in message["files"]] == ["image", "file"]
    assert message["files"][0]["url"] == "/api/v1/files/img/content"


def test_create_keeps_the_conversation_it_was_started_from(env):
    async def scenario():
        detail = await _create(env, context={"text": "用户：去哪玩？", "title": "旅行", "chat_id": "c-1"})
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["context"] == {"text": "用户：去哪玩？", "title": "旅行", "chatId": "c-1"}


def test_one_question_never_becomes_two_discussions(env):
    env.state["delay"] = 0.02

    async def scenario():
        first = await _create(env, client_key="k1")
        # the response was lost and the page sends the same request again
        again = await _create(env, client_key="k1")
        assert again["id"] == first["id"] and again["deduplicated"] is True
        # a second tab or a double tap: a fresh key, the same question and seats
        twin = await _create(env, client_key="k2")
        assert twin["id"] == first["id"] and twin["deduplicated"] is True
        # another question is another discussion
        other = await _create(env, question="另一个问题", client_key="k3")
        assert other["id"] != first["id"] and "deduplicated" not in other
        await _settle(first["id"])
        await _settle(other["id"])
        return first["id"]

    asyncio.run(scenario())
    assert len(chats_mod.ChatTable().get_chats_with_meta_key_by_user_id("u1", room.META_KEY)) == 2


def test_after_a_failure_the_same_question_starts_afresh(env):
    env.state["fail"] = {"a", "b"}

    async def scenario():
        first = await _create(env, client_key="k1")
        await _settle(first["id"])
        env.state["fail"] = set()
        second = await _create(env, client_key="k2")
        await _settle(second["id"])
        return first, second

    first, second = asyncio.run(scenario())
    assert second["id"] != first["id"]


def test_resume_picks_a_failed_question_up(env):
    env.state["fail"] = {"c"}

    async def scenario():
        detail = await _create(env)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["status"] == "done"  # the moderator failed, a seat wrote the conclusion
    assert ask["conclusion"]["standIn"]["for"] == "c"

    env.state["fail"] = {"a", "b", "c"}
    with pytest.raises(HTTPException) as finished:
        asyncio.run(api.resume_discussion(env.request, chat_id, USER))
    assert finished.value.status_code == 400

    async def broken_then_resumed():
        detail = await _create(env, question="全挂了怎么办")
        await _settle(detail["id"])
        failed = (await api.get_discussion(detail["id"], USER))["asks"][0]
        assert failed["status"] == "error" and "第一轮" in failed["error"]
        env.state["fail"] = set()
        await api.resume_discussion(env.request, detail["id"], USER)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(broken_then_resumed())
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][0]
    assert ask["status"] == "done"
    assert [(t["id"], t["status"]) for t in ask["turns"]] == [("r1-s1", "done"), ("r1-s2", "done")]


# --- 派发方式「讨论」: a chat message becomes a discussion, its conclusion comes back -------------


def _discuss_first(env, **kwargs) -> str:
    async def scenario():
        detail = await _create(env, **kwargs)
        await _settle(detail["id"])
        return detail["id"]

    return asyncio.run(scenario())


def _origin_chat(title="新对话"):
    """A Hermes chat as the page leaves it on send: the message and the reply to fill."""
    messages = {
        "q0": {"id": "q0", "parentId": None, "childrenIds": ["r0"], "role": "user", "content": "我们要做一个记账 App"},
        "r0": {"id": "r0", "parentId": "q0", "childrenIds": ["q1"], "role": "assistant", "content": "好的，先定数据存储。", "model": "hermes-agent", "done": True},
        "q1": {"id": "q1", "parentId": "r0", "childrenIds": ["r1"], "role": "user", "content": "该用 Postgres 还是 SQLite？"},
        "r1": {"id": "r1", "parentId": "q1", "childrenIds": [], "role": "assistant", "content": "", "model": "hermes-agent", "done": False},
    }
    chat = chats_mod.ChatTable().insert_new_chat(
        "u1", chats_mod.ChatForm(chat={"title": title, "models": ["hermes-agent"], "history": {"messages": messages, "currentId": "r1"}})
    )
    return chat.id


def _dispatch_form():
    return {
        "messages": [
            {"role": "system", "content": "你是 Hermes"},
            {"role": "user", "content": "我们要做一个记账 App"},
            {"role": "assistant", "content": "好的，先定数据存储。"},
            {"role": "user", "content": "该用 Postgres 还是 SQLite？"},
        ],
        "hermes_options": {"dispatch": "discuss"},
    }


def _run_dispatch(env, monkeypatch, chat_id, metadata_extra=None):
    from open_webui.utils import mode_dispatch, team_chats

    jobs, emitted = [], []

    async def emitter(event):
        emitted.append(event)

    async def no_folder(*args, **kwargs):
        return None

    from open_webui import tasks

    real_create_task = tasks.create_task

    def create_task(coro, id=None, **kwargs):
        if id != chat_id:  # the discussion's own task runs as usual
            return real_create_task(coro, id=id, **kwargs)
        jobs.append(coro)
        return "task-1", None

    monkeypatch.setattr("open_webui.socket.main.get_event_emitter", lambda metadata: emitter)
    monkeypatch.setattr(tasks, "create_task", create_task)
    monkeypatch.setattr(team_chats, "sort_into_folder", no_folder)
    metadata = {"chat_id": chat_id, "message_id": "r1", **(metadata_extra or {})}

    async def scenario():
        out = await mode_dispatch.run_mode_dispatch(env.request, _dispatch_form(), USER, metadata, "hermes-agent", "discuss")
        assert out == {"status": True, "task_id": "task-1"}
        await jobs[0]
        reply = chats_mod.ChatTable().get_chat_by_id(chat_id).chat["history"]["messages"]["r1"]
        run_chat_id = (reply.get("mode_dispatch") or {}).get("chat_id")
        if run_chat_id:
            await _settle(run_chat_id)
        return reply, run_chat_id

    reply, run_chat_id = asyncio.run(scenario())
    return reply, run_chat_id, emitted


def test_a_chat_message_becomes_a_discussion_at_the_users_last_table(env, monkeypatch):
    # the user's last discussion: b and a, c presiding
    _discuss_first(env, question="上次的问题", seats=["b", "a"], moderator="c")
    origin = _origin_chat()
    reply, run_chat_id, emitted = _run_dispatch(env, monkeypatch, origin)

    assert reply["done"] is True and reply["mode_dispatch"] == {"kind": "discuss", "chat_id": run_chat_id}
    assert "已交给讨论台" in reply["content"] and "error" not in reply
    assert emitted[0]["type"] == "chat:completion" and emitted[0]["data"]["mode_dispatch"]["chat_id"] == run_chat_id
    # the chat is named after its question (no model turn ran to name it)
    assert chats_mod.ChatTable().get_chat_by_id(origin).title == "该用 Postgres 还是 SQLite？"
    # and the sidebar reads its list again: the new name, the 讨论 mark
    assert emitted[1] == {"type": "chat:title", "data": "该用 Postgres 还是 SQLite？"}

    # one conversation in the history, as for a 协作台 team: the chat it was sent from, marked;
    # the discussion's own chat is on the 讨论台 page (and not found by the history's search)
    table = chats_mod.ChatTable()
    assert table.get_chat_by_id(run_chat_id).meta["dispatched_from"] == origin
    assert table.get_chat_by_id(origin).meta["mode_dispatch"] == ["discuss"]
    listed = [c.id for c in table.get_chat_title_id_list_by_user_id(USER.id, include_folders=True)]
    assert origin in listed and run_chat_id not in listed
    found = [c.id for c in table.get_chats_by_user_id_and_search_text(USER.id, "postgres")]
    assert origin in found and run_chat_id not in found
    page = asyncio.run(api.list_discussions(USER))
    assert run_chat_id in [row["id"] for row in page["items"]]

    detail = asyncio.run(api.get_discussion(run_chat_id, USER))
    ask = detail["asks"][0]
    assert ask["question"] == "该用 Postgres 还是 SQLite？" and ask["status"] == "done"
    assert [s["model"] for s in detail["setup"]["seats"]] == ["b", "a"]  # the same table as last time
    assert detail["setup"]["moderator"]["model"] == "c"
    assert ask["origin"] == {"chatId": origin, "messageId": "r1"}
    assert ask["context"]["chatId"] == origin
    assert "用户：我们要做一个记账 App" in ask["context"]["text"] and "Hermes：好的，先定数据存储。" in ask["context"]["text"]
    assert "该用 Postgres" not in ask["context"]["text"]  # the question itself is not background


def test_the_conclusion_goes_back_into_the_chat_once(env, monkeypatch):
    from open_webui.utils import hermes_notify, mode_dispatch

    _discuss_first(env, question="上次的问题")
    origin = _origin_chat()
    _, run_chat_id, _ = _run_dispatch(env, monkeypatch, origin)
    ask = asyncio.run(api.get_discussion(run_chat_id, USER))["asks"][0]

    notice, content, run_id = mode_dispatch.report_of("discuss", run_chat_id, ask)
    assert notice.startswith("[讨论结论] 「该用 Postgres 还是 SQLite？」：2 个模型圆桌讨论（a、b）")
    assert f"/discuss/{run_chat_id}" in notice
    assert content.startswith("## 结论\n用 Postgres") and run_id == f"discuss:{run_chat_id}:{ask['id']}"

    posted = []
    busy = {"left": 1}

    async def show(request, **kwargs):
        if busy["left"]:
            busy["left"] -= 1
            raise hermes_notify.HermesNotifyError(409, "chat is busy")
        posted.append(kwargs)
        return {"status": True}

    monkeypatch.setattr(hermes_notify, "show_notification_report", show)
    monkeypatch.setattr(mode_dispatch, "RETRY_SECONDS", 0)

    async def later():
        mode_dispatch.report_back_later(env.request, "discuss", run_chat_id, ask)
        await asyncio.gather(*list(mode_dispatch._background))

    asyncio.run(later())  # busy once, then posted
    assert len(posted) == 1
    sent = posted[0]
    assert sent["chat_id"] == origin and sent["source"] == "discuss" and sent["run_id"] == run_id
    assert sent["notice"] == notice and sent["content"] == content and sent["design"] is False

    # 「把结论放进这个对话」 by hand: the route, quietly
    out = asyncio.run(api.report_back(env.request, run_chat_id, USER))
    assert out["chat_id"] == origin and posted[-1]["quiet"] is True
    # someone else's discussion, or one not dispatched from a chat: refused
    with pytest.raises(HTTPException):
        asyncio.run(api.report_back(env.request, run_chat_id, OTHER))
    plain = _discuss_first(env, question="自己开的讨论", seats=["a", "c"])
    with pytest.raises(HTTPException) as not_dispatched:
        asyncio.run(api.report_back(env.request, plain, USER))
    assert not_dispatched.value.status_code == 400


def test_after_done_sends_a_dispatched_conclusion_back(env, monkeypatch):
    from open_webui.utils import mode_chats, mode_dispatch

    sent = []

    async def no_title(*args, **kwargs):
        return "标题", None

    monkeypatch.setattr(mode_chats, "auto_title_and_folder", no_title)
    monkeypatch.setattr(mode_dispatch, "report_back_later", lambda request, kind, chat_id, run: sent.append((kind, chat_id, run["id"])))
    detail = asyncio.run(_create(env))
    asyncio.run(_settle(detail["id"]))
    ask = asyncio.run(api.get_discussion(detail["id"], USER))["asks"][0]
    asyncio.run(ORIGINAL_AFTER_DONE(env.request, USER, detail["id"], ask))
    assert sent == []  # started on its page: nothing to send back
    asyncio.run(ORIGINAL_AFTER_DONE(env.request, USER, detail["id"], {**ask, "origin": {"chatId": "c-1", "messageId": "m"}}))
    assert sent == [("discuss", detail["id"], ask["id"])]


def test_a_dispatched_discussion_without_a_last_table_seats_different_families():
    from open_webui.utils import assistant_library as lib

    models = {m: {"id": m, "name": m} for m in ("gpt-chat", "gpt-mini", "claude-chat", "deepseek-chat", "hermes-agent")}
    original = chats_mod.Chats.get_chats_with_meta_key_by_user_id
    chats_mod.Chats.get_chats_with_meta_key_by_user_id = lambda *a, **k: []
    try:
        setup = api.dispatch_setup(USER, models, set())
    finally:
        chats_mod.Chats.get_chats_with_meta_key_by_user_id = original
    assert [s["model"] for s in setup["seats"]] == ["gpt-chat", "claude-chat", "deepseek-chat"]
    assert setup["moderator"]["model"] == "gpt-chat" and setup["autoMatch"] is True
    assert {s["assist"] for s in setup["seats"]} == {"auto"}
    assert lib.library(models, USER)[1]  # sanity: these are text models the library offers


def test_the_list_comes_a_page_at_a_time_with_search_and_the_live_filter(env):
    ids = [_discuss_first(env, question=q) for q in ("选数据库", "选框架", "选云厂商", "选编辑器", "选显示器")]

    first = asyncio.run(api.list_discussions(USER, limit=2))
    assert first["total"] == 5 and first["next"] and first["live"] == 0
    second = asyncio.run(api.list_discussions(USER, limit=2, before=first["next"]))
    third = asyncio.run(api.list_discussions(USER, limit=2, before=second["next"]))
    assert third["next"] is None and second["total"] is None
    paged = [d["id"] for d in first["items"] + second["items"] + third["items"]]
    assert sorted(paged) == sorted(ids) and len(set(paged)) == 5

    # the question is in the chat's summary as \uXXXX escapes: found either way
    found = asyncio.run(api.list_discussions(USER, q="云厂商"))
    assert [d["id"] for d in found["items"]] == [ids[2]] and found["total"] == 1
    assert asyncio.run(api.list_discussions(USER, q="100%_"))["items"] == []

    env.state["delay"] = 0.05

    async def live_one():
        detail = await _create(env, question="正在讨论的问题")
        live = await api.list_discussions(USER, status="live")
        ended = await api.list_discussions(USER, status="ended")
        await api.stop(detail["id"], USER)
        return detail["id"], live, ended

    live_id, live, ended = asyncio.run(live_one())
    assert [d["id"] for d in live["items"]] == [live_id] and live["live"] == 1
    assert live_id not in [d["id"] for d in ended["items"]] and ended["total"] == 5
