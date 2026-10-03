"""快答: a goal that is one simple question or fact check gets a plan marked effort "quick" — one
member answers it directly, the estimate comes from quick answers (not ten-minute research), and
the plan says so in HaloWebUI and on Telegram."""

import copy

import pytest

QUICK_PLAN = {
    "title": "核查开播状态",
    "summary": "一名调研成员查实时来源，确认是否开播",
    "effort": "quick",
    "members": [{"name": "researcher", "role": "调研", "kind": "research", "focus": "查证"}],
    "tasks": [{"key": "T1", "title": "核实当前开播状态", "description": "查询旭旭宝宝当前是否在直播，给出来源和时间",
               "member": "researcher", "depends_on": []}],
}


@pytest.fixture
def quick_plan():
    return copy.deepcopy(QUICK_PLAN)


def test_a_quick_plan_keeps_its_effort_only_where_it_fits(pkg, quick_plan, plan_dict):
    plan, errors = pkg.plan.validate_plan(quick_plan)
    assert not errors and plan["effort"] == "quick"
    # a second task, an image, code or a project is not a quick answer
    two = copy.deepcopy(quick_plan)
    two["tasks"].append({"key": "T2", "title": "复核", "description": "复核", "member": "researcher", "depends_on": ["T1"]})
    assert "effort" not in pkg.plan.validate_plan(two)[0]
    for kind in ("image", "code"):
        other = copy.deepcopy(quick_plan)
        other["members"][0]["kind"] = kind
        assert "effort" not in pkg.plan.validate_plan(other)[0]
    project = dict(copy.deepcopy(quick_plan), project={"path": "/root/HaloWebUI", "name": "HaloWebUI"})
    assert "effort" not in pkg.plan.validate_plan(project)[0]
    plan_dict["effort"] = "quick"  # three members
    assert "effort" not in pkg.plan.validate_plan(plan_dict)[0]
    # an unmarked plan stays unmarked; a re-plan shows the lead what it decided
    assert "effort" not in pkg.plan.validate_plan(dict(quick_plan, effort=None))[0]
    assert pkg.plan._plan_for_lead(plan)["effort"] == "quick"
    assert "\"effort\": \"quick" in pkg.plan.system_prompt() and "快答" in pkg.plan.system_prompt()


def test_a_quick_members_task_asks_for_a_direct_answer(pkg, quick_plan, plan_dict, team_id):
    import uuid

    plan, _ = pkg.plan.validate_plan(quick_plan)
    pkg.teams.create_team(team_id, plan, owner="u1", goal="旭旭宝宝停播开播了吗")
    team = pkg.common.read_team(pkg.common.board_slug(team_id))
    assert team["effort"] == "quick"
    body = pkg.teams._task_body(team, plan["tasks"][0], plan["members"][0])
    assert "快答任务" in body and "smart-search research --budget quick" in body and "不必另写文件" in body
    assert "不要写 Obsidian" in body
    other, _ = pkg.plan.validate_plan(plan_dict)
    other_id = str(uuid.uuid4())
    pkg.teams.create_team(other_id, other, owner="u1", goal="做个小工具")
    normal = pkg.common.read_team(pkg.common.board_slug(other_id))
    assert normal["effort"] == "" and "快答任务" not in pkg.teams._task_body(normal, other["tasks"][0], other["members"][0])


def test_a_quick_answer_is_estimated_from_quick_answers(pkg, quick_plan, team_id, monkeypatch):
    import halowebui_teams.progress as progress
    from hermes_cli import kanban_db as kb

    plan, _ = pkg.plan.validate_plan(quick_plan)
    # no history yet: the quick prior, not the research median
    stats = {"task": {"hermes/research": {"n": 9, "median": 480, "p75": 650}}, "task_all": None,
             "conclusion": {"n": 9, "median": 25, "p75": 40}, "acceptance": {"n": 6, "median": 5, "p75": 8}}
    monkeypatch.setattr(progress, "history", lambda force=False: stats)
    est = progress.estimate_plan(plan)
    assert est["seconds"] == progress.DEFAULTS["quick"] + 25 + 5 and "快答" in est["basis"]
    assert progress.estimate_plan(dict(plan, effort=None))["seconds"] == 480 + 25 + 5
    # the quick team's own runs land under hermes/quick, not in the research or overall medians
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="旭旭宝宝停播开播了吗")
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        tid = created["tasks"]["T1"]
        assert kb.claim_task(conn, tid, claimer="test") is not None
        kb.complete_task(conn, tid, result="没有开播", summary="没有开播")
        conn.execute("UPDATE task_runs SET started_at = ended_at - 90")
        conn.commit()
    monkeypatch.setattr(progress, "MIN_SAMPLES", 1)
    monkeypatch.setattr(progress, "team_boards", lambda: [slug])
    real = progress._collect()
    assert real["task"]["hermes/quick"]["median"] == 90
    assert "hermes/research" not in real["task"] and "hermes" not in real["task"] and real["task_all"] is None
    assert progress.typical("task", "hermes", real, "quick")["basis"] == "本机最近 1 次 hermes 快答"


def test_the_plan_card_says_it_is_a_quick_answer(pkg, quick_plan):
    import halowebui_teams.notify as notify

    plan, _ = pkg.plan.validate_plan(quick_plan)
    text, _ = notify.plan_message({"id": "t1", "title": "核查开播状态", "plan": plan})
    assert "计划好了 · 快答" in text.splitlines()[0]
    text, _ = notify.plan_message({"id": "t1", "title": "x", "plan": dict(plan, effort=None)})
    assert "快答" not in text.splitlines()[0]
