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
    def start(owner, kind, question, key):
        remote.calls.append((owner, kind, question, key))
        return {"kind": kind, "id": "chat-1"}

    monkeypatch.setattr(remote.link, "remote_start", start)
    result = _dispatch(remote.remote, _event("telegram", TG_USER, "/answer 为什么天是蓝的"))
    assert result == {"action": "skip", "reason": "halo answer command"}
    assert remote.calls == [(OWNER, "answer", "为什么天是蓝的", f"telegram:{TG_USER}:77")]
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
    assert "计划会照常发到 Telegram" in tg["text"] and "只读" in tg["text"]
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
    monkeypatch.setattr(remote.link, "create", lambda owner, goal, origin, auto: created.append((goal, origin, auto))
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
