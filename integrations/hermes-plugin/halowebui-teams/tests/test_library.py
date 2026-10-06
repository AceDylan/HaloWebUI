"""The user's assistants (助手库) in a plan: the lead picks, upgrades or proposes them per member;
the validator records the decisions (limits, merging, permissions, the user's preferred
assistant) and writes nothing; at approval HaloWebUI's snapshot of each member's assistant is
what the task bodies use."""

import copy
import json

import pytest

LONG = "你是一位资深的数据可视化分析师。先澄清目标和读者，再选图表类型、核对数据口径，最后自查数字和单位。输出：结论、图表说明、数据来源。不知道就说不知道。"

LIBRARY = {
    "may_write": True,
    "assistants": [
        {"ref": "model:asst-viz", "name": "图表分析师", "emoji": "📊", "domain": "数据", "description": "把数据做成图表",
         "editable": True, "version": 3, "prompt": "你是图表分析师…"},
        {"ref": "model:asst-law", "name": "合同审阅", "emoji": "⚖️", "domain": "法务", "description": "审阅合同风险",
         "editable": False, "version": 1, "prompt": "你是合同审阅…"},
        {"ref": "model:asst-seo", "name": "SEO 顾问", "emoji": "🔎", "domain": "增长", "description": "搜索优化",
         "editable": True, "version": 2, "prompt": "你是 SEO 顾问…"},
        {"ref": "model:asst-cn", "name": "中文润色", "emoji": "✍️", "domain": "写作", "description": "润色中文稿件",
         "editable": True, "version": 1, "prompt": "你是中文润色…"},
    ],
    "templates": [{"ref": "builtin:4", "name": "内容运营", "description": "内容运营", "prompt": "…"}],
    "preferred": [],
}

PLAN = {
    "title": "季度数据报告",
    "summary": "分析、作图、写报告、评审",
    "members": [
        {"name": "analyst", "role": "数据分析", "assistant": "model:asst-viz", "assistant_reason": "做图表的老手", "focus": "分析销量"},
        {"name": "charter", "role": "作图", "assistant": "model:asst-viz", "focus": "画图"},
        {"name": "writer", "role": "撰写报告", "assistant": "new:A1", "focus": "写报告"},
        {"name": "editor", "role": "编辑", "assistant": "new:A1", "focus": "润色报告"},
        {"name": "reviewer", "role": "评审", "assistant": "18", "focus": "检查"},
    ],
    "tasks": [
        {"key": "T1", "title": "分析销量数据", "description": "写 analysis.md", "member": "analyst", "depends_on": []},
        {"key": "T2", "title": "画图", "description": "写 charts.md", "member": "charter", "depends_on": ["T1"]},
        {"key": "T3", "title": "写报告", "description": "写 report.md", "member": "writer", "depends_on": ["T2"]},
        {"key": "T4", "title": "润色", "description": "改 report.md", "member": "editor", "depends_on": ["T3"]},
        {"key": "T5", "title": "评审", "description": "检查 report.md", "member": "reviewer", "depends_on": ["T4"]},
    ],
    "assistant_upgrades": [
        {"ref": "model:asst-viz", "change": "会核对数据口径", "system_prompt": LONG},
        {"ref": "model:asst-viz", "change": "重复的一条", "system_prompt": LONG + "（重复）"},
    ],
    "new_assistants": [
        {"key": "A1", "name": "报告撰稿人", "emoji": "📝", "domain": "写作", "description": "把分析写成报告", "system_prompt": LONG},
    ],
}


@pytest.fixture
def lib(pkg):
    import halowebui_teams.library as library

    return library


def _validate(pkg, lib, plan, library=LIBRARY):
    return pkg.plan.validate_plan(copy.deepcopy(plan), library=lib.usable(copy.deepcopy(library)))


