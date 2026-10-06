"""Teams on a real project: the team branch in a worktree, a commit per finished task, the change
set, merge / push / discard as explicit actions, and which directories may never be a project."""

import os
import subprocess

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


def _create(pkg, team_id, plan_dict, repo):
    plan_dict["project"] = {"path": str(repo), "name": "myapp", "auto": True}
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors and plan["project"]["path"] == str(repo)
    return pkg.teams.create_team(team_id, plan, owner="u1", goal="改 myapp")


def _finish(pkg, slug, task_id, change=None):
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        kb.recompute_ready(conn)
        kb.claim_task(conn, task_id, claimer="w")
        if change:
            change()
        kb.complete_task(conn, task_id, result="ok", summary="ok")


def test_team_gets_its_own_branch_and_commits_per_task(pkg, team_id, plan_dict, repo):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    team = pkg.common.read_team(slug)
    ws = team["workspace"]
    assert team["project"]["branch"] == f"halo/{slug}" and team["project"]["base_branch"] == "main"
    assert _git(ws, "rev-parse", "--abbrev-ref", "HEAD") == f"halo/{slug}"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"  # the user's checkout is untouched
    with pkg.common.board_conn(slug) as conn:
        body = _kb().get_task(conn, first["tasks"]["T1"]).body
    assert "不要 git push" in body and f"halo/{slug}" in body

    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "api.md"), "w").write("接口\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    _finish(pkg, slug, first["tasks"]["T2"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    bridge._commit_finished(slug, pkg.common.read_team(slug))  # nothing new: no empty commit
    subjects = _git(ws, "log", "--format=%s", "main..HEAD").splitlines()
    assert subjects == ["[T2 · frontend-dev] 写页面", "[T1 · backend-dev] 写接口"]

    os.makedirs(os.path.join(ws, ".halo"), exist_ok=True)
    open(os.path.join(ws, ".halo", "conclusion.md"), "w").write("结论")
    open(os.path.join(ws, "notes.txt"), "w").write("还没提交")
    data = projects.changes(pkg.common.read_team(slug))
    assert [c["task_key"] for c in data["commits"]] == ["T2", "T1"]
    assert {f["path"] for f in data["files"]} == {"api.md", "app.py"}
    assert data["pending"] == ["notes.txt"] and data["merged"] is False
    assert "+print('v2')" in projects.diff(pkg.common.read_team(slug), "app.py")
    assert "还没提交" in projects.diff(pkg.common.read_team(slug), "notes.txt")
    with pytest.raises(projects.ProjectError):
        projects.diff(pkg.common.read_team(slug), "../etc/passwd")
    files = {f["path"] for f in pkg.conclusion.list_files(pkg.common.read_team(slug))}
    assert files == {"api.md", "app.py", "notes.txt"}  # what changed, not the whole repository
    assert "README.md" not in files
    assert "api.md" in projects.summary_text(pkg.common.read_team(slug))


def test_merge_push_and_discard_are_explicit_and_safe(pkg, team_id, plan_dict, repo):
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "api.md"), "w").write("接口\n"))

    with pytest.raises(projects.ProjectError) as err:
        projects.push(slug, pkg.common.read_team(slug), "base")
    assert "先合并" in err.value.message
    assert projects.push(slug, pkg.common.read_team(slug), "branch")["ref"] == f"halo/{slug}"
    assert _git(repo.parent / "origin.git", "branch", "--list", f"halo/{slug}")

    (repo / "app.py").write_text("print('dirty')\n")  # the user is in the middle of something
    with pytest.raises(projects.ProjectError) as err:
        projects.merge(slug, pkg.common.read_team(slug))
    assert "未提交" in err.value.message
    _git(repo, "checkout", "--", "app.py")
    out = projects.merge(slug, pkg.common.read_team(slug))
    assert out["how"] == "fast-forward" and (repo / "api.md").read_text() == "接口\n"
    assert projects.changes(pkg.common.read_team(slug))["merged"] is True
    assert projects.push(slug, pkg.common.read_team(slug), "base")["ref"] == "main"

    os.makedirs(os.path.join(ws, ".halo"), exist_ok=True)
    open(os.path.join(ws, ".halo", "conclusion.md"), "w").write("结论")
    projects.discard(slug, pkg.common.read_team(slug))
    assert not _git(repo, "branch", "--list", f"halo/{slug}")
    assert open(os.path.join(ws, ".halo", "conclusion.md")).read() == "结论"  # the report survives
    assert projects.changes(pkg.common.read_team(slug))["available"] is False


