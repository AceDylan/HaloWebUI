"""Project delivery pipeline (deploy.py): profiles, merge → push → CI → deploy → cleanup,
auto-deploy on completion (with acceptance unmet guard), progress stage, and Telegram notice."""

import json
import os
import subprocess
import time

import pytest


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "myapp"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "me@example.com")
    _git(path, "config", "user.name", "Me")
    (path / "README.md").write_text("# myapp\n")
    (path / "app.py").write_text("print('v1')\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    _git(path, "remote", "add", "origin", str(origin))
    return path


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


def _create(pkg, team_id, plan_dict, repo, *, auto_deploy=False):
    plan_dict["project"] = {"path": str(repo), "name": "myapp", "auto": True}
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    return pkg.teams.create_team(team_id, plan, owner="u1", goal="改 myapp", auto_deploy=auto_deploy)


def _finish(pkg, slug, task_id, change=None):
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        kb.recompute_ready(conn)
        kb.claim_task(conn, task_id, claimer="w")
        if change:
            change()
        kb.complete_task(conn, task_id, result="ok", summary="ok")


def _wait_done(pkg, slug, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        team = pkg.common.read_team(slug)
        dep = ((team or {}).get("project") or {}).get("deploy") or {}
        if dep.get("status") in ("succeeded", "failed", "skipped"):
            return team, dep
        time.sleep(0.05)
    raise AssertionError("deploy did not finish in time")


def test_custom_config_ship_merges_pushes_runs_command_and_cleans_up(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy
    import halowebui_teams.projects as projects

    marker = tmp_path / "deployed.txt"
    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({
        "projects": {
            str(repo): {
                "label": "MyApp 本地测试部署",
                "command": f"echo deployed:$HALO_DEPLOY_SHORT_SHA:{{short_sha}} > {marker}",
                "cleanup": True,
            }
        }
    }), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))
    monkeypatch.setenv("HALO_TEAMS_NO_GATEWAY_RESTART", "1")

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    os.makedirs(os.path.join(ws, ".halo"), exist_ok=True)
    open(os.path.join(ws, ".halo", "conclusion.md"), "w").write("完整结论")

    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))

    pub = deploy.public_profile(str(repo))
    assert pub["configured"] is True and pub["has_command"] is True and "command" not in pub

    deploy.start(slug, by="user", cleanup=True)
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "succeeded"
    assert [s["status"] for s in dep["steps"]] == ["done", "done", "done", "done"]
    assert (repo / "app.py").read_text() == "print('v2')\n"
    head = _git(repo, "rev-parse", "main")
    assert _git(repo.parent / "origin.git", "rev-parse", "main") == head
    assert marker.read_text().strip() == f"deployed:{head[:8]}:{head[:8]}"
    assert not _git(repo, "branch", "--list", f"halo/{slug}")
    assert team["project"]["shipped_cleaned"] is True
    assert open(os.path.join(ws, ".halo", "conclusion.md")).read() == "完整结论"
    ch = projects.changes(team)
    assert ch["available"] is False and ch["deploy"]["status"] == "succeeded"


def test_ci_failure_stops_before_deploy_and_keeps_branch_for_retry(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy

    marker = tmp_path / "should-not-run.txt"
    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({
        "projects": {
            str(repo): {
                "label": "MyApp CI",
                "wait_ci": True,
                "ci_workflow": "Docker Image CI",
                "command": f"touch {marker}",
                "cleanup": True,
            }
        }
    }), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))
    monkeypatch.setattr(deploy, "CI_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(deploy, "_github_repo", lambda _p: "AceDylan/myapp")

    def fake_gh(args, *, cwd, timeout=30):
        assert "--commit" not in args and "headSha" in " ".join(args)
        head = _git(repo, "rev-parse", "main")
        out = json.dumps([
            {"databaseId": 998, "headSha": "0" * 40, "status": "completed", "conclusion": "success",
             "name": "Docker Image CI", "url": "https://github.com/AceDylan/myapp/actions/runs/998"},
            {"databaseId": 999, "headSha": head, "status": "completed", "conclusion": "failure",
             "name": "Docker Image CI", "url": "https://github.com/AceDylan/myapp/actions/runs/999"},
        ])
        return subprocess.CompletedProcess(["gh", *args], 0, out, "")

    monkeypatch.setattr(deploy, "_run_gh", fake_gh)

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v3')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))

    deploy.start(slug, by="user", cleanup=True)
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "failed"
    assert dep["ci_url"] == "https://github.com/AceDylan/myapp/actions/runs/999"
    assert "failure" in dep["error"]
    assert not marker.exists()
    assert _git(repo, "branch", "--list", f"halo/{slug}")  # kept on failure


def test_auto_deploy_respects_acceptance_unmet_and_ships_when_met(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))

    first = _create(pkg, team_id, plan_dict, repo, auto_deploy=True)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('auto')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))

    # Acceptance unmet -> skipped safely, branch untouched
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed",
        "conclusion": {"status": "ready", "generated_at": 100, "acceptance": {"status": "ready", "verdict": "unmet"}},
    }))
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False
    dep = pkg.common.read_team(slug)["project"]["deploy"]
    assert dep["status"] == "skipped" and "未通过" in dep["error"]
    assert _git(repo, "branch", "--list", f"halo/{slug}")

    # New round with acceptance met -> ships automatically
    pkg.common.update_team(slug, lambda rec: rec.update({
        "round": 1,
        "conclusion": {"status": "ready", "generated_at": 200, "acceptance": {"status": "ready", "verdict": "met"}},
    }))
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is True
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "succeeded" and dep["by"] == "auto"
    assert (repo / "app.py").read_text() == "print('auto')\n"
    assert not _git(repo, "branch", "--list", f"halo/{slug}")


