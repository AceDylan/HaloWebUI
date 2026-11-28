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
    return _make_repo(tmp_path, "myapp")


def _make_repo(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "me@example.com")
    _git(path, "config", "user.name", "Me")
    (path / "README.md").write_text("# myapp\n")
    (path / "app.py").write_text("print('v1')\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    origin = tmp_path / ("origin.git" if name == "myapp" else f"{name}-origin.git")
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
    assert [(s["key"], s["status"]) for s in dep["steps"]] == [
        (key, "done") for key in ("review", "merge", "push", "deploy", "cleanup")]
    assert (repo / "app.py").read_text() == "print('v2')\n"
    head = _git(repo, "rev-parse", "main")
    assert _git(repo.parent / "origin.git", "rev-parse", "main") == head
    assert marker.read_text().strip() == f"deployed:{head[:8]}:{head[:8]}"
    assert not _git(repo, "branch", "--list", f"halo/{slug}")
    assert team["project"]["shipped_cleaned"] is True
    assert open(os.path.join(ws, ".halo", "conclusion.md")).read() == "完整结论"
    ch = projects.changes(team)
    assert ch["available"] is False and ch["deploy"]["status"] == "succeeded"


def test_builtin_profile_with_missing_entry_point_is_blocked_not_push_only(pkg, tmp_path, monkeypatch):
    import halowebui_teams.deploy as deploy

    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(tmp_path / "absent.json"))
    halo = _make_repo(tmp_path, "HaloWebUI")
    script = tmp_path / "deploy.sh"
    monkeypatch.setattr(deploy, "HALOWEBUI_DEPLOY_SCRIPT", str(script))

    missing = deploy.profile_for(str(halo))
    assert missing["wait_ci"] and missing["configured"]
    assert str(script) in missing["blocked"] and "不会只合并推送" in missing["blocked"]
    assert deploy.public_profile(str(halo))["blocked"] == missing["blocked"]

    script.write_text("#!/bin/sh\n")
    ready = deploy.profile_for(str(halo))
    assert not ready["blocked"] and "blocked" not in deploy.public_profile(str(halo))
    assert ready["command"] == f"sh {script} {{short_sha}}"

    # Projects without a built-in recipe keep the plain push-only pipeline.
    plain = deploy.profile_for(str(_make_repo(tmp_path, "otherapp")))
    assert not plain["configured"] and not plain["blocked"]


def test_missing_entry_point_refuses_manual_and_skips_auto_ship(pkg, team_id, plan_dict, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.deploy as deploy
    import halowebui_teams.projects as projects

    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.setattr(deploy, "HALOWEBUI_DEPLOY_SCRIPT", str(tmp_path / "gone" / "deploy.sh"))
    halo = _make_repo(tmp_path, "HaloWebUI")
    first = _create(pkg, team_id, plan_dict, halo, auto_deploy=True)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed",
        "conclusion": {"status": "ready", "generated_at": 100, "acceptance": {"status": "ready", "verdict": "met"}},
    }))
    base_head = _git(halo, "rev-parse", "main")

    with pytest.raises(projects.ProjectError) as err:
        deploy.start(slug, by="user")
    assert err.value.status == 409 and "部署入口" in err.value.message

    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False
    dep = pkg.common.read_team(slug)["project"]["deploy"]
    assert dep["status"] == "skipped" and "部署入口" in dep["error"]
    # Nothing merged or pushed, team branch kept, and the same attempt is not re-skipped every tick.
    assert _git(halo, "rev-parse", "main") == base_head
    assert _git(halo, "ls-remote", "origin") == ""
    assert _git(halo, "branch", "--list", f"halo/{slug}")
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False
    assert pkg.common.read_team(slug)["project"]["deploy"]["finished_at"] == dep["finished_at"]


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


