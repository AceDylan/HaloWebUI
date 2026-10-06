"""精答工作台: the dispatcher's decision, the assistant library it writes, and the API on in-memory
chat and model tables with fake model streams."""

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
from open_webui.models import models as models_mod  # noqa: E402
from open_webui.routers import answers as api  # noqa: E402
from open_webui.utils import answer_desk as desk  # noqa: E402
from open_webui.utils import assistant_library as assistant_lib  # noqa: E402
from open_webui.utils import chat as chat_utils  # noqa: E402
from open_webui.utils import models as models_utils  # noqa: E402

USER = SimpleNamespace(id="u1", role="admin")
BASES = {
    "conn.gpt-chat": {"id": "conn.gpt-chat", "name": "gpt-chat"},
    "conn.deepseek-chat": {"id": "conn.deepseek-chat", "name": "deepseek-chat"},
    "conn.hermes-agent": {"id": "conn.hermes-agent", "name": "hermes-agent"},
    "conn.gpt-image-2": {"id": "conn.gpt-image-2", "name": "gpt-image-2"},
}

LAWYER_PROMPT = "你是一名合同审查律师。先确认合同类型与用户立场，再逐条找出风险条款，给出修改建议与理由。输出：风险清单表格 + 修改后条款。"


def _assistant(id, name, system="你是一名严谨的专家，回答要具体。" * 3, editable=True, base="conn.gpt-chat", description=""):
    return {"ref": f"model:{id}", "id": id, "name": name, "description": description, "domain": "", "emoji": "", "prompt": system, "base": base, "editable": editable, "owned": True, "hidden": False, "source": "manual", "version": 1, "updatedAt": 1}


BASE_LIST = [{"id": "conn.gpt-chat", "name": "gpt-chat"}, {"id": "conn.deepseek-chat", "name": "deepseek-chat"}]
OPTS = {"default_base": "conn.gpt-chat", "may_create": True, "web_allowed": True}


def _plan(raw, lib, templates=(), **kw):
    return desk.normalize_plan(raw, lib, list(templates), BASE_LIST, **{**OPTS, **kw})


def _is_plan(messages):
    return messages[0]["role"] == "system" and "You staff work in HaloWebUI" in messages[0]["content"]


# ---------------------------------------------------------------------------------------------
# The dispatcher's decision


def test_use_keeps_an_existing_assistant():
    lib = [_assistant("a1", "合同审查")]
    plan = _plan({"action": "use", "assistant_id": "a1", "reason": "合同问题", "web_search": False}, lib)
    assert plan["action"] == "use" and plan["decision"]["target"]["id"] == "a1" and plan["webSearch"] is False
    # the shared shape: one unit keyed "q"
    plan = _plan({"units": [{"key": "q", "action": "use", "ref": "model:a1"}], "web_search": True}, lib)
    assert plan["decision"]["target"]["id"] == "a1" and plan["webSearch"] is True


def test_use_accepts_an_assistant_named_instead_of_its_id():
    lib = [_assistant("a1", "合同审查")]
    plan = _plan({"action": "use", "assistant_id": "合同审查"}, lib)
    assert plan["decision"]["target"]["id"] == "a1"


def test_update_of_an_assistant_the_user_cannot_edit_is_a_one_off_upgrade():
    lib = [_assistant("a1", "合同审查", editable=False)]
    raw = {"action": "update", "assistant_id": "a1", "assistant": {"system_prompt": LAWYER_PROMPT}}
    plan = _plan(raw, lib)
    assert plan["action"] == "temporary" and "没有修改" in plan["note"]
    assert plan["decision"]["spec"]["system"] == LAWYER_PROMPT and plan["decision"]["spec"]["name"] == "合同审查"


def test_update_without_a_new_prompt_becomes_use():
    lib = [_assistant("a1", "合同审查")]
    plan = _plan({"action": "update", "assistant_id": "a1", "assistant": {"system_prompt": "短"}}, lib)
    assert plan["action"] == "use"


