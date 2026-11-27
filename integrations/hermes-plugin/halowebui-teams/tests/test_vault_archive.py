"""The completion workflow against an isolated Vault and the host CLI's real policy gates."""

import json
import subprocess
from pathlib import Path

import pytest

from halowebui_teams import deploy, link, notify, progress, projects, remote
from halowebui_teams import vault_archive as archive


@pytest.fixture
def vault(tmp_path, monkeypatch):
    helper = Path("/root/.hermes/scripts/vault-archive.py")
    if not helper.is_file():
        pytest.skip("host vault-archive.py is not installed")
    root = tmp_path / "vault"
    (root / "项目").mkdir(parents=True)
    monkeypatch.setenv("HALO_TEAMS_AUTO_VAULT_ARCHIVE", "1")
    monkeypatch.setenv("HALO_TEAMS_VAULT_ARCHIVE_SCRIPT", str(helper))
    monkeypatch.setenv("VAULT_ARCHIVE_ROOT", str(root))
    monkeypatch.setenv("VAULT_ARCHIVE_STATE_DIR", str(tmp_path / "archive-state"))
    monkeypatch.setenv("VAULT_ARCHIVE_SECRET_SOURCES", str(tmp_path / "no-secret-fixtures"))
    return root


def completed(pkg, team_id, plan_dict, *, goal="测试并验证协作归档", allowed=True, **fields):
    created = pkg.teams.create_team(team_id, plan_dict, owner="u1", goal=goal, vault_archive=allowed)
    slug = created["board"]
    stamp = pkg.common.now()
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed", "completed_at": stamp, "effort": "",
        "conclusion": {"status": "ready", "source": "lead", "by": "auto", "generated_at": stamp,
                       "tasks_done": 1, "acceptance": {"status": "ready", "verdict": "met"}},
        **fields,
    }))
    path = pkg.conclusion.conclusion_path(pkg.common.read_team(slug))
    path.parent.mkdir(exist_ok=True)
    path.write_text("# 归档验证\n\n已通过协作归档的定向单测。\n", encoding="utf-8")
    return slug, path.parent


def model(pkg, monkeypatch, replies):
    seen = []
    sequence = iter(replies)

    def respond(messages, **kwargs):
        details = json.loads(messages[1]["content"])
        seen.append(details)
        assert "Obsidian 知识库归档规则" in messages[0]["content"]
        reply = next(sequence)
        data = reply(details) if callable(reply) else reply
        return (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)), "", {"model": "stub-model"}

    monkeypatch.setattr(pkg.plan, "call_model", respond)
    return seen


def receipts(run_dir):
    return [json.loads(line) for line in (run_dir / "obsidian-archive.jsonl").read_text().splitlines()]


NOTE = "项目/协作归档（2026-11-27）.md"
DECISION = {"should_archive": True, "reason": "有可复用证据", "kind": "decision",
            "search_queries": ["协作归档"], "candidate_paths": [], "manual_request": ""}


def body(slug, evidence, *, updated=False, timeline=False):
    return ("---\nkind: decision\nstatus: verified\ncreated: 2026-11-27\n"
            f"source: hermes run {slug}\n"
            + ("updated: 2026-11-28\n" if updated else "")
            + ("maintenance: timeline\n" if timeline else "")
            + "---\n# 协作归档\n\n## 结论\n一个已验证的结果可以按规则统一归档到知识库。\n"
            + f"\n## 验证\n{evidence}\n")


