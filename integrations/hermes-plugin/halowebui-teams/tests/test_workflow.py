"""Multi-model dev pipeline templates (workflow.py) and per-family runner overrides."""

import pytest


def test_dev_pipeline_full_dag_matches_reference_workflow(pkg, availability):
    res = pkg.plan.propose_plan(
        "给协作台增加多模型研发流水线和审批界面",
        "/tmp/ws",
        workflow="dev_pipeline",
    )
    assert res["ok"] is True
    plan = res["plan"]
    assert plan["workflow"] == "dev_pipeline"
    members = {m["name"]: m for m in plan["members"]}
    assert set(members) == {"claude-lead", "agy-advisor", "codex-dev"}
    assert members["claude-lead"]["executor"] == "officlaude"
    assert members["claude-lead"]["executor_source"] == "auto"
    assert members["agy-advisor"]["executor"] == "offiagy"
    assert members["agy-advisor"]["executor_source"] == "auto"
    assert members["codex-dev"]["executor"] == "codex"

    tasks = {t["key"]: t for t in plan["tasks"]}
    assert len(tasks) == 9
    # T2 (Claude) and T3 (AGY) both depend on T1 and run in parallel
    assert tasks["T2"]["depends_on"] == ["T1"] and tasks["T2"]["member"] == "claude-lead"
    assert tasks["T3"]["depends_on"] == ["T1"] and tasks["T3"]["member"] == "agy-advisor"
    # T4 compares both proposals and pauses with QUESTION: for user approval
    assert tasks["T4"]["depends_on"] == ["T2", "T3"] and "QUESTION:" in tasks["T4"]["description"]
    # T5-T7: design draft -> AGY UX/copy review -> revise + backend spec
    assert tasks["T5"]["member"] == "claude-lead" and tasks["T6"]["member"] == "agy-advisor"
    assert tasks["T7"]["depends_on"] == ["T6"]
    # T8: Codex implements backend; T9: Claude reads diff, builds frontend, runs tests
    assert tasks["T8"]["member"] == "codex-dev" and tasks["T9"]["member"] == "claude-lead"


def test_dev_pipeline_skips_design_for_backend_only_goal(pkg, availability):
    res = pkg.plan.propose_plan("纯后端接口优化：新增缓存层与单测", "/tmp/ws", workflow="dev_pipeline")
    assert res["ok"] is True
    tasks = {t["key"]: t for t in res["plan"]["tasks"]}
    assert len(tasks) == 7
    assert tasks["T5"]["member"] == "claude-lead" and tasks["T6"]["member"] == "codex-dev"
    assert tasks["T7"]["member"] == "claude-lead"


def test_dev_lite_pipeline_and_explicit_runner_prefs_never_auto_fallback(pkg, availability):
    availability.down["cchclaude"] = "cchclaude 维护中"
    res = pkg.plan.propose_plan(
        "修一个后端接口并发 bug",
        "/tmp/ws",
        workflow="dev_lite",
        runner_prefs={"claude": "cchclaude"},
    )
    assert res["ok"] is True
    plan = res["plan"]
    assert plan["workflow"] == "dev_lite" and plan["runner_prefs"] == {"claude": "cchclaude"}
    assert len(plan["tasks"]) == 3
    by = {m["name"]: m for m in plan["members"]}
    # User explicitly picked cchclaude -> locked, does NOT auto-fallback to anyclaude
    assert by["claude-lead"]["executor"] == "cchclaude"
    assert by["claude-lead"]["executor_source"] == "user"
    assert by["claude-lead"]["runner"] is None
    assert "维护中" in by["claude-lead"]["runner_note"]
    assert by["codex-dev"]["runner"] == "codex"


def test_dev_pipeline_auto_mode_walks_family_order_when_top_down(pkg, availability):
    availability.down["officlaude"] = "官方 Claude 5 小时额度剩余 0%"
    availability.down["offiagy"] = "offiagy OAuth 过期"
    res = pkg.plan.propose_plan("新增协作统计页面", "/tmp/ws", workflow="dev_pipeline")
    assert res["ok"] is True
    by = {m["name"]: m for m in res["plan"]["members"]}
    assert by["claude-lead"]["executor"] == "officlaude" and by["claude-lead"]["runner"] == "cchclaude"
    assert by["agy-advisor"]["executor"] == "offiagy" and by["agy-advisor"]["runner"] == "agy"
    assert by["codex-dev"]["runner"] == "codex"
