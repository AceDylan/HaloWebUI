"""助手库: the shared rules (decisions, writes, versions, pins) and the 讨论台 seats that use them,
on in-memory chat and model tables with fake model streams."""

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
from open_webui.routers import discussions as api  # noqa: E402
from open_webui.utils import assistant_library as lib  # noqa: E402
from open_webui.utils import chat as chat_utils  # noqa: E402
from open_webui.utils import discussion_room as room  # noqa: E402
from open_webui.utils import models as models_utils  # noqa: E402

USER = SimpleNamespace(id="u1", role="admin", settings=None)
PROMPT = "你是一名软件架构师。先弄清系统现状和目标，再比较方案的收益、代价和适用条件，最后给出可执行的建议与验证方法。"
BASES = [{"id": "conn.gpt-chat", "name": "gpt-chat"}]


def _entry(id, name, prompt=PROMPT, editable=True, version=1):
    return {"ref": f"model:{id}", "id": id, "name": name, "description": "", "domain": "", "emoji": "", "prompt": prompt, "base": "conn.gpt-chat", "editable": editable, "owned": True, "hidden": True, "source": "manual", "version": version, "updatedAt": 1}


def _spec(name, prompt=PROMPT):
    return {"name": name, "emoji": "🏗", "description": f"{name}的描述", "system_prompt": prompt, "base_model": "gpt-chat"}


def _decide(raw, units, assistants=(), **kw):
    return lib.normalize_decisions(raw, [{"key": k} for k in units], list(assistants), [], BASES, default_base="conn.gpt-chat", may_write=True, **kw)


# ---------------------------------------------------------------------------------------------
# Decisions


def test_one_upgrade_shared_by_several_seats_is_one_version():
    lib_entries = [_entry("a1", "架构师")]
    raw = {
        "units": [
            {"key": "s1", "action": "update", "ref": "model:a1", "assistant": {"system_prompt": PROMPT + "（一）"}},
            {"key": "s2", "action": "update", "ref": "model:a1", "assistant": {"system_prompt": PROMPT + "（二）"}},
        ]
    }
    decisions = _decide(raw, ["s1", "s2"], lib_entries)
    assert decisions["s1"]["action"] == decisions["s2"]["action"] == "update"
    assert decisions["s1"]["spec"] is decisions["s2"]["spec"] and "合并" in decisions["s2"]["note"]


def test_creates_and_upgrades_are_limited_per_run_and_same_names_are_shared():
    raw = {"units": [{"key": f"s{i}", "action": "create", "assistant": _spec(f"专家{i}")} for i in range(1, 4)]}
    raw["units"].append({"key": "s4", "action": "create", "assistant": _spec("专家1")})
    decisions = _decide(raw, ["s1", "s2", "s3", "s4"])
    assert [decisions[k]["action"] for k in ("s1", "s2", "s3")] == ["create", "create", "temporary"]
    assert decisions["s4"]["action"] == "create" and decisions["s4"]["spec"] is decisions["s1"]["spec"]


def test_generic_only_when_allowed_and_unknown_units_are_left_out():
    raw = {"units": [{"key": "s1", "action": "generic"}, {"key": "zz", "action": "use", "ref": "model:a1"}]}
    assert _decide(raw, ["s1"], [_entry("a1", "x")]) == {}
    assert _decide(raw, ["s1"], [_entry("a1", "x")], allow_generic=True)["s1"]["action"] == "generic"


def test_shortlist_keeps_favourites_and_finds_templates_by_words():
    many = [_entry(f"a{i}", f"助手{i}") for i in range(30)] + [_entry("arch", "软件架构师")]
    picked, templates = lib.shortlist("是否迁移到微服务架构", many, favorites=["model:a3"], user_limit=5)
    refs = [a["ref"] for a in picked]
    assert "model:a3" in refs and "model:arch" in refs and len(picked) == 5
    assert all(t["ref"].startswith("builtin:") for t in templates) and len(templates) <= lib.SHORTLIST_BUILTIN


