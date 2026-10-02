import json
import os

import pytest


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


def _create(pkg, team_id, plan_dict, owner="u1"):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    result = pkg.teams.create_team(team_id, plan, owner=owner, chat_id="chat-1", goal="做一个小工具")
    return result


def _statuses(pkg, team_id):
    snap = pkg.teams.snapshot(team_id, "u1")
    return {t["key"]: (t["status"], t["sub_status"]) for t in snap["tasks"]}, snap


# --- plan ---------------------------------------------------------------------------------------

def test_plan_validation_normalizes_layers_and_parallelism(pkg, plan_dict):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert errors == []
    assert plan["layers"] == [["T1", "T2"], ["T3"]]
    assert plan["max_parallel"] == 2 and plan["widest_layer"] == 2
    assert [m["name"] for m in plan["members"]] == ["backend-dev", "frontend-dev", "reviewer"]
    assert plan["lead"]["name"] == "team-lead"


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["tasks"][0].update(depends_on=["T3"]), "循环依赖"),
    (lambda p: p["tasks"][2].update(member="ghost"), "不存在的成员"),
    (lambda p: p["tasks"][2].update(depends_on=["T9"]), "不存在的任务"),
    (lambda p: p["tasks"][1].update(key="T1"), "重复"),
    (lambda p: p["members"][0].update(executor="gpt"), "不支持"),
    (lambda p: p["members"][0].update(name="Team Lead!"), "不合法"),
    (lambda p: p["tasks"][0].update(depends_on=["T1"]), "依赖了它自己"),
])
def test_plan_validation_rejects_bad_plans(pkg, plan_dict, mutate, needle):
    mutate(plan_dict)
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert plan is None
    assert any(needle in e for e in errors), errors


def test_extract_json_tolerates_fences_and_chatter(pkg):
    raw = "好的，计划如下：\n```json\n{\"title\": \"x\", \"members\": []}\n```\n就这样"
    assert pkg.plan.extract_json(raw) == {"title": "x", "members": []}
    assert pkg.plan.extract_json("not json") is None


def test_propose_plan_retries_once_with_the_validation_errors(pkg, monkeypatch, plan_dict):
    replies = iter([json.dumps({"members": [], "tasks": []}), json.dumps(plan_dict)])
    seen = []

    def fake(messages, timeout=150):
        seen.append(messages)
        return next(replies), "", {"model": "gpt-chat", "source": "hermes_default"}

    monkeypatch.setattr(pkg.plan, "call_model", fake)
    out = pkg.plan.propose_plan("目标", "/tmp/ws")
    assert out["ok"] and out["attempts"] == 2
    assert "这个计划不能用" in seen[1][-1]["content"]


# --- create / dependencies / fold ------------------------------------------------------------