def test_the_prompt_lists_the_library_only_when_halowebui_sent_one(pkg, lib):
    plain = pkg.plan.system_prompt()
    assert '"assistant": "17"' in plain and "assistant_upgrades" not in plain and "你的助手库" not in plain
    with_lib = pkg.plan.system_prompt(lib.usable({**LIBRARY, "preferred": ["model:asst-seo"]}))
    assert "model:asst-viz：📊 图表分析师（数据）" in with_lib and "｜可升级" in with_lib
    assert "assistant_upgrades" in with_lib and "new_assistants" in with_lib and "new:A1" in with_lib
    assert "绝不写进助手设定" in with_lib and "最多升级 2 个助手、新建 2 个" in with_lib
    assert "model:asst-seo（SEO 顾问）" in with_lib  # the user's pick
    assert "builtin:4：内容运营" in with_lib  # a shortlisted template beyond 「协作」
    no_write = pkg.plan.system_prompt(lib.usable({**LIBRARY, "may_write": False}))
    assert "没有保存助手的权限" in no_write


def test_decisions_are_recorded_merged_and_nothing_is_written(pkg, lib):
    plan, errors = _validate(pkg, lib, PLAN)
    assert not errors
    by = {m["name"]: m["assistant"] for m in plan["members"]}
    assert by["analyst"]["action"] == "update" and by["analyst"]["proposal"] == "model:asst-viz"
    assert by["analyst"]["reason"] == "做图表的老手" and by["analyst"]["version"] == 3
    assert by["charter"]["action"] == "update" and by["charter"]["proposal"] == "model:asst-viz"
    assert by["writer"]["action"] == "create" and by["editor"]["proposal"] == by["writer"]["proposal"] == "new:A1"
    assert by["reviewer"]["action"] == "template" and by["reviewer"]["ref"] == "builtin:18"
    proposals = {p["key"]: p for p in plan["assistant_proposals"]}
    # one upgrade per assistant (the first), one new assistant shared by two members
    assert set(proposals) == {"model:asst-viz", "new:A1"}
    assert proposals["model:asst-viz"]["system_prompt"] == LONG and proposals["model:asst-viz"]["change"] == "会核对数据口径"
    assert proposals["new:A1"]["name"] == "报告撰稿人" and proposals["new:A1"]["action"] == "create"
    assert plan["assistant_library"] == {"may_write": True}


def test_limits_permissions_and_unknown_refs(pkg, lib):
    raw = copy.deepcopy(PLAN)
    raw["members"][4]["assistant"] = "model:asst-law"
    raw["members"].append({"name": "seo", "role": "SEO", "assistant": "model:asst-seo"})
    raw["members"].append({"name": "polish", "role": "润色", "assistant": "model:asst-cn"})
    raw["tasks"] += [{"key": "T6", "title": "SEO", "description": "x", "member": "seo", "depends_on": []},
                     {"key": "T7", "title": "润色", "description": "x", "member": "polish", "depends_on": []}]
    raw["members"] = raw["members"][:6]  # MAX_MEMBERS
    raw["members"][3]["assistant"] = "new:A3"
    raw["tasks"] = [t for t in raw["tasks"] if t["member"] in {m["name"] for m in raw["members"]}]
    raw["assistant_upgrades"] = [
        {"ref": "model:asst-viz", "system_prompt": LONG},
        {"ref": "model:asst-seo", "system_prompt": LONG},
        {"ref": "model:asst-law", "system_prompt": LONG},  # not editable → this run only
        {"ref": "model:asst-cn", "system_prompt": LONG},  # a third upgrade → used as it is
        {"ref": "model:gone", "system_prompt": LONG},  # not in the library → ignored
    ]
    raw["new_assistants"] = [
        {"key": "A1", "name": "报告撰稿人", "system_prompt": LONG},
        {"key": "A2", "name": "另一个", "system_prompt": LONG},
        {"key": "A3", "name": "第三个", "system_prompt": LONG},
        {"key": "A4", "name": "太短", "system_prompt": "短"},
    ]
    raw["members"][2]["assistant"] = "new:A2"
    plan, errors = _validate(pkg, lib, raw)
    assert not errors, errors
    by = {m["name"]: m["assistant"] for m in plan["members"]}
    assert by["analyst"]["action"] == "update" and by["seo"]["action"] == "update"
    assert by["reviewer"]["action"] == "temporary" and "权限" in by["reviewer"]["note"]
    assert by["writer"]["action"] == "create" and by["editor"]["action"] == "create"  # A2 and A3: the two allowed
    keys = {p["key"]: p["action"] for p in plan["assistant_proposals"]}
    assert keys == {"model:asst-viz": "update", "model:asst-seo": "update", "model:asst-law": "temporary",
                    "new:A2": "create", "new:A3": "create"}
    # no right to save: every upgrade / new one is for this run only
    plan, _ = _validate(pkg, lib, PLAN, {**LIBRARY, "may_write": False})
    assert {m["assistant"]["action"] for m in plan["members"][:4]} == {"temporary"}
    # an assistant the library does not have is no assistant
    raw = copy.deepcopy(PLAN)
    raw["members"][0]["assistant"] = "model:deleted"
    plan, _ = _validate(pkg, lib, raw)
    assert plan["members"][0]["assistant"] is None


