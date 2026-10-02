"""Hermes members' models: the lead recommends one per member, the user can change it before
approval, and every task is created with its member's model and provider pinned (so a Hermes
worker never depends on the CLI's own resolution of the default)."""

CFG = {
    "model": {"default": "gpt-chat", "provider": "custom:gw.example:23001"},
    "custom_providers": [
        {"name": "gw.example:23001", "model": "gpt-chat", "base_url": "https://gw.example:23001/v1"},
        {"name": "deepseek-chat", "model": "deepseek-chat", "base_url": "https://gw.example:23001/v1"},
        {"name": "claude-chat", "model": "claude-chat", "base_url": "https://gw.example:23001/v1"},
    ],
    "fallback_providers": [{"provider": "custom", "model": "deepseek-chat"}],
}


def _cfg(pkg, monkeypatch, cfg=CFG):
    monkeypatch.setattr(pkg.plan, "_config", lambda: cfg)


def test_member_model_rules(pkg, monkeypatch):
    _cfg(pkg, monkeypatch)
    mm = pkg.plan.member_model
    assert mm({"model": "claude-chat"}) == {"model": "claude-chat", "model_source": "lead", "model_recommended": "claude-chat"}
    # not a model Hermes has, or none given: Hermes' default
    assert mm({"model": "gpt-9"}) == {"model": "gpt-chat", "model_source": "default", "model_recommended": "gpt-chat"}
    assert mm({}) == {"model": "gpt-chat", "model_source": "default", "model_recommended": "gpt-chat"}
    # the user's pick stays, with what the lead recommended beside it
    assert mm({"model": "deepseek-chat", "model_source": "user", "model_recommended": "claude-chat"}) == {
        "model": "deepseek-chat", "model_source": "user", "model_recommended": "claude-chat"}
    assert mm({"model": "deepseek-chat", "model_source": "user"})["model_recommended"] == "gpt-chat"
    assert [m["model"] for m in pkg.plan.hermes_models()] == ["gpt-chat", "deepseek-chat", "claude-chat"]
    assert pkg.plan.hermes_models()[0]["default"] is True and pkg.plan.hermes_models()[2]["hint"]
    # nothing configured (or unreadable): keep what was asked
    _cfg(pkg, monkeypatch, {})
    assert mm({"model": "x-chat"})["model"] == "x-chat" and mm({}) == {
        "model": "", "model_source": "default", "model_recommended": ""}


def test_the_lead_is_told_the_models_and_the_plan_keeps_its_picks(pkg, monkeypatch, plan_dict):
    _cfg(pkg, monkeypatch)
    prompt = pkg.plan.system_prompt()
    assert '"gpt-chat"（默认）' in prompt and '"claude-chat"：写作' in prompt and '"model"' in prompt
    plan_dict["members"][0]["model"] = "claude-chat"
    plan_dict["members"][1]["model"] = "nonsense"
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    by = {m["name"]: m for m in plan["members"]}
    assert (by["backend-dev"]["model"], by["backend-dev"]["model_source"]) == ("claude-chat", "lead")
    assert (by["frontend-dev"]["model"], by["frontend-dev"]["model_source"]) == ("gpt-chat", "default")
    # the user's pick survives re-validation (approval) and goes back to the lead on a re-plan
    by["frontend-dev"].update(model="deepseek-chat", model_source="user")
    again, _ = pkg.plan.validate_plan(plan)
    assert {m["name"]: m["model"] for m in again["members"]}["frontend-dev"] == "deepseek-chat"
    lead_view = pkg.plan._plan_for_lead(again)
    assert [m.get("model") for m in lead_view["members"]] == [None, "deepseek-chat", None]


def test_tasks_pin_their_members_model_and_provider(pkg, monkeypatch, team_id, plan_dict):
    _cfg(pkg, monkeypatch)
    plan_dict["members"][0]["model"] = "claude-chat"
    plan_dict["members"][1].update(model="deepseek-chat", model_source="user")
    plan, _ = pkg.plan.validate_plan(plan_dict)
    pkg.teams.create_team(team_id, plan, owner="u1", goal="做一个小工具")
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        rows = {r[0].split(" ", 1)[0]: (r[1], r[2]) for r in
                conn.execute("SELECT title, model_override, provider_override FROM tasks")}
    assert rows["T1"] == ("claude-chat", "custom:claude-chat")
    assert rows["T2"] == ("deepseek-chat", "custom:deepseek-chat")
    assert rows["T3"] == ("gpt-chat", "custom:gw.example:23001")  # the default, pinned explicitly
    snap = pkg.teams.snapshot(team_id)
    assert {t["key"]: t["model"] for t in snap["tasks"]} == {"T1": "claude-chat", "T2": "deepseek-chat", "T3": "gpt-chat"}
    assert {m["name"]: m["model"] for m in snap["members"]}["backend-dev"] == "claude-chat"
    assert pkg.plan.task_model({"model": "gone"}) == {"model_override": "gpt-chat",
                                                      "provider_override": "custom:gw.example:23001"}