# ---------------------------------------------------------------------------------------------
# Writes, versions, pins (database)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats_mod.Chat.__table__.create(engine)
    models_mod.Model.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as s:
            yield s

    monkeypatch.setattr(chats_mod, "get_db", get_db)
    monkeypatch.setattr(models_mod, "get_db", get_db)
    monkeypatch.setattr(chats_mod.ChatMessages, "upsert_message", lambda **_kwargs: None)
    yield engine
    engine.dispose()


def _row(model_id):
    return models_mod.Models.get_model_by_id(model_id)


def _new(name="架构师"):
    spec = lib.spec_of(_spec(name), BASES, "conn.gpt-chat")
    return lib.create_assistant(USER, spec, source="discuss", run_ref="discuss:c:1", question="q")


def test_a_shared_spec_is_written_once_and_a_moved_version_is_used_for_this_run_only(db):
    row = _new()
    entry = _entry(row.id, row.name)
    raw = {"units": [{"key": k, "action": "update", "ref": f"model:{row.id}", "assistant": {"system_prompt": PROMPT + "（加强）"}} for k in ("s1", "s2")]}
    choices = lib.carry_out(USER, _decide(raw, ["s1", "s2"], [entry]), source="discuss", run_ref="discuss:c:2", question="q", may_write=True)
    assert choices["s1"]["action"] == choices["s2"]["action"] == "update" and choices["s1"]["version"] == 2
    record = lib.lib_meta(_row(row.id).meta)
    assert record["version"] == 2 and len(record["revisions"]) == 1

    # the dispatcher read version 1, the assistant is at 2 now: not written, used once
    stale = _entry(row.id, row.name, version=1)
    raw = {"units": [{"key": "s1", "action": "update", "ref": f"model:{row.id}", "assistant": {"system_prompt": PROMPT + "（再加强）"}}]}
    choice = lib.carry_out(USER, _decide(raw, ["s1"], [stale]), source="discuss", run_ref="discuss:c:3", question="q", may_write=True)["s1"]
    assert choice["action"] == "temporary" and choice["system"].endswith("（再加强）") and "刚被改过" in choice["note"]
    assert lib.lib_meta(_row(row.id).meta)["version"] == 2


def test_a_new_assistant_is_private_hidden_and_tagged_with_its_source(db):
    row = _new()
    meta = row.meta.model_dump()
    assert row.access_control == {} and meta["hidden"] is True and meta["tags"] == [{"name": "讨论台"}]
    assert meta["assistant"]["source"] == "discuss" and meta["assistant"]["version"] == 1


def test_a_hand_edit_is_a_version_and_blocks_undoing_an_earlier_run(db):
    row = _new()
    lib.upgrade_assistant(USER, row.id, {"system": PROMPT + "（一）"}, expected_version=1, source="answer", run_ref="answer:c1", change="x")
    current = _row(row.id)
    form = models_mod.ModelForm(**{**current.model_dump(), "params": {"system": "用户自己改的"}})
    models_mod.Models.update_model_by_id(row.id, lib.note_manual_edit(current, form))
    record = lib.lib_meta(_row(row.id).meta)
    assert record["version"] == 3 and record["revisions"][-1]["source"] == "manual"
    with pytest.raises(lib.LibraryError) as conflict:
        lib.undo_run(USER, row.id, "answer:c1")
    assert conflict.value.status_code == 409
    # an explicit restore of version 1 is a new version
    lib.restore_version(USER, row.id, 1)
    restored = _row(row.id)
    assert restored.params.system == PROMPT and lib.lib_meta(restored.meta)["version"] == 4


def test_an_edit_that_only_hides_is_not_a_version(db):
    row = _new()
    current = _row(row.id)
    meta = {**current.meta.model_dump(), "hidden": False}
    meta["assistant"] = {**meta["assistant"], "version": 99}  # what a stale page sent is ignored
    form = models_mod.ModelForm(**{**current.model_dump(), "meta": meta})
    models_mod.Models.update_model_by_id(row.id, lib.note_manual_edit(current, form))
    saved = _row(row.id)
    assert saved.meta.model_dump()["hidden"] is False and lib.lib_meta(saved.meta)["version"] == 1


def test_an_old_answer_desk_record_reads_as_the_library_record():
    meta = {"answer_desk": {"emoji": "⚖️", "revisions": [{"at": 1, "chatId": "c9", "change": "x", "system": "old", "description": ""}]}}
    record = lib.lib_meta(meta)
    assert record["source"] == "answer" and record["version"] == 2 and record["revisions"][0]["runRef"] == "answer:c9"