def test_create_picks_the_base_by_name_and_reuses_a_same_named_assistant():
    raw = {"action": "create", "assistant": {"name": "合同审查", "emoji": "⚖️", "system_prompt": LAWYER_PROMPT, "base_model": "deepseek-chat"}}
    plan = _plan(raw, [])
    assert plan["action"] == "create" and plan["decision"]["spec"]["base"] == "conn.deepseek-chat" and plan["decision"]["spec"]["emoji"] == "⚖️"
    same = _plan(raw, [_assistant("a1", "合同审查")])
    assert same["action"] == "use" and same["decision"]["target"]["id"] == "a1"
    unknown_base = _plan({**raw, "assistant": {**raw["assistant"], "base_model": "nope"}}, [])
    assert unknown_base["decision"]["spec"]["base"] == "conn.gpt-chat"
    # no right to save: written for this run only
    assert _plan(raw, [], may_create=False)["action"] == "temporary"


def test_a_builtin_template_is_used_as_it_is_and_upgraded_into_a_new_assistant():
    template = {"ref": "builtin:9", "id": "9", "name": "律师", "emoji": "⚖️", "description": "法律", "groups": [], "prompt": "你是律师。" * 10}
    used = _plan({"action": "use", "assistant_id": "builtin:9"}, [], [template])
    assert used["action"] == "template" and used["decision"]["template"]["id"] == "9"
    grown = _plan({"action": "update", "assistant_id": "builtin:9", "assistant": {"system_prompt": LAWYER_PROMPT}}, [], [template])
    assert grown["action"] == "create" and grown["decision"]["spec"]["from"] == "builtin:9" and grown["decision"]["spec"]["name"] == "律师"


def test_a_chosen_assistant_is_kept_whatever_the_dispatcher_says():
    lib = [_assistant("a1", "合同审查"), _assistant("a2", "写作")]
    plan = _plan({"action": "use", "assistant_id": "a2", "web_search": True}, lib, chosen="model:a1")
    assert plan["decision"]["target"]["id"] == "a1" and plan["webSearch"] is True


def test_web_search_only_when_allowed_and_bad_plans_raise():
    lib = [_assistant("a1", "通用")]
    plan = _plan({"action": "use", "assistant_id": "a1", "web_search": True}, lib, web_allowed=False)
    assert plan["webSearch"] is False
    for raw in ({"action": "dance"}, {"action": "use", "assistant_id": "missing"}, {"action": "create", "assistant": {"name": "x"}}):
        with pytest.raises(ValueError):
            _plan(raw, lib)
    with pytest.raises(ValueError):
        desk.parse_json_object("没有 JSON")
    assert desk.parse_json_object('<think>x</think>好的：{"action": "use"}')["action"] == "use"


def test_plan_messages_show_the_library_and_the_limits():
    lib = [_assistant("a1", "合同审查", system="x" * 900)]
    messages = desk.plan_messages("帮我看合同", lib, [], BASE_LIST, default_base="conn.gpt-chat", may_create=False, web_allowed=False)
    assert _is_plan(messages)
    body = messages[1]["content"]
    payload = json.loads(body[: body.index("\n\n")])
    assert payload["units"] == [{"key": "q", "question": "帮我看合同"}]
    entry = payload["library"][0]
    assert entry["ref"] == "model:a1" and entry["system_prompt"].endswith("…") and len(entry["system_prompt"]) == assistant_lib.PROMPT_EXCERPT_CHARS + 1
    assert payload["base_models"] == ["gpt-chat", "deepseek-chat"] and payload["default_base_model"] == "gpt-chat"
    assert "may not save" in body and '"web_search" must be false' in body


def test_library_keeps_hidden_assistants_and_leaves_out_hidden_bases_agents_and_image_models():
    models_map = {
        **BASES,
        "alias-of-gpt": BASES["conn.gpt-chat"],
        "a1": {"id": "a1", "name": "合同审查", "info": {"base_model_id": "conn.gpt-chat", "user_id": "u1", "meta": {"description": "看合同", "hidden": True}, "params": {"system": "s"}}},
        "a2": {"id": "a2", "name": "代理", "info": {"base_model_id": "conn.hermes-agent", "user_id": "u1", "meta": {}, "params": {}}},
        "a3": {"id": "a3", "name": "收起的", "info": {"base_model_id": "conn.gpt-chat", "user_id": "u1", "meta": {"assistant": {"archived": True}}, "params": {}}},
        "a4": {"id": "a4", "name": "别人的私有", "info": {"base_model_id": "conn.gpt-chat", "user_id": "u9", "access_control": {}, "meta": {}, "params": {}}},
        "a5": {"id": "a5", "name": "公开的", "info": {"base_model_id": "conn.gpt-chat", "user_id": "u9", "access_control": None, "meta": {}, "params": {}}},
        "hidden": {"id": "hidden", "name": "h", "info": {"meta": {"hidden": True}}},
    }
    assistants, bases = desk.lib.library(models_map, USER)
    assert sorted(a["id"] for a in assistants) == ["a1", "a5"]
    a1 = next(a for a in assistants if a["id"] == "a1")
    assert a1["editable"] is True and a1["hidden"] is True and a1["ref"] == "model:a1"
    assert [b["name"] for b in bases] == ["gpt-chat", "deepseek-chat"]
    other = SimpleNamespace(id="u2", role="user")
    assert all(a["editable"] is False for a in desk.lib.library(models_map, other)[0])