def test_a_third_upgrade_is_used_as_it_is(pkg, lib):
    raw = copy.deepcopy(PLAN)
    raw["members"][2]["assistant"] = "model:asst-seo"
    raw["members"][3]["assistant"] = "model:asst-cn"
    raw["assistant_upgrades"] = [{"ref": r, "system_prompt": LONG} for r in ("model:asst-viz", "model:asst-seo", "model:asst-cn")]
    plan, _ = _validate(pkg, lib, raw)
    by = {m["name"]: m["assistant"] for m in plan["members"]}
    assert by["editor"]["action"] == "use" and "已升级 2 个" in by["editor"]["note"]


def test_a_new_assistant_named_like_a_library_one_is_that_one(pkg, lib):
    raw = copy.deepcopy(PLAN)
    raw["new_assistants"][0]["name"] = "中文润色"
    plan, _ = _validate(pkg, lib, raw)
    writer = plan["members"][2]["assistant"]
    assert writer["action"] == "use" and writer["ref"] == "model:asst-cn" and "同名" in writer["note"]
    assert all(p["key"] != "new:A1" for p in plan.get("assistant_proposals") or [])


def test_the_users_preferred_assistant_gets_a_member(pkg, lib):
    raw = copy.deepcopy(PLAN)
    raw["members"].append({"name": "seo-writer", "role": "搜索优化", "assistant": None, "focus": "搜索关键词和标题"})
    raw["tasks"].append({"key": "T6", "title": "SEO 标题", "description": "x", "member": "seo-writer", "depends_on": []})
    plan, _ = _validate(pkg, lib, raw, {**LIBRARY, "preferred": ["model:asst-seo"]})
    member = next(m for m in plan["members"] if m["name"] == "seo-writer")
    assert member["assistant"]["ref"] == "model:asst-seo" and member["assistant"]["action"] == "use"
    assert member["assistant_preferred"] is True
    # already used by the lead: nothing changes
    raw["members"][-1]["assistant"] = "model:asst-seo"
    plan, _ = _validate(pkg, lib, raw, {**LIBRARY, "preferred": ["model:asst-seo"]})
    assert not any(m.get("assistant_preferred") for m in plan["members"])
    # a template the user picked
    plan, _ = _validate(pkg, lib, PLAN, {**LIBRARY, "preferred": ["builtin:590"]})
    picked = [m for m in plan["members"] if (m["assistant"] or {}).get("ref") == "builtin:590"]
    assert len(picked) == 1 and picked[0]["assistant"]["action"] == "template"


def test_a_stored_plan_keeps_its_decisions_when_validated_again(pkg, lib):
    plan, _ = _validate(pkg, lib, PLAN)
    again, errors = pkg.plan.validate_plan(json.loads(json.dumps(plan)))
    assert not errors
    assert [m["assistant"] for m in again["members"]] == [m["assistant"] for m in plan["members"]]
    assert again["assistant_proposals"] == plan["assistant_proposals"]
    assert again["assistant_library"] == {"may_write": True}
    # the lead sees them on a re-plan
    for_lead = pkg.plan._plan_for_lead(plan)
    assert [m["assistant"] for m in for_lead["members"]] == ["model:asst-viz", "model:asst-viz", "new:A1", "new:A1", "builtin:18"]
    assert for_lead["assistant_upgrades"][0]["ref"] == "model:asst-viz"
    assert for_lead["new_assistants"][0]["key"] == "A1"


