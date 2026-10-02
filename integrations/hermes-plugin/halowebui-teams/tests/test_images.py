"""生图: a goal that needs pictures gets an image member (gpt-image through Hermes' image_generate,
so a Hermes member only), offered the owner's own HaloWebUI image templates; every image it makes
is kept in the workspace with its prompt, and the conclusion shows them."""

import json
from pathlib import Path

PLAN = {
    "title": "雨山云树图解",
    "members": [
        {"name": "researcher", "role": "调研", "kind": "research"},
        {"name": "illustrator", "role": "插画师", "kind": "image", "executor": "cchclaude"},
    ],
    "tasks": [
        {"key": "T1", "title": "查成因", "description": "写 notes.md", "member": "researcher"},
        {"key": "T2", "title": "画图解", "description": "按 notes.md 画一张横版信息图", "member": "illustrator",
         "depends_on": ["T1"]},
    ],
}
TEMPLATES = [
    {"id": "halo_hand_v1_auto_style", "name": "手绘万能图 · 自动选画风与画幅", "tags": ["图解", "创意"],
     "aspect": "3:2", "size": "1536x1024", "prompt": "请把下面的内容画成一张手绘信息图……\n\n内容："},
    {"id": "x", "name": "知识卡片 · 小红书封面", "aspect": "2:3", "prompt": "你是一位擅长做「知识卡片」的平面设计师。\n内容："},
    {"id": "empty", "name": "没有提示词的", "prompt": ""},
]


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


def test_an_image_member_runs_on_hermes_and_is_told_how_images_work(pkg, team_id):
    plan, errors = pkg.plan.validate_plan(json.loads(json.dumps(PLAN)))
    assert not errors
    image = next(m for m in plan["members"] if m["name"] == "illustrator")
    # only Hermes has gpt-image: the kind's chain is Hermes alone, whatever the lead wrote
    assert image["kind"] == "image" and pkg.runners.kind_default("image") == "hermes"
    assert image["executor"] == "hermes" and image["runner"] == "hermes"  # not the cchclaude the lead wrote
    assert pkg.runners.chain_from("hermes") == ["hermes"]
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="分析雨天山上树木有云的原因，然后生成一张图",
                                    image_templates=TEMPLATES)
    slug = pkg.common.board_slug(team_id)
    team = pkg.common.read_team(slug)
    assert team["image_templates"] == ["手绘万能图 · 自动选画风与画幅（3:2）", "知识卡片 · 小红书封面（2:3）"]
    written = (Path(team["workspace"]) / ".halo" / "image-templates.md").read_text(encoding="utf-8")
    assert "## 手绘万能图 · 自动选画风与画幅（图解 / 创意；3:2；1536x1024）" in written and "内容：" in written
    assert "没有提示词的" not in written
    with pkg.common.board_conn(slug) as conn:
        bodies = {k: _kb().get_task(conn, tid).body for k, tid in created["tasks"].items()}
    assert "image_generate" in bodies["T2"] and "images/" in bodies["T2"] and ".halo/image-templates.md" in bodies["T2"]
    assert "手绘万能图" in bodies["T2"]
    assert "绝不要因此停下来问人" in bodies["T2"]  # a rate-limited vision check once blocked a finished picture
    assert "image_generate" not in bodies["T1"]
    # the image is not in a listing of the team's deliverables (.halo is hidden)
    assert not any(f["path"].startswith(".halo") for f in pkg.conclusion.list_files(team))


def test_a_plan_without_kinds_still_recognises_an_image_member(pkg):
    assert pkg.plan.infer_kind("插画师", "给文章配图") == "image"
    assert pkg.plan.infer_kind("visual", "把整体生成一张图") == "image"
    assert pkg.plan.infer_kind("前端", "写页面组件") == "ui"
    assert "kind 为 \"image\"" in pkg.plan.system_prompt() and "生图 / 插画 / 信息图" in pkg.plan.system_prompt()


