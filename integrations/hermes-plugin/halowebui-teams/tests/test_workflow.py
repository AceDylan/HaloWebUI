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


PROJECT = {"name": "HaloWebUI", "path": "/root/HaloWebUI", "branch": "main"}
NOTES = ("\n\n笔记库里可能相关的笔记（用户自己的知识库，宿主机只读路径，按需阅读；可能过时，以实际系统为准）：\n"
         "- AICheckIn 修改记录：/root/Documents/Obsidian Vault/项目/AICheckIn.md")


@pytest.fixture
def lead(pkg, monkeypatch):
    """The lead's answer to a free-form goal (``lead.answer``) and what it was asked."""
    import json

    class Lead:
        answer: dict = {}
        prompts: list = []

        def says(self, repo_change=None, **member):
            self.answer = {
                "title": "任务", "summary": "分工",
                "members": [{"name": "dev", "role": "开发", "kind": "code", **member}],
                "tasks": [{"key": "T1", "title": "做", "description": "做", "member": "dev", "depends_on": []}],
                **({} if repo_change is None else {"repo_change": repo_change})}

    fake = Lead()
    fake.prompts = []

    def call(messages, **kw):
        fake.prompts.append(messages)
        return json.dumps(fake.answer), "", {"model": "gpt-chat", "requested": kw.get("preferred") or ""}

    monkeypatch.setattr(pkg.plan, "call_model", call)
    return fake


def _plan(pkg, goal, **kw):
    res = pkg.plan.propose_plan(goal, "/tmp/ws", project=kw.pop("project", PROJECT), **kw)
    assert res["ok"] is True, res
    return res["plan"]


def test_repo_change_is_promoted_whatever_the_notes_say(pkg, availability, lead):
    lead.says(repo_change=True)
    plan = _plan(pkg, "修一下 HaloWebUI 下拉框错位" + NOTES)
    assert (plan["workflow"], plan["promoted_from"], plan["repo_change"]) == ("dev_lite", "auto", True)
    assert [m["name"] for m in plan["members"]] == ["claude-lead", "codex-dev"] and len(plan["tasks"]) == 3
    assert plan["lead_model"]["model"] == "gpt-chat"  # the model that judged it, not a placeholder


def test_analysis_of_a_project_is_not_promoted_and_ships_nothing(pkg, availability, lead):
    lead.says(repo_change=False)
    plan = _plan(pkg, "hub书签服务的UI还有优化空间吗 给个策略")
    assert "workflow" not in plan and "promoted_from" not in plan and plan["repo_change"] is False
    # an explicit read-only goal wins over the lead
    lead.says(repo_change=True)
    plan = _plan(pkg, "看下 HaloWebUI 自动分流\n\n用户约束：只读任务。只查看和分析")
    assert "workflow" not in plan and plan["repo_change"] is False
    text = pkg.teams._workspace_text({"workspace": "/w", "repo_change": False,
                                      "project": {"name": "a", "path": "/a", "branch": "halo/x"}})
    assert "不要改动仓库里的任何文件" in text


def test_lead_that_does_not_say_is_read_from_its_members(pkg, availability, lead):
    lead.says()
    assert _plan(pkg, "给 HaloWebUI 加按钮")["workflow"] == "dev_lite"
    lead.says(kind="research")
    assert _plan(pkg, "评估 HaloWebUI")["repo_change"] is False
    # without a project there is nothing to change
    lead.says(repo_change=True)
    plan = _plan(pkg, "写个脚本", project=None)
    assert "workflow" not in plan and "repo_change" not in plan


def test_runners_named_in_the_goal_survive_promotion(pkg, availability, lead):
    lead.says(repo_change=True, executor="reclaude")
    plan = _plan(pkg, "用 reclaude 修复 HaloWebUI 登录 bug")
    by = {m["name"]: m["executor"] for m in plan["members"]}
    assert plan["workflow"] == "dev_lite" and by == {"claude-lead": "reclaude", "codex-dev": "codex"}
    # a division of work the template does not have: the lead's own plan stays
    lead.says(repo_change=True, executor="offiagy")
    plan = _plan(pkg, "用 offiagy 改 HaloWebUI 首页")
    assert "workflow" not in plan and plan["members"][0]["executor"] == "offiagy" and plan["repo_change"] is True
    lead.says(repo_change=True)
    lead.answer["members"].append({"name": "dev2", "role": "后端", "kind": "code", "executor": "cchclaude"})
    lead.answer["members"][0]["executor"] = "reclaude"
    lead.answer["tasks"].append({"key": "T2", "title": "后端", "description": "做", "member": "dev2", "depends_on": []})
    plan = _plan(pkg, "用 reclaude 改前端，cchclaude 写后端")
    assert "workflow" not in plan and [m["executor"] for m in plan["members"]] == ["reclaude", "cchclaude"]


