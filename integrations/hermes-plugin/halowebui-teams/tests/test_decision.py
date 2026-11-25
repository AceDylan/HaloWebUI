"""HaloWebUI's 辅助决策模型 picks members' executors, models and assistants after the lead's plan
(POST /plan/decide): only what is still automatic changes, and the plan is validated again."""

from test_models import _cfg

LIBRARY = {
    "may_write": True,
    "assistants": [{"ref": "model:sql-pro", "id": "sql-pro", "name": "SQL 专家", "emoji": "🗄", "description": "查询优化",
                    "domain": "数据库", "editable": True, "version": 2, "prompt": "你是 SQL 专家"}],
    "templates": [],
    "preferred": [],
}


def _auto_plan(pkg, plan_dict):
    for m in plan_dict["members"]:
        m.pop("executor", None)  # chosen by kind, not named in the goal
    plan_dict["members"][0]["kind"] = "code"
    plan_dict["members"][1]["kind"] = "ui"
    plan_dict["members"][2]["kind"] = "writing"
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    return plan


def test_decision_picks_apply_to_what_is_automatic(pkg, monkeypatch, plan_dict):
    _cfg(pkg, monkeypatch)
    plan = _auto_plan(pkg, plan_dict)
    by = {m["name"]: m for m in plan["members"]}
    assert by["backend-dev"]["executor_source"] == "auto"
    by["frontend-dev"].update(executor="agy", executor_source="user", model="deepseek-chat", model_source="user")
    picks = {
        "backend-dev": {"executor": "codex", "model": "claude-chat", "assistant": "model:sql-pro", "reason": "r"},
        "frontend-dev": {"executor": "codex", "model": "claude-chat"},  # the user's picks stay
        "reviewer": {"executor": "nonsense", "model": "gpt-9"},  # outside the options: ignored
    }
    decided, errors = pkg.plan.apply_decision(plan, picks, {**LIBRARY})
    assert not errors
    out = {m["name"]: m for m in decided["members"]}
    assert (out["backend-dev"]["executor"], out["backend-dev"]["executor_source"], out["backend-dev"]["runner"]) == (
        "codex", "decision", "codex")
    assert (out["backend-dev"]["model"], out["backend-dev"]["model_source"]) == ("claude-chat", "decision")
    assert out["backend-dev"]["assistant"]["ref"] == "model:sql-pro" and out["backend-dev"]["assistant"]["action"] == "use"
    assert (out["frontend-dev"]["executor"], out["frontend-dev"]["executor_source"]) == ("agy", "user")
    assert (out["frontend-dev"]["model"], out["frontend-dev"]["model_source"]) == ("deepseek-chat", "user")
    assert out["reviewer"]["executor_source"] == "auto" and out["reviewer"]["model"] == "gpt-chat"
    # the decided start survives a later re-validation (approval / runner change)
    again, _ = pkg.plan.validate_plan(decided)
    assert {m["name"]: (m["executor"], m["executor_source"]) for m in again["members"]}["backend-dev"] == ("codex", "decision")


def test_decision_keeps_image_members_goal_executors_and_preferred_assistants(pkg, monkeypatch, plan_dict):
    _cfg(pkg, monkeypatch)
    plan_dict["members"][0]["executor"] = "reclaude"  # named in the goal
    plan_dict["members"][2]["kind"] = "image"
    plan, _ = pkg.plan.validate_plan(plan_dict)
    plan["members"][1]["assistant_preferred"] = True
    plan["members"][1]["assistant"] = {"action": "template", "ref": "builtin:x", "id": "x", "name": "X"}
    decided, errors = pkg.plan.apply_decision(plan, {
        "backend-dev": {"executor": "codex"},
        "frontend-dev": {"assistant": "model:sql-pro"},
        "reviewer": {"executor": "codex"},
    }, {**LIBRARY})
    assert not errors
    out = {m["name"]: m for m in decided["members"]}
    assert (out["backend-dev"]["executor"], out["backend-dev"]["executor_source"]) == ("reclaude", "goal")
    assert out["frontend-dev"]["assistant"]["ref"] == "builtin:x"
    assert out["reviewer"]["executor"] == "hermes"


def test_decision_falls_back_along_the_chain_when_its_pick_is_down(pkg, monkeypatch, plan_dict, availability):
    _cfg(pkg, monkeypatch)
    plan = _auto_plan(pkg, plan_dict)
    availability.down["offiagy"] = "额度用完"
    decided, _ = pkg.plan.apply_decision(plan, {"backend-dev": {"executor": "offiagy"}})
    member = decided["members"][0]
    # the model's pick is automatic, not the user's: it still falls back in its family
    assert member["executor"] == "offiagy" and member["executor_source"] == "decision"
    assert member["runner"] == "agy" and member["runner_note"]


def test_decision_picks_the_engine_not_the_order_inside_it(pkg, monkeypatch, plan_dict, availability):
    _cfg(pkg, monkeypatch)
    plan = _auto_plan(pkg, plan_dict)
    decided, _ = pkg.plan.apply_decision(plan, {"backend-dev": {"executor": "anyclaude"},  # same family: no change
                                                "reviewer": {"executor": "reclaude"}})     # another: its first runner
    out = {m["name"]: (m["executor"], m["executor_source"]) for m in decided["members"]}
    assert out["backend-dev"] == ("officlaude", "auto") and out["reviewer"] == ("officlaude", "decision")


def test_decision_leaves_a_template_plan_alone(pkg, monkeypatch, availability):
    _cfg(pkg, monkeypatch)
    plan = pkg.plan.propose_plan("修接口", "/tmp/ws", workflow="dev_lite")["plan"]
    decided, errors = pkg.plan.apply_decision(plan, {"codex-dev": {"executor": "hermes"}})
    assert not errors and {m["name"]: m["executor"] for m in decided["members"]}["codex-dev"] == "codex"


def test_decision_chosen_task_falls_back_at_runtime(pkg, monkeypatch, team_id, plan_dict, availability):
    import halowebui_teams.fallback as fallback

    _cfg(pkg, monkeypatch)
    plan, _ = pkg.plan.apply_decision(_auto_plan(pkg, plan_dict), {"backend-dev": {"executor": "offiagy"}})
    first = pkg.teams.create_team(team_id, plan, owner="u1", goal="g")
    slug, t1 = first["board"], first["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        assert fallback.reroute(slug, conn, t1, "offiagy", "额度用完", phase="launch") == "agy"


def test_decision_options_and_bad_input(pkg, monkeypatch, plan_dict, availability):
    _cfg(pkg, monkeypatch)
    availability.down["offiagy"] = "地区限制"
    availability.down["codex"] = "未登录"
    options = pkg.plan.decision_options()
    assert [m["model"] for m in options["models"]] == ["gpt-chat", "deepseek-chat", "claude-chat"]
    by = {e["name"]: e for e in options["executors"]}
    assert set(by) == {"officlaude", "codex", "offiagy", "hermes"}  # one per engine family
    assert by["offiagy"]["available"] is True  # agy of its family can run
    assert by["codex"]["available"] is False and by["hermes"]["available"] is True
    assert options["kinds"]["ui"] == "offiagy"
    assert pkg.plan.apply_decision("x", {})[0] is None
    assert pkg.plan.apply_decision(plan_dict, None)[0] is None