@pytest.mark.parametrize("field", [
    "disabled", "owner", "quick", "opt-out", "read-only", "old", "baseline", "no-helper", "manual-rewrite",
])
def test_hard_gates_use_no_model_or_cli(pkg, team_id, plan_dict, vault, monkeypatch, field):
    goal = {"opt-out": "验证流程，请不要动 Obsidian", "read-only": "用户约束：只读任务"}.get(field, "验证流程")
    slug, run_dir = completed(pkg, team_id, plan_dict, allowed=field != "owner",
                               goal=goal)
    if field == "disabled":
        monkeypatch.setenv("HALO_TEAMS_AUTO_VAULT_ARCHIVE", "0")
    elif field == "no-helper":
        monkeypatch.setenv("HALO_TEAMS_VAULT_ARCHIVE_SCRIPT", str(vault / "missing"))
    elif field == "quick":
        pkg.common.update_team(slug, lambda rec: rec.update(effort="quick"))
    elif field in ("old", "baseline"):
        threshold = archive.ARCHIVE_WINDOW if field == "old" else archive.ARCHIVE_BASELINE_AGE
        old = pkg.common.now() - threshold - 1
        pkg.common.update_team(slug, lambda rec: (rec.update(completed_at=old),
                                                  rec["conclusion"].update(generated_at=old)))
    elif field == "manual-rewrite":
        pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(by="user"))

    def unexpected(*args, **kwargs):
        pytest.fail("gated team reached the model or archive CLI")

    monkeypatch.setattr(pkg.plan, "call_model", unexpected)
    monkeypatch.setattr(archive, "_cli", unexpected)
    archive.tick_board(slug, pkg.common.read_team(slug))
    entry = pkg.common.read_team(slug)["conclusion"].get("vault_archive")
    if field in ("quick", "opt-out", "read-only"):
        assert entry["status"] == "skipped"
    else:
        assert entry is None
    assert not (run_dir / "obsidian-archive.jsonl").exists()


def test_conclusion_marks_pending_before_acceptance_and_skips_after(pkg, team_id, plan_dict, vault, monkeypatch):
    created = pkg.teams.create_team(team_id, plan_dict, owner="u1", goal="看一下验证结果", vault_archive=True)
    slug = created["board"]
    from hermes_cli import kanban_db as kb

    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2", "T3"):
            kb.recompute_ready(conn)
            tid = created["tasks"][key]
            assert kb.claim_task(conn, tid, claimer="test")
            kb.complete_task(conn, tid, result="定向验证通过", summary="定向验证通过")

    def respond(messages, **kwargs):
        system = messages[0]["content"]
        if "Obsidian 知识库归档规则" in system:
            assert pkg.common.read_team(slug)["conclusion"]["acceptance"]["status"] == "ready"
            return '{"should_archive":false,"reason":"一次性检查"}', "", {}
        if "验收" in system[:80]:
            team = pkg.common.read_team(slug)
            assert team["conclusion"]["vault_archive"]["status"] == "pending"
            assert notify.pending(team, {"team": {"phase": "completed"}}) == []
            return '{"verdict":"met","summary":"已验证","gaps":[]}', "", {}
        return "# 验证结果\n\n" + "该任务的定向验证已经完成。" * 6, "", {}

    monkeypatch.setattr(pkg.plan, "call_model", respond)
    snap = pkg.teams.snapshot(team_id, "u1")
    assert snap["team"]["conclusion"]["vault_archive"]["status"] == "skipped"
    team = pkg.common.read_team(slug)
    assert "一次性检查" in notify.done_message(team, snap, "结果")[0]
    timeline = pkg.teams.timeline(team_id, "u1")["events"]
    assert any(e.get("data", {}).get("action") == "vault_archive_skipped" for e in timeline)


