"""阶段与预计时间: the stage a team is in, what each running member is doing, and an estimate from
this machine's own history (by executor and task kind), replayed on the dependencies."""

import json

import pytest

STATS = {
    "task": {"hermes": {"n": 40, "median": 150, "p75": 260}, "hermes/research": {"n": 8, "median": 500, "p75": 600},
             "cchclaude": {"n": 5, "median": 60, "p75": 90}},
    "task_all": {"n": 60, "median": 140, "p75": 250},
    "conclusion": {"n": 20, "median": 30, "p75": 45},
    "acceptance": {"n": 6, "median": 5, "p75": 8},
    "plan": {"n": 10, "median": 40, "p75": 70},
}


@pytest.fixture
def progress(monkeypatch):
    import halowebui_teams.progress as progress

    monkeypatch.setattr(progress, "history", lambda force=False: STATS)
    return progress


def _create(pkg, team_id, plan_dict):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    return pkg.teams.create_team(team_id, plan, owner="u1", goal="做个小工具")


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


def test_the_estimate_replays_the_dependencies_with_the_parallel_cap(progress):
    # T1 ∥ T2 (cap 2) → T3: 150 (both hermes, in parallel) + 150, then the conclusion and the check
    tasks = [{"id": "a", "parents": [], "status": "todo", "executor": "hermes"},
             {"id": "b", "parents": [], "status": "todo", "executor": "hermes"},
             {"id": "c", "parents": ["a", "b"], "status": "todo", "executor": "hermes"}]
    est = progress.estimate(tasks, cap=2)
    assert est["seconds"] == 150 + 150 + 30 + 5
    assert est["high"] >= round(est["seconds"] * 1.35) and "hermes" in est["basis"]
    # one at a time: three tasks in a row
    assert progress.estimate(tasks, cap=1, with_conclusion=False)["seconds"] == 450
    # a research member takes its kind's time; two members of the same runner never run together
    tasks[0]["kind"] = "research"
    assert progress.estimate(tasks, cap=2, with_conclusion=False)["seconds"] == 500 + 150
    runner = [{"id": "x", "parents": [], "status": "todo", "executor": "cchclaude"},
              {"id": "y", "parents": [], "status": "todo", "executor": "cchclaude"}]
    assert progress.estimate(runner, cap=2, with_conclusion=False)["seconds"] == 120
    # a running task counts what is left of it; one past its usual time a little more, flagged
    at = 10_000
    running = [{"id": "a", "parents": [], "status": "running", "executor": "hermes", "current_run": {"started_at": at - 100}}]
    assert progress.estimate(running, at=at, with_conclusion=False)["seconds"] == 50
    late = progress.estimate([{**running[0], "current_run": {"started_at": at - 400}}], at=at, with_conclusion=False)
    assert late["overtime"] is True and late["seconds"] == 45
    # done tasks cost nothing; a quota wait counts until the reset
    waiting = [{"id": "q", "parents": [], "status": "running", "sub_status": "quota_wait", "executor": "cchclaude",
                "current_run": {"started_at": at - 10, "resume_at": at + 600}},
               {"id": "d", "parents": [], "status": "done", "executor": "hermes"}]
    assert progress.estimate(waiting, at=at, with_conclusion=False)["seconds"] == 660


def test_a_plan_comes_with_how_long_it_takes_once_approved(pkg, progress, plan_dict):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    est = progress.estimate_plan(plan)
    assert est["seconds"] == 150 + 150 + 30 + 5 and est["high"] > est["seconds"]
    plan["members"][0]["kind"] = "research"
    assert progress.estimate_plan(plan)["seconds"] == 500 + 150 + 30 + 5
    assert progress.eta_text(30) == "不到 1 分钟" and progress.eta_text(335, 470) == "约 6–8 分钟"
    assert progress.eta_text(600, 610) == "约 10 分钟"