def test_create_team_is_idempotent_and_gates_dependencies(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    again = _create(pkg, team_id, plan_dict)
    assert first["created"] and not again["created"]
    assert again["tasks"] == first["tasks"]
    states, snap = _statuses(pkg, team_id)
    assert states == {"T1": ("ready", "queued"), "T2": ("ready", "queued"), "T3": ("todo", "waiting_deps")}
    assert snap["team"]["phase"] == "running"
    assert {m["name"]: m["status"] for m in snap["members"]} == {
        "backend-dev": "queued", "frontend-dev": "queued", "reviewer": "waiting_deps"}
    kb = _kb()
    slug = snap["team"]["board"]
    t1, t2, t3 = (first["tasks"][k] for k in ("T1", "T2", "T3"))
    with pkg.common.board_conn(slug) as conn:
        # The successor cannot be claimed while its parents are open.
        assert kb.claim_task(conn, t3, claimer="test") is None
        assert kb.claim_task(conn, t1, claimer="test") is not None
        assert kb.claim_task(conn, t2, claimer="test") is not None
        kb.complete_task(conn, t1, result="api.md 写好了", summary="api.md 写好了")
        kb.recompute_ready(conn)
        assert kb.get_task(conn, t3).status == "todo"   # T2 still running
        kb.complete_task(conn, t2, result="page.md 写好了", summary="page.md 写好了")
        kb.recompute_ready(conn)
        assert kb.get_task(conn, t3).status == "ready"
    states, snap = _statuses(pkg, team_id)
    assert states["T3"] == ("ready", "queued")
    assert snap["members"][0]["status"] == "done"


def test_timeline_fold_matches_live_rows_and_pages_without_duplicates(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    t1, t2, t3 = (first["tasks"][k] for k in ("T1", "T2", "T3"))
    with pkg.common.board_conn(slug) as conn:
        kb.claim_task(conn, t1, claimer="w1")
        kb.add_comment(conn, t1, "default", "我先写接口草稿")
        kb.claim_task(conn, t2, claimer="w2")
        kb.block_task(conn, t2, reason="缺少设计稿")
        kb.unblock_task(conn, t2)
        kb.claim_task(conn, t2, claimer="w2")
        kb.complete_task(conn, t2, result="page", summary="页面完成，见 page.md")
        kb.complete_task(conn, t1, result="api", summary="接口完成，见 api.md")
        kb.recompute_ready(conn)
        kb.claim_task(conn, t3, claimer="w3")
    full = pkg.teams.timeline(team_id, "u1", after=0, limit=2000)
    assert full["reconcile"] == []
    # Fold: the last status each task got in the timeline equals the live row.
    last = {}
    for ev in full["events"]:
        if ev.get("task_id") and ev.get("status"):
            last[ev["key"]] = ev["status"]
    assert last == {"T1": "done", "T2": "done", "T3": "running"}
    kinds = [(ev["type"], ev.get("key")) for ev in full["events"]]
    assert ("handoff", "T1") in kinds and ("handoff", "T2") in kinds
    handoff = next(ev for ev in full["events"] if ev["type"] == "handoff" and ev["key"] == "T1")
    assert handoff["data"]["to"][0]["member"] == "reviewer"
    msg = next(ev for ev in full["events"] if ev["type"] == "message")
    assert msg["who"] == "member" and msg["member"] == "backend-dev" and msg["text"] == "我先写接口草稿"
    blocked = next(ev for ev in full["events"] if ev["kind"] == "blocked")
    assert blocked["sub_status"] == "blocked" and "缺少设计稿" in blocked["text"]
    unblocked = next(ev for ev in full["events"] if ev["kind"] == "unblocked")
    assert (unblocked["status"], unblocked["sub_status"]) == ("ready", "queued")
    # Paging: small pages concatenate to the full list, no duplicates.
    seen, after = [], 0
    while True:
        page = pkg.teams.timeline(team_id, "u1", after=after, limit=3)
        seen += [ev["seq"] for ev in page["events"]]
        after = page["next_after"]
        if not page["has_more"]:
            break
    full_seqs = [ev["seq"] for ev in full["events"]]
    assert sorted(set(seen)) == sorted(set(full_seqs))
    # Re-reading from a cursor returns nothing new.
    assert pkg.teams.timeline(team_id, "u1", after=full["latest_seq"])["events"] == []


def test_reconcile_notice_when_history_disagrees(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (first["tasks"]["T1"],))
    out = pkg.teams.timeline(team_id, "u1")
    assert out["reconcile"] == [{"task_id": first["tasks"]["T1"], "key": "T1", "history": "ready", "live": "done"}]


def test_owner_mismatch_is_not_found(pkg, team_id, plan_dict):
    _create(pkg, team_id, plan_dict)
    with pytest.raises(pkg.teams.TeamError) as err:
        pkg.teams.snapshot(team_id, "someone-else")
    assert err.value.status == 404
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.timeline(team_id, "someone-else")
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.post_message(team_id, "t_x", "hi", author_name="x", owner="someone-else")


# --- messages / delivery -----------------------------------------------------------------------

def test_user_note_delivery_is_tracked_from_the_worker(pkg, team_id, plan_dict, monkeypatch):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    t1 = first["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        run = kb.claim_task(conn, t1, claimer="w1")
        run_id = conn.execute("SELECT current_run_id FROM tasks WHERE id = ?", (t1,)).fetchone()[0]
    out = pkg.teams.post_message(team_id, t1, "接口用 REST", author_name="Ace", owner="u1")
    assert out["delivery"] == "queued" and "工具调用结束后" in out["expect"]
    events = pkg.teams.timeline(team_id, "u1")["events"]
    note = next(ev for ev in events if ev["type"] == "message")
    assert note["who"] == "user" and note["author"] == "Ace" and note["data"]["delivery"] == "queued"
    # Inside the worker: the comment poll seeded, then moved past the note.
    from tools import kanban_tools

    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", t1)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(run_id))
    monkeypatch.setenv("HERMES_PROFILE", "default")
    pkg.hooks._state.update({"tool_events": 0, "truncated": False, "delivered_upto": None})
    monkeypatch.setitem(kanban_tools._comment_watermark, t1, out["comment_id"] - 1 if out["comment_id"] > 1 else 0)
    if kanban_tools._comment_watermark[t1] == 0:
        kanban_tools._comment_watermark[t1] = -1
    pkg.hooks.on_post_tool_call(tool_name="terminal", args={"command": "ls"}, duration_ms=5, status="ok")
    kanban_tools._comment_watermark[t1] = out["comment_id"]
    pkg.hooks.on_post_tool_call(tool_name="terminal", args={"command": "cat api.md"}, duration_ms=5, status="ok")
    events = pkg.teams.timeline(team_id, "u1")["events"]
    note = next(ev for ev in events if ev["type"] == "message")
    assert note["data"]["delivered_via"] == "steer" and note["data"]["delivered_seq"] > note["seq"]
    tools = [ev for ev in events if ev["type"] == "tool"]
    assert [t["text"] for t in tools] == ["ls", "cat api.md"]


def test_note_before_attempt_is_delivered_with_the_attempt(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    t3 = first["tasks"]["T3"]
    out = pkg.teams.post_message(team_id, t3, "评审时重点看错误处理", author_name="Ace", owner="u1")
    assert "下一次开始执行" in out["expect"]
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2"):
            kb.claim_task(conn, first["tasks"][key], claimer="w")
            kb.complete_task(conn, first["tasks"][key], result="ok", summary="ok")
        kb.recompute_ready(conn)
        kb.claim_task(conn, t3, claimer="w3")
    note = next(ev for ev in pkg.teams.timeline(team_id, "u1")["events"] if ev["type"] == "message")
    assert note["data"]["delivered_via"] == "attempt_context"


def test_tool_preview_is_redacted(pkg, team_id, plan_dict, monkeypatch):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", first["tasks"]["T1"])
    pkg.hooks._state.update({"tool_events": 0, "truncated": False, "delivered_upto": None})
    secret = "sk-" + "a" * 40
    pkg.hooks.on_post_tool_call(tool_name="terminal", args={"command": f"curl -H 'Authorization: Bearer {secret}' x"})
    tool = next(ev for ev in pkg.teams.timeline(team_id, "u1")["events"] if ev["type"] == "tool")
    assert secret not in tool["text"]


def test_hooks_do_nothing_outside_team_boards(pkg, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "default")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_x")
    pkg.hooks.on_post_tool_call(tool_name="terminal", args={"command": "ls"})  # no error, no board
    monkeypatch.delenv("HERMES_KANBAN_BOARD")
    pkg.hooks.on_subagent_start(child_subagent_id="sa-0-x", child_goal="g")


def test_subagent_events_are_recorded(pkg, team_id, plan_dict, monkeypatch):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", first["tasks"]["T2"])
    pkg.hooks.on_subagent_start(child_subagent_id="sa-0-abc", child_session_id="s1", child_role="leaf", child_goal="查资料")
    pkg.hooks.on_post_tool_call(tool_name="web_search", args={"query": "svelte"}, task_id="sa-0-abc")
    pkg.hooks.on_subagent_stop(child_session_id="s1", child_status="completed", child_summary="找到了", tool_call_history=[{}],
                               duration_ms=1200)
    events = pkg.teams.timeline(team_id, "u1")["events"]
    subs = [ev for ev in events if ev["type"] == "subagent"]
    assert [s["data"]["phase"] for s in subs] == ["start", "stop"]
    assert subs[1]["data"]["id"] == "sa-0-abc" and subs[1]["data"]["tools"] == 1
    tool = next(ev for ev in events if ev["type"] == "tool")
    assert tool["data"]["subagent"] == "sa-0-abc"


# --- control / retry ----------------------------------------------------------------------------

def test_pause_resume_stop(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    assert pkg.teams.control(team_id, "pause", owner="u1")["state"] == "paused"
    assert kb.read_board_metadata(slug)["archived"] is True
    assert pkg.teams.snapshot(team_id, "u1")["team"]["phase"] == "paused"
    assert pkg.teams.control(team_id, "resume", owner="u1")["state"] == "running"
    assert kb.read_board_metadata(slug)["archived"] is False
    with pkg.common.board_conn(slug) as conn:
        kb.claim_task(conn, first["tasks"]["T1"], claimer="w1")
    out = pkg.teams.control(team_id, "stop", owner="u1", actor="Ace")
    assert set(out["stopped_tasks"]) == {first["tasks"]["T1"], first["tasks"]["T2"]}
    states, snap = _statuses(pkg, team_id)
    assert states["T1"] == ("blocked", "stopped") and states["T2"] == ("blocked", "stopped")
    assert snap["team"]["phase"] == "stopped"
    by_key = {t["key"]: t for t in snap["tasks"]}
    assert by_key["T1"]["attempts"] == 1 and by_key["T2"]["attempts"] == 0  # stop adds no attempt
    assert by_key["T1"]["block_reason"] == "用户停止了协作任务"
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.retry(team_id, first["tasks"]["T1"], owner="u1")
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.control(team_id, "resume", owner="u1")
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.post_message(team_id, first["tasks"]["T3"], "x", author_name="a", owner="u1")
    tl = pkg.teams.timeline(team_id, "u1")
    assert tl["reconcile"] == []
    assert any(ev["type"] == "team" and ev["data"]["action"] == "stopped" for ev in tl["events"])
    stopped = [ev for ev in tl["events"] if ev.get("sub_status") == "stopped"]
    assert {ev["key"] for ev in stopped} == {"T1", "T2"}


def test_retry_failed_task_keeps_completed_work(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    t1, t2 = first["tasks"]["T1"], first["tasks"]["T2"]
    with pkg.common.board_conn(slug) as conn:
        kb.claim_task(conn, t1, claimer="w")
        kb.complete_task(conn, t1, result="ok", summary="ok")
        kb.claim_task(conn, t2, claimer="w")
        kb.block_task(conn, t2, reason="编译失败")
    with pytest.raises(pkg.teams.TeamError):
        pkg.teams.retry(team_id, t1, owner="u1")  # done: nothing to retry
    assert pkg.teams.retry(team_id, t2, owner="u1")["retried"]
    states, _ = _statuses(pkg, team_id)
    assert states["T1"] == ("done", "done") and states["T2"][0] == "ready"
    with pkg.common.board_conn(slug) as conn:
        assert len(kb.list_runs(conn, t1)) == 1


def test_completion_is_recorded_once(pkg, team_id, plan_dict):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2"):
            kb.claim_task(conn, first["tasks"][key], claimer="w")
            kb.complete_task(conn, first["tasks"][key], result="ok", summary="ok")
        kb.recompute_ready(conn)
        kb.claim_task(conn, first["tasks"]["T3"], claimer="w")
        kb.complete_task(conn, first["tasks"]["T3"], result="ok", summary="评审通过")
    for _ in range(3):
        snap = pkg.teams.snapshot(team_id, "u1")
    assert snap["team"]["phase"] == "completed" and snap["team"]["lead"]["status"] == "done"
    events = pkg.teams.timeline(team_id, "u1")["events"]
    assert sum(1 for ev in events if ev["type"] == "team" and ev["data"]["action"] == "completed") == 1


def test_note_read_through_kanban_show_counts_as_delivered(pkg, team_id, plan_dict, monkeypatch):
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    t1 = first["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        kb.claim_task(conn, t1, claimer="w1")
    out = pkg.teams.post_message(team_id, t1, "最后一行写上已收到", author_name="Ace", owner="u1")
    from tools import kanban_tools

    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", t1)
    pkg.hooks._state.update({"tool_events": 0, "truncated": False, "delivered_upto": None, "read_upto": 0,
                             "reported": set()})
    kanban_tools._comment_watermark[t1] = out["comment_id"]  # first poll seeded past it: never steered
    pkg.hooks.on_post_tool_call(tool_name="kanban_show", args={"task_id": t1})
    pkg.hooks.on_post_tool_call(tool_name="kanban_show", args={"task_id": t1})  # no second delivery
    events = pkg.teams.timeline(team_id, "u1")["events"]
    note = next(ev for ev in events if ev["type"] == "message")
    assert note["data"]["delivered_via"] == "task_read"
    assert sum(1 for ev in events if ev["type"] == "delivery") == 1


def test_note_steered_after_an_empty_first_poll_is_delivered(pkg, team_id, plan_dict, monkeypatch):
    """E2E-9: the worker's first comment poll found no comments (watermark 0); the note came later
    and was steered in. 0 must count as a seen watermark."""
    first = _create(pkg, team_id, plan_dict)
    kb = _kb()
    slug = pkg.common.board_slug(team_id)
    t1 = first["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        kb.claim_task(conn, t1, claimer="w1")
    from tools import kanban_tools

    monkeypatch.setenv("HERMES_KANBAN_BOARD", slug)
    monkeypatch.setenv("HERMES_KANBAN_TASK", t1)
    monkeypatch.setenv("HERMES_PROFILE", "default")
    pkg.hooks._state.update({"tool_events": 0, "truncated": False, "delivered_upto": None, "read_upto": 0,
                             "reported": set()})
    kanban_tools._comment_watermark[t1] = 0
    pkg.hooks.on_post_tool_call(tool_name="terminal", args={"command": "sleep 50"})
    out = pkg.teams.post_message(team_id, t1, "加第二行：收到", author_name="Ace", owner="u1")
    kanban_tools._comment_watermark[t1] = out["comment_id"]
    pkg.hooks.on_post_tool_call(tool_name="write_file", args={"path": "a.md"})
    note = next(ev for ev in pkg.teams.timeline(team_id, "u1")["events"] if ev["type"] == "message")
    assert note["data"]["delivered_via"] == "steer"