def test_every_generated_image_is_kept_with_its_prompt(pkg, team_id, monkeypatch, tmp_path):
    plan, errors = pkg.plan.validate_plan(json.loads(json.dumps(PLAN)))
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="画图")
    slug = pkg.common.board_slug(team_id)
    t2 = created["tasks"]["T2"]
    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", t2)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "")
    pkg.hooks._state.update({"tool_events": 0, "truncated": False, "delivered_upto": None})
    cache = tmp_path / "cache"
    cache.mkdir()
    first = cache / "openai_gpt-image-2-medium_1.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
    second = cache / "openai_gpt-image-2-high_2.png"
    second.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 32)
    prompt = "手绘信息图：雨天暖湿空气沿山坡抬升，冷却凝结成低云，笼罩山坡树林；标题「为什么山上的树在云里」"
    pkg.hooks.on_post_tool_call(tool_name="image_generate", args=json.dumps({"prompt": prompt, "aspect_ratio": "landscape"}),
                                result=json.dumps({"success": True, "image": str(first), "model": "gpt-image-2-medium",
                                                   "provider": "openai", "actual_size": "1672x941"}), status="ok")
    pkg.hooks.on_post_tool_call(tool_name="image_generate", args={"prompt": "第二张", "aspect_ratio": "square"},
                                result={"success": True, "image": str(second)}, status="ok")
    # nothing to keep: a failure, a remote URL, a file that is not an image
    pkg.hooks.on_post_tool_call(tool_name="image_generate", args={"prompt": "x"}, result={"success": False, "error": "429"})
    pkg.hooks.on_post_tool_call(tool_name="image_generate", args={"prompt": "x"},
                                result={"success": True, "image": "https://example.com/a.png"})
    pkg.hooks.on_post_tool_call(tool_name="image_generate", args={"prompt": "x"}, result="not json")
    ws = Path(pkg.common.read_team(slug)["workspace"])
    assert (ws / "images" / "T2-1.png").read_bytes() == first.read_bytes()
    assert (ws / "images" / "T2-2.png").exists() and not (ws / "images" / "T2-3.png").exists()
    note = (ws / "images" / "T2-1.prompt.md").read_text(encoding="utf-8")
    assert prompt in note and "gpt-image-2-medium（openai）" in note and "landscape · 实际 1672x941" in note
    assert "成员 illustrator" in note
    tools = [e for e in pkg.teams.timeline(team_id, "u1")["events"] if e["type"] == "tool"]
    assert tools[0]["text"].startswith("已保存 images/T2-1.png · 手绘信息图")
    files = {f["path"]: f["kind"] for f in pkg.conclusion.list_files(pkg.common.read_team(slug))}
    assert files["images/T2-1.png"] == "image" and files["images/T2-1.prompt.md"] == "text"


def test_the_conclusion_is_asked_to_show_the_images_with_their_prompts(pkg):
    assert "images/" in pkg.conclusion.SYSTEM_PROMPT and ".prompt.md" in pkg.conclusion.SYSTEM_PROMPT
    assert "提示词：" in pkg.conclusion.SYSTEM_PROMPT


# --- 为结果配图 --------------------------------------------------------------------------------------

def _concluded_team(pkg, team_id, plan_dict, monkeypatch, report="# 科学戒烟行动指南\n\n> 先定戒烟日。\n\n## 一、准备\n\n选一个具体的日子，告诉家人朋友，清理香烟和打火机。\n"):
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: (report, "", {"model": "gpt-chat"}))
    plan, errors = pkg.plan.validate_plan(plan_dict)
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="如何戒烟")
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        for key, tid in created["tasks"].items():
            assert _kb().claim_task(conn, tid, claimer="test") is not None
            _kb().complete_task(conn, tid, result="好了", summary="好了")
    pkg.teams.snapshot(team_id, "u1")  # completes → writes the conclusion (sync in tests)
    return slug