def test_replanning_a_promoted_plan_follows_the_feedback(pkg, availability, lead):
    lead.says(repo_change=True)
    first = _plan(pkg, "修复 HaloWebUI 下拉框")
    lead.says(repo_change=True)
    lead.answer["members"].append({"name": "qa", "role": "测试", "kind": "code"})
    lead.answer["tasks"].append({"key": "T2", "title": "测试", "description": "测", "member": "qa", "depends_on": ["T1"]})
    again = _plan(pkg, "修复 HaloWebUI 下拉框", feedback="加一个测试成员", previous=first)
    assert [m["name"] for m in again["members"]] == ["dev", "qa"]
    assert (again["workflow"], again["promoted_from"]) == ("dev_lite", "auto")
    assert "claude-lead" in lead.prompts[-1][-1]["content"]  # the lead saw the plan it adjusts
    free = _plan(pkg, "修复 HaloWebUI 下拉框", feedback="不要用流水线，保持自由协作", previous=again)
    assert "workflow" not in free and "promoted_from" not in free
    # and the per-family choice made when the team was started is kept
    first = _plan(pkg, "修复 HaloWebUI 下拉框", runner_prefs={"claude": "cchclaude"})
    again = _plan(pkg, "修复 HaloWebUI 下拉框", feedback="加测试", previous=first, runner_prefs={})
    assert again["runner_prefs"] == {"claude": "cchclaude"} and again["members"][0]["executor"] == "cchclaude"


def test_chosen_template_keeps_the_chosen_lead_model(pkg, availability):
    plan = pkg.plan.propose_plan("改接口", "/tmp/ws", workflow="dev_lite", lead_model="claude-chat")["plan"]
    assert plan["lead_model"]["requested"] == "claude-chat"
    plan = pkg.plan.propose_plan("改接口", "/tmp/ws", workflow="dev_lite")["plan"]
    assert not plan["lead_model"].get("model")


def test_a_note_does_not_pick_the_project(pkg, monkeypatch):
    import halowebui_teams.projects as projects

    monkeypatch.setattr(projects, "candidates", lambda: [{"path": "/root/AICheckIn", "name": "AICheckIn", "aliases": []}])
    monkeypatch.setattr(projects, "describe", lambda path: {"path": path, "name": "AICheckIn"})
    assert pkg.plan.resolve_project("写一份周报" + NOTES, "") is None
    assert pkg.plan.resolve_project("改 AICheckIn 侧栏" + NOTES, "")["path"] == "/root/AICheckIn"


def test_create_team_defaults_auto_deploy_for_project_and_exposes_promoted_from(pkg, availability, tmp_path, lead):
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
    lead.says(repo_change=True)
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
    raw_team = pkg.teams.read_team(out["board"])
    ws_text = pkg.teams._workspace_text(raw_team)
    assert "不要自行调用外部 Codex / AGY / CCG" in ws_text
    assert "不要 git push" in ws_text
    assert "不要自行调用外部 Codex / AGY / CCG" in pkg.teams._workspace_text({"workspace": "/tmp/ws"})

    lead.says(repo_change=False)
    plan = _plan(pkg, "分析 repo", project=proj)
    pkg.teams.create_team("team-analysis-1", plan, owner="u1", goal="分析 repo")
    assert pkg.teams.snapshot("team-analysis-1")["team"]["auto_deploy"] is False


