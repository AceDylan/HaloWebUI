"""辅助决策模型: one protocol (Jev's typed questions) for 自动分流 / 精答 / 讨论 / 协作, answered
natively by Jev or by a text model, checked against the options, with the module's own logic
as the fallback."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from open_webui.utils import decision_model as dm

USER = SimpleNamespace(id="u1", role="admin", settings=None)


def run(coro):
    return asyncio.run(coro)


def _decider(kind="text", name="judge"):
    return dm.Decider(model=f"conn.{name}", name=name, kind=kind, request=SimpleNamespace(), user=USER)


def _configured(monkeypatch, model="conn.judge", kind="text"):
    monkeypatch.setattr(dm, "current", lambda user: model)
    monkeypatch.setattr(dm, "lookup", lambda *a: {"id": model, "name": model.split(".")[-1], "kind": kind, "connection": ""})


QUESTIONS = {
    "mode": dm.choice("which", {"answer": "a", "discuss": "d"}),
    "level": dm.score("how much", ["low", "mid", "high"]),
    "yes": dm.noul("is it"),
}


# --- the protocol ------------------------------------------------------------------------------


def test_answers_must_stay_inside_the_options():
    good = {"mode": {"choice": "discuss", "probabilities": {"discuss": 0.7, "answer": 0.3, "team": 0.9}, "confidence": 2},
            "level": {"score": 1.6}, "yes": {"noul": 0.2}}
    out = dm.check_answers(QUESTIONS, good)
    assert out["mode"]["choice"] == "discuss" and "team" not in out["mode"]["probabilities"]
    assert out["mode"]["confidence"] == 1.0 and dm.level(out["level"]) == 2 and not dm.yes(out["yes"])
    assert dm.ranked(out["mode"]) == ["discuss", "answer"]
    for bad in (
        {**good, "mode": {"choice": "team"}},
        {**good, "level": {"score": 3}},
        {**good, "yes": {"noul": 1.5}},
        {k: v for k, v in good.items() if k != "yes"},
        {**good, "level": {"score": "nan"}},
    ):
        with pytest.raises(dm.DecisionError):
            dm.check_answers(QUESTIONS, bad)
    with pytest.raises(dm.DecisionError):
        dm.check_answers(QUESTIONS, None)


def test_text_model_answers_the_protocol_as_json(monkeypatch):
    seen = []

    async def call(self, payload):
        seen.append(payload)
        body = json.loads(payload["messages"][1]["content"])
        assert set(body) == {"state", "questions"} and payload["metadata"] == {"task": "decision"}
        answers = {"mode": {"choice": "answer"}, "level": {"score": 0}, "yes": {"noul": 0.9}}
        return {"choices": [{"message": {"content": "```json\n" + json.dumps({"answers": answers, "reason": "简单问题"}) + "\n```"}}]}

    monkeypatch.setattr(dm.Decider, "_call", call)
    answers, reason = run(_decider().judge({"question": "q"}, QUESTIONS))
    assert answers["mode"]["choice"] == "answer" and reason == "简单问题"
    assert "System One" in seen[0]["messages"][0]["content"]


def test_jev_gets_the_request_natively_and_more_questions_go_as_several(monkeypatch):
    bodies = []

    async def call(self, payload):
        native = payload["metadata"][dm.REQUEST_KEY]
        assert payload["metadata"]["task"] == "decision" and payload["stream"] is False
        bodies.append(native)
        return {"answers": {q: {"type": "noul", "noul": 0.8} for q in native["questions"]}}

    monkeypatch.setattr(dm.Decider, "_call", call)
    many = {f"q{i}": dm.noul(f"q{i}?") for i in range(11)}
    answers, reason = run(_decider("system_one", "jev-latest").judge({"a": 1}, many))
    assert len(answers) == 11 and reason == ""
    assert [len(b["questions"]) for b in bodies] == [8, 3]


def test_a_decision_never_asks_for_another_one(monkeypatch):
    async def call(self, payload):
        await _decider().judge({}, {"x": dm.noul("x")})

    monkeypatch.setattr(dm.Decider, "_call", call)
    with pytest.raises(dm.DecisionError):
        run(_decider().judge({}, {"x": dm.noul("x")}))


def test_jev_hook_posts_the_request_without_drafting(monkeypatch):
    from open_webui.routers import studio_prep
    from open_webui.utils import system_one as s1

    posted = []

    async def post(url, headers, body):
        posted.append((url, body))
        return {"answers": {"x": {"type": "noul", "noul": 0.4}}, "usage": {"input_tokens": 3}}

    async def no_planner(*a):
        raise AssertionError("a decision must not draft questions with gpt-chat")

    monkeypatch.setattr(s1, "post_system_one", post)
    monkeypatch.setattr(studio_prep, "prep_model", no_planner)
    out = run(s1.chat_completion(
        None, USER, form_data={"messages": []}, model="jev-latest", url="https://relay.example/v1", headers={"Authorization": "x"},
        metadata={"task": "decision", s1.DECISION_REQUEST_KEY: {"state": {}, "questions": {"x": {"type": "noul", "instructions": "?"}}}},
    ))
    assert out["answers"] == {"x": {"type": "noul", "noul": 0.4}}
    assert posted[0][0] == "https://relay.example/v1/systemone" and posted[0][1]["model"] == "jev-latest"


# --- decide: not set, fallback, used ------------------------------------------------------------


def test_nothing_set_means_the_modules_own_logic(monkeypatch):
    monkeypatch.setattr(dm, "current", lambda user: "")

    async def never(decider):
        raise AssertionError("not called")

    assert run(dm.decide(SimpleNamespace(), USER, "auto", never, models_map={})) == (None, None)


def test_failures_fall_back_with_a_trace_and_no_provider_text(monkeypatch):
    _configured(monkeypatch)

    async def boom(decider):
        raise RuntimeError("upstream said: key sk-secret is invalid")

    result, trace = run(dm.decide(SimpleNamespace(), USER, "answer", boom, models_map={}))
    assert result is None and trace["fallback"] and not trace["used"]
    assert "sk-secret" not in json.dumps(trace) and "RuntimeError" in trace["reason"]

    async def slow(decider):
        await asyncio.sleep(1)

    _, trace = run(dm.decide(SimpleNamespace(), USER, "answer", slow, models_map={}, timeout=0.01))
    assert trace["reason"] == "辅助决策超时"

    def gone(*a):
        raise dm.DecisionError("辅助决策模型已不可用（被删除、停用或没有权限）")

    monkeypatch.setattr(dm, "lookup", gone)
    _, trace = run(dm.decide(SimpleNamespace(), USER, "team", boom, models_map={}))
    assert trace["fallback"] and "不可用" in trace["reason"] and trace["model"] == "conn.judge"


def test_a_used_decision_records_model_and_result(monkeypatch):
    _configured(monkeypatch, "conn.jev-latest", "system_one")

    async def ok(decider):
        assert decider.kind == "system_one" and decider.model == "conn.jev-latest"
        return {"mode": "answer"}, {"mode": "answer"}

    result, trace = run(dm.decide(SimpleNamespace(), USER, "auto", ok, models_map={}))
    assert result == {"mode": "answer"} and trace["used"] and trace["result"] == {"mode": "answer"}
    assert dm.fell_back(trace, "后来没用上")["fallback"]


def test_candidates_are_text_bases_and_jev_models_with_their_connection(monkeypatch):
    from open_webui.utils import assistant_library as lib

    models = {
        "a.gpt-chat": {"id": "a.gpt-chat", "name": "gpt-chat", "connection_name": "A"},
        "b.gpt-chat": {"id": "b.gpt-chat", "name": "gpt-chat", "connection_name": "B"},
        "c.jev-latest": {"id": "c.jev-latest", "name": "jev-latest", "connection_name": "C"},
        "helper": {"id": "helper", "name": "助手", "info": {"base_model_id": "a.gpt-chat"}},
        "judge-preset": {"id": "judge-preset", "name": "判断助手", "info": {"base_model_id": "c.jev-latest"}},
    }
    monkeypatch.setattr(lib, "_offered_to", lambda *a: True)
    out = {c["id"]: c for c in dm.candidates(models, USER)}
    assert set(out) == {"a.gpt-chat", "b.gpt-chat", "c.jev-latest"}
    assert out["c.jev-latest"]["kind"] == "system_one" and out["b.gpt-chat"]["connection"] == "B"
    with pytest.raises(dm.DecisionError):
        dm.lookup(models, set(), USER, "gone.model")
    assert dm.configured(SimpleNamespace(settings={"decision_model": {"model": "b.gpt-chat"}})) == "b.gpt-chat"
    assert dm.configured(SimpleNamespace(settings={"decision_model": {"model": ""}})) == ""


# --- 自动分流 ----------------------------------------------------------------------------------


def _auto_env(monkeypatch, models):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library

    async def models_for(*args):
        return models, set()

    monkeypatch.setattr(answers, "_models", models_for)
    monkeypatch.setattr(answers, "_resolve_planner", lambda *a: {"model": "gpt", "name": "GPT"})
    monkeypatch.setattr(assistant_library, "library", lambda *a: ([], [{"id": m, "name": m} for m in models]))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_WEB_SEARCH=True, TASK_MODEL_EXTERNAL=""))))


def test_auto_routing_asks_the_decision_model_first(monkeypatch):
    from open_webui.routers import auto as api
    from open_webui.utils import chat

    request = _auto_env(monkeypatch, {"gpt": {"id": "gpt"}, "claude": {"id": "claude"}})
    _configured(monkeypatch, "conn.jev-latest", "system_one")
    calls = []

    async def completion(request, payload, user):
        calls.append(payload["metadata"]["task"])
        native = payload["metadata"][dm.REQUEST_KEY]
        assert set(native["questions"]["mode"]["criteria"]) == {"answer", "discuss"}  # no team: disabled here
        return {"answers": {"mode": {"choice": "discuss", "confidence": 0.81}}}

    monkeypatch.setattr(chat, "generate_chat_completion", completion)
    monkeypatch.setattr("open_webui.utils.agent_teams.ENABLE_AGENT_TEAMS", False, raising=False)
    decision = run(api.select(request, USER, api.CreateForm(question="A 还是 B", client_key="k"), []))[0]
    assert calls == ["decision"] and decision["mode"] == "discuss"
    assert decision["routing_model"] == "conn.jev-latest" and decision["decision"]["used"]
    assert "81%" in decision["reason"]


def test_auto_routing_falls_back_to_its_classifier_once(monkeypatch):
    from open_webui.routers import auto as api
    from open_webui.utils import chat

    request = _auto_env(monkeypatch, {"gpt": {"id": "gpt"}, "claude": {"id": "claude"}})
    _configured(monkeypatch)
    calls = []

    async def completion(request, payload, user):
        calls.append(payload["metadata"]["task"])
        if payload["metadata"]["task"] == "decision":
            return {"choices": [{"message": {"content": json.dumps({"answers": {"mode": {"choice": "nonsense"}}})}}]}
        return {"choices": [{"message": {"content": json.dumps({"mode": "answer", "reason": "普通问答"})}}]}

    monkeypatch.setattr(chat, "generate_chat_completion", completion)
    decision = run(api.select(request, USER, api.CreateForm(question="解释一下", client_key="k"), []))[0]
    assert calls == ["decision", "auto_routing"] and decision["mode"] == "answer"
    assert decision["decision"]["fallback"] and decision["routing_model"] != "conn.judge"


def test_auto_routing_manual_mode_never_asks(monkeypatch):
    from open_webui.routers import auto as api
    from open_webui.utils import chat

    request = _auto_env(monkeypatch, {"gpt": {"id": "gpt"}, "claude": {"id": "claude"}})
    _configured(monkeypatch)

    async def completion(*a):
        raise AssertionError("manual mode")

    monkeypatch.setattr(chat, "generate_chat_completion", completion)
    decision = run(api.select(request, USER, api.CreateForm(question="q", client_key="k", mode="discuss"), []))[0]
    assert decision["mode"] == "discuss" and "decision" not in decision


def test_auto_decision_still_passes_the_analysis_only_rule():
    from open_webui.utils.auto_routing import decision_request, normalize_selection, selection_from_answers

    state, questions = decision_request("只分析，不要修改代码", "", [], teams_available=True, discussion_available=False)
    assert set(questions["mode"]["criteria"]) == {"answer", "team"} and "execution" in questions
    raw = selection_from_answers({"mode": {"choice": "team"}, "execution": {"noul": 0.95}}, "", "jev")
    out = normalize_selection(raw, question=state["question"], teams_available=True, discussion_available=False)
    assert out["mode"] == "answer" and not out["execution_requested"]


# --- 精答 -------------------------------------------------------------------------------------


ASSISTANTS = [{"ref": "model:sql", "id": "sql", "name": "SQL 专家", "description": "查询优化", "domain": "数据库",
               "prompt": "p", "base": "conn.gpt", "editable": True, "hidden": False, "source": "manual", "version": 1}]
TEMPLATES = [{"ref": "builtin:writer", "id": "writer", "name": "写作助手", "description": "写文章", "emoji": "✍", "prompt": "写"}]
BASES = [{"id": "conn.gpt", "name": "gpt-chat"}, {"id": "conn.claude", "name": "claude-chat"}]


def test_answer_decision_maps_into_the_dispatchers_checks():
    from open_webui.utils import answer_desk as desk

    state, questions, keys = desk.decision_request("SQL 慢", ASSISTANTS, TEMPLATES, BASES, default_base="conn.gpt", web_allowed=False)
    assert set(questions) == {"assistant", "base"} and "new" in questions["assistant"]["criteria"]
    raw = desk.raw_from_answers({"assistant": {"choice": "t1"}, "base": {"choice": "m2"}}, keys, "r")
    plan = desk.normalize_plan(raw, ASSISTANTS, TEMPLATES, BASES, default_base="conn.gpt", may_create=True, web_allowed=False)
    assert plan["action"] == "template" and plan["decision"]["spec"]["base"] == "conn.claude" and plan["webSearch"] is False
    assert desk.raw_from_answers({"assistant": {"choice": "new"}, "base": {"choice": "m1"}}, keys, "r") is None
    # the web switch is off: a decision cannot turn web search on
    raw = desk.raw_from_answers({"assistant": {"choice": "a1"}, "base": {"choice": "m1"}, "web_search": {"noul": 1}}, keys, "r")
    assert desk.normalize_plan(raw, ASSISTANTS, TEMPLATES, BASES, default_base="conn.gpt", may_create=True, web_allowed=False)["webSearch"] is False


def test_answer_decision_keeps_the_users_assistant():
    from open_webui.utils import answer_desk as desk

    _, questions, keys = desk.decision_request("q", ASSISTANTS, TEMPLATES, BASES, default_base="conn.gpt", web_allowed=True, chosen="model:sql")
    assert "assistant" not in questions and "web_search" in questions
    raw = desk.raw_from_answers({"base": {"choice": "m1"}, "web_search": {"noul": 0.9}}, keys, "r", chosen="model:sql")
    plan = desk.normalize_plan(raw, ASSISTANTS, TEMPLATES, BASES, default_base="conn.gpt", may_create=True, web_allowed=True, chosen="model:sql")
    assert plan["decision"]["target"]["ref"] == "model:sql" and plan["webSearch"] is True


# --- 讨论 -------------------------------------------------------------------------------------


POOL = [{"id": n, "name": n, "vision": n != "deepseek-chat", "ref": f"conn.{n}", "profile": {"family": n.split("-")[0]}}
        for n in ("gpt-chat", "claude-chat", "deepseek-chat", "gemini-chat")]


def test_discussion_decision_sets_format_rounds_and_distinct_seats():
    from open_webui.utils import discussion_room as room

    draft = {"mode": "roundtable", "rounds": 2, "reason": "r",
             "seats": [{"model": "conn.gpt-chat", "role": "架构师", "duty": "看架构"}, {"model": "conn.claude-chat", "role": "风险", "duty": "看风险"}]}
    ask = {"question": "选 A 还是 B", "files": [{"type": "image"}]}
    state, questions, keys = room.plan_decision_request(ask=ask, pool=POOL, draft=draft)
    assert "deepseek-chat" not in json.dumps(questions)  # images: only models that see them
    assert set(questions) == {"mode", "rounds", "seat1", "seat2"} and state["seats"][0]["role"] == "架构师"
    first = next(k for k, v in keys["model"].items() if v == "gemini-chat")
    answers = {"mode": {"choice": "debate"}, "rounds": {"choice": "r4"},
               "seat1": {"choice": first, "probabilities": {first: 0.9}},
               "seat2": {"choice": first, "probabilities": {first: 0.6, "m1": 0.3}}}
    plan = room.plan_from_decision(answers, keys, draft, POOL, "")
    assert plan["mode"] == "debate" and plan["rounds"] == 4
    assert [s["model"] for s in plan["seats"]] == ["conn.gemini-chat", "conn.gpt-chat"]  # no model twice
    assert [s["role"] for s in plan["seats"]] == ["正方", "反方"]  # a debate gets sides
    answers["mode"] = {"choice": "compare"}
    assert room.plan_from_decision(answers, keys, draft, POOL, "")["rounds"] == 1


def test_discussion_match_decision():
    from open_webui.utils import discussion_room as room

    seats = [{"id": "s1", "role": "架构师"}, {"id": "s2", "role": "风险"}, {"id": "s3"}]
    _, questions, keys = room.match_decision_request(ask={"question": "q", "mode": "roundtable"}, seats=seats,
                                                     assistants=ASSISTANTS, templates=TEMPLATES, last={"s1": "SQL 专家"})
    assert set(questions) == {"s1", "s2", "s3"} and {"generic", "new"} <= set(questions["s1"]["criteria"])
    raw, new = room.match_from_decision({"s1": {"choice": "a1"}, "s2": {"choice": "generic"}, "s3": {"choice": "new"}}, keys, seats, "r")
    assert new == ["s3"] and [u["action"] for u in raw["units"]] == ["use", "generic"] and raw["units"][0]["ref"] == "model:sql"


# --- 协作 -------------------------------------------------------------------------------------


TEAM_PLAN = {
    "summary": "s",
    "members": [
        {"name": "dev", "role": "开发", "kind": "code", "executor": "cchclaude", "executor_source": "auto", "recommended": "cchclaude",
         "model": "gpt-chat", "model_source": "lead", "assistant": {"ref": "builtin:dev", "name": "开发", "action": "template"}},
        {"name": "ui", "role": "界面", "kind": "ui", "executor": "agy", "executor_source": "user", "model": "claude-chat", "model_source": "user",
         "assistant_preferred": True},
        {"name": "art", "role": "配图", "kind": "image", "executor": "hermes", "executor_source": "auto", "model": "gpt-chat", "model_source": "default"},
    ],
    "tasks": [{"key": "T1", "title": "写代码", "member": "dev"}],
}
OPTIONS = {
    "models": [{"model": "gpt-chat", "default": True, "hint": "强"}, {"model": "claude-chat", "default": False, "hint": "写"}],
    "executors": [{"name": "hermes", "label": "Hermes", "available": True}, {"name": "codex", "label": "Codex", "available": True},
                  {"name": "cchclaude", "label": "cch", "available": True}, {"name": "agy", "label": "agy", "available": False}],
}
REQUEST = SimpleNamespace(state=SimpleNamespace(MODELS={"conn.judge": {"id": "conn.judge"}}, MODELS_AMBIGUOUS=set()))
TEAM_LIBRARY = {"assistants": [{"ref": "model:sql", "name": "SQL 专家", "description": "d"}], "templates": []}


def test_team_decision_asks_only_what_is_automatic():
    from open_webui.utils import team_decision as td

    state, questions, keys = td.decision_request("做个工具", TEAM_PLAN, OPTIONS, TEAM_LIBRARY)
    assert set(questions) == {"exec_1", "model_1", "assistant_1", "model_3", "assistant_3"}
    assert "agy" not in json.dumps(keys["exec_1"])  # unavailable executors are not offered
    assert state["members"][0]["tasks"] == ["写代码"]
    answers = {
        "exec_1": {"choice": next(k for k, v in keys["exec_1"][2].items() if v == "codex")},
        "model_1": {"choice": "o1"},  # gpt-chat: what it has already
        "assistant_1": {"choice": "a1"},
        "model_3": {"choice": "o2"},
        "assistant_3": {"choice": "keep"},
    }
    picks = td.picks_from_answers(answers, keys, TEAM_PLAN, "r")
    assert picks == {"dev": {"reason": "r", "executor": "codex", "assistant": "model:sql"}, "art": {"reason": "r", "model": "claude-chat"}}


def test_team_decision_failure_keeps_the_leads_plan(monkeypatch):
    from open_webui.utils import agent_teams, team_decision as td

    _configured(monkeypatch)

    async def call(self, payload):
        return {"choices": [{"message": {"content": json.dumps({"answers": {}})}}]}

    async def hermes(*a, **k):
        raise AssertionError("nothing to apply")

    monkeypatch.setattr(dm.Decider, "_call", call)
    monkeypatch.setattr(agent_teams, "hermes_call", hermes)
    team = SimpleNamespace(goal="做个工具")
    out = run(td.assist(REQUEST, USER, None, team, TEAM_PLAN, OPTIONS, TEAM_LIBRARY))
    assert out["members"] == TEAM_PLAN["members"] and out["decider"]["fallback"]
    assert "缺少" in out["decider"]["reason"]  # an answer missing questions is not used


def test_team_decision_applies_through_hermes(monkeypatch):
    from open_webui.utils import agent_teams, team_decision as td

    _configured(monkeypatch)

    async def call(self, payload):
        questions = json.loads(payload["messages"][1]["content"])["questions"]
        answers = {q: {"choice": "keep" if q.startswith("assistant") else next(iter(v["criteria"]))} for q, v in questions.items()}
        return {"choices": [{"message": {"content": json.dumps({"answers": answers})}}]}

    sent = []

    async def hermes(target, method, path, json_body=None, timeout=None):
        sent.append((path, json_body["picks"]))
        return {"ok": True, "plan": {**json_body["plan"], "checked": True}}

    monkeypatch.setattr(dm.Decider, "_call", call)
    monkeypatch.setattr(agent_teams, "hermes_call", hermes)
    out = run(td.assist(REQUEST, USER, None, SimpleNamespace(goal="g"), TEAM_PLAN, OPTIONS, TEAM_LIBRARY))
    assert sent, out.get("decider")
    assert sent[0][0] == "/plan/decide" and sent[0][1]["dev"]["executor"] == "hermes"
    assert out["checked"] and out["decider"]["used"] and out["decider"]["result"]["picks"]["dev"] == {"executor": "hermes"}
