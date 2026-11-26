"""精答 / 讨论 / 自动分流 (and QQ's /team) from Telegram and QQ: commands and the read-back (no real
chat platform, no real HaloWebUI)."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

TG_USER = "5550001"
QQ_USER = "QQOPENID01"
OWNER = "u1"


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """Linked Telegram and QQ users, a temp job store, adapters that record what they send."""
    import halowebui_teams.link as link
    import halowebui_teams.remote as remote

    cfg = tmp_path / "halo-teams.json"
    cfg.write_text(json.dumps({
        "halowebui": {"url": "http://127.0.0.1:9", "public_url": "https://halo.example"},
        "telegram": {"owners": {TG_USER: OWNER}},
        "qqbot": {"owners": {QQ_USER: OWNER}},
    }))
    monkeypatch.setenv("HALO_TEAMS_LINK_FILE", str(cfg))
    monkeypatch.setenv("HALO_REMOTE_JOBS", str(tmp_path / "jobs.json"))
    link._cache.update(mtime=None, data={})
    sent = []

    class Adapter:
        def __init__(self, platform):
            self.platform = SimpleNamespace(value=platform)

        async def send(self, chat_id, text, reply_to=None, metadata=None):
            sent.append({"platform": self.platform.value, "chat": chat_id, "text": text, "reply_to": reply_to})
            return SimpleNamespace(success=True, message_id="m1")

        async def send_image_file(self, chat_id, path, caption=None, metadata=None):
            sent.append({"platform": self.platform.value, "chat": chat_id, "photo": path, "text": caption})
            return SimpleNamespace(success=True)

    for platform in ("telegram", "qqbot"):
        remote._state["adapters"][platform] = Adapter(platform)
    monkeypatch.setattr(remote, "ready", lambda platform: platform in ("telegram", "qqbot"))

    def run_sync(make):  # the bridge thread's send, without a gateway loop
        return asyncio.run(make())

    monkeypatch.setattr(remote, "_from_thread", run_sync)
    calls = []
    yield SimpleNamespace(remote=remote, link=link, sent=sent, calls=calls)
    remote._state["adapters"].clear()


def _event(platform, user, text, message_id="77"):
    command, _, args = text[1:].partition(" ") if text.startswith("/") else (None, "", "")
    source = SimpleNamespace(platform=SimpleNamespace(value=platform), chat_id=user, user_id=user, thread_id=None,
                             user_name="me")
    return SimpleNamespace(source=source, text=text, message_id=message_id, internal=False,
                           is_command=lambda: command is not None, get_command=lambda: command,
                           get_command_args=lambda: args)


def _dispatch(remote, event):
    async def go():
        result = remote._dispatch(event)
        while remote._tasks:
            await asyncio.gather(*list(remote._tasks))
        return result

    return asyncio.run(go())


def test_answer_from_telegram_starts_a_run_and_remembers_it(remote, monkeypatch):
    def start(owner, kind, question, key, origin):
        remote.calls.append((owner, kind, question, key, origin))
        return {"kind": kind, "id": "chat-1"}

    monkeypatch.setattr(remote.link, "remote_start", start)
    result = _dispatch(remote.remote, _event("telegram", TG_USER, "/answer 为什么天是蓝的"))
    assert result == {"action": "skip", "reason": "halo answer command"}
    # the chat it came from goes along: a team 自动分流 starts sends its plan back there
    origin = {"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER}
    assert remote.calls == [(OWNER, "answer", "为什么天是蓝的", f"telegram:{TG_USER}:77", origin)]
    job = remote.remote.jobs()["answer:chat-1"]
    assert job["platform"] == "telegram" and job["chat_id"] == TG_USER and job["reply_to"] == "77"
    assert "已交给精答" in remote.sent[-1]["text"] and "https://halo.example/answer/chat-1" in remote.sent[-1]["text"]


def test_a_redelivered_command_says_nothing_twice(remote, monkeypatch):
    monkeypatch.setattr(remote.link, "remote_start",
                        lambda *a: {"kind": "discuss", "id": "chat-2", "deduplicated": True})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/discuss 要不要换工作"))
    assert remote.sent == []
    assert "discuss:chat-2" in remote.remote.jobs()


def test_unlinked_users_and_other_messages_go_on_to_hermes(remote, monkeypatch):
    monkeypatch.setattr(remote.link, "remote_start", lambda *a: pytest.fail("must not start"))
    assert _dispatch(remote.remote, _event("telegram", "999", "/answer 你好")) is None
    assert _dispatch(remote.remote, _event("telegram", TG_USER, "随便聊聊")) is None
    # Telegram's /team is tg.py's (buttons and replies), not this module's
    assert _dispatch(remote.remote, _event("telegram", TG_USER, "/team 做个网站")) is None
    # 「批准」 with no plan waiting is an ordinary message
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "批准")) is None


def test_the_command_alone_explains_and_lists_what_is_going(remote, monkeypatch):
    remote.remote.put_job({"kind": "discuss", "id": "c9", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "周末去哪", "at": time.time() - 120})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/answer"))
    text = remote.sent[-1]["text"]
    assert "/answer 问题" in text and "/team 目标" in text and "周末去哪" in text
    assert "**" not in text  # QQ gets plain text


def test_a_finished_answer_comes_back_with_its_picture(remote, monkeypatch):
    remote.remote.put_job({"kind": "answer", "id": "chat-1", "owner": OWNER, "platform": "telegram",
                           "chat_id": TG_USER, "reply_to": "77", "question": "为什么天是蓝的", "at": time.time()})
    states = iter([{"status": "running"},
                   {"status": "done", "title": "天空为什么是蓝色", "by": "🔭物理老师", "text": "因为**瑞利散射**。",
                    "url": "/answer/chat-1", "picture": True}])
    monkeypatch.setattr(remote.link, "remote_state", lambda owner, kind, run_id: next(states))
    monkeypatch.setattr(remote.link, "remote_picture", lambda owner, kind, run_id: b"\x89PNG fake")
    remote.remote.tick()
    assert remote.sent == []
    remote.remote.tick()
    text, photo = remote.sent[0], remote.sent[1]
    assert text["reply_to"] == "77"
    assert "精答好了" in text["text"] and "物理老师" in text["text"] and "瑞利散射" in text["text"]
    assert "https://halo.example/answer/chat-1" in text["text"]
    assert photo["photo"].endswith("picture.png") and "天空为什么是蓝色" in photo["text"]
    assert remote.remote.jobs() == {}


def test_a_long_result_goes_out_whole(remote, monkeypatch):
    remote.remote.put_job({"kind": "discuss", "id": "d1", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "q", "at": time.time()})
    remote.remote.put_job({"kind": "answer", "id": "a9", "owner": OWNER, "platform": "telegram", "chat_id": TG_USER,
                           "question": "q", "at": time.time()})
    texts = {"d1": "字" * 20000, "a9": "长" * (remote.remote.TEXT_MAX_CHARS + 100)}
    monkeypatch.setattr(remote.link, "remote_state", lambda owner, kind, run_id: {
        "status": "done", "title": "长结论", "text": texts[run_id], "url": f"/{kind}/{run_id}"})
    remote.remote.tick()
    qq = next(m["text"] for m in remote.sent if m["platform"] == "qqbot")
    tg = next(m["text"] for m in remote.sent if m["platform"] == "telegram")
    # the adapter splits it into messages; nothing is left to the page
    assert "字" * 20000 in qq and "后面的在网页看" not in qq and "https://halo.example/discuss/d1" in qq
    # only past the cap
    assert "后面的在网页看" in tg and tg.count("长") <= remote.remote.TEXT_MAX_CHARS + 10


def test_a_failed_run_is_told_once(remote, monkeypatch):
    remote.remote.put_job({"kind": "answer", "id": "a2", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "q", "at": time.time()})
    monkeypatch.setattr(remote.link, "remote_state", lambda *a: {"status": "failed", "error": "模型超时",
                                                                 "url": "/answer/a2"})
    remote.remote.tick()
    remote.remote.tick()
    assert len(remote.sent) == 1 and "没完成：模型超时" in remote.sent[0]["text"]


def test_not_sent_is_tried_again(remote, monkeypatch):
    remote.remote.put_job({"kind": "answer", "id": "a3", "owner": OWNER, "platform": "telegram", "chat_id": TG_USER,
                           "question": "q", "at": time.time()})
    monkeypatch.setattr(remote.link, "remote_state", lambda *a: {"status": "done", "text": "答案", "url": "/answer/a3"})
    monkeypatch.setattr(remote.remote, "send", lambda job, text: False)
    remote.remote.tick()
    assert "answer:a3" in remote.remote.jobs()


def test_auto_routing_follows_the_run_it_picked(remote, monkeypatch):
    remote.remote.put_job({"kind": "auto", "id": "r1", "owner": OWNER, "platform": "telegram", "chat_id": TG_USER,
                           "question": "比较三种方案", "at": time.time()})
    monkeypatch.setattr(remote.link, "remote_state", lambda *a: {
        "status": "dispatched", "mode": "discuss", "target_id": "d7", "reason": "需要多角度权衡"})
    remote.remote.tick()
    assert "交给讨论（需要多角度权衡）" in remote.sent[0]["text"]
    assert "https://halo.example/discuss/d7" in remote.sent[0]["text"]
    assert list(remote.remote.jobs()) == ["discuss:d7"]


def test_auto_routing_to_a_team(remote, monkeypatch):
    for platform, user in (("telegram", TG_USER), ("qqbot", QQ_USER)):
        remote.remote.put_job({"kind": "auto", "id": f"r-{platform}", "owner": OWNER, "platform": platform,
                               "chat_id": user, "question": "做个小工具", "at": time.time()})
    monkeypatch.setattr(remote.link, "remote_state", lambda owner, kind, run_id: {
        "status": "dispatched", "mode": "team", "target_id": f"team{run_id[2:]}", "read_only": True})
    remote.remote.tick()
    # Telegram: the 协作台's own notices (buttons) take over; QQ: followed here
    assert list(remote.remote.jobs()) == ["team:teamqqbot"]
    tg, qq = (next(m for m in remote.sent if m["platform"] == p) for p in ("telegram", "qqbot"))
    assert "计划好了发到这里" in tg["text"] and "批准并开始" in tg["text"] and "只读" in tg["text"]
    assert "回「批准」开始" in qq["text"]


def test_auto_routing_that_failed(remote, monkeypatch):
    remote.remote.put_job({"kind": "auto", "id": "r2", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "改服务器配置", "at": time.time()})
    monkeypatch.setattr(remote.link, "remote_state", lambda *a: {"status": "failed", "error": "需要真实文件检查"})
    remote.remote.tick()
    assert "没有派发" in remote.sent[0]["text"] and "需要真实文件检查" in remote.sent[0]["text"]
    assert remote.remote.jobs() == {}


def test_a_job_that_never_finishes_is_given_up(remote, monkeypatch):
    remote.remote.put_job({"kind": "answer", "id": "old", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "q", "at": time.time() - 4 * 3600})
    monkeypatch.setattr(remote.link, "remote_state", lambda *a: pytest.fail("not read again"))
    remote.remote.tick()
    assert "不再等了" in remote.sent[0]["text"] and remote.remote.jobs() == {}


def test_a_vanished_run_is_dropped(remote, monkeypatch):
    remote.remote.put_job({"kind": "answer", "id": "x", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "q", "at": time.time()})

    def gone(*a):
        raise remote.link.HaloError(404, "不存在")

    monkeypatch.setattr(remote.link, "remote_state", gone)
    remote.remote.tick()
    assert remote.remote.jobs() == {} and remote.sent == []


PLAN_TEAM = {"id": "5f3c2a10-team-q", "title": "做个小工具", "status": "plan_ready",
             "plan": {"summary": "两人分工", "members": [{"name": "dev", "role": "开发", "runner": "codex"}],
                      "tasks": [{"key": "T1", "title": "写代码", "member": "dev"}]}}


def test_qq_team_plan_approve_and_result(remote, monkeypatch, tmp_path):
    created = []
    monkeypatch.setattr(remote.link, "create", lambda owner, goal, origin, auto, workflow="auto": created.append((goal, origin, auto))
                        or {"id": "5f3c2a10-team-q", "title": goal})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/team 做个小工具"))
    assert created == [("做个小工具", {"platform": "qqbot", "chat_id": QQ_USER, "user_id": QQ_USER}, False)]
    assert "回「批准」才开始" in remote.sent[-1]["text"]

    team = dict(PLAN_TEAM)
    monkeypatch.setattr(remote.link, "get", lambda owner, team_id: team)
    remote.remote.tick()
    remote.remote.tick()
    plans = [m for m in remote.sent if "· 计划好了" in m["text"]]
    assert len(plans) == 1
    assert "<b>" not in plans[0]["text"] and "写代码" in plans[0]["text"] and "回「批准」开始" in plans[0]["text"]
    assert "回复这条消息" not in plans[0]["text"]

    approved = []
    monkeypatch.setattr(remote.link, "approve", lambda owner, team_id: approved.append(team_id) or team)
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "批准", "78")) == {
        "action": "skip", "reason": "answer the team plan (QQ)"}
    assert approved == ["5f3c2a10-team-q"] and "已批准" in remote.sent[-1]["text"]
    # once approved, 「批准」 is an ordinary message again
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "批准", "79")) is None

    team.update(status="running", phase="running")
    remote.remote.tick()
    team.update(phase="completed")
    import halowebui_teams.notify as notify

    picture = tmp_path / "pic.png"
    picture.write_bytes(b"png")
    board = {"conclusion": {"status": "ready"}}
    monkeypatch.setattr("halowebui_teams.common.read_team", lambda slug: board)
    monkeypatch.setattr(notify, "_conclusion_markdown", lambda rec: "## 结论\n小工具做好了。")
    monkeypatch.setattr(notify, "picture_of", lambda rec: picture)
    remote.remote.tick()
    done = [m for m in remote.sent if "协作好了" in (m.get("text") or "")]
    assert len(done) == 1 and "小工具做好了" in done[0]["text"] and "/teams/5f3c2a10-team-q/conclusion" in done[0]["text"]
    assert remote.sent[-1].get("photo") == str(picture)
    assert remote.remote.jobs() == {}


def test_qq_team_waits_for_its_conclusion(remote, monkeypatch):
    remote.remote.put_job({"kind": "team", "id": "7a1b2c3d-team-w", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "g", "at": time.time(), "approved": True})
    monkeypatch.setattr(remote.link, "get", lambda *a: {"id": "7a1b2c3d-team-w", "title": "t", "status": "running",
                                                        "phase": "completed"})
    monkeypatch.setattr("halowebui_teams.common.read_team", lambda slug: {"conclusion": {"status": "generating"}})
    remote.remote.tick()
    assert remote.sent == [] and "team:7a1b2c3d-team-w" in remote.remote.jobs()


def test_qq_team_cancel_and_replan(remote, monkeypatch):
    remote.remote.put_job({"kind": "team", "id": "teamc", "owner": OWNER, "platform": "qqbot", "chat_id": QQ_USER,
                           "question": "g", "at": time.time(), "plan_sent": True, "plan_at": time.time()})
    replans = []
    monkeypatch.setattr(remote.link, "replan", lambda owner, team_id, feedback: replans.append(feedback) or {})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/team 重做 只要一个人"))
    assert replans == ["只要一个人"]
    assert remote.remote.jobs()["team:teamc"]["plan_sent"] is False
    remote.remote.update_job("team:teamc", plan_sent=True, plan_at=time.time())
    cancelled = []
    monkeypatch.setattr(remote.link, "cancel", lambda owner, team_id: cancelled.append(team_id) or {})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "取消"))
    assert cancelled == ["teamc"] and remote.remote.jobs() == {}


def test_qq_gets_plain_text_and_telegram_markdown(remote):
    async def go():
        await remote.remote.asend("qqbot", QQ_USER, "**粗体** 和 `代码`")
        await remote.remote.asend("telegram", TG_USER, "**粗体**")

    asyncio.run(go())
    assert remote.sent[0]["text"] == "粗体 和 代码"
    assert remote.sent[1]["text"] == "**粗体**"


def test_a_team_started_from_qq_does_not_notify_telegram(remote):
    import halowebui_teams.notify as notify

    team = {"owner": OWNER, "origin": {"platform": "qqbot", "chat_id": QQ_USER, "user_id": QQ_USER}}
    assert notify.target_for(team) is None
    assert notify.target_for({"owner": OWNER, "origin": {}}) == {"chat_id": TG_USER}


def test_install_captures_the_adapters(remote):
    remote.remote._state["adapters"].clear()

    async def go():
        remote.remote.install(None, SimpleNamespace(platform=SimpleNamespace(value="qqbot")))
        remote.remote.install(None, SimpleNamespace(platform=SimpleNamespace(value="discord")))

    asyncio.run(go())
    assert list(remote.remote._state["adapters"]) == ["qqbot"]


def test_qq_team_command_picks_a_workflow(remote, monkeypatch):
    created = []
    monkeypatch.setattr(remote.link, "create", lambda owner, goal, origin, auto, workflow="auto":
                        created.append((goal, auto, workflow)) or {"id": "5f3c2a10-team-m", "title": goal})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/team 直接 多模型 给 HaloWebUI 加按钮"))
    assert created == [("给 HaloWebUI 加按钮", True, "dev_pipeline")]
    assert "（多模型研发）" in remote.sent[-1]["text"]


def test_qq_prompt_replies_parse():
    import halowebui_teams.remote as remote

    assert remote.prompt_reply("答 用方案 B") == ("answer", None, "用方案 B")
    assert remote.prompt_reply("答#2：用 A") == ("answer", 2, "用 A")
    assert remote.prompt_reply("回答：好") == ("answer", None, "好")
    assert remote.prompt_reply("重试") == ("retry", None, "")
    assert remote.prompt_reply("重试＃3 换个端口") == ("retry", 3, "换个端口")
    assert remote.prompt_reply("按建议。") == ("advice", None, "")
    for text in ("答案是 42", "答", "重试一下行不行吗", "你好"):
        assert remote.prompt_reply(text) is None, text


def _qq_team_board(monkeypatch, tasks, diagnoses=None):
    """A running QQ team whose board says *tasks* (the snapshot) need the user."""
    import halowebui_teams.notify as notify

    board = {"team_id": "9a8b7c6d-team-a", "title": "加按钮", "members": [{"name": "claude-lead", "role": "主控"}],
             "diagnoses": diagnoses or {}}
    monkeypatch.setattr("halowebui_teams.common.read_team", lambda slug: board)
    snap = {"team": {"phase": "attention"}, "tasks": tasks}
    monkeypatch.setattr("halowebui_teams.teams.snapshot", lambda team_id, owner=None: snap)
    monkeypatch.setattr(notify, "now", lambda: int(time.time()))
    return snap


def test_qq_team_question_comes_in_full_and_an_answer_goes_to_the_member(remote, monkeypatch):
    remote.remote.put_job({"kind": "team", "id": "9a8b7c6d-team-a", "owner": OWNER, "platform": "qqbot",
                           "chat_id": QQ_USER, "question": "g", "at": time.time(), "approved": True})
    team = {"id": "9a8b7c6d-team-a", "title": "加按钮", "status": "running", "phase": "attention"}
    monkeypatch.setattr(remote.link, "get", lambda *a: team)
    ask = {"id": "t_aaaa", "title": "合成方案", "member": "claude-lead", "sub_status": "waiting_user", "attempts": 1,
           "current_run": {"question": "方案 A 还是方案 B？A 快，B 稳。"}}
    snap = _qq_team_board(monkeypatch, [ask])
    remote.remote.tick()
    remote.remote.tick()  # once only
    asks = [m for m in remote.sent if "在任务「合成方案」里问你" in m["text"]]
    assert len(asks) == 1
    text = asks[0]["text"]
    assert text.startswith("【#1】❓") and "方案 A 还是方案 B" in text and "回「答 你的回答」" in text
    assert "<b>" not in text and "回复这条消息" not in text and "请到网页看" not in text

    posted = []
    import halowebui_teams.teams as teams

    monkeypatch.setattr(teams, "post_message", lambda team_id, task_id, body, author_name, owner=None:
                        posted.append((team_id, task_id, body, owner)) or {})
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "答 用 B", "80")) == {
        "action": "skip", "reason": "answer a team notice (QQ)"}
    assert posted == [("9a8b7c6d-team-a", "t_aaaa", "用 B", OWNER)]
    assert "已转给 claude-lead" in remote.sent[-1]["text"]
    # answered: the next 「答」 is an ordinary message; the same wait is not sent again
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "答 再说一次", "81")) is None
    remote.remote.tick()
    assert len([m for m in remote.sent if "在任务「合成方案」里问你" in m["text"]]) == 1
    # the member works again: the notice is closed
    snap["tasks"] = []
    team["phase"] = "running"
    remote.remote.tick()
    assert remote.remote.jobs()["team:9a8b7c6d-team-a"]["prompts"] == {}


def test_qq_team_failure_retries_with_a_note_or_the_leads_advice(remote, monkeypatch):
    remote.remote.put_job({"kind": "team", "id": "9a8b7c6d-team-a", "owner": OWNER, "platform": "qqbot",
                           "chat_id": QQ_USER, "question": "g", "at": time.time(), "approved": True})
    monkeypatch.setattr(remote.link, "get", lambda *a: {"id": "9a8b7c6d-team-a", "title": "加按钮",
                                                        "status": "running", "phase": "attention"})
    diagnosis = {"status": "ready", "cause": "端口被占", "action": "retry_with_note", "note": "换 8081"}
    fail = {"id": "t_bbbb", "title": "写后端", "member": "codex-dev", "sub_status": "failed", "attempts": 2,
            "block_reason": "address already in use", "diagnosis": diagnosis}
    other = {"id": "t_cccc", "title": "写前端", "member": "claude-lead", "sub_status": "failed", "attempts": 1,
             "block_reason": "tests failed"}
    _qq_team_board(monkeypatch, [fail, other])
    remote.remote.tick()
    fails = [m["text"] for m in remote.sent if "失败" in m["text"]]
    assert [t[:4] for t in fails] == ["【#1】", "【#2】"]
    assert "「按建议」" in fails[0] and "「按建议」" not in fails[1] and "address already in use" in fails[0]

    import halowebui_teams.teams as teams
    import halowebui_teams.lead as lead

    calls = []
    monkeypatch.setattr(teams, "post_message", lambda team_id, task_id, body, author_name, owner=None:
                        calls.append(("note", task_id, body)) or {})
    monkeypatch.setattr(teams, "retry", lambda team_id, task_id, owner=None, actor="": calls.append(("retry", task_id)) or {})
    monkeypatch.setattr(lead, "apply_diagnosis", lambda team_id, task_id, owner=None, actor="":
                        calls.append(("advice", task_id)) or {})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "重试#1 换个端口", "82"))
    assert calls == [("note", "t_bbbb", "换个端口"), ("retry", "t_bbbb")] and "带着你的说明重试" in remote.sent[-1]["text"]
    # 按建议: only the failure with advice; #1 is settled, #2 has none → an ordinary message
    assert _dispatch(remote.remote, _event("qqbot", QQ_USER, "按建议", "83")) is None
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "重试", "84"))
    assert calls[-1] == ("retry", "t_cccc") and remote.sent[-1]["text"] == "🔁 已重试。"


def test_qq_failure_waits_for_the_leads_diagnosis_without_a_generic_notice(remote, monkeypatch):
    remote.remote.put_job({"kind": "team", "id": "9a8b7c6d-team-a", "owner": OWNER, "platform": "qqbot",
                           "chat_id": QQ_USER, "question": "g", "at": time.time(), "approved": True})
    monkeypatch.setattr(remote.link, "get", lambda *a: {"id": "9a8b7c6d-team-a", "title": "加按钮",
                                                        "status": "running", "phase": "attention"})
    fail = {"id": "t_bbbb", "title": "写后端", "member": "codex-dev", "sub_status": "failed", "attempts": 1,
            "block_reason": "boom"}
    thinking = {"t_bbbb": {"status": "thinking", "attempt": 1, "started_at": int(time.time())}}
    _qq_team_board(monkeypatch, [fail], diagnoses=thinking)
    remote.remote.tick()
    assert remote.sent == []
    # a task in triage: nothing to answer here, the page once
    _qq_team_board(monkeypatch, [{"id": "t_dddd", "title": "x", "member": "m", "sub_status": "", "status": "triage"}])
    remote.remote.tick()
    remote.remote.tick()
    assert [m["text"][:12] for m in remote.sent] == ["🟣 协作「加按钮」需要你"]


def test_qq_work_command_starts_the_work_workflow(remote, monkeypatch):
    created = []
    monkeypatch.setattr(remote.link, "create", lambda owner, goal, origin, auto, workflow="auto", runner_prefs=None:
                        created.append((goal, auto, workflow, runner_prefs)) or {"id": "5f3c2a10-team-w", "title": goal})
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/work anyclaude 给 HaloWebUI 加按钮"))
    assert created == [("给 HaloWebUI 加按钮", True, "work", {"claude": "anyclaude"})]
    text = remote.sent[-1]["text"]
    assert "已交给工作流" in text and "anyclaude 审阅修复" in text and "<b>" not in text
    assert any(j["kind"] == "team" and j["id"] == "5f3c2a10-team-w" for j in remote.remote.chat_jobs("qqbot", QQ_USER))
    _dispatch(remote.remote, _event("qqbot", QQ_USER, "/work"))
    assert "/work 需求" in remote.sent[-1]["text"] and len(created) == 1


def test_qq_team_receives_deploy_notice_without_notifying_telegram(remote, monkeypatch):
    import halowebui_teams.notify as notify

    remembered = []
    monkeypatch.setattr(notify, "_remember", lambda slug, keys: remembered.extend(keys))
    team = {
        "team_id": "5f3c2a10-team-w",
        "title": "工作：加减法",
        "owner": OWNER,
        "origin": {"platform": "qqbot", "chat_id": QQ_USER, "user_id": QQ_USER},
        "project": {
            "name": "calc",
            "deploy": {
                "status": "succeeded",
                "base_branch": "main",
                "sha": "abcdef123456",
                "seconds": 12,
                "cleanup": True,
                "finished_at": 1700000000,
                "ci_url": "https://github.com/AceDylan/calc/actions/runs/1",
            },
        },
        "notified": [],
    }
    assert notify.deploy_notice("halo-5f3c2a10", team) == 1
    assert len(remote.sent) == 1 and remote.sent[0]["platform"] == "qqbot"
    text = remote.sent[0]["text"]
    assert "推送部署完成" in text and "<b>" not in text and "https://github.com/AceDylan/calc/actions/runs/1" in text
    assert remembered == ["deploy:succeeded:1700000000"]