def test_merge_with_a_moved_base_makes_a_merge_commit_or_reports_the_conflict(pkg, team_id, plan_dict, repo):
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('team')\n"))
    (repo / "app.py").write_text("print('mine')\n")
    _git(repo, "commit", "-q", "-am", "my own change")
    with pytest.raises(projects.ProjectError) as err:
        projects.merge(slug, pkg.common.read_team(slug))
    assert "冲突" in err.value.message
    assert not os.path.exists(repo / ".git" / "MERGE_HEAD")  # aborted, the checkout is as it was
    assert (repo / "app.py").read_text() == "print('mine')\n"


def test_home_hermes_home_and_non_repos_are_never_projects(pkg, tmp_path, repo, monkeypatch):
    import halowebui_teams.projects as projects

    monkeypatch.setenv("HOME", str(tmp_path))
    assert projects.toplevel(str(tmp_path)) is None
    assert projects.toplevel(str(repo)) == os.path.realpath(repo)
    assert projects.toplevel(str(repo / "nope")) is None
    plain = tmp_path / "plain"
    plain.mkdir()
    assert projects.toplevel(str(plain)) is None
    monkeypatch.setenv("HERMES_DISPATCH_PROJECTS", f"我的应用={repo};home={tmp_path}")
    names = [c["name"] for c in projects.candidates()]
    assert names == ["myapp"] and projects.candidates()[0]["aliases"] == ["我的应用"]
    assert projects.suggest("给 myapp 加一个接口")["path"] == os.path.realpath(repo)
    assert projects.suggest("给我的应用加一个接口")["path"] == os.path.realpath(repo)
    assert projects.suggest("写一首诗") is None


def test_plan_project_choice(pkg, repo, monkeypatch):
    monkeypatch.setenv("HERMES_DISPATCH_PROJECTS", f"myapp={repo}")
    assert pkg.plan.resolve_project("写一首诗", "") is None
    auto = pkg.plan.resolve_project("给 myapp 加接口", "")
    assert auto["path"] == os.path.realpath(repo) and auto["auto"] is True and auto["branch"] == "main"
    assert pkg.plan.resolve_project("给 myapp 加接口", "none") is None
    with pytest.raises(ValueError):
        pkg.plan.resolve_project("x", "/definitely/not/a/repo")
    messages = pkg.plan.build_messages("给 myapp 加接口", "/w", project=auto)
    assert "README.md 开头" in messages[1]["content"] and "不要安排 push" in messages[0]["content"]


def test_errors_never_carry_url_credentials(pkg):
    import halowebui_teams.projects as projects

    err = projects.ProjectError(502, "推送失败：fatal: unable to access 'https://bot:ghp_secret123@github.com/x/y.git/'")
    assert "ghp_secret123" not in err.message and "https://***@github.com" in err.message


def test_member_commits_count_for_their_task_and_junk_is_never_committed(pkg, team_id, plan_dict, repo):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]

    def work():  # the member commits its own work, and running tests leaves caches behind
        open(os.path.join(ws, "app.py"), "w").write("print('v2')\n")
        _git(ws, "-c", "user.email=m@x", "-c", "user.name=m", "commit", "-qam", "feat: v2")
        os.makedirs(os.path.join(ws, "__pycache__"), exist_ok=True)
        open(os.path.join(ws, "__pycache__", "app.cpython-311.pyc"), "wb").write(b"\0")

    _finish(pkg, slug, first["tasks"]["T1"], work)
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    data = projects.changes(pkg.common.read_team(slug))
    assert [(c["subject"], c["task_key"], c["member"]) for c in data["commits"]] == [("feat: v2", "T1", "backend-dev")]
    assert data["pending"] == [] and {f["path"] for f in data["files"]} == {"app.py"}
    projects.merge(slug, pkg.common.read_team(slug))
    assert "__pycache__" not in _git(repo, "ls-files")


