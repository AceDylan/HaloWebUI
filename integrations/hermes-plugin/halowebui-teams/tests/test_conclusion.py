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

    def fake(messages, *a, **k):  # the acceptance check after each report answers on its own
        if "验收" in messages[0]["content"][:80]:
            return '{"verdict": "met", "summary": "达成", "gaps": []}', "", {"model": "gpt-chat"}
        return next(replies), "", {"model": "gpt-chat"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
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


# --- the conclusion is the complete result -------------------------------------------------------

GUIDE = "# 科学戒烟行动指南\n\n## 一、设定戒烟日\n\n" + "选一个具体日子。" * 900 + "\n\n![流程](img/flow.png)\n\n[来源](refs.md)\n"


def _guide_team(pkg):
    team_id, slug, ws = _finished_team(pkg, results={"T1": "查到了权威资料", "T2": "完整指南写在 docs/guide.md"})
    (ws / "docs" / "img").mkdir(parents=True)
    (ws / "docs" / "guide.md").write_text("---\ntitle: x\n---\n" + GUIDE, encoding="utf-8")
    (ws / "docs" / "img" / "flow.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return team_id, slug, ws


def test_the_lead_places_a_finished_document_in_full(pkg, monkeypatch):
    seen = []

    def fake(messages, timeout=150, **kw):
        seen.append((messages, kw, timeout))
        if "验收" in messages[0]["content"][:80]:
            return '{"verdict": "met", "summary": "达成", "gaps": []}', "", {"model": "gpt-chat"}
        return ("# 戒烟：完整方案\n\n> 先定戒烟日。\n\n<!-- halo:include docs/guide.md -->\n\n"
                "```\n<!-- halo:include report.md -->\n```\n\n<!-- halo:include ../../etc/passwd -->\n"
                "<!-- halo:include shots/home.png -->\n\n## 附注\n\n没有个性化。\n"), "", {"model": "gpt-chat"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
    team_id, slug, _ws = _guide_team(pkg)
    pkg.teams.snapshot(team_id, "u1")
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    md = data["markdown"]
    # The whole document, not a summary: every sentence of it, its headings under the result's title.
    assert md.count("选一个具体日子。") == 900
    assert "\n## 科学戒烟行动指南\n" in md and "\n### 一、设定戒烟日\n" in md and md.startswith("# 戒烟：完整方案")
    assert "title: x" not in md  # front matter dropped
    # Its relative links now resolve from the workspace root.
    assert "![流程](docs/img/flow.png)" in md and "[来源](docs/refs.md)" in md
    # Inside code it stays literal; outside the workspace / binary files are never placed.
    assert "```\n<!-- halo:include report.md -->\n```" in md
    assert "passwd" not in md.replace("../../etc/passwd", "") and "PNG" not in md
    assert md.rstrip().endswith("没有个性化。")
    entry = data["entry"]
    assert entry["format"] == 2 and entry["included"] == ["docs/guide.md"] and entry["chars"] == len(md)
    brief = pkg.teams.snapshot(team_id, "u1")["team"]["conclusion"]
    assert brief["format"] == 2 and brief["included"] == ["docs/guide.md"]
    # The lead was asked for the complete result, with room for it, and saw the whole document.
    messages, kw, timeout = seen[0]
    assert "完整结果" in messages[0]["content"] and "halo:include" in messages[0]["content"]
    assert kw["max_tokens"] >= 16000 and timeout >= 600
    assert messages[1]["content"].count("选一个具体日子。") == 900


def test_a_long_document_is_cut_in_the_prompt_but_placed_in_full(pkg, monkeypatch):
    seen = []
    monkeypatch.setattr(pkg.plan, "call_model", lambda m, *a, **k: (seen.append(m) or "# 结果\n\n<!-- halo:include book.md -->\n", "", {"model": "gpt-chat"}))
    team_id, slug, ws = _finished_team(pkg)
    (ws / "book.md").write_text("# 书\n\n" + "长" * 90000 + "\n结尾句。\n", encoding="utf-8")
    pkg.teams.snapshot(team_id, "u1")
    prompt = seen[0][1]["content"]
    assert "全文 9" in prompt and "用 halo:include 引用时放的是全文" in prompt and "结尾句" not in prompt
    md = pkg.conclusion.read(slug, pkg.common.read_team(slug))["markdown"]
    assert md.count("长") >= 90000 and "结尾句。" in md


def test_a_wrapped_answer_is_unwrapped_and_includes_still_work(pkg, monkeypatch):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: ("```markdown\n# 结果\n\n<!-- halo:include report.md -->\n```", "", {"model": "gpt-chat"}))
    team_id, slug, _ws = _finished_team(pkg)
    pkg.teams.snapshot(team_id, "u1")
    md = pkg.conclusion.read(slug, pkg.common.read_team(slug))["markdown"]
    assert md.startswith("# 结果") and "## 报告" in md and "结论：可行。" in md and "```" not in md


def test_without_a_model_the_main_document_is_still_there_in_full(pkg, monkeypatch):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (None, "负责人模型都调用失败", {}))
    team_id, slug, _ws = _guide_team(pkg)
    pkg.teams.snapshot(team_id, "u1")
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    assert data["entry"]["source"] == "assembled" and data["markdown"].count("选一个具体日子。") == 900
    assert data["entry"]["included"] == ["docs/guide.md"]


def test_a_provider_with_a_lower_output_cap_gets_its_cap(pkg, monkeypatch):
    import agent.auxiliary_client as aux

    calls = []

    class Resp:
        def __init__(self, text):
            self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]

    def fake_llm(**kw):
        calls.append(kw["max_tokens"])
        if kw["max_tokens"] > 8192:
            raise RuntimeError("Invalid max_tokens value, the valid range of max_tokens is [1, 8192]")
        return Resp("好")

    monkeypatch.setattr(aux, "call_llm", fake_llm)
    monkeypatch.setattr(pkg.plan, "lead_routes", lambda **k: [{"provider": "deepseek", "model": "deepseek-chat", "source": "hermes_default"}])
    text, reason, used = pkg.plan.call_model([{"role": "user", "content": "x"}], max_tokens=16000)
    assert text == "好" and calls == [16000, pkg.plan.SAFE_MAX_TOKENS] and used["model"] == "deepseek-chat"