def test_done_notice_waits_for_the_deployment_and_says_both(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.notify as notify
    import halowebui_teams.tg as tg

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))
    first = _create(pkg, team_id, plan_dict, repo, auto_deploy=True)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('one')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    clock = [pkg.common.now()]
    monkeypatch.setattr(notify, "now", lambda: clock[0])
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed", "completed_at": clock[0], "notified": [],
        "conclusion": {"status": "ready", "generated_at": clock[0], "acceptance": {"status": "ready", "verdict": "met"}},
    }))
    snap = {"team": {"phase": "completed"}, "tasks": []}
    sent = []
    monkeypatch.setattr(tg, "ready", lambda: True)
    monkeypatch.setattr(tg, "send", lambda chat, text, buttons, **kw: sent.append((text, buttons)) or 7)
    monkeypatch.setattr(notify, "target_for", lambda _team: {"chat_id": "tg-chat"})
    monkeypatch.setattr(notify, "watching", lambda _id: False)

    def set_deploy(**dep):
        pkg.common.update_team(slug, lambda rec: rec["project"].update(deploy=dep))
        return pkg.common.read_team(slug)

    # finished, the deployment not started yet (the bridge starts it right after): the done notice waits
    board = pkg.common.read_team(slug)
    assert notify.waits_for_deploy(board) and not notify.pending(board, snap)
    board = set_deploy(status="running", started_at=clock[0] + 5, steps=[])
    clock[0] += 20 * 60
    assert notify.waits_for_deploy(board) and not notify.pending(board, snap)

    # it ends: its notice is handed over, the done notice says both, with the CI link
    board = set_deploy(status="succeeded", started_at=board["project"]["deploy"]["started_at"], finished_at=clock[0],
                       sha="4f1e7e00" + "0" * 32, base_branch="main", seconds=600, cleanup=True,
                       profile_label="HaloWebUI（GitHub CI 构建镜像 → 拉取部署）", ci_url="https://ci.test/1")
    assert notify.deploy_notice(slug, board) is None and not sent
    board = pkg.common.read_team(slug)
    assert not notify.waits_for_deploy(board) and notify.pending(board, snap) == [("done", "done", None)]
    text, buttons = notify.done_message(board, snap, "结论正文")
    assert text.index("· 完成") < text.index("🚀 推送部署完成") < text.index("结论正文")
    assert "(4f1e7e00) · 用时 10 分钟" in text and "已清理团队分支" in text and "已开启自动部署" not in text
    assert ("🔗 查看 CI", "url:https://ci.test/1") in [b for row in buttons for b in row]

    # a deployment after the done notice went out (pushed by hand later) still gets its own notice
    board = set_deploy(status="failed", started_at=clock[0] + 60, finished_at=clock[0] + 90, error="CI 失败")
    pkg.common.update_team(slug, lambda rec: rec.update(notified=[*rec.get("notified", []), "done"]))
    assert notify.deploy_notice(slug, pkg.common.read_team(slug)) == 7
    assert "推送部署失败" in sent[-1][0] and ("🔁 重试推送部署", f"cb:dp:{team_id}") in sent[-1][1][0]

    # a deployment that hangs does not hold the result back forever
    board = set_deploy(status="running", started_at=clock[0])
    pkg.common.update_team(slug, lambda rec: rec.update(notified=[]))
    clock[0] += notify.DEPLOY_WAIT
    assert not notify.waits_for_deploy(pkg.common.read_team(slug))


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

    def fake_codex(workspace, base_branch, round_num, max_rounds, *, goal="", previous=""):
        review_calls.append((round_num, max_rounds))
        assert goal == "改 myapp" and ("缺少异常处理" in previous) == (round_num == 2)
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

    monkeypatch.setattr(deploy, "_run_codex_once", lambda *_a, **_k: ("FAIL", "VERDICT: FAIL\n仍有严重缺陷"))
    monkeypatch.setattr(deploy, "_run_claude_fix", lambda *_a: "尝试修复")

    deploy.start(slug, by="user", cleanup=True, codex_review=True)
    team, dep = _wait_done(pkg, slug)
    assert dep["status"] == "failed"
    assert "第 2/2 轮审查未通过" in dep["error"]
    # Main branch untouched and team branch preserved
    assert (repo / "app.py").read_text() == "print('v1')\n"
    assert _git(repo, "branch", "--list", f"halo/{slug}")


