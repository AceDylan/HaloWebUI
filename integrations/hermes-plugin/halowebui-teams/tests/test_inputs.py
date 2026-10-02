"""Files given with the goal (HaloWebUI uploads): the lead plans knowing them, the team gets them
in its workspace (inputs/, or .halo/inputs/ in a project's worktree), members are told where."""

import json
from pathlib import Path


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


def test_the_lead_plans_knowing_the_files(pkg):
    messages = pkg.plan.build_messages("根据体检报告给饮食建议", "/w", inputs=["体检报告.pdf", "../../etc/x", "舌苔.png"])
    user = messages[1]["content"]
    assert "- inputs/体检报告.pdf" in user and "- inputs/舌苔.png" in user and "- inputs/x" in user
    assert "../" not in user.split("用户随目标附带了文件")[1]
    project = pkg.plan.build_messages("改代码", "/repo", project={"path": "/repo", "name": "repo"}, inputs=["spec.md"])
    assert "- .halo/inputs/spec.md" in project[1]["content"]


def test_the_team_gets_the_files_and_members_are_told(pkg, team_id, plan_dict, tmp_path):
    report = tmp_path / "f-pdf_体检报告.pdf"
    report.write_bytes(b"%PDF-1.4 x")
    photo = tmp_path / "f-img.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    link = tmp_path / "link.txt"
    link.symlink_to(report)
    plan, errors = pkg.plan.validate_plan(plan_dict)
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="根据体检报告和照片给饮食建议", inputs=[
        {"name": "体检报告.pdf", "path": str(report)}, {"name": "体检报告.pdf", "path": str(report)},
        {"name": "舌苔.png", "path": str(photo)}, {"name": "x.txt", "path": str(link)},
        {"name": "missing.txt", "path": str(tmp_path / "nope.txt")}, {"name": "rel.txt", "path": "relative.txt"}])
    slug = pkg.common.board_slug(team_id)
    team = pkg.common.read_team(slug)
    assert team["inputs"] == ["inputs/体检报告.pdf", "inputs/体检报告 (2).pdf", "inputs/舌苔.png"]
    ws = Path(team["workspace"])
    assert (ws / "inputs" / "舌苔.png").read_bytes() == photo.read_bytes()
    with pkg.common.board_conn(slug) as conn:
        body = _kb().get_task(conn, created["tasks"]["T1"]).body
    assert "inputs/体检报告.pdf" in body and "inputs/舌苔.png" in body and "看图" in body
    # the files the user gave are not what the team made
    (ws / "advice.md").write_text("建议", encoding="utf-8")
    assert [f["path"] for f in pkg.conclusion.list_files(team)] == ["advice.md"]