# ---------------------------------------------------------------------------------------------
# The API


class _Stream:
    def __init__(self, text, delay=0.0):
        self.text = text
        self.delay = delay

    @property
    def body_iterator(self):
        async def gen():
            for ch in [self.text[i : i + 4] for i in range(0, len(self.text), 4)]:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield f'data: {json.dumps({"choices": [{"delta": {"content": ch}}]}, ensure_ascii=False)}\n\n'
            yield "data: [DONE]\n\n"

        return gen()


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats_mod.Chat.__table__.create(engine)
    models_mod.Model.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(chats_mod, "get_db", get_db)
    monkeypatch.setattr(models_mod, "get_db", get_db)
    monkeypatch.setattr(chats_mod.ChatMessages, "upsert_message", lambda **_kwargs: None)

    calls, events, after = [], [], []
    state = {"plan": {}, "delay": 0.0, "fail": set(), "plan_fail": False}

    async def fake_completion(request, payload, user, bypass_filter=False):
        model, messages = payload["model"], payload["messages"]
        calls.append((model, messages))
        if _is_plan(messages):
            if state["plan_fail"]:
                return _Stream("我不想给 JSON")
            return _Stream(json.dumps(state["plan"], ensure_ascii=False))
        if model in state["fail"]:
            raise RuntimeError(f"{model} is down")
        return _Stream(f"{model} 的回答：要点一。", state["delay"])

    monkeypatch.setattr(chat_utils, "generate_chat_completion", fake_completion)

    async def fake_all_models(request, user=None):
        models = dict(BASES)
        for row in models_mod.Models.get_all_models():
            if row.base_model_id and row.is_active:
                models[row.id] = {"id": row.id, "name": row.name, "info": row.model_dump()}
        request.state.MODELS, request.state.MODELS_AMBIGUOUS = models, set()
        return list(models.values())

    monkeypatch.setattr(models_utils, "get_all_models", fake_all_models)

    def emitter(user, chat_id, message_id):
        async def emit(event):
            events.append(event)

        return emit

    monkeypatch.setattr(api, "_emitter", emitter)

    async def fake_after_done(request, user, chat_id, run):
        after.append((chat_id, run["status"]))

    monkeypatch.setattr(api, "_after_done", fake_after_done)
    request = SimpleNamespace(
        state=SimpleNamespace(MODELS=None, MODELS_AMBIGUOUS=set()),
        app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_WEB_SEARCH=True, USER_PERMISSIONS={}))),
    )
    desk.LIVE.clear()
    api._recent.clear()
    yield SimpleNamespace(request=request, calls=calls, events=events, after=after, state=state)
    desk.LIVE.clear()
    api._recent.clear()
    engine.dispose()


async def _settle(chat_id):
    live = desk.LIVE.get(chat_id)
    if live and live.task:
        await live.task
    await asyncio.sleep(0)


def _ask(env, question="帮我审一份租房合同", **kw):
    return api.create_answer(env.request, api.CreateForm(question=question, **kw), USER)


CREATE_PLAN = {
    "action": "create",
    "reason": "合同审查需要律师视角",
    "web_search": False,
    "change": "能逐条审查合同风险",
    "assistant": {"name": "合同审查", "emoji": "⚖️", "description": "逐条找合同风险", "system_prompt": LAWYER_PROMPT, "base_model": "deepseek-chat"},
}


