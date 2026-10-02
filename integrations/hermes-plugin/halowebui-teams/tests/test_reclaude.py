import json
import os
import uuid

import pytest


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


PLAN = {
    "title": "混合团队",
    "members": [
        {"name": "backend-dev", "role": "后端开发", "executor": "reclaude"},
        {"name": "frontend-dev", "role": "前端开发", "executor": "hermes"},
        {"name": "reviewer", "role": "评审", "executor": "hermes"},
    ],
    "tasks": [
        {"key": "T1", "title": "后端", "description": "写 api.md", "member": "backend-dev", "depends_on": []},
        {"key": "T2", "title": "前端", "description": "写 page.md", "member": "frontend-dev", "depends_on": []},
        {"key": "T3", "title": "评审", "description": "评审", "member": "reviewer", "depends_on": ["T1", "T2"]},
    ],
}


class FakeRunner:
    def __init__(self, root):
        self.root = root
        self.calls = []

    def __call__(self, unit, argv):
        self.calls.append(argv)
        if argv[1] == "run":
            run_id = argv[argv.index("--run-id") + 1]
            parent = ""
        else:  # answer RUN_ID
            parent = argv[2]
            n = 1
            while os.path.exists(os.path.join(self.root, f"{parent}-a{n}")):
                n += 1
            run_id = f"{parent}-a{n}"
        self.write(run_id, status="running", runner_pid=os.getpid(), session_id="sess-1", parent_run=parent)
        return True, ""

    def write(self, run_id, **meta):
        d = os.path.join(self.root, run_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "meta.json")
        current = json.load(open(path)) if os.path.exists(path) else {"run_id": run_id}
        current.update(meta)
        json.dump(current, open(path, "w"))

    def result(self, run_id, text):
        json.dump({"result": text, "status": "success"}, open(os.path.join(self.root, run_id, "result.json"), "w"))

    def progress(self, run_id, lines):
        with open(os.path.join(self.root, run_id, "progress.log"), "a") as handle:
            handle.write("\n".join(lines) + "\n")


@pytest.fixture
def setup(pkg, monkeypatch):
    root = os.environ["HALO_TEAMS_RECLAUDE_RUNS_ROOT"]
    os.makedirs(root, exist_ok=True)
    fake = FakeRunner(root)
    monkeypatch.setitem(pkg.reclaude._launcher, "fn", fake)
    plan, errors = pkg.plan.validate_plan(json.loads(json.dumps(PLAN)))
    assert not errors
    team_id = str(uuid.uuid4())
    created = pkg.teams.create_team(team_id, plan, owner="u1", goal="混合团队")
    slug = pkg.common.board_slug(team_id)
    mine = [slug]
    # Earlier tests leave running reclaude tasks on their boards; each test sees only its own.
    monkeypatch.setattr(pkg.reclaude, "team_boards", lambda: list(mine))

    def tick():
        pkg.reclaude.tick_board(slug, pkg.common.read_team(slug))

    def task(key):
        with pkg.common.board_conn(slug) as conn:
            return _kb().get_task(conn, created["tasks"][key])

    def run_meta(key):
        with pkg.common.board_conn(slug) as conn:
            return pkg.reclaude._run_meta(conn, _kb().get_task(conn, created["tasks"][key]).current_run_id)

    def snap(key):
        return next(t for t in pkg.teams.snapshot(team_id, "u1")["tasks"] if t["key"] == key)

    return type("S", (), dict(fake=fake, team_id=team_id, slug=slug, mine=mine, tasks=created["tasks"], tick=staticmethod(tick),
                              task=staticmethod(task), run_meta=staticmethod(run_meta), snap=staticmethod(snap)))


def test_launch_follow_quota_wait_continuation_and_success(pkg, setup):
    s = setup
    s.tick()
    assert s.task("T1").status == "running" and s.task("T1").claim_lock == pkg.reclaude.CLAIMER
    assert s.task("T2").status == "ready"  # Hermes members are the dispatcher's, not the bridge's
    run_id = s.run_meta("T1")["runner_run_id"]
    argv = s.fake.calls[0]
    assert argv[1] == "run" and "--no-vault-archive" in argv
    task_file = argv[argv.index("--task-file") + 1]
    assert "写 api.md" in open(task_file).read()
    s.fake.progress(run_id, ["12:00:01 [tool#1] Bash: npm test", "12:00:02 [assistant] 正在测试"])
    s.tick()
    s.tick()
    events = pkg.teams.timeline(s.team_id, "u1")["events"]
    tools = [e for e in events if e["type"] == "tool"]
    assert [(t["data"]["name"], t["text"]) for t in tools] == [("Bash", "npm test")]
    # Quota: the runner parks itself and will resume as <id>-a1. Not a failure.
    s.fake.write(run_id, status="error", auto_resume="scheduled", auto_resume_pid=os.getpid(),
                 auto_resume_at="2026-10-02 13:00:00 +0800", auto_resume_run=f"{run_id}-a1", failure_kind="quota_exhausted")
    s.tick()
    s.tick()
    assert s.snap("T1")["sub_status"] == "quota_wait" and s.task("T1").status == "running"
    tl = pkg.teams.timeline(s.team_id, "u1")
    waits = [e for e in tl["events"] if e["type"] == "runner" and e["data"]["phase"] == "quota_wait"]
    assert len(waits) == 1 and waits[0]["sub_status"] == "quota_wait" and "不是失败" in waits[0]["text"]
    # The runner resumes by itself.
    s.fake.write(f"{run_id}-a1", status="running", runner_pid=os.getpid(), session_id="sess-1", parent_run=run_id)
    s.fake.write(run_id, auto_resume="started")
    s.tick()
    meta = s.run_meta("T1")
    assert meta["runner_run_id"] == f"{run_id}-a1"
    assert [r["kind"] for r in meta["runner_runs"]] == ["launch", "auto_continue"]
    assert s.snap("T1")["sub_status"] == "running"
    # A note written while it runs waits for the end of this run, then goes in with `answer`.
    out = pkg.teams.post_message(s.team_id, s.tasks["T1"], "顺便加上分页", author_name="Ace", owner="u1")
    assert "续跑同一会话时送达" in out["expect"]
    s.fake.write(f"{run_id}-a1", status="success")
    s.fake.result(f"{run_id}-a1", "接口写好了，见 api.md")
    s.tick()
    assert s.task("T1").status == "running"  # not done yet: the note goes first
    assert s.fake.calls[-1][1] == "answer" and s.fake.calls[-1][2] == f"{run_id}-a1"
    note = next(e for e in pkg.teams.timeline(s.team_id, "u1")["events"] if e["type"] == "message")
    assert note["data"]["delivered_via"] == "runner_answer"
    last = s.run_meta("T1")["runner_run_id"]
    assert last == f"{run_id}-a1-a1"
    s.fake.write(last, status="success")
    s.fake.result(last, "接口和分页都写好了，见 api.md")
    s.tick()
    t1 = s.task("T1")
    assert t1.status == "done" and "分页" in (t1.result or "")
    handoff = next(e for e in pkg.teams.timeline(s.team_id, "u1")["events"] if e["type"] == "handoff")
    assert "分页" in handoff["text"] and handoff["data"]["to"][0]["key"] == "T3"
    assert pkg.teams.timeline(s.team_id, "u1")["reconcile"] == []


