"""The completion workflow against an isolated Vault and the host CLI's real policy gates."""

import json
import subprocess
from pathlib import Path

import pytest

from halowebui_teams import deploy, link, notify, progress, projects, remote, tg
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


@pytest.mark.parametrize("padding, try_content_first, truncated", [(1200, False, False), (1200, True, False),
                                                                   (3300, True, True)])
def test_long_evergreen_note_uses_exact_edits_and_real_cli(
        pkg, team_id, plan_dict, vault, monkeypatch, padding, try_content_first, truncated):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    evidence = "`pytest -q test_old.py` → 2 passed"
    old = body(slug, evidence) + "\n## 历史\n" + "早期协作流程的验证证据应保留。\n" * padding
    note = vault / NOTE
    note.write_text(old, encoding="utf-8")
    outputs = []
    real = archive._cli

    def cli(script, slug, run_dir, deadline, command, *args, body=None):
        result = real(script, slug, run_dir, deadline, command, *args, body=body)
        if command == "update":
            outputs.append((args, result))
        return result

    monkeypatch.setattr(archive, "_cli", cli)

    def update(details):
        shown, = details["notes"]
        assert shown["truncated"] is truncated and shown["chars"] == len(old) > 15000
        assert (shown["body"] != old) is truncated
        assert evidence in shown["body"] and "full_body" not in shown
        if try_content_first:
            assert "请改用 edits" in details["feedback"] and "content" not in details["previous"]
        return {"action": "update", "path": NOTE, "expect_sha": shown["sha256"][:12],
                "edits": [{"old": evidence, "new": evidence + "\n`pytest -q test_new.py` → 5 passed"}]}

    def full_rewrite(details):
        return {"action": "update", "path": NOTE, "expect_sha": details["notes"][0]["sha256"],
                "content": "会丢掉旧段落"}

    seen = model(pkg, monkeypatch, [DECISION, full_rewrite, update] if try_content_first else [DECISION, update])
    result = archive.run(slug)
    assert result["status"] == "saved" and result["action"] == "update"
    date = seen[-1]["date"]
    assert note.read_text() == old.replace("created: 2026-11-27\n", f"created: 2026-11-27\nupdated: {date}\n").replace(
        evidence, evidence + "\n`pytest -q test_new.py` → 5 passed")
    (args, cli_result), = outputs
    assert "已读回核验" in cli_result.stdout
    assert args[args.index("--expect-sha") + 1] == seen[-1]["notes"][0]["sha256"]
    backup, = [p for p in (run_dir / "obsidian-backups").rglob("*") if p.is_file()]
    assert backup.read_text() == old
    assert "/obsidian-backups/" in (run_dir / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize("edits, feedback", [
    ([{"old": "不存在的片段", "new": "新"}], "第 1 条 edit（old: '不存在的片段'）：匹配 0 处"),
    ([{"old": "重复", "new": "新"}], "匹配多处"),
    ([{"old": "重重", "new": "新"}], "匹配多处"),
    ([{"old": "重复", "new": "重复"}], "无变化"),
    ([{"old": "", "new": "新"}], "old 不能为空"),
    ([{"old": "删除" * 2000, "new": ""}], "缩减超过 50%"),
    ([{"old": "一次", "new": "新"}] * 21, "最多允许 20 条"),
])
def test_invalid_edits_are_refused_before_any_vault_write(pkg, team_id, plan_dict, vault, monkeypatch, edits, feedback):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    note = vault / NOTE
    old = body(slug, "`pytest -q` → 2 passed") + "重复，重复，重重重。\n" + "删除" * 2000 + "\n"
    note.write_text(old)

    def update(details):
        return {"action": "update", "path": NOTE, "expect_sha": details["notes"][0]["sha256"], "edits": edits}

    def skip(details):
        assert feedback in details["feedback"]
        assert details["previous"]["edits"] == edits
        return {"action": "skip", "reason": "草稿被拒"}

    model(pkg, monkeypatch, [DECISION, update, skip])
    assert archive.run(slug)["status"] == "skipped"
    assert note.read_text() == old and [row["action"] for row in receipts(run_dir)] == ["search"]


@pytest.mark.parametrize("use_edits", [False, True])
def test_show_masks_known_credentials_and_update_preserves_original(
        pkg, team_id, plan_dict, vault, monkeypatch, tmp_path, use_edits):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    fake_value = "9R2wJ_54HzPm6qG1Lkx"
    source = tmp_path / "fixture.env"
    source.write_text(f"FAKE_API_KEY={fake_value}\n")
    monkeypatch.setenv("VAULT_ARCHIVE_SECRET_SOURCES", str(source))
    evidence = "`pytest -q test_old.py` → 1 passed"
    note = vault / NOTE
    old = body(slug, evidence) + f"\n已有私密内容：{fake_value}\n"
    note.write_text(old)

    def update(details):
        shown, = details["notes"]
        assert shown["masked"] and fake_value not in shown["body"]
        replacement = "`pytest -q test_new.py` → 2 passed"
        changes = {"edits": [{"old": evidence, "new": replacement}]} if use_edits else {
            "content": shown["body"].replace(evidence, replacement),
        }
        return {"action": "update", "path": NOTE, "expect_sha": shown["sha256"], **changes}

    def skip(details):
        assert "含已遮蔽的凭据" in details["feedback"]
        return {"action": "skip", "reason": "需要人工整合"}

    model(pkg, monkeypatch, [DECISION, update, skip])
    assert archive.run(slug)["status"] == "skipped"
    assert note.read_text() == old and [row["action"] for row in receipts(run_dir)] == ["search"]


def test_show_counts_existing_matches_and_bounds_note_views(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, _run_dir = completed(pkg, team_id, plan_dict)
    paths = ["项目/首篇.md", "项目/次篇.md", "项目/过长.md"]
    for path, length in zip(paths, (27000, 24000, 41000)):
        prefix = body(slug, "开头的验证") + "甲" * 8000
        (vault / path).write_text(prefix + "\n## 中间的标题\n只存在于中间\n" + "乙" * length + "末尾标记\n")
    (vault / NOTE).write_text(body(slug, "命中笔记"))

    def skip(details):
        notes = details["notes"]
        assert [n["path"] for n in notes] == [*paths, NOTE]
        # Make the first note eligible for the full view and the second exceed the accumulated budget.
        assert not notes[0]["truncated"] and "只存在于中间" in notes[0]["body"]
        for truncated in notes[1:3]:
            assert truncated["truncated"] and "## 中间的标题" in truncated["body"]
            assert "只存在于中间" not in truncated["body"] and "末尾标记" in truncated["body"]
        assert all("full_body" not in n for n in notes)
        return {"action": "skip"}

    model(pkg, monkeypatch, [{**DECISION, "candidate_paths": ["项目/不存在1.md", "项目/不存在2.md", *paths]}, skip])
    assert archive.run(slug)["status"] == "skipped"


def test_three_drafts_recover_from_topic_conflict_and_bad_edit(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    topics = {"项目/协作归档（2026-11-25）.md", "项目/协作归档（2026-11-26）.md"}
    evidence = "`pytest -q test_old.py` → 2 passed"

    def create(details):
        assert not details["notes"]
        for path in topics:
            (vault / path).write_text(body(slug, evidence, updated=True))
        return {"action": "create", "path": NOTE, "content": body(slug, evidence)}

    def invalid(details):
        assert "同主题笔记已存在" in details["feedback"]
        assert {n["path"] for n in details["notes"]} == topics
        shown = details["notes"][0]
        return {"action": "update", "path": shown["path"], "expect_sha": shown["sha256"],
                "content": "无效而且应该从反馈中移除", "edits": [{"old": "不存在", "new": evidence}]}

    def revised(details):
        assert "匹配 0 处" in details["feedback"]
        previous = details["previous"]
        assert "content" not in previous and previous["edits"] == [{"old": "不存在", "new": evidence}]
        return {**previous, "edits": [
            {"old": evidence, "new": "验证：`pytest -q test_mid.py` → 2 passed"},
            {"old": "`pytest -q test_mid.py`", "new": "`pytest -q test_new.py`"},
        ]}

    seen = model(pkg, monkeypatch, [DECISION, create, invalid, revised])
    result = archive.run(slug)
    assert result["status"] == "saved" and result["path"] in topics and len(seen) == 4
    assert "test_new.py" in (vault / result["path"]).read_text()
    assert f"updated: {seen[-1]['date']}" in (vault / result["path"]).read_text()
    assert [(r["action"], r["ok"]) for r in receipts(run_dir)] == [
        ("search", True), ("create", False), ("update", True),
    ]


def test_wrong_sha_is_refused_and_absolute_distinct_from_is_accepted(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    evidence = "`pytest -q test_old.py` → 2 passed"
    old = body(slug, evidence)
    note = vault / NOTE
    note.write_text(old)
    new_path = "项目/协作归档（2026-11-28）.md"

    def wrong_sha(details):
        sha = details["notes"][0]["sha256"]
        wrong = ("1" if sha[0] == "0" else "0") + sha[1:12]
        return {"action": "update", "path": NOTE, "expect_sha": wrong,
                "edits": [{"old": evidence, "new": "`pytest -q test_new.py` → 5 passed"}]}

    def distinct(details):
        assert "使用准确的 sha256" in details["feedback"]
        return {"action": "create", "path": new_path, "distinct_from": [str(note)],
                "content": body(slug, "`pytest -q test_separate.py` → 3 passed")}

    model(pkg, monkeypatch, [DECISION, wrong_sha, distinct])
    assert archive.run(slug)["path"] == new_path
    assert note.read_text() == old and (vault / new_path).is_file()
    assert [r["action"] for r in receipts(run_dir)] == ["search", "create"]


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
    model(pkg, monkeypatch, [DECISION, draft, draft, draft])
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
    assert sleeps == [3] and len(writes) == 4
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
    model(pkg, monkeypatch, [{**DECISION, "manual_request": requested}, draft, draft, draft])
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


@pytest.mark.parametrize("terminal, reload", [
    ("succeeded", "new_process"), ("failed", "new_process"), ("succeeded", "schedule_failed"),
    ("succeeded", "stalled"), ("succeeded", "disabled"), ("succeeded", "unchanged"), ("skipped", "unchanged"),
])
def test_release_defers_archive_and_notifies_with_terminal_evidence(
        pkg, team_id, plan_dict, vault, monkeypatch, terminal, reload):
    slug, run_dir = completed(pkg, team_id, plan_dict, auto_deploy=True)
    stamp = pkg.common.now()
    verdict = "unmet" if terminal == "skipped" else "met"
    # the done notice already went out (the page was open, say): the deployment gets a notice of its own
    pkg.common.update_team(slug, lambda rec: rec.update(
        reported=str(stamp), project={"path": "/test/repo", "branch": "halo/branch", "base_branch": "main"},
        notified=["done"]))
    pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(
        generated_at=stamp, acceptance={"status": "ready", "verdict": verdict}))
    monkeypatch.setattr(projects, "changes", lambda _team: {"commits": [1]})
    monkeypatch.setattr(projects, "changed_paths", lambda _team: ["app.py"])
    fresh = pkg.common.read_team(slug)
    assert archive.waits_for_deploy(fresh) and archive.pre_mark(fresh) is None
    assert archive.run(slug) is None
    assert notify.waits_for_deploy(fresh) and not notify.pending(fresh, {"team": {"phase": "completed"}})
    calls = []
    deferred = reload in ("new_process", "schedule_failed", "stalled")
    if reload == "disabled":
        monkeypatch.setenv("HALO_TEAMS_NO_GATEWAY_RESTART", "1")
    else:
        monkeypatch.delenv("HALO_TEAMS_NO_GATEWAY_RESTART", raising=False)

    def decision(details):
        deployment = details["deployment"]
        assert deployment["touched_files"] == ["app.py"]
        assert deployment["status"] == terminal
        if terminal != "skipped":
            assert deployment["sha"] == "a" * 40
            assert deployment["ci_url"] == "https://example.test/ci"
            assert deployment["ci_run_id"] == 123
            if terminal == "succeeded":
                assert "health=healthy" in deployment["log_tail"]
                assert bool(deployment["note"]) == deferred
            else:
                assert "HTTP 503" in deployment["log_tail"] and "线上验证" in deployment["error"]
        return {"should_archive": False, "reason": "没有可补充的知识"}

    seen = model(pkg, monkeypatch, [decision])
    monkeypatch.setattr(link, "vault_archived", lambda *args: calls.append("refresh"))
    monkeypatch.setattr(notify, "target_for", lambda _team: {"chat_id": "tg-chat", "thread_id": "thread"})
    monkeypatch.setattr(tg, "ready", lambda: True)

    def send(chat, message, _buttons, *, thread_id):
        assert (chat, thread_id) == ("tg-chat", "thread")
        if message.startswith("📚"):
            assert "Obsidian：未写入知识库（没有可补充的知识）" in message
            calls.append("archive notice")
        else:
            assert ("网关重启加载新插件后自动归档" in message) == deferred
            assert ("没有可补充的知识" in message) != deferred
            calls.append("notice")
        return 100 + len(calls)

    monkeypatch.setattr(tg, "send", send)
    if verdict == "met":
        profile = {**deploy.profile_for("/test/repo"), "wait_ci": True, "command": "deploy",
                   "verify_command": "verify", "restart_gateway_paths": [] if reload == "unchanged" else ["app.py"]}
        monkeypatch.setattr(projects, "merge", lambda *a: {"sha": "a" * 40})
        monkeypatch.setattr(projects, "push", lambda *a: None)
        monkeypatch.setattr(deploy, "_wait_for_ci", lambda *a: ("https://example.test/ci", 123))
        monkeypatch.setattr(deploy, "_run_deploy_command", lambda *a: None)
        monkeypatch.setattr(projects, "discard", lambda *a, **kw: calls.append("cleanup"))

        def verify(*args):
            calls.append("verify")
            if terminal == "failed":
                deploy._append_log(slug, "HTTP 503")
                raise projects.ProjectError(502, "线上验证失败")
            deploy._append_log(slug, "health=healthy")

        monkeypatch.setattr(deploy, "_run_verify_command", verify)

        def tick_before_notice(_slug):
            if deferred:
                archive.tick_board(slug, pkg.common.read_team(slug))
                assert not seen

        def restart():
            if reload == "disabled":
                return False
            calls.append("restart")
            return reload != "schedule_failed"

        monkeypatch.setattr(deploy, "_mark_attempt", tick_before_notice)
        monkeypatch.setattr(deploy, "_schedule_gateway_restart", restart)
        deploy._run_ship(slug, profile, "auto", cleanup=True)
        prefix = ["cleanup", "verify"]
        if deferred:
            prefix += ["notice", "restart"]
            if reload != "schedule_failed":
                assert calls == prefix and not seen
                team = pkg.common.read_team(slug)
                entry = team["conclusion"]["vault_archive"]
                assert entry["status"] == "pending"
                if reload == "new_process":
                    monkeypatch.setattr(archive, "_PROCESS_TOKEN", "new-gateway")
                else:
                    monkeypatch.setattr(archive, "now", lambda: entry["deferred_at"] + archive.ARCHIVE_STALE - 1)
                    archive.tick_board(slug, team)
                    assert calls == prefix and not seen
                    monkeypatch.setattr(archive, "now", lambda: entry["deferred_at"] + archive.ARCHIVE_STALE)
                archive.tick_board(slug, team)
            assert calls == prefix + ["refresh", "archive notice"]
            team = pkg.common.read_team(slug)
            assert f"archive:{archive.version_key(team)}" in team["notified"]
            assert notify.archive_notice(slug, team) is None
            archive.tick_board(slug, team)
            assert calls == prefix + ["refresh", "archive notice"]
        else:
            assert calls == prefix + ["refresh", "notice"]
    else:
        monkeypatch.setattr(deploy, "_attempt_key", lambda _team: "0:abcdef")
        assert not deploy.tick_board(slug, pkg.common.read_team(slug))
        assert calls == ["refresh", "notice"]
    assert archive.run(slug)["status"] == "skipped"
    assert len(seen) == 1
    assert not (run_dir / "obsidian-archive.jsonl").exists()


@pytest.mark.parametrize("status, logic, age, allowed, rejudge", [
    ("skipped", None, 0, True, True),
    ("failed", None, 599, True, True),
    ("failed", 1, 0, True, True),
    ("skipped", None, 601, True, False),
    ("skipped", archive.ARCHIVE_LOGIC, 0, True, False),
    ("saved", None, 0, True, False),
    ("failed", None, 0, False, False),
])
def test_new_archive_logic_rejudges_only_recent_eligible_terminal_failures(
        pkg, team_id, plan_dict, vault, monkeypatch, status, logic, age, allowed, rejudge):
    slug, _run_dir = completed(pkg, team_id, plan_dict, allowed=allowed)
    now = pkg.common.now()
    monkeypatch.setattr(archive, "now", lambda: now)

    def mark(rec):
        rec.update(completed_at=now - 900, project={"deploy": {"status": "succeeded", "finished_at": now - age}})
        rec["conclusion"]["generated_at"] = now - 900
        rec["conclusion"]["vault_archive"] = {
            "status": status, "version_key": archive.version_key(rec), **({"logic": logic} if logic is not None else {}),
        }

    team = pkg.common.update_team(slug, mark)
    before = team["conclusion"]["vault_archive"]
    seen = model(pkg, monkeypatch, [{"should_archive": False, "reason": "新逻辑已复查"}] if rejudge else [])
    sent = []
    monkeypatch.setattr(notify, "archive_notice", lambda _slug, rec: sent.append(rec["conclusion"]["vault_archive"]))
    archive.tick_board(slug, team)
    fresh = pkg.common.read_team(slug)
    archive.tick_board(slug, fresh)
    current = fresh["conclusion"]["vault_archive"]
    if rejudge:
        assert len(seen) == 1 and sent == [current]
        assert current["status"] == "skipped" and current["reason"] == "新逻辑已复查"
        assert current["logic"] == archive.ARCHIVE_LOGIC
    else:
        assert not seen and not sent and current == before


def test_archive_notice_uses_the_qq_thread_and_deduplicates_stale_snapshots(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, _run_dir = completed(pkg, team_id, plan_dict, title="协作台 <复核>")
    origin = {"platform": "qqbot", "chat_id": "qq-chat", "thread_id": "thread", "user_id": "qq-user"}

    def mark(rec):
        rec["origin"] = origin
        rec["conclusion"]["vault_archive"] = {"status": "skipped", "version_key": archive.version_key(rec),
                                               "reason": "已有笔记"}

    team = pkg.common.update_team(slug, mark)
    monkeypatch.setattr(link, "owner_for", lambda platform, user: "u1" if (platform, user) == ("qqbot", "qq-user") else None)
    monkeypatch.setattr(link, "team_url", lambda *_a: "https://example.test/team")
    monkeypatch.setattr(remote, "ready", lambda platform: platform == "qqbot")
    monkeypatch.setattr(remote, "jobs", lambda: {f"team:{team_id}": {
        **origin, "owner": "u1", "reply_to": "qq-message",
    }})
    sent = []
    monkeypatch.setattr(remote, "send", lambda job, message: sent.append((job, message)) or True)
    assert notify.archive_notice(slug, team) == 1
    assert notify.archive_notice(slug, team) is None
    assert sent == [({"platform": "qqbot", "chat_id": "qq-chat", "thread_id": "thread", "reply_to": "qq-message"},
                     "📚 协作台 <复核> · Obsidian：未写入知识库（已有笔记）\n🌐 协作台：https://example.test/team")]


def test_public_state_cleans_a_historical_reason_and_keeps_internal_fields_private():
    entry = {"status": "skipped", "after_reload": "token", "announce": True, "logic": 2,
             "reason": "📚 Obsidian：未写入知识库，Obsidian: 未写入。已有完整笔记"}
    assert archive.public_state(entry) == {"status": "skipped", "reason": "已有完整笔记"}
    assert archive.summary_line(entry) == "📚 Obsidian：未写入知识库（已有完整笔记）"


def test_archive_receipts_and_backups_stay_out_of_a_members_git_add(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    workspace = run_dir.parent
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (run_dir / ".gitignore").write_text("scratch/", encoding="utf-8")  # a member's own entry survives
    model(pkg, monkeypatch, [DECISION, {"action": "create", "path": NOTE, "reason": "验证通过",
                                        "content": body(slug, "`pytest -q t.py` → 1 passed")}])
    assert archive.run(slug)["status"] == "saved"
    pkg.common.update_team(slug, lambda rec: rec["conclusion"].update(
        generated_at=rec["conclusion"]["generated_at"] + 1))

    def update(details):
        note, = details["notes"]
        return {"action": "update", "path": NOTE, "expect_sha": note["sha256"],
                "content": body(slug, "`pytest -q t2.py` → 2 passed", updated=True)}

    model(pkg, monkeypatch, [DECISION, update])
    assert archive.run(slug)["status"] == "saved"
    assert any(p.is_file() for p in (run_dir / "obsidian-backups").rglob("*"))
    lines = (run_dir / ".gitignore").read_text().splitlines()
    assert lines == ["scratch/", "/obsidian-archive.jsonl", "/obsidian-backups/"]
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    staged = subprocess.run(["git", "-C", str(workspace), "diff", "--cached", "--name-only"],
                            check=True, capture_output=True, text=True).stdout.split()
    assert ".halo/.gitignore" in staged
    assert not [p for p in staged if "obsidian" in p]


@pytest.mark.parametrize("goal, skipped", [
    ("协作台完成后不自动存入知识库，修一下", False),
    ("排查 Obsidian 不更新的原因", False),
    ("验证流程，请不要动 Obsidian", True),
    ("这次不用写笔记", True),
    ("跳过知识库归档", True),
])
def test_opt_out_matches_imperatives_not_bug_reports(goal, skipped):
    assert bool(archive._SKIP.search(goal)) is skipped


def test_draft_gets_a_longer_per_call_budget_than_the_decision(pkg, team_id, plan_dict, vault, monkeypatch):
    slug, run_dir = completed(pkg, team_id, plan_dict)
    timeouts = []

    def respond(messages, **kwargs):
        timeouts.append(kwargs["timeout"])
        return json.dumps(DECISION if len(timeouts) == 1 else {"action": "skip", "reason": "已有"}), "", {"model": "m"}

    monkeypatch.setattr(pkg.plan, "call_model", respond)
    assert archive.run(slug)["status"] == "skipped"
    assert timeouts == [40, 75]
