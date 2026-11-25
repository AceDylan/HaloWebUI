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


def test_auto_promotes_to_dev_lite_for_repo_code_changes(pkg, availability):
    project = {"name": "HaloWebUI", "path": "/root/HaloWebUI", "branch": "main"}
    res = pkg.plan.propose_plan(
        "给 HaloWebUI 协作台修复接口并发 bug 并补单元测试",
        "/tmp/ws",
        project=project,
        workflow="auto",
    )
    assert res["ok"] is True
    plan = res["plan"]
    assert plan["workflow"] == "dev_lite"
    assert plan["promoted_from"] == "auto"
    assert plan["auto_deploy"] is True
    assert len(plan["tasks"]) == 3


def test_auto_stays_freeform_for_readonly_repo_goal_or_explicit_feedback(pkg, availability, monkeypatch):
    import halowebui_teams.workflow as workflow_mod

    project = {"name": "HaloWebUI", "path": "/root/HaloWebUI", "branch": "main"}
    assert workflow_mod.should_promote_to_dev_lite("审查 HaloWebUI 最近的提交并出报告", project) is False
    assert workflow_mod.should_promote_to_dev_lite("给 HaloWebUI 写新接口", None) is False
    assert workflow_mod.should_promote_to_dev_lite("给 HaloWebUI 写新接口", project) is True

    # Feedback asking for 自由协作 keeps workflow free-form instead of re-promoting
    import json

    fake_free = json.dumps({
        "title": "自由协作任务",
        "summary": "自定义",
        "members": [{"name": "m1", "role": "开发", "executor": "codex"}],
        "tasks": [{"key": "T1", "title": "执行", "description": "做", "member": "m1", "depends_on": []}],
    })
    monkeypatch.setattr(pkg.plan, "call_model", lambda messages, **kw: (fake_free, "", {"model": "gpt-chat"}))
    res = pkg.plan.propose_plan(
        "给 HaloWebUI 加一个按钮",
        "/tmp/ws",
        project=project,
        workflow="auto",
        feedback="不要用流水线，保持自由协作",
    )
    assert res["ok"] is True
    assert res["plan"].get("workflow", "auto") == "auto"
    assert res["plan"].get("promoted_from") is None


def test_create_team_defaults_auto_deploy_for_project_and_exposes_promoted_from(pkg, availability, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    proj = {"name": "repo", "path": str(repo), "branch": "main"}
    plan = pkg.plan.propose_plan(
        "修改 repo 页面样式",
        str(tmp_path / "ws"),
        project=proj,
        workflow="auto",
    )["plan"]
    out = pkg.teams.create_team(
        "team-promo-1",
        plan,
        owner="u1",
        goal="修改 repo 页面样式",
        title="修改样式",
    )
    snap = pkg.teams.snapshot("team-promo-1")
    assert snap["team"]["auto_deploy"] is True
    assert snap["team"]["workflow"] == "dev_lite"
    assert snap["team"]["promoted_from"] == "auto"