def test_progress_stage_and_telegram_done_button(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.notify as notify
    import halowebui_teams.progress as progress

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))

    first = _create(pkg, team_id, plan_dict, repo, auto_deploy=False)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('tg')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed",
        "conclusion": {"status": "ready", "generated_at": 100},
    }))

    snap = pkg.teams.snapshot(team_id)
    text, buttons = notify.done_message(pkg.common.read_team(slug), snap, "结论")
    flat = [cb for row in buttons for _label, cb in row]
    assert f"cb:dp:{team_id}" in flat and "推送部署" in text

    pkg.common.update_team(slug, lambda rec: rec.setdefault("project", {}).update({
        "deploy": {"status": "running", "started_at": 100, "steps": [{"key": "ci", "label": "等待 CI", "status": "running", "detail": "CI 运行中"}]}
    }))
    st = progress.stage(slug, pkg.common.read_team(slug), snap["tasks"], "completed")
    assert st["key"] == "deploying" and "CI 运行中" in st["now"]


def test_codex_review_fail_then_claude_fix_then_pass_and_verify(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy

    verify_marker = tmp_path / "verified.txt"
    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({
        "projects": {
            str(repo): {
                "label": "MyApp 审查+核实",
                "command": "echo deployed",
                "verify_command": f"echo online-ok:$HALO_DEPLOY_SHORT_SHA > {verify_marker}",
                "codex_review": True,
                "cleanup": True,
            }
        }
    }), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))
    monkeypatch.setenv("HALO_TEAMS_NO_GATEWAY_RESTART", "1")

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))

    review_calls = []
    fix_calls = []

    def fake_codex(workspace, base_branch, round_num, max_rounds):
        review_calls.append((round_num, max_rounds))
        if round_num == 1:
            return "FAIL", "VERDICT: FAIL\napp.py 缺少异常处理"
        return "PASS", "VERDICT: PASS\n问题已修复"

    def fake_fix(runner_name, workspace, review_text, round_num):
        fix_calls.append((runner_name, round_num))
        open(os.path.join(workspace, "app.py"), "w").write("print('v2-fixed')\n")
        _git(workspace, "add", "app.py")
        _git(workspace, "commit", "-q", "-m", "fix review")
        return "已修复 app.py"

    monkeypatch.setattr(deploy, "_run_codex_once", fake_codex)
    monkeypatch.setattr(deploy, "_run_claude_fix", fake_fix)

    deploy.start(slug, by="user", cleanup=True)
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "succeeded"
    assert review_calls == [(1, 2), (2, 2)]
    assert fix_calls == [("officlaude", 1)]
    assert [s["key"] for s in dep["steps"]] == ["review", "merge", "push", "deploy", "cleanup", "verify"]
    assert all(s["status"] == "done" for s in dep["steps"])
    assert (repo / "app.py").read_text() == "print('v2-fixed')\n"
    assert verify_marker.read_text().strip().startswith("online-ok:")


def test_codex_review_exhausted_stops_before_merge(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {str(repo): {"label": "MyApp", "codex_review": True}}}), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('bad')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))

    monkeypatch.setattr(deploy, "_run_codex_once", lambda *_a: ("FAIL", "VERDICT: FAIL\n仍有严重缺陷"))
    monkeypatch.setattr(deploy, "_run_claude_fix", lambda *_a: "尝试修复")

    deploy.start(slug, by="user", cleanup=True, codex_review=True)
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "failed"
    assert "第 2/2 轮审查未通过" in dep["error"]
    # Main branch untouched and team branch preserved
    assert (repo / "app.py").read_text() == "print('v1')\n"
    assert _git(repo, "branch", "--list", f"halo/{slug}")


def test_codex_review_never_passes_model_flag(pkg, tmp_path, monkeypatch):
    import halowebui_teams.deploy as deploy

    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "VERDICT: PASS\nall good", "")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    verdict, text = deploy._run_codex_once(str(tmp_path), "main", 1, 2)
    assert verdict == "PASS" and "all good" in text
    assert seen and seen[0][1] == "review" and "--model" not in seen[0] and "--reasoning-effort" not in seen[0]
