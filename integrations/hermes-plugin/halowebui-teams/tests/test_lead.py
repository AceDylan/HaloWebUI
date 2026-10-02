"""The lead after approval: change requests (对负责人说) proposed by the lead and applied by the
user, a finished team reopened by new work, failure diagnosis with a one-click suggestion, the
acceptance check after the conclusion, and how all of it reaches Telegram."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from test_tg import OWNER, TG_USER, _buttons, _event, _run, linked  # noqa: F401 — fixture reuse


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


class Lead:
    """A fake lead model: answers by the kind of prompt (change / diagnosis / acceptance / report)."""

    def __init__(self):
        self.change = []
        self.diagnosis = {"cause": "cchclaude 中转额度用完", "action": "switch_runner", "runner": "codex", "note": ""}
        self.acceptance = {"verdict": "met", "summary": "达成", "gaps": []}
        self.report = "# 报告\n\n> 做完了\n\n" + "内容" * 30
        self.prompts = []

    def __call__(self, messages, *a, **k):
        system = messages[0]["content"]
        self.prompts.append((system, messages[-1]["content"]))
        if "说了一段话" in system:
            reply = self.change.pop(0) if self.change else {"reply": "收到", "add_tasks": []}
            return json.dumps(reply, ensure_ascii=False), "", {"model": "gpt-chat"}
        if "处理建议" in system:
            return json.dumps(self.diagnosis, ensure_ascii=False), "", {"model": "gpt-chat"}
        if "验收" in system[:80]:
            return json.dumps(self.acceptance, ensure_ascii=False), "", {"model": "gpt-chat"}
        return self.report, "", {"model": "gpt-chat"}


@pytest.fixture
def lead(pkg, monkeypatch):
    fake = Lead()
    monkeypatch.setattr(pkg.plan, "call_model", fake)
    import halowebui_teams.lead as lead_mod

    return SimpleNamespace(fake=fake, mod=lead_mod)


def _create(pkg, team_id, plan_dict, origin=None):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    return pkg.teams.create_team(team_id, plan, owner=OWNER, goal="做一个小工具", origin=origin)


def _finish(pkg, slug, task_id, result="ok"):
    with pkg.common.board_conn(slug) as conn:
        assert _kb().claim_task(conn, task_id, claimer="w") is not None
        _kb().complete_task(conn, task_id, result=result, summary=result)


def _fail(pkg, slug, task_id, reason="cchclaude 运行失败：quota exceeded"):
    with pkg.common.board_conn(slug) as conn:
        _kb().claim_task(conn, task_id, claimer="w")
        _kb().block_task(conn, task_id, reason=reason)


def _task(snap, key):
    return next(t for t in snap["tasks"] if t["key"] == key)


def test_change_request_is_proposed_then_applied_onto_the_board(pkg, team_id, plan_dict, lead):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    _finish(pkg, slug, first["tasks"]["T1"], "api.md 写好了")
    _fail(pkg, slug, first["tasks"]["T2"], "page.md 写不出来：设计不清楚")
    lead.fake.change.append({
        "reply": "加一个测试成员写接口测试，评审改成只看接口，页面那步改成先出线框。",
        "add_members": [{"name": "qa-engineer", "role": "测试", "kind": "code", "focus": "接口测试"}],
        "add_tasks": [{"key": "N1", "title": "接口测试", "description": "给 api.md 写 tests.md", "member": "qa-engineer",
                       "depends_on": ["T1"]},
                      {"key": "N2", "title": "汇总", "description": "汇总到 summary.md", "member": "reviewer",
                       "depends_on": ["N1", "T3"]}],
        "edit_tasks": [{"key": "T2", "description": "先出线框 wireframe.md 再写 page.md"}],
        "cancel_tasks": [],
    })
    entry = lead.mod.request_change(team_id, "加上接口测试，页面先出线框", owner=OWNER, actor="Ace")
    assert entry["status"] == "ready"  # sync in tests
    proposal = entry["proposal"]
    assert [t["key"] for t in proposal["add_tasks"]] == ["T4", "T5"]
    assert proposal["add_tasks"][1]["depends_on"] == ["T4", "T3"]
    assert proposal["edit_tasks"][0]["retry"] is True
    # what the lead was shown: the team's state, the finished result, the failure reason
    shown = lead.fake.prompts[-1][1]
    assert "api.md 写好了" in shown and "设计不清楚" in shown and "加上接口测试" in shown
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["change"]["status"] == "ready"

    result = lead.mod.apply_change(team_id, entry["id"], owner=OWNER, actor="Ace")
    assert result["added"] == ["T4", "T5"] and result["members"] == ["qa-engineer"] and result["edited"] == ["T2"]
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["change"] is None
    assert snap["team"]["changes_log"][-1]["status"] == "applied"
    t4, t5 = _task(snap, "T4"), _task(snap, "T5")
    assert t4["member"] == "qa-engineer" and t4["parents"] == [first["tasks"]["T1"]]
    assert t4["status"] == "ready"  # T1 is done: it can start now
    assert set(t5["parents"]) == {t4["id"], first["tasks"]["T3"]} and t5["status"] == "todo"
    assert any(m["name"] == "qa-engineer" for m in snap["members"])
    t2 = _task(snap, "T2")
    assert t2["status"] == "ready"  # rewritten and retried
    with pkg.common.board_conn(slug) as conn:
        assert "wireframe.md" in _kb().get_task(conn, t2["id"]).body
        assert "qa-engineer（测试）" in _kb().get_task(conn, t5["id"]).body  # new members known to the team
    texts = [e["text"] for e in pkg.teams.timeline(team_id, OWNER)["events"] if e["type"] == "team"]
    assert any(t.startswith("Ace 对负责人说：加上接口测试") for t in texts)
    assert any("负责人提出计划变更" in t for t in texts)
    assert any(t.startswith("计划变更已应用：加入成员 qa-engineer；新任务 T4、T5；改写 T2") for t in texts)
    with pytest.raises(pkg.teams.TeamError):  # once only
        lead.mod.apply_change(team_id, entry["id"], owner=OWNER)


def test_invalid_change_gets_one_correction_and_running_tasks_are_never_touched(pkg, team_id, plan_dict, lead):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        _kb().claim_task(conn, first["tasks"]["T1"], claimer="w")  # T1 running
    lead.fake.change += [{"reply": "取消 T1", "cancel_tasks": ["T1"]},
                         {"reply": "T1 在做，不能取消；改成取消评审", "cancel_tasks": ["T3"]}]
    entry = lead.mod.request_change(team_id, "不要接口了", owner=OWNER)
    assert entry["status"] == "ready"
    assert [c["key"] for c in entry["proposal"]["cancel_tasks"]] == ["T3"]
    assert "T1 执行中，不能取消" in lead.fake.prompts[-1][1]  # the correction named the problem

    # T3 starts before the user applies: the change is refused, nothing is half-applied
    with pkg.common.board_conn(slug) as conn:
        conn.execute("UPDATE tasks SET status='running' WHERE id=?", (first["tasks"]["T3"],))
        conn.commit()
    with pytest.raises(pkg.teams.TeamError) as err:
        lead.mod.apply_change(team_id, entry["id"], owner=OWNER)
    assert "T3 已经执行中" in err.value.message
    assert pkg.common.read_team(slug)["change"]["status"] == "ready"


def test_a_question_is_just_answered_and_a_proposal_can_be_discarded(pkg, team_id, plan_dict, lead):
    _create(pkg, team_id, plan_dict)
    lead.fake.change.append({"reply": "接口和页面都在做，评审等它们。", "add_tasks": [], "cancel_tasks": []})
    entry = lead.mod.request_change(team_id, "进展怎么样？", owner=OWNER)
    assert entry["status"] == "answered" and entry["proposal"]["reply"].startswith("接口和页面")
    with pytest.raises(pkg.teams.TeamError):
        lead.mod.apply_change(team_id, entry["id"], owner=OWNER)
    lead.fake.change.append({"reply": "加一个文档任务", "add_tasks": [
        {"key": "N1", "title": "文档", "description": "写 README.md", "member": "reviewer", "depends_on": ["T3"]}]})
    second = lead.mod.request_change(team_id, "再写个文档", owner=OWNER)
    team = pkg.common.read_team(pkg.common.board_slug(team_id))
    assert team["changes_log"][-1]["id"] == entry["id"]  # the answered one moved to the log
    lead.mod.discard_change(team_id, second["id"], owner=OWNER, actor="Ace")
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["change"] is None and not any(t["key"] == "T4" for t in snap["tasks"])
    assert snap["team"]["changes_log"][-1]["status"] == "discarded"
    # other owners cannot see or drive it
    with pytest.raises(pkg.teams.TeamError):
        lead.mod.request_change(team_id, "x", owner="someone-else")


def test_finished_team_reopens_with_new_work_and_rewrites_its_conclusion(pkg, team_id, plan_dict, lead, linked):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))  # baseline
    for key in ("T1", "T2", "T3"):
        _finish(pkg, slug, first["tasks"][key])
    lead.fake.acceptance = {"verdict": "partial", "summary": "缺了部署说明",
                            "gaps": [{"title": "部署说明", "detail": "没有写怎么部署"}]}
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["phase"] == "completed"
    acceptance = snap["team"]["conclusion"]["acceptance"]
    assert acceptance["verdict"] == "partial" and acceptance["gaps"][0]["title"] == "部署说明"
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    done = linked.sent[-1]
    assert "负责人验收" in done["text"] and "部署说明" in done["text"]
    assert f"cb:fx:{team_id}" in _buttons(done)

    lead.fake.change.append({"reply": "补一个部署说明", "add_tasks": [
        {"key": "N1", "title": "部署说明", "description": "写 DEPLOY.md", "member": "reviewer", "depends_on": ["T3"]}]})
    entry = lead.mod.fill_gaps(team_id, owner=OWNER, actor="Ace")
    assert entry["source"] == "acceptance" and "部署说明" in entry["text"]
    result = lead.mod.apply_change(team_id, entry["id"], owner=OWNER)
    assert result["reopened"] is True
    team = pkg.common.read_team(slug)
    assert team["state"] == "running" and team["round"] == 1 and team["completed_at"] is None
    assert team["conclusion"]["status"] == "outdated" and team["conclusion"].get("acceptance") is None
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["phase"] == "running" and snap["team"]["round"] == 1

    lead.fake.report = "# 第二版报告\n\n" + "内容" * 30
    lead.fake.acceptance = {"verdict": "met", "summary": "都做到了", "gaps": []}
    _finish(pkg, slug, _task(snap, "T4")["id"], "DEPLOY.md 写好了")
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert snap["team"]["phase"] == "completed"
    data = pkg.conclusion.read(slug, pkg.common.read_team(slug))
    assert data["markdown"].startswith("# 第二版报告")  # rewritten, not the old one
    assert snap["team"]["conclusion"]["acceptance"]["verdict"] == "met"
    # the second check judges against the goal *and* what the user asked for since
    acceptance_prompt = [text for head, text in lead.fake.prompts if "验收" in head][-1]
    assert "用户在执行中追加" in acceptance_prompt and "按验收发现的缺口补上" in acceptance_prompt
    report_prompt = [text for head, text in lead.fake.prompts if "最终结论" in head][-1]
    assert "用户在执行中追加" in report_prompt
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    assert "完成" in linked.sent[-1]["text"] and "目标已达成" in linked.sent[-1]["text"]  # a second done notice
    assert "done:1" in pkg.common.read_team(slug)["notified"]


def test_failed_task_is_diagnosed_and_the_suggestion_applies_in_one_click(pkg, team_id, plan_dict, lead):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    t1 = first["tasks"]["T1"]
    _fail(pkg, slug, t1)
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    snap = pkg.teams.snapshot(team_id, OWNER)
    diagnosis = _task(snap, "T1")["diagnosis"]
    assert diagnosis["status"] == "ready" and diagnosis["action"] == "switch_runner" and diagnosis["runner"] == "codex"
    assert diagnosis["action_label"] == "换执行器重试"
    # one diagnosis per attempt: the next tick does not ask again
    calls = len(lead.fake.prompts)
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    assert len(lead.fake.prompts) == calls

    lead.mod.apply_diagnosis(team_id, t1, owner=OWNER, actor="Ace")
    snap = pkg.teams.snapshot(team_id, OWNER)
    task = _task(snap, "T1")
    assert task["status"] == "ready" and task["executor"] == "codex" and task["chosen_by"] == "lead"
    assert task["trail"][-1]["phase"] == "lead"
    assert "diagnosis" not in task  # no longer failed

    # a note from the lead reaches the member like a user's note and shows as the lead's
    lead.fake.diagnosis = {"cause": "说明里没写输出格式", "action": "retry_with_note", "note": "用 Markdown 表格输出接口列表"}
    _fail(pkg, slug, t1, "不知道输出什么格式")
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    lead.mod.apply_diagnosis(team_id, t1, owner=OWNER)
    events = pkg.teams.timeline(team_id, OWNER)["events"]
    note = [e for e in events if e["type"] == "message" and e.get("who") == "lead"]
    assert note and note[-1]["text"] == "用 Markdown 表格输出接口列表" and note[-1]["author"] == "team-lead"
    assert any(e["type"] == "team" and e["text"].startswith("负责人诊断：说明里没写输出格式") for e in events)

    # skip: the task leaves the plan and what waited for it goes on
    lead.fake.diagnosis = {"cause": "评审不是必需的", "action": "skip"}
    t2 = first["tasks"]["T2"]
    _finish(pkg, slug, t1)
    _fail(pkg, slug, t2, "页面写不出来")
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    lead.mod.apply_diagnosis(team_id, t2, owner=OWNER)
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert _task(snap, "T2")["status"] == "archived" and _task(snap, "T3")["status"] == "ready"


def test_ask_user_suggestion_is_not_applied_by_a_click(pkg, team_id, plan_dict, lead):
    first = _create(pkg, team_id, plan_dict)
    slug = pkg.common.board_slug(team_id)
    lead.fake.diagnosis = {"cause": "需要 GitHub 账号", "action": "ask_user", "note": "用哪个 GitHub 账号？"}
    _fail(pkg, slug, first["tasks"]["T1"], "没有 GitHub 账号")
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    with pytest.raises(pkg.teams.TeamError):
        lead.mod.apply_diagnosis(team_id, first["tasks"]["T1"], owner=OWNER)


def test_failure_notice_waits_for_the_diagnosis_and_offers_it(pkg, team_id, plan_dict, lead, linked):
    first = _create(pkg, team_id, plan_dict, origin={"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})
    slug = pkg.common.board_slug(team_id)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    t1 = first["tasks"]["T1"]
    _fail(pkg, slug, t1)
    # the lead is still thinking: no notice yet
    pkg.common.update_team(slug, lambda rec: rec.setdefault("diagnoses", {}).update(
        {t1: {"attempt": 1, "status": "thinking", "started_at": pkg.common.now()}}))
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    assert linked.sent == []
    pkg.common.update_team(slug, lambda rec: rec["diagnoses"].pop(t1))
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    msg = linked.sent[-1]
    assert "负责人判断" in msg["text"] and "换成 codex 重试" in msg["text"]
    assert f"cb:dx:{team_id}:{t1}" in _buttons(msg)

    class Query:
        def __init__(self, data):
            self.data = data
            self.from_user = SimpleNamespace(id=int(TG_USER), first_name="Ace")
            self.message = SimpleNamespace(chat_id=int(TG_USER), message_id=9, text_html="卡片", reply_markup=None,
                                           message_thread_id=None)
            self.answers = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append(text)

        async def edit_message_text(self, **kw):
            pass

    query = Query(f"ht:dx:{team_id}:{t1}")
    asyncio.run(linked.telegram._handle_callback(query))
    assert query.answers == ["✅ 已按负责人的建议处理"]
    assert _task(pkg.teams.snapshot(team_id, OWNER), "T1")["executor"] == "codex"


def test_telegram_reply_to_the_done_notice_goes_to_the_lead_and_the_card_comes_back(pkg, team_id, plan_dict, lead,
                                                                                       linked, monkeypatch):
    first = _create(pkg, team_id, plan_dict, origin={"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})
    slug = pkg.common.board_slug(team_id)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    for key in ("T1", "T2", "T3"):
        _finish(pkg, slug, first["tasks"][key])
    pkg.teams.snapshot(team_id, OWNER)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    done_id = 1000 + len(linked.sent)
    assert linked.telegram.lookup(TG_USER, done_id)["kind"] == "done"

    lead.fake.change.append({"reply": "加一个英文版", "add_tasks": [
        {"key": "N1", "title": "英文版", "description": "把 api.md 翻成 api.en.md", "member": "backend-dev",
         "depends_on": ["T1"]}]})
    assert _run(lambda: linked.telegram.on_pre_gateway_dispatch(event=_event("再出一个英文版", reply_to=str(done_id))))
    card = next(m for m in linked.sent if "负责人回复" in m["text"])
    assert "＋ T4 英文版 — backend-dev" in card["text"] and "重新开工" in card["text"]
    change_id = pkg.common.read_team(slug)["change"]["id"]
    assert f"cb:ca:{team_id}:{change_id}" in _buttons(card)
    card_id = 1000 + linked.sent.index(card) + 1
    assert linked.telegram.lookup(TG_USER, card_id)["change"] == change_id

    class Query:
        def __init__(self, data):
            self.data = data
            self.from_user = SimpleNamespace(id=int(TG_USER), first_name="Ace")
            self.message = SimpleNamespace(chat_id=int(TG_USER), message_id=card_id, text_html="卡片", reply_markup=None)
            self.answers = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append(text)

        async def edit_message_text(self, **kw):
            pass

    synced = []
    monkeypatch.setattr(linked.link, "sync", lambda owner, tid: synced.append((owner, tid)) or {})
    query = Query(f"ht:ca:{team_id}:{change_id}")
    asyncio.run(linked.telegram._handle_callback(query))
    assert query.answers == ["✅ 变更已应用"]
    assert synced == [(OWNER, team_id)]  # HaloWebUI hears the finished team runs again
    snap = pkg.teams.snapshot(team_id, OWNER)
    assert _task(snap, "T4")["status"] == "ready" and snap["team"]["phase"] == "running"
    assert linked.telegram.lookup(TG_USER, card_id)["acted"] == "ca"
    again = Query(f"ht:ca:{team_id}:{change_id}")
    asyncio.run(linked.telegram._handle_callback(again))
    assert "已经" in again.answers[0]  # a second tap is refused with the reason


def test_a_member_that_stops_to_ask_gets_the_leads_take_and_an_answer_resumes_it(pkg, team_id, plan_dict, lead, linked):
    first = _create(pkg, team_id, plan_dict, origin={"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})
    slug = pkg.common.board_slug(team_id)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    t1 = first["tasks"]["T1"]
    with pkg.common.board_conn(slug) as conn:
        _kb().claim_task(conn, t1, claimer="w")
        _kb().block_task(conn, t1, reason="input.txt 不存在，要补文件还是作废？", kind="needs_input")
    lead.fake.diagnosis = {"cause": "输入文件不存在，接口说明已在目标里写清", "action": "retry_with_note",
                           "note": "不用 input.txt，按目标里的接口清单写 api.md"}
    lead.mod.tick_board(slug, pkg.common.read_team(slug))
    task = _task(pkg.teams.snapshot(team_id, OWNER), "T1")
    assert task["sub_status"] == "waiting_user" and task["diagnosis"]["action"] == "retry_with_note"
    assert task["block_reason"] == "input.txt 不存在，要补文件还是作废？"  # the lead's note does not hide it
    assert "input.txt 不存在" in lead.fake.prompts[-1][1]  # the lead read the member's question
    linked.notify.tick_board(slug, pkg.common.read_team(slug))
    ask = linked.sent[-1]
    assert "问你" in ask["text"] and "负责人判断" in ask["text"] and f"cb:dx:{team_id}:{t1}" in _buttons(ask)

    # the user's own answer (here, in the browser) resumes the member: a new attempt reads it
    out = pkg.teams.post_message(team_id, t1, "作废 input.txt，按目标写", author_name="Ace", owner=OWNER)
    assert out["resumed"] is True
    assert _task(pkg.teams.snapshot(team_id, OWNER), "T1")["status"] == "ready"


def test_a_runner_question_on_an_open_run_is_not_diagnosed(pkg, lead):
    assert lead.mod.diagnosable({"sub_status": "waiting_user", "status": "running"}) is False
    assert lead.mod.diagnosable({"sub_status": "waiting_user", "status": "blocked"}) is True
    assert lead.mod.diagnosable({"sub_status": "failed", "status": "blocked"}) is True
    assert lead.mod.diagnosable({"sub_status": "stopped", "status": "blocked"}) is False