def test_work_workflow_plans_with_agy_builds_with_codex_reviews_with_claude(pkg, availability):
    proj = {"name": "repo", "path": "/tmp/repo", "branch": "main"}
    res = pkg.plan.propose_plan("给设置页加个开关", "/tmp/ws", workflow="work", project=proj)
    assert res["ok"] is True
    plan = res["plan"]
    assert plan["workflow"] == "work" and plan["repo_change"] is True
    assert plan["title"].startswith("工作：")
    by = {m["name"]: m for m in plan["members"]}
    assert by["agy-planner"]["executor"] == "offiagy" and by["agy-planner"]["executor_source"] == "auto"
    assert by["codex-dev"]["executor"] == "codex"
    assert by["claude-review"]["executor"] == "officlaude" and by["claude-review"]["executor_source"] == "auto"
    tasks = {t["key"]: t for t in plan["tasks"]}
    assert [tasks[k]["member"] for k in ("T1", "T2", "T3")] == ["agy-planner", "codex-dev", "claude-review"]
    assert tasks["T2"]["depends_on"] == ["T1"] and tasks["T3"]["depends_on"] == ["T2"]
    assert ".halo/plan.md" in tasks["T2"]["description"] and "直接修改代码" in tasks["T3"]["description"]
    import halowebui_teams.workflow as wf

    assert wf.skips_codex_review("work") and not wf.skips_codex_review("dev_lite")


def test_work_workflow_falls_back_in_family_unless_a_runner_is_named(pkg, availability):
    proj = {"name": "repo", "path": "/tmp/repo", "branch": "main"}
    availability.down["officlaude"] = "额度用完"
    availability.down["offiagy"] = "没登录"
    plan = pkg.plan.propose_plan("修个 bug", "/tmp/ws", workflow="work", project=proj)["plan"]
    by = {m["name"]: m for m in plan["members"]}
    assert by["claude-review"]["executor"] == "officlaude" and by["claude-review"]["runner"] == "cchclaude"
    assert by["agy-planner"]["executor"] == "offiagy" and by["agy-planner"]["runner"] == "agy"

    availability.down["cchclaude"] = "维护中"
    plan = pkg.plan.propose_plan("修个 bug", "/tmp/ws", workflow="work", project=proj,
                                 runner_prefs={"claude": "cchclaude"})["plan"]
    by = {m["name"]: m for m in plan["members"]}
    assert plan["runner_prefs"] == {"claude": "cchclaude"}
    assert by["claude-review"]["executor"] == "cchclaude" and by["claude-review"]["executor_source"] == "user"
    assert by["claude-review"].get("runner") != "anyclaude"  # named: never walks on to the next Claude


def test_work_workflow_needs_a_project(pkg, availability):
    res = pkg.plan.propose_plan("写个周报", "/tmp/ws", workflow="work")
    assert res["ok"] is False and "git 项目" in res["error"]


def test_work_plan_review_is_a_dependency_and_cli_prefs_lock_by_primary_family(pkg, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg["plan_review"] = True
    cfg["steps"]["plan"] = {"runner": "agy", "fallback": ["officlaude"]}
    cfg["steps"]["dev"] = {"runner": "codex", "fallback": ["officlaude"]}
    cfg["steps"]["review"] = {"runner": "cchclaude", "fallback": []}
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)
    availability.down.update(agy="网关不可用", codex="维护中", cchclaude="额度不足", reclaude="账号不可用")
    raw = workflow.build_pipeline_plan("修个 bug", workflow="work")
    plan, errors = pkg.plan.validate_plan(raw)
    assert not errors
    assert plan["layers"] == [["T1"], ["T2"], ["T3"], ["T4"]]
    assert [task["member"] for task in plan["tasks"]] == ["agy-planner", "plan-reviewer", "codex-dev", "claude-review"]
    assert all(word in plan["tasks"][1]["description"] for word in (".halo/plan.md", ".halo/plan-review.md", "QUESTION:"))
    assert ".halo/plan-review.md" in plan["tasks"][2]["description"]
    assert "officlaude" in plan["summary"] and "审阅规划" in plan["summary"]
    by = {m["name"]: m for m in plan["members"]}
    assert by["agy-planner"]["executor"] == by["agy-planner"]["recommended"] == "agy"
    assert by["agy-planner"]["runner"] == by["codex-dev"]["runner"] == "officlaude"
    assert by["claude-review"]["runner"] is None
    assert by["claude-review"]["fallback_chain"] == ["cchclaude"]

    preview, _ = pkg.plan.validate_plan(raw, check_runners=False)
    assert preview["members"][0]["executor"] == preview["members"][0]["recommended"] == "agy"
    locked = workflow.build_pipeline_plan("修个 bug", workflow="work", runner_prefs={"claude": "reclaude"})
    plan, errors = pkg.plan.validate_plan(locked)
    assert not errors
    for m in plan["members"]:
        if m["name"] in ("plan-reviewer", "claude-review"):
            assert m["executor"] == "reclaude" and m["executor_source"] == "user"
            assert m["runner"] is None and "fallback_chain" not in m
        else:
            assert m["runner"] == "officlaude" and m["executor_source"] == "auto"