def test_real_cli_search_create_reject_retry_and_update_with_cas(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)

    def revised(details):
        assert "缺少 frontmatter" in details["feedback"]
        assert details["source"] == f"hermes run {slug}"
        assert details["top_directories"] == ["项目"]
        return {"action": "create", "path": NOTE, "reason": "验证通过",
                "content": body(slug, "`pytest -q test_first.py` → 2 passed")}

    seen = model(pkg, monkeypatch, [
        "not JSON", DECISION, {"action": "create", "path": NOTE, "content": "invalid"}, revised,
    ])
    result = archive.run(slug)
    assert result["status"] == "saved" and result["action"] == "create"
    assert result["path"] == NOTE and len(result["sha_after"]) == 64
    assert [r["action"] for r in receipts(run_dir)] == ["search", "create", "create"]
    assert receipts(run_dir)[1]["outcome"] == "refused"
    assert archive.run(slug) == result
    assert len(seen) == 4

    pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(
        generated_at=rec["conclusion"]["generated_at"] + 1))
    path = vault / NOTE

    def draft(details):
        note, = details["notes"]
        assert note["path"] == NOTE and "test_first.py" in note["body"]
        # Simulate a writer between show and update in the isolated Vault.
        path.write_text(path.read_text() + "\n同期用户补充了可复测的说明。\n")
        return {"action": "update", "path": NOTE, "expect_sha": note["sha256"],
                "content": body(slug, "`pytest -q test_second.py` → 3 passed", updated=True)}

    def retry(details):
        note, = details["notes"]
        assert "重新 show" in details["feedback"] and "同期用户补充" in note["body"]
        return {"action": "update", "path": NOTE, "expect_sha": note["sha256"],
                "content": body(slug, "`pytest -q test_second.py` → 3 passed", updated=True)
                + "\n同期用户补充了可复测的说明。\n"}

    model(pkg, monkeypatch, [DECISION, draft, retry])
    result = archive.run(slug)
    assert result["status"] == "saved" and result["action"] == "update"
    assert "test_second.py" in path.read_text() and "同期用户补充" in path.read_text()
    backup, = [p for p in (run_dir / "obsidian-backups").rglob("*") if p.is_file()]
    assert "test_first.py" in backup.read_text()
    team = pkg.common.read_team(slug)
    assert "sha_after" not in pkg.conclusion.read(slug, team)["entry"]["vault_archive"]
    for artifact in (backup, run_dir / "obsidian-archive.jsonl"):
        assert pkg.conclusion.resolve_file(team, str(artifact.relative_to(run_dir.parent))) is None
    alias = run_dir.parent / "note-alias.md"
    alias.symlink_to(backup)
    assert pkg.conclusion.resolve_file(team, alias.name) is None