def test_an_old_plan_still_reads_its_template_ids(pkg):
    raw = {"title": "x", "members": [{"name": "dev", "role": "开发", "assistant": "17"}],
           "tasks": [{"key": "T1", "title": "写", "description": "写", "member": "dev", "depends_on": []}]}
    plan, _ = pkg.plan.validate_plan(raw)
    assert plan["members"][0]["assistant"]["id"] == "17" and plan["members"][0]["assistant"]["action"] == "template"
    old = {**raw, "members": [{"name": "dev", "role": "开发", "assistant": {"id": "17", "name": "开发工程师"}}]}
    plan, _ = pkg.plan.validate_plan(old)
    assert plan["members"][0]["assistant"]["ref"] == "builtin:17"


def test_propose_plan_hands_the_library_to_the_lead(pkg, lib, monkeypatch):
    seen = {}

    def fake(messages, **kwargs):
        seen["system"] = messages[0]["content"]
        return json.dumps(PLAN, ensure_ascii=False), "", {"model": "gpt-chat"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
    result = pkg.plan.propose_plan("季度数据报告", "/tmp/x", library=copy.deepcopy(LIBRARY))
    assert result["ok"] and "model:asst-viz" in seen["system"]
    assert result["plan"]["members"][0]["assistant"]["action"] == "update"


def test_the_snapshot_from_halowebui_is_the_members_role(pkg, lib, team_id):
    plan, _ = _validate(pkg, lib, PLAN)
    snapshots = {
        "analyst": {"action": "update", "ref": "model:asst-viz", "id": "asst-viz", "name": "图表分析师", "emoji": "📊",
                    "version": 4, "system": "第四版设定：" + LONG + "\n我的第一个请求是：画一张图"},
        "writer": {"action": "create", "ref": "model:asst-new", "id": "asst-new", "name": "报告撰稿人", "version": 1, "system": LONG},
        "editor": {"action": "generic", "note": "「报告撰稿人」已不在助手库，按角色执行"},
        "reviewer": {"action": "template", "ref": "builtin:18", "id": "builtin:18", "name": "测试工程师", "system": "模板设定" * 20},
    }
    pkg.teams.create_team(team_id, plan, owner="u1", goal="季度数据报告", member_assistants=snapshots)
    team = pkg.common.read_team(pkg.common.board_slug(team_id))
    members = {m["name"]: m for m in team["members"]}
    tasks = {t["key"]: t for t in plan["tasks"]}
    body = pkg.teams._task_body(team, tasks["T1"], members["analyst"])
    assert "来自 HaloWebUI 助手「图表分析师」，第 4 版" in body and "第四版设定" in body
    assert "我的第一个请求是" not in body  # cleaned like a template
    assert members["analyst"]["assistant"]["version"] == 4 and members["analyst"]["assistant"]["action"] == "update"
    assert "角色设定" not in pkg.teams._task_body(team, tasks["T4"], members["editor"])
    assert members["editor"]["assistant"] is None and "不在助手库" in members["editor"]["assistant_note"]
    assert "助手模板「测试工程师」" in pkg.teams._task_body(team, tasks["T5"], members["reviewer"])
    # charter got no snapshot: a plan member without one keeps the old lookup (nothing for a library ref)
    assert "角色设定" not in pkg.teams._task_body(team, tasks["T2"], members["charter"])
    snap = pkg.teams.snapshot(team_id, owner="u1")
    assert all("assistant_prompt" not in m for m in snap["members"])


def test_a_plan_without_snapshots_uses_the_template_catalog(pkg, team_id):
    raw = {"title": "x", "members": [{"name": "dev", "role": "开发", "assistant": "17"}],
           "tasks": [{"key": "T1", "title": "写", "description": "写", "member": "dev", "depends_on": []}]}
    plan, _ = pkg.plan.validate_plan(raw)
    pkg.teams.create_team(team_id, plan, owner="u1", goal="写")
    team = pkg.common.read_team(pkg.common.board_slug(team_id))
    assert "助手模板「开发工程师」" in pkg.teams._task_body(team, plan["tasks"][0], team["members"][0])