def test_work_board_uses_the_saved_chain_for_launch_runtime_and_retry(pkg, team_id, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    chain = ["codex", "officlaude", "agy"]
    cfg["steps"]["plan"] = {"runner": chain[0], "fallback": chain[1:]}
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)
    raw = workflow.build_pipeline_plan("修个 bug", workflow="work")
    created = pkg.teams.create_team(team_id, raw, owner="u1")
    slug, tid = created["board"], created["tasks"]["T1"]
    assert pkg.common.read_team(slug)["tasks"][tid]["chain"] == chain
    assert pkg.common.read_team(slug)["tasks"][created["tasks"]["T2"]]["depends_on"] == ["T1"]
    # A configuration change cannot change a team that's already running.
    cfg["steps"]["plan"]["fallback"] = []
    availability.down["codex"] = "维护中"
    pkg.reclaude.tick_board(slug, pkg.common.read_team(slug))
    with pkg.common.board_conn(slug) as conn:
        assert pkg.common.kb().get_task(conn, tid).assignee == "officlaude"
        assert pkg.fallback.reroute(slug, conn, tid, "officlaude", "网络错误", phase="runtime") == "agy"
        assert pkg.common.kb().get_task(conn, tid).assignee == "agy"
        availability.down.clear()
        assert pkg.fallback.reselect_for_retry(slug, conn, tid) == "codex"
        assert pkg.fallback.reselect_for_retry(slug, conn, tid, executor="cchclaude") == "cchclaude"
        entry = pkg.common.read_team(slug)["tasks"][tid]
        assert entry["chosen_by"] == "user" and "chain" not in entry
        assert pkg.fallback.reroute(slug, conn, tid, "cchclaude", "不可用", phase="launch") is None
        assert pkg.common.kb().get_task(conn, tid).status == "blocked"


def test_work_empty_fallback_pauses_without_choosing_the_next_family_runner(pkg, team_id, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg["steps"]["plan"]["fallback"] = []
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)
    availability.down["offiagy"] = "未登录"
    created = pkg.teams.create_team(team_id, workflow.build_pipeline_plan("修个 bug", workflow="work"), owner="u1")
    slug, tid = created["board"], created["tasks"]["T1"]
    pkg.reclaude.tick_board(slug, pkg.common.read_team(slug))
    with pkg.common.board_conn(slug) as conn:
        task = pkg.common.kb().get_task(conn, tid)
        assert task.status == "blocked" and task.assignee == "offiagy"
    entry = pkg.common.read_team(slug)["tasks"][tid]
    assert entry["chain"] == ["offiagy"]
    assert "执行链 offiagy" in entry["trail"][-1]["reason"]