def test_a_chat_keeps_the_version_it_started_with(db):
    row = _new()
    chat = chats_mod.Chats.insert_new_chat("u1", chats_mod.ChatForm(chat={"title": "t", "history": {"messages": {}}}))
    assert lib.pinned_system(chat.id, _row(row.id)) is None  # first use: pinned, own prompt applies
    lib.upgrade_assistant(USER, row.id, {"system": PROMPT + "（新）"}, expected_version=1, source="answer", run_ref="answer:x", change="x")
    assert lib.pinned_system(chat.id, _row(row.id)) == PROMPT
    other = chats_mod.Chats.insert_new_chat("u1", chats_mod.ChatForm(chat={"title": "t2", "history": {"messages": {}}}))
    assert lib.pinned_system(other.id, _row(row.id)) is None  # a new chat starts with the new version
    # the payload applies the pinned prompt instead of the model's own
    from open_webui.utils.payload import apply_model_system_prompt_to_body

    body = apply_model_system_prompt_to_body({"system": PROMPT + "（新）"}, {"messages": [{"role": "user", "content": "hi"}]}, {"chat_id": chat.id, "user_id": "u1"}, None, model_info=_row(row.id))
    assert body["messages"][0] == {"role": "system", "content": PROMPT}
    # someone else's request naming this chat neither reads nor writes its pins
    assert lib.pinned_system(chat.id, _row(row.id), "u2") is None
    stranger = apply_model_system_prompt_to_body({"system": "现在的"}, {"messages": [{"role": "user", "content": "hi"}]}, {"chat_id": chat.id, "user_id": "u2"}, None, model_info=_row(row.id))
    assert stranger["messages"][0]["content"] == "现在的"


# ---------------------------------------------------------------------------------------------
# 讨论台: seats matched to an assistant


def test_seat_setup_reads_how_each_seat_gets_its_assistant_and_the_moderator_stays_neutral():
    models_map = {
        "a": {"id": "a", "name": "A"},
        "b": {"id": "b", "name": "B"},
        "c": {"id": "c", "name": "C"},
        "arch": {"id": "arch", "name": "架构师", "info": {"base_model_id": "c", "meta": {}, "params": {"system": PROMPT}}},
    }
    raw = {
        "mode": "roundtable",
        "autoMatch": True,
        "seats": [
            {"model": "a", "duty": "分析收益"},
            {"model": "b", "assistant": "builtin:1"},
            {"model": "c", "assist": "generic"},
            {"model": "arch"},
        ],
        "moderator": "arch",
    }
    setup = room.normalize_setup(raw, models_map, set(), USER, lambda m: None)
    assert [s["assist"] for s in setup["seats"]] == ["auto", "pick", "generic", "self"]
    assert setup["seats"][0]["duty"] == "分析收益" and setup["seats"][1]["assistant"] == "builtin:1"
    assert setup["moderator"]["model"] == "c" and setup["moderator"]["persona"] == "架构师"
    assert setup["autoMatch"] is True
    # without 自动匹配, a seat with no choice keeps its plain role
    plain = room.normalize_setup({**raw, "autoMatch": False}, models_map, set(), USER, lambda m: None)
    assert plain["seats"][0]["assist"] == "generic"


def test_a_seat_speaks_with_its_assistant_settings_on_its_own_model_and_the_debate_side_comes_first():
    models_map = {"a": {"id": "a", "name": "A"}, "b": {"id": "b", "name": "B"}}
    setup = room.normalize_setup({"mode": "debate", "seats": [{"model": "a"}, {"model": "b"}]}, models_map, set(), USER, lambda m: None)
    ask = room.new_ask(question="要不要上微服务", setup=setup, user_message_id="u", message_id="m")
    ask["seats"][0]["assistant_choice"] = {"action": "use", "name": "软件架构师", "system": PROMPT}
    ask["seats"][0]["duty"] = "分析架构收益"
    messages = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[])
    system = messages[0]["content"]
    assert system.startswith(PROMPT) and "Your duty in this discussion: 分析架构收益" in system
    assert "Your side (正方)" in system
    other = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][1], round_index=1, history=[])[0]["content"]
    assert not other.startswith(PROMPT) and "[软件架构师]" in other