CODEX_SCRIPT = "/root/.hermes/scripts/codex-run.sh"
STUB_CODEX = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["STUB_ARGS"], "w").write(json.dumps(args))
sys.stdin.read()
text = os.environ["STUB_ANSWER"]
open(args[args.index("-o") + 1], "w").write(text)
for event in ({"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}},
              {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}):
    print(json.dumps(event), flush=True)
"""


@pytest.mark.skipif(not os.path.isfile(CODEX_SCRIPT), reason="needs the host's codex-run.sh")
@pytest.mark.parametrize("answer, verdict", [
    ("没有必须修的问题。\n\nVERDICT: PASS\nFAILURE_CLASS: none", "PASS"),
    ("app.py:1 会崩溃。\nPass 参数未校验。\n\nVERDICT: FAIL\nFAILURE_CLASS: findings", "FAIL"),
    ("VERDICT: PASS", "BLOCKED"),  # not the pair the runner requires
    ("看起来不错", "BLOCKED"),
])
def test_codex_review_runs_the_real_runner_script(pkg, tmp_path, monkeypatch, real_review, answer, verdict):
    """The real codex-run.sh with a stub codex: the subcommand and options must exist, and only the
    verdict the runner parsed counts."""
    import dataclasses

    import halowebui_teams.deploy as deploy
    import halowebui_teams.runners as runners

    stub = tmp_path / "codex"
    stub.write_text(STUB_CODEX)
    stub.chmod(0o755)
    runs = tmp_path / "runs"

    class Spec:
        label, script_path, runs_root = "codex", CODEX_SCRIPT, runs

    monkeypatch.setitem(runners.BY_NAME, "codex", Spec)
    for key, value in {"CODEX_BIN": stub, "CODEX_RUNS_ROOT": runs, "CODEX_SCOPE": "0",
                       "STUB_ARGS": tmp_path / "args.json", "STUB_ANSWER": answer}.items():
        monkeypatch.setenv(key, str(value))
    got, text = real_review(str(tmp_path), "main", 1, 2)
    assert got == verdict and answer.splitlines()[0] in text
    argv = json.loads((tmp_path / "args.json").read_text())
    assert "-m" not in argv and not any("model" in a for a in argv)  # Codex's own configured model
    assert any("hermes-audit" in a for a in argv)  # read-only


def _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, **profile):
    """A finished auto-deploy team with one change in app.py."""
    import halowebui_teams.bridge as bridge

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {str(repo): {"label": "MyApp", **profile}}}), encoding="utf-8")
    monkeypatch.setenv("HALO_TEAMS_DEPLOY_CONFIG", str(cfg))
    monkeypatch.setenv("HALO_TEAMS_NO_GATEWAY_RESTART", "1")
    first = _create(pkg, team_id, plan_dict, repo, auto_deploy=True)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed", "conclusion": {"status": "ready", "acceptance": {"status": "ready", "verdict": "met"}}}))
    return slug, ws


def _settle(pkg, slug):
    import halowebui_teams.deploy as deploy

    deadline = time.time() + 10
    while slug in deploy._inflight and time.time() < deadline:
        time.sleep(0.02)
    return _wait_done(pkg, slug)


def test_exhausted_review_does_not_start_over(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.deploy as deploy

    slug, ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch)
    calls = {"review": 0, "fix": 0}

    def review(*_a, **_k):
        calls["review"] += 1
        return "FAIL", "还有问题"

    def fix(*_a):
        calls["fix"] += 1
        open(os.path.join(ws, "app.py"), "w").write(f"print('fix{calls['fix']}')\n")
        _git(ws, "commit", "-qam", "fix")
        return "改了"

    monkeypatch.setattr(deploy, "_run_codex_once", review)
    monkeypatch.setattr(deploy, "_run_claude_fix", fix)
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is True
    assert _settle(pkg, slug)[1]["status"] == "failed"
    for _ in range(3):  # the fix moved the branch's head: still the same work
        assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False
    assert calls == {"review": 2, "fix": 1}

    # the user's own retry failing does not hand it back to auto-deploy either
    deploy.start(slug, by="user")
    _settle(pkg, slug)
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False

    # new work does ship
    open(os.path.join(ws, "app.py"), "w").write("print('v3')\n")
    _git(ws, "commit", "-qam", "more work")
    monkeypatch.setattr(deploy, "_run_codex_once", lambda *_a, **_k: ("PASS", "ok"))
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is True
    assert _settle(pkg, slug)[1]["status"] == "succeeded"


def test_blocked_review_pauses_without_a_fix(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.deploy as deploy

    slug, _ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch)
    monkeypatch.setattr(deploy, "_run_codex_once", lambda *_a, **_k: ("BLOCKED", "codex-run.sh: 网络不可用"))
    deploy.start(slug, by="user")
    dep = _settle(pkg, slug)[1]
    assert dep["status"] == "failed" and "没有给出结论" in dep["error"] and "网络不可用" in dep["error"]
    assert (repo / "app.py").read_text() == "print('v1')\n"


def test_review_sees_uncommitted_work_and_can_be_turned_off(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.deploy as deploy

    slug, ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, cleanup=False)
    open(os.path.join(ws, "late.py"), "w").write("x = 1\n")
    seen = []
    monkeypatch.setattr(deploy, "_run_codex_once",
                        lambda ws_, *_a, **_k: seen.append(_git(ws_, "diff", "--name-only", "main...HEAD")) or ("PASS", "ok"))
    deploy.start(slug, by="user")
    _settle(pkg, slug)
    assert "late.py" in seen[0]
    # shipped without cleanup: the same head is not shipped a second time
    assert deploy.tick_board(slug, pkg.common.read_team(slug)) is False

    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"projects": {str(repo): {"label": "MyApp", "codex_review": False}}}), encoding="utf-8")
    assert deploy.public_profile(str(repo))["codex_review"] is False


def test_failed_verify_still_reloads_the_changed_plugin(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.deploy as deploy

    slug, _ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, command="true",
                           verify_command="echo connection refused; false", restart_gateway_paths=["app.py"])
    reloads = []
    monkeypatch.setattr(deploy, "_schedule_gateway_restart", lambda: reloads.append(1) or True)
    deploy.start(slug, by="user")
    dep = _settle(pkg, slug)[1]
    assert dep["status"] == "failed" and dep["error"] == "线上核实失败（exit 1）：connection refused"
    deadline = time.time() + 5
    while not reloads and time.time() < deadline:  # scheduled last, after the notice
        time.sleep(0.02)
    assert reloads == [1]


def test_schedule_gateway_restart_reports_disabled_and_spawn_failure(monkeypatch):
    import halowebui_teams.deploy as deploy

    def fail(*args, **kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setenv("HALO_TEAMS_NO_GATEWAY_RESTART", "1")
    monkeypatch.setattr(deploy.subprocess, "Popen", lambda *a, **kw: pytest.fail("restart is disabled"))
    assert deploy._schedule_gateway_restart() is False
    monkeypatch.delenv("HALO_TEAMS_NO_GATEWAY_RESTART")
    monkeypatch.setattr(deploy.subprocess, "Popen", fail)
    assert deploy._schedule_gateway_restart() is False


def test_fix_run_is_bounded_and_committed(pkg, repo, tmp_path, monkeypatch, real_fix):
    import halowebui_teams.deploy as deploy
    import halowebui_teams.projects as projects

    seen = []
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if not str(argv[0]).endswith("-run.sh"):
            return real_run(argv, **kwargs)
        seen.append((argv, kwargs))
        (repo / "app.py").write_text("print('fixed')\n")
        return subprocess.CompletedProcess(argv, 0, "done", "")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    real_fix("cchclaude", str(repo), "app.py:1 有问题", 1)
    argv, kwargs = seen[0]
    inner = int(argv[argv.index("--timeout") + 1])
    assert inner == deploy.FIX_TIMEOUT and kwargs["timeout"] > inner
    assert kwargs["env"]["RECLAUDE_AUTO_CONTINUE"] == "0" and kwargs["env"]["RUNNER_SUPPRESS_NOTIFY"] == "1"
    assert "Codex 审查修复" in _git(repo, "log", "-1", "--format=%s")

    def hangs(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(deploy.subprocess, "run", hangs)
    with pytest.raises(projects.ProjectError, match="超时"):
        real_fix("cchclaude", str(repo), "x", 1)


def test_shell_step_timeout_reports_itself(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    import halowebui_teams.deploy as deploy
    import halowebui_teams.projects as projects

    slug, _ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch)
    with pytest.raises(projects.ProjectError, match="部署命令超时"):
        deploy._run_shell_step(slug, str(repo), "echo half; sleep 5", "", "main", "b", 1, "部署命令")


def test_work_workflow_ships_without_a_codex_review(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, availability):
    """/work ends with Claude reviewing and fixing: the release does not run Codex review after it."""
    import halowebui_teams.deploy as deploy

    slug, _ws = _completed(pkg, team_id, plan_dict, repo, tmp_path, monkeypatch, command="true", cleanup=True)
    pkg.common.update_team(slug, lambda rec: rec.update({"workflow": "work"}))
    reviews = []
    monkeypatch.setattr(deploy, "_run_codex_once", lambda *a, **k: reviews.append(1) or ("PASS", "ok"))
    entry = deploy.start(slug, by="auto")
    assert entry["codex_review"] is False and [s["key"] for s in entry["steps"]][0] == "merge"
    team, dep = _settle(pkg, slug)
    assert dep["status"] == "succeeded" and reviews == []
    assert team["project"].get("merged_at") and team["project"].get("discarded_at")
    assert _git(repo, "show", "main:app.py") == "print('v2')"