def test_work_unavailable_native_runner_with_no_fallback_is_never_ready(pkg, team_id, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg["steps"]["plan"] = {"runner": "hermes", "fallback": []}
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)
    availability.down["hermes"] = "已停用"
    created = pkg.teams.create_team(team_id, workflow.build_pipeline_plan("修个 bug", workflow="work"), owner="u1")
    slug, tid = created["board"], created["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        assert pkg.common.kb().get_task(conn, tid).status == "blocked"
        assert pkg.common.kb().claim_task(conn, tid) is None
    assert "已停用" in pkg.common.read_team(slug)["tasks"][tid]["trail"][-1]["reason"]


def test_work_native_outage_routes_to_fallback_and_generic_questions_still_block(pkg, team_id, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg["steps"]["plan"] = {"runner": "hermes", "fallback": ["codex"]}
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)
    created = pkg.teams.create_team(team_id, workflow.build_pipeline_plan("修个 bug", workflow="work"), owner="u1")
    slug, tid, dev = created["board"], created["tasks"]["T1"], created["tasks"]["T2"]
    kb = pkg.common.kb()
    with pkg.common.board_conn(slug) as conn:
        assert kb.claim_task(conn, tid)
        assert kb.block_task(conn, tid, reason="需要确认 API 的范围", kind="needs_input")
    pkg.fallback.reroute_native_work(slug, pkg.common.read_team(slug))
    with pkg.common.board_conn(slug) as conn:
        assert kb.get_task(conn, tid).status == "blocked"
        assert kb.get_task(conn, dev).status == "todo"
        assert kb.unblock_task(conn, tid)
        conn.execute("UPDATE tasks SET last_failure_error = ? WHERE id = ?",
                     ("401 Unauthorized", tid))
        conn.commit()
    pkg.fallback.reroute_native_work(slug, pkg.common.read_team(slug))
    with pkg.common.board_conn(slug) as conn:
        assert kb.get_task(conn, tid).assignee == "codex"
        assert kb.get_task(conn, dev).status == "todo"
    assert pkg.common.read_team(slug)["tasks"][tid]["trail"][-1]["fail_kind"] == "auth"


def test_work_deep_preset_combines_multi_model_stages_with_work_chains(pkg, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg["steps"]["plan"] = {"runner": "offiagy", "fallback": ["agy"]}
    cfg["steps"]["plan_review"] = {"runner": "officlaude", "fallback": ["anyclaude", "reclaude"]}
    cfg["steps"]["dev"] = {"runner": "codex", "fallback": []}
    cfg["steps"]["review"] = {"runner": "officlaude", "fallback": ["anyclaude", "reclaude"]}
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)

    proj = {"name": "HaloWebUI", "path": "/tmp/repo", "branch": "main"}
    res = pkg.plan.propose_plan("给协作台加多模型工作流界面", "/tmp/ws", workflow="work", project=proj, work_preset="deep")
    assert res["ok"] is True
    plan = res["plan"]
    assert plan["workflow"] == "work"
    assert plan["work_preset"] == "deep"
    assert plan["codex_review"] is True
    assert workflow.skips_codex_review("work", plan) is False

    tasks = {t["key"]: t for t in plan["tasks"]}
    assert len(tasks) == 9
    assert tasks["T2"]["depends_on"] == ["T1"] and tasks["T3"]["depends_on"] == ["T1"]
    assert tasks["T2"]["member"] == "plan-reviewer" and tasks["T3"]["member"] == "agy-planner"
    assert tasks["T4"]["depends_on"] == ["T2", "T3"] and "拍板闸门" in tasks["T4"]["description"]
    assert tasks["T5"]["member"] == "plan-reviewer" and tasks["T6"]["member"] == "agy-planner"
    assert tasks["T8"]["member"] == "codex-dev" and tasks["T9"]["member"] == "claude-review"
    by = {m["name"]: m for m in plan["members"]}
    assert by["plan-reviewer"]["fallback_chain"] == ["officlaude", "anyclaude", "reclaude"]
    assert by["claude-review"]["fallback_chain"] == ["officlaude", "anyclaude", "reclaude"]

    # Backend-only goal skips UI design review (7 tasks instead of 9).
    backend = pkg.plan.propose_plan("纯后端接口优化", "/tmp/ws", workflow="work", project=proj, work_preset="deep")["plan"]
    assert len(backend["tasks"]) == 7
    assert backend["codex_review"] is True


def test_work_fast_preset_overrides_enabled_modules_and_skips_codex_review(pkg, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg.update(plan_review=True, dual_plan=True, plan_approval=True, ui_review=True, split_dev=True)
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)

    proj = {"name": "HaloWebUI", "path": "/tmp/repo", "branch": "main"}
    plan = pkg.plan.propose_plan("改个按钮文案", "/tmp/ws", workflow="work", project=proj, work_preset="fast")["plan"]
    assert plan["work_preset"] == "fast"
    assert plan["codex_review"] is False
    assert workflow.skips_codex_review("work", plan) is True
    assert [t["member"] for t in plan["tasks"]] == ["agy-planner", "codex-dev", "claude-review"]


def test_work_modular_flags_persisted_onto_team_board_for_deploy_review(pkg, team_id, availability, monkeypatch):
    from halowebui_teams import workflow

    cfg = pkg.runners.work_config()
    cfg.update(plan_review=True, plan_approval=True, split_dev=True)
    monkeypatch.setattr(pkg.runners, "work_config", lambda: cfg)

    raw = workflow.build_pipeline_plan("新增后端接口", workflow="work")
    plan, errors = pkg.plan.validate_plan(raw)
    assert not errors
    assert plan["codex_review"] is True
    assert "拍板闸门" in plan["tasks"][1]["description"]
    created = pkg.teams.create_team(team_id, plan, owner="u1")
    team_rec = pkg.common.read_team(created["board"])
    assert team_rec["codex_review"] is True
    assert workflow.skips_codex_review(team_rec["workflow"], team_rec) is False