def test_supplementary_search_and_timeline_append(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    note = vault / NOTE
    note.write_text(body(slug, "`pytest -q test_first.py` → 2 passed", timeline=True), encoding="utf-8")

    def append(details):
        assert "补充检索发现相关笔记" in details["feedback"]
        old, = details["notes"]
        assert old["path"] == NOTE and old["timeline"]
        return {"action": "append", "path": NOTE, "expect_sha": old["sha256"],
                "content": f"## 更新（2026-11-28，hermes run {slug}）\n状态：verified\n"
                           "验证：`pytest -q test_next.py` → 1 passed\n"}

    model(pkg, monkeypatch, [
        {**DECISION, "search_queries": ["无关主题"]},
        {"action": "create", "path": NOTE, "content": "should not reach create"},
        append,
    ])
    assert archive.run(slug)["action"] == "append"
    assert "test_next.py" in note.read_text()
    assert [r["action"] for r in receipts(run_dir)] == ["search", "search", "append"]


def test_lock_timeout_retries_once_and_permanent_refusal_is_visible(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    draft = {"action": "create", "path": NOTE, "content": "invalid"}
    model(pkg, monkeypatch, [DECISION, draft, draft])
    real = archive._cli
    writes = []
    sleeps = []

    def cli(script, slug, run_dir, deadline, command, *args, body=None):
        if command == "create":
            writes.append(command)
            if len(writes) == 1:
                return subprocess.CompletedProcess(args, 5, "", "锁超时")
        return real(script, slug, run_dir, deadline, command, *args, body=body)

    monkeypatch.setattr(archive, "_cli", cli)
    monkeypatch.setattr(archive.time, "sleep", sleeps.append)
    entry = archive.run(slug)
    assert sleeps == [3] and len(writes) == 3
    assert entry["status"] == "failed" and "拒绝写入" in entry["error"]
    assert not (vault / NOTE).exists()


def test_stale_attempt_recovers_the_write_receipt_without_a_second_write(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    model(pkg, monkeypatch, [DECISION, {"action": "create", "path": NOTE,
                                      "content": body(slug, "`pytest -q` → 2 passed")}])
    assert archive.run(slug)["status"] == "saved"
    old = pkg.common.now() - archive.ARCHIVE_STALE - 1
    pkg.common.update_team(slug, lambda rec: rec["conclusion"]["vault_archive"].update(
        status="running", started_at=old, attempt_at=old))
    archive.tick_board(slug, pkg.common.read_team(slug))
    result = pkg.common.read_team(slug)["conclusion"]["vault_archive"]
    assert result["status"] == "saved" and "回执确认" in result["reason"]
    assert [r["action"] for r in receipts(run_dir)] == ["search", "create"]


@pytest.mark.parametrize("explicit", [False, True])
def test_manual_override_requires_the_original_request(pkg, team_id, plan_dict, vault, monkeypatch, explicit):
    requested = "请把结论存入知识库"
    slug, run_dir = completed(pkg, team_id, plan_dict, goal=requested if explicit else "验证归档功能")
    draft = {"action": "create", "path": NOTE, "content": "# 协作归档 · 2026-11-27\n\n用户要求留档。"}
    model(pkg, monkeypatch, [{**DECISION, "manual_request": requested}, draft, draft])
    result = archive.run(slug)
    assert (vault / NOTE).is_file() == explicit
    assert result["status"] == ("saved" if explicit else "failed")
    assert bool(receipts(run_dir)[-1].get("manual")) == explicit


def test_bridge_resumes_acceptance_interrupted_before_archive(pkg, team_id, plan_dict, vault, monkeypatch):
    from halowebui_teams import bridge

    slug, _run_dir = completed(pkg, team_id, plan_dict)

    def interrupted(rec):
        rec["conclusion"]["acceptance"] = {"status": "checking", "started_at": pkg.common.now()}
        rec["conclusion"]["vault_archive"] = archive.pre_mark(rec)

    team = pkg.common.update_team(slug, interrupted)

    def respond(messages, **kwargs):
        if "Obsidian 知识库归档规则" in messages[0]["content"]:
            return '{"should_archive":false,"reason":"已有记录"}', "", {}
        return '{"verdict":"met","summary":"验收已恢复","gaps":[]}', "", {}

    monkeypatch.setattr(pkg.plan, "call_model", respond)
    bridge._catch_up_conclusion(slug, team)
    with pkg.conclusion._jobs_lock:
        worker = pkg.conclusion._jobs.get(slug)
    if worker:
        worker.join(timeout=5)
    entry = pkg.common.read_team(slug)["conclusion"]
    assert entry["acceptance"]["status"] == "ready" and entry["acceptance"]["verdict"] == "met"
    assert entry["vault_archive"]["status"] == "skipped"


def test_qq_and_progress_wait_for_active_archive_then_show_its_result(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, _run_dir = completed(pkg, team_id, plan_dict)
    team = pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(vault_archive=archive.pre_mark(rec)))
    sent = []
    job = {"id": team_id}
    monkeypatch.setattr(remote, "send", lambda _job, message: sent.append(message) or True)
    monkeypatch.setattr(remote, "update_job", lambda *a, **kw: None)
    monkeypatch.setattr(remote, "drop_job", lambda *a: None)
    monkeypatch.setattr(link, "team_url", lambda *a: "https://example.test/conclusion")
    assert progress.stage(slug, team, [], "completed")["key"] == "archiving"
    remote._team_done("qq-test", job, {"title": "复核流程"})
    assert not sent

    model(pkg, monkeypatch, [{"should_archive": False, "reason": "已有完整笔记"}])
    assert archive.run(slug)["status"] == "skipped"
    remote._team_done("qq-test", job, {"title": "复核流程"})
    assert len(sent) == 1 and "Obsidian：未写入知识库（已有完整笔记）" in sent[0]


@pytest.mark.parametrize("terminal", ["succeeded", "failed", "skipped"])
def test_release_defers_archive_and_notifies_with_terminal_evidence(
        pkg, team_id, plan_dict, vault, monkeypatch, terminal):
    slug, run_dir = completed(pkg, team_id, plan_dict, auto_deploy=True)
    stamp = pkg.common.now()
    verdict = "unmet" if terminal == "skipped" else "met"
    pkg.common.update_team(slug, lambda rec: rec.update(
        reported=str(stamp), project={"path": "/test/repo", "branch": "halo/branch", "base_branch": "main"}))
    pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(
        generated_at=stamp, acceptance={"status": "ready", "verdict": verdict}))
    monkeypatch.setattr(projects, "changes", lambda _team: {"commits": [1]})
    monkeypatch.setattr(projects, "changed_paths", lambda _team: ["app.py"])
    fresh = pkg.common.read_team(slug)
    assert archive.waits_for_deploy(fresh) and archive.pre_mark(fresh) is None
    assert archive.run(slug) is None
    assert notify.pending(fresh, {"team": {"phase": "completed"}})[0][1] == "done"
    calls = []

    def decision(details):
        deployment = details["deployment"]
        assert deployment["touched_files"] == ["app.py"]
        assert deployment["status"] == terminal
        if terminal != "skipped":
            assert deployment["sha"] == "a" * 40
            assert deployment["ci_url"] == "https://example.test/ci"
            if terminal == "succeeded":
                assert "health=healthy" in deployment["log_tail"]
            else:
                assert "HTTP 503" in deployment["log_tail"] and "线上验证" in deployment["error"]
        return {"should_archive": False, "reason": "没有可补充的知识"}

    model(pkg, monkeypatch, [decision])
    monkeypatch.setattr(link, "vault_archived", lambda *args: calls.append("refresh"))

    def send(_slug, board):
        assert "没有可补充的知识" in notify.deploy_message(board)[0]
        calls.append("notice")

    monkeypatch.setattr(notify, "deploy_notice", send)
    if verdict == "met":
        profile = {**deploy.profile_for("/test/repo"), "wait_ci": True, "command": "deploy",
                   "verify_command": "verify", "restart_gateway_paths": ["app.py"]}
        monkeypatch.setattr(projects, "merge", lambda *a: {"sha": "a" * 40})
        monkeypatch.setattr(projects, "push", lambda *a: None)
        monkeypatch.setattr(deploy, "_wait_for_ci", lambda *a: ("https://example.test/ci", 123))
        monkeypatch.setattr(deploy, "_run_deploy_command", lambda *a: None)
        def verify(*args):
            if terminal == "failed":
                deploy._append_log(slug, "HTTP 503")
                raise projects.ProjectError(502, "线上验证失败")
            deploy._append_log(slug, "health=healthy")

        monkeypatch.setattr(deploy, "_run_verify_command", verify)
        monkeypatch.setattr(deploy, "_mark_attempt", lambda *a: None)
        monkeypatch.setattr(deploy, "_schedule_gateway_restart", lambda: calls.append("restart"))
        deploy._run_ship(slug, profile, "auto", cleanup=False)
        assert calls == ["refresh", "notice", "restart"]
    else:
        monkeypatch.setattr(deploy, "_attempt_key", lambda _team: "0:abcdef")
        assert not deploy.tick_board(slug, pkg.common.read_team(slug))
        assert calls == ["refresh", "notice"]
    assert archive.run(slug)["status"] == "skipped"
    assert not (run_dir / "obsidian-archive.jsonl").exists()