class _Stream:
    def __init__(self, text):
        self.text = text

    @property
    def body_iterator(self):
        async def gen():
            yield f'data: {json.dumps({"choices": [{"delta": {"content": self.text}}]}, ensure_ascii=False)}\n\n'
            yield "data: [DONE]\n\n"

        return gen()


@pytest.fixture
def env(db, monkeypatch):
    calls, state = [], {"plan": {}, "plan_fail": False}

    async def fake_completion(request, payload, user, bypass_filter=False):
        model, messages = payload["model"], payload["messages"]
        calls.append((model, messages))
        system = messages[0]["content"]
        if "You staff work in HaloWebUI" in system:
            if state["plan_fail"]:
                return _Stream("不给 JSON")
            return _Stream(json.dumps(state["plan"], ensure_ascii=False))
        if system.startswith("You moderated"):
            return _Stream("## 结论\n好。")
        return _Stream(f"{model} 的观点")

    monkeypatch.setattr(chat_utils, "generate_chat_completion", fake_completion)

    async def fake_all_models(request, user=None):
        models = {m: {"id": m, "name": m} for m in ("a", "b", "c")}
        for row in models_mod.Models.get_all_models():
            if row.base_model_id and row.is_active:
                models[row.id] = {"id": row.id, "name": row.name, "info": row.model_dump()}
        request.state.MODELS, request.state.MODELS_AMBIGUOUS = models, set()
        return list(models.values())

    monkeypatch.setattr(models_utils, "get_all_models", fake_all_models)

    def emitter(user, chat_id, message_id):
        async def emit(event):
            pass

        return emit

    monkeypatch.setattr(api, "_emitter", emitter)

    async def fake_after_done(request, user, chat_id, ask):
        pass

    monkeypatch.setattr(api, "_after_done", fake_after_done)
    request = SimpleNamespace(
        state=SimpleNamespace(MODELS=None, MODELS_AMBIGUOUS=set()),
        app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_WEB_SEARCH=True, USER_PERMISSIONS={}))),
    )
    room.LIVE.clear()
    api._recent.clear()
    yield SimpleNamespace(request=request, calls=calls, state=state)
    room.LIVE.clear()
    api._recent.clear()


async def _settle(chat_id):
    live = room.LIVE.get(chat_id)
    if live and live.task:
        await live.task
    await asyncio.sleep(0)


def _discuss(env, mode="roundtable", seats=None, **kw):
    seats = seats or [api.SeatForm(model="a"), api.SeatForm(model="b"), api.SeatForm(model="c")]
    return api.create_discussion(env.request, api.CreateForm(question="是否将现有系统迁移到微服务", mode=mode, seats=seats, moderator="c", auto_match=True, **kw), USER)


def _assistants():
    return [m for m in models_mod.Models.get_all_models() if m.base_model_id]


def _plan_calls(env):
    return [c for c in env.calls if "You staff work in HaloWebUI" in c[1][0]["content"]]