def test_a_new_assistant_is_created_and_answers_in_an_ordinary_chat(env):
    env.state["plan"] = CREATE_PLAN

    async def scenario():
        detail = await _ask(env, planner="conn.gpt-chat")
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    rows = [m for m in models_mod.Models.get_all_models() if m.base_model_id]
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "合同审查" and row.base_model_id == "conn.deepseek-chat" and row.params.system == LAWYER_PROMPT
    assert row.access_control == {} and row.meta.tags == [{"name": "精答"}]
    # made by a workbench: hidden from the model menus, version 1, source 精答
    assert row.meta.model_dump()["hidden"] is True
    assert row.meta.model_dump()["assistant"]["version"] == 1 and row.meta.model_dump()["assistant"]["source"] == "answer"
    # the chat keeps the version it started with
    assert chats_mod.ChatTable().get_chat_by_id(chat_id).meta["assistant_pins"][row.id]["version"] == 1
    assert row.meta.profile_image_url.startswith("data:image/svg+xml")
    # the planner was the dispatcher, the new assistant answered (by its id: the app adds its prompt)
    assert env.calls[0][0] == "conn.gpt-chat" and env.calls[1][0] == row.id
    assert env.calls[1][1] == [{"role": "user", "content": "帮我审一份租房合同"}]

    detail = asyncio.run(api.get_answer(chat_id, USER))
    run = detail["run"]
    assert run["status"] == "done" and run["plan"]["action"] == "create" and run["plan"]["reason"] == "合同审查需要律师视角"
    assert run["assistant"]["id"] == row.id and run["assistant"]["action"] == "create" and "before" not in run["assistant"]
    assert run["answer"]["content"] == f"{row.id} 的回答：要点一。"
    chat = chats_mod.ChatTable().get_chat_by_id(chat_id)
    message = chat.chat["history"]["messages"][run["id"]]
    assert message["done"] is True and message["model"] == row.id and message["modelName"] == "合同审查"
    assert chat.chat["models"] == [row.id]
    assert chat.chat["history"]["messages"][run["userMessageId"]]["models"] == [row.id]
    assert chat.meta["answer_desk"]["assistant"]["name"] == "合同审查" and chat.meta["answer_desk"]["status"] == "done"
    assert env.after == [(chat_id, "done")]
    kinds = [e["data"]["kind"] for e in env.events if e["type"] == "answer"]
    assert "delta" in kinds and kinds[-1] == "end"

    listed = asyncio.run(api.list_answers(USER))
    assert listed[0]["id"] == chat_id and listed[0]["assistant"]["name"] == "合同审查"
    library = asyncio.run(api.list_assistants(env.request, USER))
    assert library["may_create"] is True and library["assistants"][0]["name"] == "合同审查"
    assert library["assistants"][0]["baseName"] == "deepseek-chat" and "prompt" not in library["assistants"][0]


def test_an_upgrade_keeps_the_old_prompt_and_can_be_undone(env):
    env.state["plan"] = CREATE_PLAN

    async def first():
        detail = await _ask(env)
        await _settle(detail["id"])

    asyncio.run(first())
    row = next(m for m in models_mod.Models.get_all_models() if m.base_model_id)
    upgraded = LAWYER_PROMPT + "\n劳动合同还要核对试用期、竞业限制和社保条款。"
    env.state["plan"] = {"action": "update", "assistant_id": row.id, "reason": "同领域", "change": "会审劳动合同", "assistant": {"system_prompt": upgraded}}

    async def second():
        detail = await _ask(env, question="劳动合同里的竞业限制合理吗？")
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(second())
    row = models_mod.Models.get_model_by_id(row.id)
    assert row.params.system == upgraded
    record = row.meta.model_dump()["assistant"]
    assert record["version"] == 2
    assert record["revisions"][-1]["system"] == LAWYER_PROMPT and record["revisions"][-1]["runRef"] == f"answer:{chat_id}"
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["assistant"]["action"] == "update" and run["assistant"]["system"] == upgraded and "before" not in run["assistant"]

    detail = asyncio.run(api.revert_upgrade(env.request, chat_id, USER))
    assert detail["run"]["assistant"]["reverted"] is True
    row = models_mod.Models.get_model_by_id(row.id)
    record = row.meta.model_dump()["assistant"]
    assert row.params.system == LAWYER_PROMPT and record["version"] == 3 and record["revisions"][-1]["source"] == "undo"
    assert chats_mod.ChatTable().get_chat_by_id(chat_id).meta["assistant_pins"][row.id]["version"] == 3
    with pytest.raises(HTTPException) as again:
        asyncio.run(api.revert_upgrade(env.request, chat_id, USER))
    assert again.value.status_code == 400