def test_question_waits_for_the_user_and_answers_in_the_same_session(pkg, setup):
    s = setup
    s.tick()
    run_id = s.run_meta("T1")["runner_run_id"]
    s.fake.write(run_id, status="question")
    s.fake.result(run_id, "做到一半了。\nQUESTION: 用 8080 还是 9090 端口？")
    s.tick()
    assert s.snap("T1")["sub_status"] == "waiting_user"
    assert "8080" in s.snap("T1")["current_run"]["question"]
    s.tick()  # nothing new: no second question event, no answer
    assert sum(1 for c in s.fake.calls if c[1] == "answer") == 0
    pkg.teams.post_message(s.team_id, s.tasks["T1"], "用 9090", author_name="Ace", owner="u1")
    s.tick()
    answer = [c for c in s.fake.calls if c[1] == "answer"]
    assert len(answer) == 1 and answer[0][2] == run_id
    assert open(answer[0][answer[0].index("--task-file") + 1]).read() == "用 9090"
    assert s.snap("T1")["sub_status"] == "running"


def test_failure_blocks_then_retry_starts_a_new_linked_attempt(pkg, setup):
    s = setup
    s.tick()
    first = s.run_meta("T1")["runner_run_id"]
    s.fake.write(first, status="error")
    s.tick()
    assert s.task("T1").status == "blocked" and s.snap("T1")["sub_status"] == "failed"
    tl = pkg.teams.timeline(s.team_id, "u1")
    assert any(e.get("sub_status") == "failed" and e["key"] == "T1" for e in tl["events"])
    pkg.teams.retry(s.team_id, s.tasks["T1"], owner="u1")
    s.tick()
    meta = s.run_meta("T1")
    assert meta["runner_run_id"] != first and meta["parent_runner_run_id"] == first
    with pkg.common.board_conn(s.slug) as conn:
        assert len(_kb().list_runs(conn, s.tasks["T1"])) == 2


def test_interrupted_runner_is_resumed_once_then_fails(pkg, setup):
    s = setup
    s.tick()
    first = s.run_meta("T1")["runner_run_id"]
    s.fake.write(first, runner_pid=999999999)  # dead
    s.tick()
    meta = s.run_meta("T1")
    assert meta["runner_run_id"] == f"{first}-a1" and meta["interrupt_resumes"] == 1
    s.fake.write(f"{first}-a1", runner_pid=999999999)
    s.tick()
    assert s.task("T1").status == "blocked"


def test_stop_stops_the_runner_and_nothing_restarts(pkg, setup, monkeypatch):
    s = setup
    s.tick()
    run_id = s.run_meta("T1")["runner_run_id"]
    stopped = []

    async def fake_stop(meta, stopped_by=""):
        stopped.append(meta["run_id"])
        s.fake.write(meta["run_id"], status="stopped")
        return ""

    import gateway.runner_dispatch as rd

    monkeypatch.setattr(rd, "stop_run", fake_stop)
    pkg.teams.control(s.team_id, "stop", owner="u1")
    assert stopped == [run_id]
    assert s.snap("T1")["sub_status"] == "stopped"
    calls = len(s.fake.calls)
    s.tick()
    s.tick()
    assert len(s.fake.calls) == calls


def test_one_reclaude_member_runs_at_a_time(pkg, setup, monkeypatch):
    s = setup
    plan, _ = pkg.plan.validate_plan({
        "members": [{"name": "alpha", "role": "A", "executor": "reclaude"}, {"name": "beta", "role": "B", "executor": "reclaude"}],
        "tasks": [{"key": "T1", "title": "x", "member": "alpha"}, {"key": "T2", "title": "y", "member": "beta"}],
    })
    other = str(uuid.uuid4())
    pkg.teams.create_team(other, plan, owner="u1")
    s.mine.append(pkg.common.board_slug(other))
    s.tick()  # first team's T1 starts
    slug2 = pkg.common.board_slug(other)
    pkg.reclaude.tick_board(slug2, pkg.common.read_team(slug2))
    assert sum(1 for c in s.fake.calls if c[1] == "run") == 1