def test_planning_says_each_step_and_records_how_long_it_took(pkg, progress, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    seen = []
    replies = iter(["不是 JSON", json.dumps({
        "title": "小工具", "members": [{"name": "dev", "role": "开发", "kind": "writing"}],
        "tasks": [{"key": "T1", "title": "写", "description": "写 a.md", "member": "dev"}]})])

    def fake(messages, timeout=150, preferred=None, on_route=None, **kw):
        on_route({"model": "gpt-chat", "provider": "custom"}, [])
        on_route({"model": "deepseek-chat", "provider": "deepseek"}, ["gpt-chat：TimeoutError"])
        seen.append(dict(progress.planning("team-plan-1")["progress"]))
        return next(replies), "", {"model": "deepseek-chat"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
    out = pkg.plan.propose_plan("写个文档", "/tmp/ws", team_id="team-plan-1")
    assert out["ok"] and out["attempts"] == 2
    assert "负责人（deepseek-chat）在理解目标" in seen[0]["text"] and "gpt-chat 没有响应" in seen[0]["text"]
    assert seen[0]["attempt"] == 1 and seen[1]["attempt"] == 2 and "不是 JSON" in seen[1]["text"]
    assert out["plan"]["estimate"]["seconds"] > 0
    assert progress.planning("team-plan-1")["progress"]["step"] == "check"  # until the API call ends
    progress.planning_done("team-plan-1")
    assert progress.planning("team-plan-1") == {"progress": None, "typical": {"median": 40, "p75": 70,
                                                                              "basis": "本机最近 10 次"}}
    progress.record_plan(33.3)
    progress.record_plan(41)
    assert json.loads((tmp_path / "halo-teams" / "plan-times.json").read_text()) == [41.0, 33.3]


def test_a_running_team_says_what_each_member_is_doing(pkg, progress, team_id, plan_dict):
    created = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        t1 = created["tasks"]["T1"]
        assert kb.claim_task(conn, t1, claimer="test") is not None
        pkg.common.append_event(conn, t1, "halo_tool", {"name": "web_search", "preview": "看板工具 对比", "ok": True})
    snap = pkg.teams.snapshot(team_id, "u1")
    stage = snap["team"]["stage"]
    assert stage["key"] == "running" and stage["label"] == "成员执行中"
    assert stage["now"].startswith("#T1 backend-dev：搜索 · 看板工具 对比")
    line = stage["running"][0]
    assert line["key"] == "T1" and line["text"] == "搜索 · 看板工具 对比" and line["typical"] == 150
    assert stage["eta"]["seconds"] > 0 and stage["done"] == 0 and stage["total"] == 3
    assert [s["state"] for s in stage["steps"]] == ["done", "done", "active", "pending", "pending"]
    assert progress.brief(stage)["now"].startswith("#T1")
    with pkg.common.board_conn(slug) as conn:  # running tasks count against the host-wide cap of later tests
        kb.complete_task(conn, t1, result="好了", summary="好了")


def test_a_finished_team_goes_through_writing_and_checking_the_result(pkg, progress, team_id, plan_dict, monkeypatch):
    import halowebui_teams.conclusion as conclusion

    created = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    monkeypatch.setattr(conclusion, "start", lambda slug, by="auto", force=False: conclusion._set(
        slug, status="generating", started_at=pkg.common.now(), model="gpt-chat"))
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2", "T3"):
            tid = created["tasks"][key]
            assert kb.claim_task(conn, tid, claimer="test") is not None
            kb.complete_task(conn, tid, result="好了", summary="好了")
    stage = pkg.teams.snapshot(team_id, "u1")["team"]["stage"]
    assert stage["key"] == "concluding" and "gpt-chat" in stage["now"] and "3 个任务" in stage["now"]
    assert 0 < stage["eta"]["seconds"] <= 30 + 5
    conclusion._set(slug, status="ready", generated_at=pkg.common.now(),
                    acceptance={"status": "checking", "started_at": pkg.common.now()})
    stage = pkg.teams.snapshot(team_id, "u1")["team"]["stage"]
    assert stage["key"] == "checking" and stage["eta"]["seconds"] <= 5
    conclusion._set(slug, acceptance={"status": "ready", "verdict": "met", "at": pkg.common.now()})
    stage = pkg.teams.snapshot(team_id, "u1")["team"]["stage"]
    assert stage["key"] == "done" and "eta" not in stage and all(s["state"] == "done" for s in stage["steps"])


def test_history_is_this_machines_own_by_executor_and_kind(pkg, team_id, plan_dict, monkeypatch):
    import halowebui_teams.progress as progress

    plan_dict["members"][0]["kind"] = "research"
    created = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2", "T3"):
            tid = created["tasks"][key]
            assert kb.claim_task(conn, tid, claimer="test") is not None
            kb.complete_task(conn, tid, result="好了", summary="好了")
        conn.execute("UPDATE task_runs SET started_at = ended_at - 120")
        conn.commit()
    monkeypatch.setattr(progress, "MIN_SAMPLES", 1)
    monkeypatch.setattr(progress, "team_boards", lambda: [slug])
    stats = progress.history(force=True)
    assert stats["task"]["hermes"]["n"] == 3 and stats["task"]["hermes"]["median"] == 120
    assert stats["task"]["hermes/research"]["n"] == 1
    assert progress.typical("task", "hermes", stats, "research")["basis"] == "本机最近 1 次 hermes 调研任务"
    assert progress.typical("task", "agy", stats)["basis"].startswith("本机最近 3 次成员任务")