def test_an_upgrade_changed_since_is_not_undone(env):
    env.state["plan"] = CREATE_PLAN

    async def first():
        await _settle((await _ask(env))["id"])

    asyncio.run(first())
    row = next(m for m in models_mod.Models.get_all_models() if m.base_model_id)
    env.state["plan"] = {"action": "update", "assistant_id": row.id, "assistant": {"system_prompt": LAWYER_PROMPT + "（加强版）"}}

    async def second():
        detail = await _ask(env, question="第二问")
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(second())
    current = models_mod.Models.get_model_by_id(row.id)
    form = models_mod.ModelForm(**{**current.model_dump(), "params": {"system": "用户自己改过"}})
    models_mod.Models.update_model_by_id(row.id, form)
    with pytest.raises(HTTPException) as changed:
        asyncio.run(api.revert_upgrade(env.request, chat_id, USER))
    assert changed.value.status_code == 409


def test_a_user_who_may_not_keep_assistants_gets_a_one_off_one(env, monkeypatch):
    env.state["plan"] = CREATE_PLAN
    monkeypatch.setattr(api, "_may_write_library", lambda request, user: False)

    async def scenario():
        detail = await _ask(env)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    assert [m for m in models_mod.Models.get_all_models() if m.base_model_id] == []
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["assistant"]["action"] == "temporary" and run["assistant"]["saved"] is False
    # the base model answers with the assistant's prompt given as the system message
    assert env.calls[-1][0] == "conn.deepseek-chat"
    assert env.calls[-1][1][0] == {"role": "system", "content": LAWYER_PROMPT}
    assert "may not save" in env.calls[0][1][1]["content"]
    chat = chats_mod.ChatTable().get_chat_by_id(chat_id)
    assert chat.chat["models"] == ["conn.gpt-chat"]  # not switched to a model that is not saved


def test_a_failed_dispatch_still_answers_with_the_dispatcher(env):
    env.state["plan_fail"] = True

    async def scenario():
        detail = await _ask(env, planner="conn.gpt-chat")
        await _settle(detail["id"])
        return detail["id"]

    run = asyncio.run(api.get_answer(asyncio.run(scenario()), USER))["run"]
    assert run["status"] == "done" and run["plan"]["status"] == "error" and run["plan"]["action"] == "direct"
    assert run["assistant"]["id"] == "conn.gpt-chat" and run["answer"]["content"].startswith("conn.gpt-chat")


def test_web_research_feeds_numbered_sources_and_the_chat_lists_them(env, monkeypatch):
    from open_webui.routers import discussions

    async def fake_search(request, user, moderator, question, history):
        return {"queries": ["租房合同 押金 规定"], "docs": [{"url": "https://law.example/a", "title": "押金规定", "content": "押金" * 60}]}

    monkeypatch.setattr(discussions, "_search", fake_search)
    env.state["plan"] = {**CREATE_PLAN, "web_search": True}

    async def scenario():
        detail = await _ask(env)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["research"]["status"] == "done" and run["research"]["sources"][0]["n"] == 1
    assert "[1] 押金规定 — https://law.example/a" in env.calls[-1][1][-1]["content"]
    content = chats_mod.ChatTable().get_chat_by_id(chat_id).chat["history"]["messages"][run["id"]]["content"]
    assert content.endswith("1. [押金规定](https://law.example/a)") and "资料来源" in content

    # research off on the page: the dispatcher is told and its wish ignored
    env.calls.clear()

    async def no_web():
        detail = await _ask(env, question="另一个问题", research=False)
        await _settle(detail["id"])
        return detail["id"]

    run = asyncio.run(api.get_answer(asyncio.run(no_web()), USER))["run"]
    assert run["research"] is None and '"web_search" must be false' in env.calls[0][1][1]["content"]