def test_the_result_gets_a_picture_in_the_users_template_style(pkg, team_id, plan_dict, monkeypatch, tmp_path):
    import halowebui_teams.illustrate as illustrate

    slug = _concluded_team(pkg, team_id, plan_dict, monkeypatch)
    drawn = tmp_path / "openai_gpt-image-2_1.png"
    drawn.write_bytes(b"\x89PNG\r\n\x1a\n" + b"9" * 32)
    seen = {}

    def condense(messages, *a, **k):
        seen["condense"] = messages
        return "标题：科学戒烟\n要点：\n🗓 定戒烟日\n🚭 清理香烟", "", {"model": "gpt-chat"}

    def draw(args):
        seen["draw"] = args
        return json.dumps({"success": True, "image": str(drawn), "model": "gpt-image-2-medium", "provider": "openai"})

    monkeypatch.setattr(pkg.plan, "call_model", condense)
    monkeypatch.setattr(illustrate, "generate_image", draw)
    with __import__("pytest").raises(ValueError):
        illustrate.start("halo-nothing")  # no conclusion yet
    entry = illustrate.start(slug, {"name": "知识卡片 · 小红书封面", "prompt": "做成竖版知识卡片。\n\n内容：", "aspect": "2:3"})
    assert entry["status"] == "ready" and entry["path"] == "images/result-1.png" and entry["template"] == "知识卡片 · 小红书封面"
    assert seen["draw"]["prompt"] == "做成竖版知识卡片。\n\n内容：\n标题：科学戒烟\n要点：\n🗓 定戒烟日\n🚭 清理香烟"
    assert seen["draw"]["aspect_ratio"] == "portrait" and "先定戒烟日" in seen["condense"][1]["content"]
    team = pkg.common.read_team(slug)
    ws = Path(team["workspace"])
    assert (ws / "images" / "result-1.png").exists() and "结论配图（模板：知识卡片" in (ws / "images" / "result-1.prompt.md").read_text()
    md = (ws / ".halo" / "conclusion.md").read_text(encoding="utf-8")
    # under the title and its one-line summary, before the body
    assert md.index("> 先定戒烟日。") < md.index("![科学戒烟行动指南](images/result-1.png)") < md.index("## 一、准备")
    assert "[提示词](images/result-1.prompt.md)" in md and md.count(illustrate.MARK) == 1
    brief = pkg.teams.snapshot(team_id, "u1")["team"]["conclusion"]
    assert brief["illustration"]["status"] == "ready" and brief["illustration"]["path"] == "images/result-1.png"
    # drawing again replaces the picture in place; a rewritten conclusion keeps the latest picture
    illustrate.start(slug, None)
    md = (ws / ".halo" / "conclusion.md").read_text(encoding="utf-8")
    assert md.count(illustrate.MARK) == 1 and "images/result-2.png" in md and "images/result-1.png" not in md
    assert seen["draw"]["aspect_ratio"] == "landscape"
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: ("# 新版本\n\n正文。这一版写得更完整，包含所有的步骤、注意事项、可能遇到的困难和应对办法。\n", "", {"model": "gpt-chat"}))
    pkg.conclusion.start(slug, by="user", force=True)
    md = (ws / ".halo" / "conclusion.md").read_text(encoding="utf-8")
    assert md.startswith("# 新版本") and "images/result-2.png" in md and md.index("images/result-2.png") < md.index("正文。")


def test_a_picture_that_could_not_be_drawn_says_why(pkg, team_id, plan_dict, monkeypatch):
    import halowebui_teams.illustrate as illustrate

    slug = _concluded_team(pkg, team_id, plan_dict, monkeypatch)
    monkeypatch.setattr(pkg.plan, "call_model", lambda *a, **k: ("标题：x\n要点：y", "", {"model": "gpt-chat"}))
    monkeypatch.setattr(illustrate, "generate_image", lambda args: json.dumps({"success": False, "error": "429 rate limit"}))
    entry = illustrate.start(slug, None)
    assert entry["status"] == "failed" and "429" in entry["error"]
    md = (Path(pkg.common.read_team(slug)["workspace"]) / ".halo" / "conclusion.md").read_text(encoding="utf-8")
    assert illustrate.MARK not in md


def test_drawing_shows_as_a_stage(pkg, team_id, plan_dict, monkeypatch):
    import halowebui_teams.illustrate as illustrate

    slug = _concluded_team(pkg, team_id, plan_dict, monkeypatch)
    pkg.conclusion._set(slug, acceptance={"status": "ready", "verdict": "met"})
    illustrate._set(slug, status="generating", started_at=pkg.common.now(), step="draw", template="手绘万能图")
    stage = pkg.teams.snapshot(team_id, "u1")["team"]["stage"]
    assert stage["key"] == "illustrating" and "手绘万能图" in stage["now"] and "gpt-image 在画图" in stage["now"]
    assert stage["eta"]["seconds"] > 0
    assert illustrate.aspect_of({"aspect": "1:1"}) == "square" and illustrate.aspect_of({"size": "1536x1024"}) == "landscape"