def test_auto_seats_are_matched_once_and_speak_with_the_full_settings(env):
    env.state["plan"] = {
        "units": [
            {"key": "s1", "action": "create", "reason": "架构视角", "duty": "分析架构收益与适用条件", "assistant": _spec("软件架构师")},
            {"key": "s2", "action": "create", "reason": "运维视角", "duty": "分析部署复杂度", "assistant": _spec("运维专家", PROMPT.replace("软件架构师", "运维专家"))},
            {"key": "s3", "action": "generic"},
        ]
    }

    async def scenario():
        detail = await _discuss(env)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    rows = _assistants()
    assert sorted(r.name for r in rows) == ["软件架构师", "运维专家"]
    assert all(r.meta.model_dump()["hidden"] is True for r in rows)
    ask = asyncio.run(api.get_discussion(chat_id, USER))["asks"][-1]
    assert ask["matching"]["status"] == "done"
    seats = {s["id"]: s for s in ask["seats"]}
    assert seats["s1"]["assistant_choice"]["name"] == "软件架构师" and seats["s1"]["assistant_choice"]["action"] == "create"
    assert seats["s1"]["duty"] == "分析架构收益与适用条件"
    assert seats["s3"]["assistant_choice"]["action"] == "generic"
    # each seat keeps its own model; the assistant's prompt leads its system message
    turn_calls = [c for c in env.calls if c[1][0]["content"].startswith(PROMPT) or "participants in a structured discussion" in c[1][0]["content"]]
    by_model = {model: messages[0]["content"] for model, messages in turn_calls}
    assert by_model["a"].startswith(PROMPT) and by_model["c"].startswith('You are "c"')
    assert len(_plan_calls(env)) == 1

    # resume / continue on the same question: no new matching, no new writes
    asyncio.run(api.continue_discussion(env.request, chat_id, USER))
    asyncio.run(_settle(chat_id))
    assert len(_plan_calls(env)) == 1 and len(_assistants()) == 2

    # a follow-up question matches the automatic seats again (and is told what they had)
    env.state["plan"] = {"units": [{"key": "s1", "action": "use", "ref": f"model:{rows[0].id}"}, {"key": "s2", "action": "use", "ref": f"model:{rows[1].id}"}, {"key": "s3", "action": "generic"}]}

    async def follow_up():
        await api.ask_again(env.request, chat_id, api.AskForm(question="迁移节奏怎么定"), USER)
        await _settle(chat_id)

    asyncio.run(follow_up())
    assert len(_plan_calls(env)) == 2 and len(_assistants()) == 2
    assert '"last_time"' in _plan_calls(env)[-1][1][1]["content"]


def test_compare_gives_every_seat_the_same_assistant(env):
    env.state["plan"] = {"units": [{"key": "s1", "action": "create", "assistant": _spec("软件架构师")}, {"key": "s2", "action": "create", "assistant": _spec("别的专家")}, {"key": "s3", "action": "generic"}]}

    async def scenario():
        detail = await _discuss(env, mode="compare")
        await _settle(detail["id"])
        return detail["id"]

    ask = asyncio.run(api.get_discussion(asyncio.run(scenario()), USER))["asks"][-1]
    assert {s["assistant_choice"]["name"] for s in ask["seats"]} == {"软件架构师"}
    assert [r.name for r in _assistants()] == ["软件架构师"]


def test_a_picked_assistant_is_kept_and_a_failed_dispatch_falls_back_to_roles(env):
    env.state["plan_fail"] = True
    row = _new("产品专家")
    seats = [api.SeatForm(model="a", assistant=f"model:{row.id}"), api.SeatForm(model="b"), api.SeatForm(model="c", assist="generic")]

    async def scenario():
        detail = await _discuss(env, seats=seats)
        await _settle(detail["id"])
        return detail["id"]

    ask = asyncio.run(api.get_discussion(asyncio.run(scenario()), USER))["asks"][-1]
    assert ask["status"] == "done" and ask["matching"]["status"] == "error" and "匹配助手失败" in ask["matching"]["error"]
    seats = {s["id"]: s for s in ask["seats"]}
    assert seats["s1"]["assistant_choice"]["action"] == "use" and seats["s1"]["assistant_choice"]["name"] == "产品专家"
    assert not seats["s2"].get("assistant_choice")


def test_an_upgrade_made_by_a_discussion_can_be_undone(env):
    row = _new("软件架构师")
    env.state["plan"] = {"units": [{"key": "s1", "action": "update", "ref": f"model:{row.id}", "change": "会算迁移成本", "assistant": {"system_prompt": PROMPT + "并估算迁移成本。"}}]}
    seats = [api.SeatForm(model="a"), api.SeatForm(model="b", assist="generic")]

    async def scenario():
        detail = await _discuss(env, seats=seats)
        await _settle(detail["id"])
        return detail["id"]

    chat_id = asyncio.run(scenario())
    assert _row(row.id).params.system.endswith("并估算迁移成本。")
    detail = asyncio.run(api.undo_assistant(chat_id, api.UndoAssistantForm(seat="s1"), USER))
    assert detail["asks"][-1]["seats"][0]["assistant_choice"]["reverted"] is True
    assert _row(row.id).params.system == PROMPT
    with pytest.raises(HTTPException):
        asyncio.run(api.undo_assistant(chat_id, api.UndoAssistantForm(seat="s1"), USER))
