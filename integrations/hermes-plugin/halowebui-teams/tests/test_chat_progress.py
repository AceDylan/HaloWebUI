"""Telegram and QQ progress through chat commands, the bridge tick, and their transport wrappers."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from halowebui_teams import chat_progress as chat, link, notify, progress, tg
from test_remote import QQ_USER, _dispatch, _event as qq_event, remote
from test_tg import OWNER, TG_USER, _buttons, _create, _event as tg_event, _run, linked

CI_URL = "https://github.com/example/halo/actions/runs/123"
TEAM_ID = "96f9a40a-efcc-46e9-a412-84ece5d0d1fa"


def _task(num, status, **fields):
    return {"id": f"t_{num}", "key": f"T{num}", "title": f"任务 {num}", "member": "开发者", "executor": "codex",
            "status": status, "sub_status": status, **fields}


def _snapshot(team_id=TEAM_ID, *, stage="running", phase="running", tasks=(), **fields):
    return {"team": {"team_id": team_id, "board": "halo-demo", "title": "工具 < 检查 & 验证", "phase": phase,
                     "stage": {"key": stage, "eta": {"seconds": 350, "high": 550}}, **fields}, "tasks": list(tasks)}


def _deploy(step, status="running"):
    return {"status": status, "step": step, "ci_url": CI_URL if step == "ci" or status == "succeeded" else "",
            "steps": [{"key": "push", "label": "推送 origin", "status": "done" if step == "ci" else "running"},
                      {"key": "ci", "label": "等待 CI 构建", "status": "running" if step == "ci" else "pending"}]}


@pytest.mark.parametrize(("args", "selector", "work_query"), [
    ("进度", "", True), (" STATUS ", "", True), ("进度 2", "2", True), ("详情：96F9A40A", "96f9a40a", True),
    ("进度分析报告", None, False), ("进度 分析报告", None, True), ("progress report", None, True),
    ("status 2 3", None, True),
])
def test_parse_queries_and_leave_goals_alone(args, selector, work_query):
    assert chat.parse_progress_query(args) == selector
    assert chat.is_work_progress_query(args) is work_query


def test_snapshot_cards_show_tasks_timing_waits_and_deploy(linked, monkeypatch):
    monkeypatch.setattr(chat, "now", lambda: 1000)
    tasks = [_task(1, "done", started_at=660, completed_at=790),
             _task(2, "running", started_at=880, trail=[{"from": "agy"}]),
             _task(3, "todo", parents=["t_1", "t_2"]),
             {**_task(4, "running", current_run={"resume_at": 1300}), "sub_status": "quota_wait"}]
    tasks[2]["sub_status"] = "waiting_deps"
    snap = _snapshot(tasks=tasks, approved_at=640)
    snap["team"]["stage"]["running"] = [{"key": "T2", "text": "改文件 · stage.py"}]
    view = chat.view_from_snapshot(snap)
    text, buttons = chat.render_telegram(view)
    assert "<b>📊 工具 &lt; 检查 &amp; 验证 · 成员执行中 (1/4)</b>" in text
    assert "计划 ✓ → 批准 ✓ → 执行 ● → 结论 ○ → 验收 ○" in text
    assert "已用 6 分钟 · 预计还需约 6–9 分钟" in text
    for expected in ("T1 任务 1", "2 分 10 秒", "改文件 · stage.py", "已跑 2 分钟",
                     "已兜底切换", "等 T2", "等待额度", "自动继续"):
        assert expected in text
    assert buttons[0] == [("🔄 刷新进度", f"cb:pr:{TEAM_ID}"),
                          ("🌐 打开工作台", f"url:https://halo.example/teams/{TEAM_ID}")]
    deploy_view = chat.view_from_snapshot(_snapshot(phase="completed", stage="deploying", deploy=_deploy("ci")))
    qq = chat.render_qq(deploy_view)
    assert "发布 ●" in qq and "✓ 推送 origin → ● 等待 CI 构建" in qq
    assert f"🔗 CI：{CI_URL}" in qq and "发 /team 进度 随时刷新" in qq
    assert "<b>" not in qq and "**" not in qq


def test_planning_summary_uses_live_model_and_approval_estimate(team_id, monkeypatch):
    monkeypatch.setattr(chat, "now", lambda: 1000)
    planning = {"progress": {"model": "offiagy", "text": "正在拆分任务", "started_at": 980},
                "typical": {"median": 60, "p75": 120}}
    monkeypatch.setattr(progress, "planning", lambda id: planning if id == team_id else {})
    summary = {"id": team_id, "title": "测试规划", "status": "planning"}
    view = chat.view_from_summary(summary)
    assert view["eta_seconds"] == 40 and view["eta_high"] == 100
    assert "offiagy · 正在拆分任务" in chat.render_qq(view)
    approval = chat.view_from_summary({**summary, "status": "plan_ready", "plan": {
        "estimate": {"seconds": 180, "high": 300}, "tasks": [{"key": "T1", "title": "做计划", "member": "dev"}],
        "members": [{"name": "dev", "executor": "agy"}]}})
    text = chat.render_qq(approval)
    assert "等你批准" in text and "批准后约 3–5 分钟出结果" in text and "T1 做计划 · dev · agy" in text


def test_cards_keep_running_task_and_fit_one_telegram_message(linked):
    tasks = [_task(num, "done") | {"title": "<b>finished</b>" + "&😀" * 80} for num in range(40)]
    tasks.append(_task(41, "running") | {"title": "最后一个仍在运行"})
    view = chat.view_from_snapshot(_snapshot(tasks=tasks, deploy=_deploy("ci")))
    text, _ = chat.render_telegram(view)
    assert len(text.encode("utf-16-le")) // 2 <= chat.CARD_MAX_CHARS
    assert tg.split_html(text) == [text]
    assert text.count("<b>") == text.count("</b>") == 1
    assert "T41 最后一个仍在运行" in text and "完整列表见工作台" in text
    assert "等待 CI 构建" in text and f"🔗 CI：{CI_URL}" in chat.render_qq(view)


def test_query_prefers_work_and_supports_number_local_id_and_owner(pkg, plan_dict, monkeypatch):
    normal = "aabb0001-0000-4000-8000-000000000001"
    work = "aabb0002-0000-4000-8000-000000000002"
    local = "aabb0003-0000-4000-8000-000000000003"
    foreign = "aabb0004-0000-4000-8000-000000000004"
    for id in (normal, work, local, foreign):
        _create(pkg, id, plan_dict)
    pkg.common.update_team(pkg.common.board_slug(work), lambda rec: rec.update(workflow="work"))
    pkg.common.update_team(pkg.common.board_slug(foreign), lambda rec: rec.update(owner="other"))
    recent = [{"id": id, "status": "running"} for id in (normal, work)]
    monkeypatch.setattr(link, "recent", lambda *_: recent)
    monkeypatch.setattr(chat, "team_boards", lambda: [pkg.common.board_slug(id) for id in (normal, work, local, foreign)])
    assert [v["team_id"] for v in chat.resolve_query_views(OWNER, workflow_first="work")[0]][0] == work
    assert chat.resolve_query_views(OWNER, "2")[0][0]["team_id"] == work
    assert chat.resolve_query_views(OWNER, "aabb0003")[0][0]["team_id"] == local
    assert chat.resolve_query_views(OWNER, "aabb")[0] == []
    assert chat.resolve_query_views(OWNER, "aabb0004")[0] == []
    assert chat.resolve_query_views(OWNER, "8")[0] == []


def test_telegram_commands_and_list_expose_progress_buttons(linked, monkeypatch):
    recent = [{"id": TEAM_ID, "title": "等待 CI", "status": "running", "phase": "completed",
               "stage": {"key": "deploying", "now": "CI 在构建"}},
              {"id": "aaaa0000", "title": "暂停", "status": "running", "phase": "paused",
               "stage": {"key": "paused", "now": "暂时停止派发"}}]
    monkeypatch.setattr(link, "recent", lambda *_: recent)
    monkeypatch.setattr(chat, "team_boards", lambda: [])
    config = json.loads(linked.cfg.read_text())
    config["telegram"]["progress_updates"] = False
    linked.cfg.write_text(json.dumps(config))
    monkeypatch.setattr(link, "create", lambda *args: pytest.fail("a query must not create a team"))
    for command in ("/team 进度", "/team 状态", "/team progress", "/team status", "/team 详情 2",
                    "/work 进度", "/work 状态"):
        before = len(linked.sent)
        _run(lambda: tg._dispatch(tg_event(command)))
        assert linked.sent[before]["text"].startswith("<b>📊 ")
    assert any("已暂停派发" in m["text"] for m in linked.sent)
    _run(lambda: tg._dispatch(tg_event("/work 进度 无效编号")))
    assert "/work 进度 [编号或 ID]" in linked.sent[-1]["text"]
    _run(lambda: tg._dispatch(tg_event("/team")))
    msg = linked.sent[-1]
    assert "1." in msg["text"] and "CI 在构建" in msg["text"] and "暂时停止派发" in msg["text"]
    assert f"cb:pg:{TEAM_ID}" in _buttons(msg)


def test_telegram_transport_sends_quietly_and_reports_edit_outcomes(monkeypatch):
    calls = []
    failure = None

    async def send_message(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(message_id=123)

    async def edit_message_text(**kwargs):
        calls.append(kwargs)
        if failure:
            raise RuntimeError(failure)

    bot = SimpleNamespace(send_message=send_message, edit_message_text=edit_message_text)
    monkeypatch.setitem(tg._state, "app", SimpleNamespace(bot=bot))
    assert asyncio.run(tg.asend(TG_USER, "<b>进度</b>", silent=True)) == 123
    assert calls[-1]["disable_notification"] is True
    for failure, outcome in ((None, "ok"), ("Message is not modified", "not_modified"),
                             ("Message to edit not found", "gone"), ("Message can't be edited", "gone"),
                             ("Timed out", "failed")):
        assert asyncio.run(tg.aedit(TG_USER, 123, "进度")) == outcome
        assert calls[-1]["message_id"] == 123 and calls[-1]["parse_mode"] == "HTML"


def _tg_board(pkg, plan_dict, team_id, monkeypatch, *, auto_deploy=False):
    _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    clock = [pkg.common.now()]
    monkeypatch.setattr(notify, "now", lambda: clock[0])
    monkeypatch.setattr(chat, "now", lambda: clock[0])
    snap = _snapshot(team_id, approved_at=clock[0], tasks=[_task(1, "running")])
    snap["team"]["board"] = slug
    monkeypatch.setattr(pkg.teams, "snapshot", lambda id, owner=None: snap)
    monkeypatch.setattr(notify, "done_message", lambda *_: ("✅ 结论", []))
    if auto_deploy:
        pkg.common.update_team(slug, lambda rec: rec.update(auto_deploy=True, project={"branch": "team-test"}))

    def tick():
        notify.tick_board(slug, pkg.common.read_team(slug))

    return slug, clock, snap, tick


def test_telegram_auto_card_delay_activity_milestones_and_finalization(pkg, plan_dict, team_id, linked, monkeypatch):
    slug, clock, snap, tick = _tg_board(pkg, plan_dict, team_id, monkeypatch, auto_deploy=True)
    edits = []
    monkeypatch.setattr(tg, "edit", lambda *args: edits.append(args) or "ok")
    tick()
    clock[0] += 19
    tick()
    assert linked.sent == []
    seen = True
    monkeypatch.setattr(notify, "watching", lambda *_: seen)
    clock[0] += 1
    tick()
    assert linked.sent == []
    seen = False
    tick()
    tick()
    pg = pkg.common.read_team(slug)["tg_progress"]
    assert len(linked.sent) == 1 and linked.sent[0]["silent"] is True and pg["message_id"] == 1001
    assert tg.lookup(TG_USER, 1001)["kind"] == "progress"

    stage = snap["team"]["stage"]
    stage["running"] = [{"key": "T1", "text": "改文件 · 新进度"}]
    clock[0] += 29
    tick()
    assert edits == []
    clock[0] += 1
    tick()
    assert "改文件 · 新进度" in edits[-1][2]
    snap["tasks"][:] = [_task(1, "done"), _task(2, "running")]
    clock[0] += 9
    tick()
    assert len(edits) == 1
    clock[0] += 1
    seen = True
    tick()
    assert len(edits) == 1
    seen = False
    tick()
    assert len(edits) == 2 and "T2" in edits[-1][2]

    snap["team"]["phase"] = "completed"
    for phase, label in (("concluding", "整理完整结果"), ("checking", "对照目标验收"), ("illustrating", "为结果配图")):
        stage["key"] = phase
        clock[0] += 10
        tick()
        assert label in edits[-1][2]
    stage["key"] = "done"
    pkg.common.update_team(slug, lambda rec: rec.update(state="completed", completed_at=clock[0],
                           conclusion={"status": "ready", "generated_at": clock[0]}))
    clock[0] += 10
    tick()
    assert "等待自动发布" in edits[-1][2] and not pkg.common.read_team(slug)["tg_progress"]["finalized"]
    assert len([m for m in linked.sent if m["text"] == "✅ 结论"]) == 1

    stage["key"] = "deploying"
    for step in ("push", "ci"):
        snap["team"]["deploy"] = _deploy(step)
        clock[0] += 10
        tick()
        assert edits[-1][1] == 1001 and "推送与部署中" in edits[-1][2]
    assert any(spec == "url:" + CI_URL for row in edits[-1][3] for _, spec in row)
    stage["key"] = "done"
    snap["team"]["deploy"] = _deploy("done", "succeeded")
    tick()
    assert "发布完成" in edits[-1][2] and all("cb:pr:" not in spec for row in edits[-1][3] for _, spec in row)
    assert pkg.common.read_team(slug)["tg_progress"]["finalized"]
    count = len(edits)
    clock[0] += 60
    tick()
    assert len(edits) == count and len([m for m in linked.sent if m.get("silent")]) == 1


def test_telegram_deleted_card_is_recreated_then_stopped(pkg, plan_dict, team_id, linked, monkeypatch):
    slug, clock, snap, tick = _tg_board(pkg, plan_dict, team_id, monkeypatch)
    monkeypatch.setattr(tg, "edit", lambda *_: "gone")
    tick()
    clock[0] += 20
    tick()
    snap["team"]["stage"]["key"] = "paused"
    clock[0] += 10
    tick()
    assert pkg.common.read_team(slug)["tg_progress"]["message_id"] is None
    tick()
    assert [m["silent"] for m in linked.sent] == [True, True]
    assert pkg.common.read_team(slug)["tg_progress"]["message_id"] == 1002
    snap["team"]["stage"]["key"] = "stopped"
    snap["team"]["phase"] = "stopped"
    pkg.common.update_team(slug, lambda rec: rec.update(state="stopped"))
    edits = []
    monkeypatch.setattr(tg, "edit", lambda *args: edits.append(args) or "ok")
    tick()
    assert "已停止" in edits[-1][2]
    assert all("cb:pr:" not in spec for row in edits[-1][3] for _, spec in row)
    assert pkg.common.read_team(slug)["tg_progress"]["finalized"]
    tick()
    assert len(edits) == 1


def test_telegram_failing_card_edits_back_off_then_let_the_card_go(pkg, plan_dict, team_id, linked, monkeypatch):
    slug, clock, snap, tick = _tg_board(pkg, plan_dict, team_id, monkeypatch)
    edits = []
    monkeypatch.setattr(tg, "edit", lambda *args: edits.append(args) or "failed")
    tick()
    clock[0] += 20
    tick()
    assert len(linked.sent) == 1
    first = pkg.common.read_team(slug)["tg_progress"]["milestone_sig"]
    snap["tasks"][:] = [_task(1, "done"), _task(2, "running")]
    clock[0] += 10
    tick()
    pg = pkg.common.read_team(slug)["tg_progress"]
    assert len(edits) == 1 and pg["failures"] == 1 and pg["milestone_sig"] == first and pg["message_id"] == 1001
    tick()  # the next bridge tick does not hammer Telegram
    clock[0] += 9
    tick()
    assert len(edits) == 1
    for tries in range(2, notify.PROGRESS_EDIT_TRIES + 1):
        clock[0] += 10
        tick()
        assert len(edits) == tries
    pg = pkg.common.read_team(slug)["tg_progress"]
    assert pg["message_id"] is None and "failures" not in pg
    monkeypatch.setattr(tg, "edit", lambda *args: edits.append(args) or "ok")
    tick()  # a fresh card while the team still works
    assert [m["silent"] for m in linked.sent] == [True, True]
    pg = pkg.common.read_team(slug)["tg_progress"]
    assert pg["message_id"] == 1002 and pg["milestone_sig"] != first


def test_telegram_buttons_open_new_card_refresh_in_place_and_respect_target(pkg, plan_dict, team_id, linked, monkeypatch):
    slug, clock, snap, tick = _tg_board(pkg, plan_dict, team_id, monkeypatch)
    edits, answers = [], []
    result = "not_modified"

    async def edit(*args):
        edits.append(args)
        return result

    monkeypatch.setattr(tg, "aedit", edit)
    monkeypatch.setattr(link, "telegram_progress_enabled", lambda: False)
    tick()
    clock[0] += 20
    tick()
    assert not linked.sent

    async def answer(text, **_):
        answers.append(text)

    def call(action, id, chat_id=TG_USER):
        query = SimpleNamespace(data=f"ht:{action}:{team_id}", from_user=SimpleNamespace(id=int(TG_USER)),
                                message=SimpleNamespace(chat_id=chat_id, message_id=id), answer=answer)
        asyncio.run(tg._handle_callback(query))

    call("pg", 9)
    assert len(linked.sent) == 1 and not edits and answers[-1] == "已打开进度"
    assert pkg.common.read_team(slug)["tg_progress"]["message_id"] == 2001
    call("pg", 10, "-10099")
    assert len(linked.sent) == 2 and pkg.common.read_team(slug)["tg_progress"]["message_id"] == 2001
    call("pr", 2001)
    assert edits[-1][1] == 2001 and answers[-1] == "已是最新进度"
    snap["team"].update(phase="completed")
    snap["team"]["stage"]["key"] = "done"
    result = "ok"
    call("pr", 2001)
    assert len(linked.sent) == 2 and answers[-1] == "已刷新进度"
    assert all("cb:pr:" not in spec for row in edits[-1][3] for _, spec in row)
    assert pkg.common.read_team(slug)["tg_progress"]["finalized"]


def _qq_job(remote, team_id=TEAM_ID):
    job = {"id": team_id, "owner": OWNER, "kind": "team", "platform": "qqbot", "chat_id": QQ_USER,
           "at": remote.remote.time.time(), "reply_to": "old", "approved": True}
    remote.remote.put_job(job)
    return f"team:{team_id}"


def test_qq_queries_are_passive_and_refresh_only_team_jobs_in_chat(remote, monkeypatch):
    key = _qq_job(remote)
    remote.remote.put_job({"kind": "team", "id": "other", "platform": "qqbot", "chat_id": "elsewhere", "reply_to": "old"})
    remote.remote.put_job({"kind": "answer", "id": "answer", "platform": "qqbot", "chat_id": QQ_USER, "reply_to": "old"})
    monkeypatch.setattr(link, "recent", lambda *_: [{"id": TEAM_ID, "title": "**工具**", "status": "running",
                                                     "phase": "running", "stage": {"key": "running"}}])
    monkeypatch.setattr(chat, "team_boards", lambda: [])
    monkeypatch.setattr(link, "create", lambda *args: pytest.fail("a query must not create a team"))
    monkeypatch.setattr(link, "qq_progress_enabled", lambda: False)
    for i, command in enumerate(("/team 进度", "/team 状态", "/work 进度", "/work 状态", "协作进度！",
                                 "团队进度", "工作流进度", "看协作进度"), 100):
        assert _dispatch(remote.remote, qq_event("qqbot", QQ_USER, command, str(i)))["action"] == "skip"
        assert remote.sent[-1]["reply_to"] == str(i) and "工具 · 成员执行中" in remote.sent[-1]["text"]
        assert "<b>" not in remote.sent[-1]["text"] and "**" not in remote.sent[-1]["text"]
        assert remote.remote.jobs()[key]["reply_to"] == str(i)
    assert remote.remote.jobs()["team:other"]["reply_to"] == "old"
    assert remote.remote.jobs()["answer:answer"]["reply_to"] == "old"
    _dispatch(remote.remote, qq_event("qqbot", QQ_USER, "/work 进度 无效编号"))
    assert "/work 进度 [编号或 ID]" in remote.sent[-1]["text"]
    for text in ("进度", "状态", "帮我看看协作进度", "你好"):
        assert _dispatch(remote.remote, qq_event("qqbot", QQ_USER, text)) is None


def test_qq_milestones_merge_cool_down_and_cap(remote, pkg, monkeypatch):
    key = _qq_job(remote)
    clock = [remote.remote.time.time()]
    monkeypatch.setattr(remote.remote.time, "time", lambda: clock[0])
    snap = _snapshot(tasks=[_task(1, "running"), _task(2, "ready")])
    monkeypatch.setattr(pkg.teams, "snapshot", lambda id, owner: snap)
    monkeypatch.setattr(link, "get", lambda *_: pytest.fail("approved QQ teams use the live board"))
    remote.remote.tick()
    assert not remote.sent

    snap["tasks"][:] = [_task(1, "done", started_at=100, completed_at=230), _task(2, "running")]
    remote.remote.tick()
    assert len(remote.sent) == 1 and remote.sent[0]["reply_to"] == "old"
    assert "T1 任务 1 已完成（2 分 10 秒）" in remote.sent[0]["text"] and "开始执行：T2" in remote.sent[0]["text"]
    snap["tasks"][1].update(executor="agy", trail=[{"from": "codex"}])
    clock[0] += 19
    remote.remote.tick()
    assert len(remote.sent) == 1
    clock[0] += 1
    remote.remote.tick()
    assert len(remote.sent) == 2 and "已切换到 agy" in remote.sent[-1]["text"]
    snap["tasks"][1].update(sub_status="quota_wait", current_run={"resume_at": int(clock[0] + 600)})
    clock[0] += 20
    remote.remote.tick()
    assert "等待 agy 额度" in remote.sent[-1]["text"] and "自动继续" in remote.sent[-1]["text"]
    for i in range(10):
        clock[0] += 20
        snap["tasks"][1].update(sub_status="running", trail=[{}] * (i + 2))
        remote.remote.tick()
    assert len(remote.sent) == 10 and remote.remote.jobs()[key]["progress_count"] == 10


def test_qq_failed_milestone_is_retried_after_cooldown_and_switch_disables_push(remote, pkg, monkeypatch):
    key = _qq_job(remote)
    clock = [remote.remote.time.time()]
    monkeypatch.setattr(remote.remote.time, "time", lambda: clock[0])
    snap = _snapshot(tasks=[_task(1, "done"), _task(2, "running")])
    monkeypatch.setattr(pkg.teams, "snapshot", lambda *_: snap)
    enabled = False
    monkeypatch.setattr(link, "qq_progress_enabled", lambda: enabled)
    attempts = []
    monkeypatch.setattr(remote.remote, "send", lambda *_: attempts.append(clock[0]) or len(attempts) > 1)
    remote.remote.tick()
    assert not attempts and "progress_state" not in remote.remote.jobs()[key]
    enabled = True
    remote.remote.tick()
    assert len(attempts) == 1 and "progress_count" not in remote.remote.jobs()[key]
    clock[0] += 19
    remote.remote.tick()
    assert len(attempts) == 1
    clock[0] += 1
    remote.remote.tick()
    assert len(attempts) == 2 and remote.remote.jobs()[key]["progress_count"] == 1


def test_qq_live_completion_and_auto_deploy_outlive_the_conclusion(remote, pkg, monkeypatch):
    key = _qq_job(remote)
    clock = [remote.remote.time.time()]
    monkeypatch.setattr(remote.remote.time, "time", lambda: clock[0])
    snap = _snapshot(stage="concluding", phase="completed", tasks=[_task(1, "done")])
    board = {"team_id": TEAM_ID, "title": "任务", "auto_deploy": True, "project": {"branch": "team"},
             "conclusion": {"status": "generating"}, "owner": OWNER,
             "origin": {"platform": "qqbot", "user_id": QQ_USER, "chat_id": QQ_USER}}
    monkeypatch.setattr(pkg.common, "read_team", lambda *_: board)
    monkeypatch.setattr(pkg.teams, "snapshot", lambda id, owner: snap)
    monkeypatch.setattr(link, "get", lambda *_: {"phase": "running", "status": "running"})
    monkeypatch.setattr(notify, "_remember", lambda *_: None)
    remote.remote.tick()
    assert len(remote.sent) == 1 and "整理完整结果" in remote.sent[-1]["text"]
    clock[0] += 20
    board["conclusion"].update(status="ready", acceptance={"status": "checking"})
    snap["team"]["stage"]["key"] = "checking"
    remote.remote.tick()
    assert "对照目标验收" in remote.sent[-1]["text"]

    board["conclusion"]["acceptance"] = {"status": "ready", "verdict": "met"}
    snap["team"]["stage"]["key"] = "done"
    remote.remote.tick()
    assert remote.remote.jobs()[key]["done_sent"] and "协作好了" in remote.sent[-1]["text"]
    remote.remote.tick()
    assert len(remote.sent) == 3

    snap["team"]["stage"]["key"] = "deploying"
    for step in ("push", "ci"):
        clock[0] += 20
        deploy = _deploy(step)
        snap["team"]["deploy"] = board["project"]["deploy"] = deploy
        remote.remote.tick()
        assert key in remote.remote.jobs()
    assert "推送与部署中" in remote.sent[-2]["text"] and f"CI 已开始：{CI_URL}" in remote.sent[-1]["text"]

    clock[0] += 20
    snap["team"]["stage"]["key"] = "done"
    snap["team"]["deploy"] = board["project"]["deploy"] = _deploy("done", "succeeded")
    assert notify.deploy_notice("halo-demo", board) == 1
    assert remote.sent[-1]["reply_to"] == "old"
    remote.remote.tick()
    assert remote.remote.jobs() == {} and len(remote.sent) == 6


def test_qq_drops_completed_job_if_auto_deploy_never_starts(remote, pkg, monkeypatch):
    key = _qq_job(remote)
    clock = [remote.remote.time.time()]
    monkeypatch.setattr(remote.remote.time, "time", lambda: clock[0])
    monkeypatch.setattr(pkg.teams, "snapshot", lambda *_: _snapshot(stage="done", phase="completed"))
    monkeypatch.setattr(pkg.common, "read_team", lambda *_: {"conclusion": {"status": "ready"},
                        "auto_deploy": True, "project": {"branch": "team"}})
    remote.remote.tick()
    clock[0] += 59
    remote.remote.tick()
    assert key in remote.remote.jobs() and len(remote.sent) == 1
    clock[0] += 1
    remote.remote.tick()
    assert remote.remote.jobs() == {} and len(remote.sent) == 1
