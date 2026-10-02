"""The team's conclusion: written by the lead model from the full records when the team
finishes, assembled from the records when no model answers; workspace files served safely."""

import json
import os
import uuid
from pathlib import Path

import pytest


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


LONG = "## 接口\n\n" + "\n".join(f"- 第 {i} 条要点：" + "细节" * 40 for i in range(200))


def _finished_team(pkg, *, results=None):
    plan, errors = pkg.plan.validate_plan({
        "title": "结论演练",
        "members": [{"name": "backend-dev", "role": "后端开发", "assistant": "17", "kind": "research"},
                    {"name": "writer", "role": "写报告", "kind": "writing"}],
        "tasks": [{"key": "T1", "title": "调研", "description": "写 notes.md", "member": "backend-dev"},
                  {"key": "T2", "title": "报告", "description": "写 report.md", "member": "writer", "depends_on": ["T1"]}],
    })
    assert not errors
    team_id = str(uuid.uuid4())
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="调研并写报告")
    slug = pkg.common.board_slug(team_id)
    ws = Path(pkg.common.read_team(slug)["workspace"])
    (ws / "report.md").write_text("# 报告\n\n结论：可行。\n", encoding="utf-8")
    (ws / "shots").mkdir()
    (ws / "shots" / "home.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    (ws / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    results = results or {"T1": LONG, "T2": "报告写在 report.md，截图 shots/home.png"}
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2"):
            tid = created["tasks"][key]
            assert kb.claim_task(conn, tid, claimer="test") is not None
            kb.complete_task(conn, tid, result=results[key], summary=results[key][:200])
    return team_id, slug, ws


def test_finished_team_gets_a_lead_written_conclusion(pkg, monkeypatch):
    seen = []

    def fake(messages, timeout=150, **kw):
        seen.append(messages)
        return "# 结论演练\n\n> 做成了\n\n## 产出物\n\n![首页](shots/home.png)\n", "", {
            "model": "gpt-chat", "label": "Hermes 默认模型", "source": "hermes_default"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
    team_id, slug, ws = _finished_team(pkg)
    snap = pkg.teams.snapshot(team_id, "u1")  # notices completion → writes the conclusion (sync in tests)
    assert snap["team"]["phase"] == "completed"
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    assert data["status"] == "ready" and data["markdown"].startswith("# 结论演练")
    assert data["entry"]["model"] == "gpt-chat" and data["entry"]["source"] == "lead"
    assert (ws / ".halo" / "conclusion.md").exists()
    # The lead saw the full results (not a 1500-char summary) and the deliverable files.
    prompt = seen[0][1]["content"]
    assert "第 100 条要点" in prompt and "report.md" in prompt and "结论：可行" in prompt
    assert {f["path"] for f in data["files"]} >= {"report.md", "shots/home.png", "page.html"}
    assert next(f for f in data["files"] if f["path"] == "shots/home.png")["kind"] == "image"
    assert data["tasks"][0]["result"].endswith(LONG[-40:])
    concluded = [e for e in pkg.teams.timeline(team_id, "u1")["events"] if e["type"] == "team" and e["data"].get("action") == "concluded"]
    assert len(concluded) == 1
    assert pkg.teams.snapshot(team_id, "u1")["team"]["conclusion"]["status"] == "ready"


def test_no_model_answer_still_gives_a_conclusion_from_the_records(pkg, monkeypatch):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (None, "负责人模型都调用失败：gpt-chat 502", {}))
    team_id, slug, _ws = _finished_team(pkg)
    pkg.teams.snapshot(team_id, "u1")
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    assert data["status"] == "ready" and data["entry"]["source"] == "assembled"
    md = data["markdown"]
    assert "2/2 个任务完成" in md and "第 199 条要点" in md and "![shots/home.png](shots/home.png)" in md
    assert "502" in data["entry"]["fallback_reason"]


def test_regenerate_replaces_the_report(pkg, monkeypatch):
    replies = iter(["# 第一版\n\n" + "内容" * 30, "# 第二版\n\n" + "内容" * 30])
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (next(replies), "", {"model": "gpt-chat"}))
    team_id, slug, _ws = _finished_team(pkg)
    pkg.teams.snapshot(team_id, "u1")
    assert pkg.conclusion.read(slug, pkg.common.read_team(slug))["markdown"].startswith("# 第一版")
    pkg.conclusion.start(slug, by="user", force=True)
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    assert data["markdown"].startswith("# 第二版") and data["entry"]["by"] == "user"


def test_files_are_served_only_from_the_workspace(pkg, monkeypatch, tmp_path):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (None, "x", {}))
    team_id, slug, ws = _finished_team(pkg)
    team = pkg.common.read_team(slug)
    data, ctype, name = pkg.conclusion.read_file(team, "shots/home.png")
    assert ctype == "image/png" and name == "home.png" and data.startswith(b"\x89PNG")
    _d, ctype, _n = pkg.conclusion.read_file(team, "page.html")
    assert ctype == "text/plain"  # a member's HTML never renders as a page
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    os.symlink(secret, ws / "link.txt")
    for bad in ("../" * 6 + "etc/passwd", "/etc/passwd", "link.txt", "shots/../../x", "missing.png"):
        with pytest.raises(FileNotFoundError):
            pkg.conclusion.read_file(team, bad)
    assert "link.txt" not in {f["path"] for f in pkg.conclusion.list_files(team)}


def test_conclusion_and_files_are_per_owner(pkg, monkeypatch):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (None, "x", {}))
    team_id, _slug, _ws = _finished_team(pkg)
    with pytest.raises(pkg.teams.TeamError) as err:
        pkg.teams._require_team(team_id, "someone-else")
    assert err.value.status == 404


def test_bridge_notices_a_finished_team_nobody_is_watching(pkg, monkeypatch):
    import halowebui_teams.bridge as bridge

    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: ("# 无人值守\n\n" + "内容" * 30, "", {"model": "gpt-chat"}))
    team_id, slug, _ws = _finished_team(pkg)
    assert pkg.common.read_team(slug)["state"] == "running"  # nobody read a snapshot yet
    bridge._catch_up_conclusion(slug, pkg.common.read_team(slug))
    team = pkg.common.read_team(slug)
    assert team["state"] == "completed" and team["conclusion"]["status"] == "ready"