def test_discard_waits_for_the_conclusion(pkg, team_id, plan_dict, repo):
    import halowebui_teams.projects as projects

    _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    team = {**pkg.common.read_team(slug), "conclusion": {"status": "generating"}}
    with pytest.raises(projects.ProjectError) as err:
        projects.discard(slug, team)
    assert "写结论" in err.value.message
    projects.discard(slug, pkg.common.read_team(slug))
    assert os.path.isdir(pkg.common.read_team(slug)["workspace"])  # still there (empty) for the record


def _complete(pkg, slug, **conclusion):
    pkg.common.update_team(slug, lambda rec: rec.update({
        "state": "completed", "conclusion": {"status": "ready", "generated_at": 100, **conclusion}}))


def test_more_work_after_a_merge_can_be_merged_and_pushed_again(pkg, team_id, plan_dict, repo):
    import halowebui_teams.bridge as bridge
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    _finish(pkg, slug, first["tasks"]["T1"], lambda: open(os.path.join(ws, "api.md"), "w").write("接口\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    projects.merge(slug, pkg.common.read_team(slug))
    projects.push(slug, pkg.common.read_team(slug), "base")
    assert projects.changes(pkg.common.read_team(slug))["merged"] is True

    # the lead added work after the merge (a plan change reopened the team): one more commit
    _finish(pkg, slug, first["tasks"]["T2"], lambda: open(os.path.join(ws, "app.py"), "w").write("print('v2')\n"))
    bridge._commit_finished(slug, pkg.common.read_team(slug))
    assert projects.changes(pkg.common.read_team(slug))["merged"] is False  # not hidden behind the old merge
    projects.merge(slug, pkg.common.read_team(slug))
    data = projects.changes(pkg.common.read_team(slug))
    assert data["merged"] is True and (repo / "app.py").read_text() == "print('v2')\n"
    assert "base" not in (data["project"]["pushed"] or {})  # the new merge can be pushed again
    projects.discard(slug, pkg.common.read_team(slug))
    assert projects.changes(pkg.common.read_team(slug))["merged"] is True  # still told after the branch is gone


def test_merge_names_untracked_files_it_would_overwrite(pkg, team_id, plan_dict, repo):
    import halowebui_teams.projects as projects

    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]

    def work():
        os.makedirs(os.path.join(ws, "docs"), exist_ok=True)
        open(os.path.join(ws, "docs", "new.txt"), "w").write("team\n")

    _finish(pkg, slug, first["tasks"]["T1"], work)
    (repo / "docs").mkdir()
    (repo / "docs" / "new.txt").write_text("mine\n")  # the user's own, never added to git
    with pytest.raises(projects.ProjectError) as err:
        projects.merge(slug, pkg.common.read_team(slug))
    assert "没被 git 跟踪" in err.value.message and "docs/new.txt" in err.value.message
    assert (repo / "docs" / "new.txt").read_text() == "mine\n"
    (repo / "docs" / "new.txt").unlink()
    assert projects.merge(slug, pkg.common.read_team(slug))["merged"] is True


def test_a_team_that_changed_nothing_leaves_no_branch_and_gets_it_back_for_new_work(pkg, team_id, plan_dict, repo):
    import halowebui_teams.lead as lead
    import halowebui_teams.projects as projects

    _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    os.makedirs(os.path.join(ws, ".halo", "images"), exist_ok=True)
    open(os.path.join(ws, ".halo", "conclusion.md"), "w").write("结论")
    open(os.path.join(ws, ".halo", "images", "result-1.png"), "wb").write(b"\x89PNG")  # the conclusion's picture

    pkg.common.update_team(slug, lambda rec: rec.update({"state": "completed", "conclusion": {
        "status": "ready", "generated_at": 100, "acceptance": {"status": "checking"}}}))
    assert projects.clean_if_empty(slug, pkg.common.read_team(slug)) is False  # the lead is still checking
    _complete(pkg, slug)
    assert projects.clean_if_empty(slug, pkg.common.read_team(slug)) is True
    team = pkg.common.read_team(slug)
    assert team["project"]["auto_cleaned"] is True and not _git(repo, "branch", "--list", f"halo/{slug}")
    assert open(os.path.join(ws, ".halo", "conclusion.md")).read() == "结论"
    assert pkg.teams.snapshot(team_id)["team"]["project_cleaned"] is True
    assert projects.commit_finished(slug, team, [{"id": "t", "key": "T9"}]) == []  # no git add in a plain directory
    lead._check_open(team)  # the lead can still be asked for more

    (repo / "app.py").write_text("print('v1.1')\n")
    _git(repo, "commit", "-qam", "meanwhile on main")
    projects.revive(slug, team)
    team = pkg.common.read_team(slug)
    assert _git(ws, "rev-parse", "--abbrev-ref", "HEAD") == f"halo/{slug}"
    assert team["project"]["base_sha"] == _git(repo, "rev-parse", "main")  # from main as it is now
    assert team["project"]["auto_cleaned"] is False and not team["project"]["discarded_at"]
    assert os.path.isfile(os.path.join(ws, ".halo", "images", "result-1.png"))
    assert projects.changes(team)["available"] is True and projects.changes(team)["files"] == []


def test_a_team_with_changes_or_leftovers_keeps_its_branch(pkg, team_id, plan_dict, repo):
    import halowebui_teams.projects as projects

    _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    (repo / ".gitignore").write_text("out/\n")
    os.makedirs(os.path.join(ws, "out"), exist_ok=True)
    open(os.path.join(ws, "out", "report.md"), "w").write("被忽略但有用")
    _complete(pkg, slug)
    open(os.path.join(ws, ".gitignore"), "w").write("out/\n")
    _git(ws, "add", ".gitignore")
    _git(ws, "-c", "user.email=m@x", "-c", "user.name=m", "commit", "-qm", "ignore out")
    assert projects.clean_if_empty(slug, pkg.common.read_team(slug)) is False
    assert _git(repo, "branch", "--list", f"halo/{slug}")
    assert pkg.common.read_team(slug)["project"]["clean_checked"] == 100  # not looked at again for this version
    _git(ws, "reset", "-q", "--hard", "HEAD~1")
    _complete(pkg, slug, generated_at=200)
    assert projects.clean_if_empty(slug, pkg.common.read_team(slug)) is False  # out/ is untracked now: kept
    assert _git(repo, "branch", "--list", f"halo/{slug}")


def test_a_question_about_a_project_ends_without_a_branch_and_more_work_brings_it_back(pkg, team_id, plan_dict, repo,
                                                                                       monkeypatch, tmp_path):
    """The real case: 「X 在我的 myapp 里适合吗」 picks the project, the members only read it."""
    import json

    import halowebui_teams.illustrate as illustrate
    import halowebui_teams.lead as lead
    import halowebui_teams.projects as projects
    from test_lead import Lead

    fake = Lead()
    monkeypatch.setattr(pkg.plan, "call_model", fake)
    first = _create(pkg, team_id, plan_dict, repo)
    slug = pkg.common.board_slug(team_id)
    ws = pkg.common.read_team(slug)["workspace"]
    for key in ("T1", "T2", "T3"):
        _finish(pkg, slug, first["tasks"][key])
    assert pkg.teams.snapshot(team_id, "u1")["team"]["phase"] == "completed"  # conclusion + acceptance (sync)

    drawn = tmp_path / "drawn.png"
    drawn.write_bytes(b"\x89PNG\r\n\x1a\n" + b"9" * 32)
    monkeypatch.setattr(illustrate, "generate_image", lambda args: json.dumps({"success": True, "image": str(drawn)}))
    entry = illustrate.start(slug, None)
    assert entry["path"] == ".halo/images/result-1.png"  # the picture is the team's, not a change to the project
    assert projects.changes(pkg.common.read_team(slug))["files"] == []

    assert projects.clean_if_empty(slug, pkg.common.read_team(slug)) is True
    assert not _git(repo, "branch", "--list", "halo/*") and str(ws) not in _git(repo, "worktree", "list")
    assert os.path.isfile(os.path.join(ws, ".halo", "images", "result-1.png"))

    fake.change.append({"reply": "那就接进来", "add_tasks": [
        {"key": "N1", "title": "接入", "description": "在 app.py 里接入", "member": "reviewer", "depends_on": []}]})
    change = lead.request_change(team_id, "那就接进 myapp 吧", owner="u1", actor="Ace")
    assert lead.apply_change(team_id, change["id"], owner="u1")["reopened"] is True
    team = pkg.common.read_team(slug)
    assert team["state"] == "running" and team["project"]["auto_cleaned"] is False
    assert _git(ws, "rev-parse", "--abbrev-ref", "HEAD") == f"halo/{slug}"
    assert pkg.teams.snapshot(team_id, "u1")["team"]["project_cleaned"] is False