def test_stop_then_retry_answers_again_with_the_same_assistant(env):
    env.state["plan"] = CREATE_PLAN
    env.state["delay"] = 0.05

    async def scenario():
        detail = await _ask(env)
        for _ in range(100):
            await asyncio.sleep(0.02)
            if (desk.LIVE[detail["id"]].run["answer"]["content"]):
                break
        stopped = await api.stop_answer(detail["id"], USER)
        assert stopped["run"]["status"] == "stopped" and stopped["run"]["answer"]["status"] == "stopped"
        env.state["delay"] = 0.0
        planner_calls = sum(1 for _, m in env.calls if _is_plan(m))
        await api.retry_answer(env.request, detail["id"], USER)
        await _settle(detail["id"])
        assert sum(1 for _, m in env.calls if _is_plan(m)) == planner_calls  # not dispatched again
        return detail["id"]

    chat_id = asyncio.run(scenario())
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["status"] == "done" and run["answer"]["status"] == "done"
    assert len([m for m in models_mod.Models.get_all_models() if m.base_model_id]) == 1
    with pytest.raises(HTTPException):
        asyncio.run(api.retry_answer(env.request, chat_id, USER))


def test_an_error_is_reported_and_a_restart_reads_as_interrupted(env):
    env.state["plan"] = CREATE_PLAN

    async def failing():
        original = chat_utils.generate_chat_completion

        async def broken(request, payload, user, bypass_filter=False):
            if _is_plan(payload["messages"]):
                return await original(request, payload, user)
            raise RuntimeError("invalid api key")

        chat_utils.generate_chat_completion = broken
        try:
            detail = await _ask(env)
            await _settle(detail["id"])
        finally:
            chat_utils.generate_chat_completion = original
        return detail["id"]

    chat_id = asyncio.run(failing())
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["status"] == "error" and "invalid api key" in run["error"] and run["answer"]["status"] == "error"
    assert env.after == []

    # a run marked going with no live task: cut off by a restart
    chat = chats_mod.ChatTable().get_chat_by_id(chat_id)
    message_id = chat.chat["answerDesk"]["messageId"]
    stored = dict(chat.chat["history"]["messages"][message_id]["answer_desk"])
    stored["status"] = "answering"
    stored["answer"] = {**stored["answer"], "status": "streaming", "startedAt": 1}
    chats_mod.Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, {"answer_desk": stored})
    chats_mod.Chats.set_chat_meta_value_by_id(chat_id, "answer_desk", {"status": "answering"})
    assert asyncio.run(api.list_answers(USER))[0]["status"] == "interrupted"
    run = asyncio.run(api.get_answer(chat_id, USER))["run"]
    assert run["status"] == "interrupted" and run["answer"]["status"] == "stopped"


def test_the_same_question_is_one_run_and_capacity_is_limited(env, monkeypatch):
    env.state["plan"] = CREATE_PLAN
    env.state["delay"] = 0.05

    async def scenario():
        first = await _ask(env, client_key="k1")
        again = await _ask(env, client_key="k1")
        assert again["id"] == first["id"] and again["deduplicated"] is True
        double_tap = await _ask(env)
        assert double_tap["id"] == first["id"]
        monkeypatch.setattr(desk, "MAX_RUNNING_PER_USER", 1)
        with pytest.raises(HTTPException) as busy:
            await _ask(env, question="别的问题")
        assert busy.value.status_code == 429
        await api.delete_answer(first["id"], USER)
        assert chats_mod.ChatTable().get_chat_by_id(first["id"]) is None

    asyncio.run(scenario())
    with pytest.raises(HTTPException):
        asyncio.run(_ask(env, question="  "))


def test_a_question_from_a_chat_brings_the_conversation_as_background(env):
    env.state["plan"] = CREATE_PLAN

    async def scenario():
        context = {"text": "用户：我在北京租房\n助手：好的", "title": "租房", "chat_id": "c-1"}
        detail = await _ask(env, question="押金多久退？", context=context)
        await _settle(detail["id"])
        return detail["id"]

    run = asyncio.run(api.get_answer(asyncio.run(scenario()), USER))["run"]
    assert run["context"] == {"text": "用户：我在北京租房\n助手：好的", "title": "租房", "chatId": "c-1"}
    plan_payload = env.calls[0][1][1]["content"]
    assert '"background": "用户：我在北京租房' in plan_payload
    asked = env.calls[-1][1][-1]["content"]
    assert asked.startswith("Background: the user's earlier conversation「租房」") and asked.endswith("Question: 押金多久退？")
