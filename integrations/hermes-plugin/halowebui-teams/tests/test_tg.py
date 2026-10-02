"""Telegram link: notices from the bridge loop, /team, buttons and replies (no real Telegram)."""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

TG_USER = "5550001"
OWNER = "u1"


def _kb():
    from hermes_cli import kanban_db

    return kanban_db


@pytest.fixture
def linked(tmp_path, monkeypatch):
    """halo-teams.json linking TG_USER to OWNER, a temp message store, a fake Telegram."""
    import halowebui_teams.link as link
    import halowebui_teams.notify as notify
    import halowebui_teams.tg as telegram

    cfg = tmp_path / "halo-teams.json"
    cfg.write_text(json.dumps({
        "halowebui": {"url": "http://127.0.0.1:9", "public_url": "https://halo.example"},
        "telegram": {"owners": {TG_USER: OWNER}},
    }))
    monkeypatch.setenv("HALO_TEAMS_LINK_FILE", str(cfg))
    monkeypatch.setenv("HALO_TEAMS_TG_STORE", str(tmp_path / "tg.json"))
    link._cache.update(mtime=None, data={})
    sent = []

    def fake_send(chat_id, text, buttons=None, *, thread_id=None):
        sent.append({"chat": str(chat_id), "text": text, "buttons": buttons or []})
        return 1000 + len(sent)

    async def fake_asend(chat_id, text, buttons=None, *, thread_id=None, reply_to=None):
        sent.append({"chat": str(chat_id), "text": text, "buttons": buttons or [], "reply_to": reply_to})
        return 2000 + len(sent)

    monkeypatch.setattr(telegram, "ready", lambda: True)
    monkeypatch.setattr(telegram, "send", fake_send)
    monkeypatch.setattr(telegram, "asend", fake_asend)
    notify._seen.clear()
    return SimpleNamespace(link=link, notify=notify, telegram=telegram, sent=sent, cfg=cfg)


def _create(pkg, team_id, plan_dict, origin=None):
    plan, errors = pkg.plan.validate_plan(plan_dict)
    assert not errors
    return pkg.teams.create_team(team_id, plan, owner=OWNER, goal="做一个小工具", origin=origin)


def _tick(pkg, team_id, linked):
    slug = pkg.common.board_slug(team_id)
    linked.notify.tick_board(slug, pkg.common.read_team(slug))


def _buttons(message):
    return [spec for row in message["buttons"] for _label, spec in row]


def test_first_look_records_without_sending_then_new_failure_notifies_once(pkg, team_id, plan_dict, linked):
    first = _create(pkg, team_id, plan_dict, origin={"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})
    _tick(pkg, team_id, linked)
    assert linked.sent == []
    slug = pkg.common.board_slug(team_id)
    t2 = first["tasks"]["T2"]
    with pkg.common.board_conn(slug) as conn:
        _kb().claim_task(conn, t2, claimer="w")
        _kb().block_task(conn, t2, reason="编译失败：缺少 <依赖>")
    _tick(pkg, team_id, linked)
    _tick(pkg, team_id, linked)
    assert len(linked.sent) == 1
    msg = linked.sent[0]
    assert msg["chat"] == TG_USER
    assert "frontend-dev" in msg["text"] and "&lt;依赖&gt;" in msg["text"]  # escaped for HTML
    assert f"cb:rt:{team_id}:{t2}" in _buttons(msg)
    assert any(b.startswith("url:https://halo.example/teams/") for b in _buttons(msg))
    entry = linked.telegram.lookup(TG_USER, 1001)
    assert entry["kind"] == "fail" and entry["task"] == t2 and entry["team"] == team_id


def test_open_page_suppresses_the_notice_and_counts_it_as_given(pkg, team_id, plan_dict, linked):
    first = _create(pkg, team_id, plan_dict, origin={"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})
    _tick(pkg, team_id, linked)
    slug = pkg.common.board_slug(team_id)
    with pkg.common.board_conn(slug) as conn:
        _kb().claim_task(conn, first["tasks"]["T1"], claimer="w")
        _kb().block_task(conn, first["tasks"]["T1"], reason="需要账号")
    linked.notify.mark_seen(team_id)
    _tick(pkg, team_id, linked)
    linked.notify._seen.clear()
    _tick(pkg, team_id, linked)
    assert linked.sent == []


def test_web_team_goes_to_the_owners_chat_unless_turned_off(pkg, team_id, plan_dict, linked):
    import uuid

    assert linked.notify.target_for({"owner": OWNER}) == {"chat_id": TG_USER}
    assert linked.notify.target_for({"owner": "someone-else"}) is None
    linked.cfg.write_text(json.dumps({"telegram": {"owners": {TG_USER: OWNER}, "notify_web_teams": False}}))
    os.utime(linked.cfg, (1, 1))  # a different mtime: the settings are read again
    assert linked.notify.target_for({"owner": OWNER}) is None
    origin = {"platform": "telegram", "chat_id": "-100", "thread_id": "7", "user_id": TG_USER}
    assert linked.notify.target_for({"origin": origin, "owner": OWNER}) == {"chat_id": "-100", "thread_id": "7"}
    # a chat started by someone not linked to this owner never gets the owner's notices
    assert linked.notify.target_for({"origin": {**origin, "user_id": "999"}, "owner": OWNER}) is None


def test_done_notice_carries_the_conclusion(pkg, team_id, plan_dict, linked):
    first = _create(pkg, team_id, plan_dict)  # started in the browser → owner's chat
    _tick(pkg, team_id, linked)
    slug = pkg.common.board_slug(team_id)
    kb = _kb()
    with pkg.common.board_conn(slug) as conn:
        for key in ("T1", "T2"):
            kb.claim_task(conn, first["tasks"][key], claimer="w")
            kb.complete_task(conn, first["tasks"][key], result="ok", summary="ok")
        kb.recompute_ready(conn)
        kb.claim_task(conn, first["tasks"]["T3"], claimer="w")
        kb.complete_task(conn, first["tasks"]["T3"], result="评审通过", summary="评审通过")
    _tick(pkg, team_id, linked)  # completes; the conclusion is written synchronously in tests
    _tick(pkg, team_id, linked)
    done = [m for m in linked.sent if m["text"].startswith("✅")]
    assert len(done) == 1
    assert "3/3 个任务" in done[0]["text"]
    assert any(b.endswith(f"/teams/{team_id}/conclusion") for b in _buttons(done[0]))


def test_plan_card_lists_members_tasks_and_buttons(linked):
    team = {"id": "11111111-2222-3333-4444-555555555555", "title": "研究 <雨>", "plan": {
        "summary": "两人并行", "max_parallel": 2,
        "members": [{"name": "researcher", "role": "研究员", "executor": "hermes", "runner": "hermes"},
                    {"name": "dev", "role": "开发", "executor": "agy", "runner": "codex", "runner_note": "agy 不可用"}],
        "tasks": [{"key": "T1", "title": "查资料", "member": "researcher", "depends_on": []},
                  {"key": "T2", "title": "画图", "member": "dev", "depends_on": ["T1"]}],
        "lead_model": {"model": "gpt-chat"}}}
    text, buttons = linked.notify.plan_message(team)
    assert "研究 &lt;雨&gt;" in text and "codex（agy 不可用）" in text and "2. 画图 — dev（等 1）" in text
    specs = [spec for row in buttons for _l, spec in row]
    assert f"cb:ap:{team['id']}" in specs and f"cb:cx:{team['id']}" in specs
    assert "gpt-chat" in text


def test_plan_notice_only_for_telegram_teams(linked):
    team = {"id": "11111111-2222-3333-4444-555555555555", "title": "x", "plan": {"members": [], "tasks": []}}
    assert linked.notify.plan_notice(OWNER, "plan_ready", team, {})["sent"] is False
    tg = {"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER}
    assert linked.notify.plan_notice("u-other", "plan_ready", team, tg)["sent"] is False
    out = linked.notify.plan_notice(OWNER, "plan_ready", team, tg)
    assert out["sent"] is True
    assert linked.telegram.latest_open_plan(TG_USER)[1]["team"] == team["id"]
    linked.telegram.mark_acted(TG_USER, out["message_id"], "approve")
    assert linked.telegram.latest_open_plan(TG_USER) is None


def test_markdown_to_plain_text(linked):
    md = "# 结论\n\n**要点**：`a` 和 [链接](http://x)\n\n| 列 | 值 |\n|---|---|\n| a | 1 |\n- 一\n- 二"
    out = linked.notify.plain(md)
    assert "#" not in out and "**" not in out and "`" not in out and "http" not in out
    assert "a · 1" in out and "• 一" in out


# --- incoming ------------------------------------------------------------------------------------

def _event(text, user=TG_USER, reply_to=None, platform="telegram"):
    from gateway.platforms.event import MessageEvent
    from gateway.session import Platform, SessionSource

    source = SessionSource(platform=Platform(platform), chat_id=user, user_id=user, user_name="Ace")
    return MessageEvent(text=text, source=source, user_id=user, message_id="77", reply_to_message_id=reply_to)


def _run(coro_fn):
    async def main():
        result = coro_fn()
        await asyncio.sleep(0)
        for task in list(__import__("halowebui_teams.tg", fromlist=["_tasks"])._tasks):
            await task
        return result

    return asyncio.run(main())


def test_team_command_starts_a_team_with_its_origin(linked, monkeypatch):
    calls = []
    monkeypatch.setattr(linked.link, "create", lambda owner, goal, origin: calls.append((owner, goal, origin)) or
                        {"id": "11111111-2222-3333-4444-555555555555", "title": goal})
    result = _run(lambda: linked.telegram.on_pre_gateway_dispatch(event=_event("/team 研究下雨天山上的云")))
    assert result == {"action": "skip", "reason": "halo team command"}
    assert calls == [(OWNER, "研究下雨天山上的云", {"platform": "telegram", "chat_id": TG_USER, "user_id": TG_USER})]
    assert "负责人做计划" in linked.sent[-1]["text"] and linked.sent[-1]["reply_to"] == "77"


def test_strangers_and_other_platforms_pass_through(linked):
    assert linked.telegram.on_pre_gateway_dispatch(event=_event("/team x", user="999")) is None
    assert linked.telegram.on_pre_gateway_dispatch(event=_event("/team x", platform="discord")) is None
    assert linked.telegram.on_pre_gateway_dispatch(event=_event("你好")) is None
    assert linked.sent == []


def test_reply_to_plan_replans_and_plain_approve_approves(linked, monkeypatch):
    team_id = "11111111-2222-3333-4444-555555555555"
    linked.telegram.remember_message(TG_USER, 501, {"team": team_id, "kind": "plan", "owner": OWNER})
    calls = []
    monkeypatch.setattr(linked.link, "replan", lambda o, t, f: calls.append(("replan", t, f)) or {})
    monkeypatch.setattr(linked.link, "approve", lambda o, t: calls.append(("approve", t)) or {"id": t, "title": "x"})
    assert _run(lambda: linked.telegram.on_pre_gateway_dispatch(event=_event("加一个评审", reply_to="501")))
    assert calls == [("replan", team_id, "加一个评审")]
    assert linked.telegram.latest_open_plan(TG_USER) is None  # the card was answered
    linked.telegram.remember_message(TG_USER, 502, {"team": team_id, "kind": "plan", "owner": OWNER})
    assert _run(lambda: linked.telegram.on_pre_gateway_dispatch(event=_event("批准")))
    assert calls[-1] == ("approve", team_id)
    assert linked.telegram.on_pre_gateway_dispatch(event=_event("批准")) is None  # nothing open any more


def test_reply_to_question_answers_the_member(linked, monkeypatch):
    import halowebui_teams.teams as teams

    posted = []
    monkeypatch.setattr(teams, "post_message", lambda *a, **k: posted.append((a, k)) or {})
    linked.telegram.remember_message(TG_USER, 601, {"team": "t-1", "kind": "ask", "task": "t_abc", "owner": OWNER,
                                                    "member": "writer"})
    assert _run(lambda: linked.telegram.on_pre_gateway_dispatch(event=_event("用 A 方案", reply_to="601")))
    assert posted == [(("t-1", "t_abc", "用 A 方案"), {"author_name": "Ace", "owner": OWNER})]
    assert "writer" in linked.sent[-1]["text"]


def test_buttons_approve_and_retry(linked, monkeypatch):
    import halowebui_teams.teams as teams

    calls = []
    monkeypatch.setattr(linked.link, "approve", lambda o, t: calls.append(("approve", o, t)) or {})
    monkeypatch.setattr(teams, "retry", lambda t, k, **kw: calls.append(("retry", t, k, kw["owner"])) or {})
    answers, edits = [], []

    class Query:
        def __init__(self, data, user):
            self.data = data
            self.from_user = SimpleNamespace(id=int(user), first_name="Ace")
            self.message = SimpleNamespace(chat_id=int(TG_USER), message_id=9, text_html="卡片", reply_markup=None)

        async def answer(self, text="", show_alert=False):
            answers.append(text)

        async def edit_message_text(self, **kw):
            edits.append(kw["text"])

    asyncio.run(linked.telegram._handle_callback(Query("ht:ap:team-1", TG_USER)))
    asyncio.run(linked.telegram._handle_callback(Query("ht:rt:team-1:t_9", TG_USER)))
    asyncio.run(linked.telegram._handle_callback(Query("ht:ap:team-1", "999")))
    assert calls == [("approve", OWNER, "team-1"), ("retry", "team-1", "t_9", OWNER)]
    assert answers[-1].startswith("只有") and edits[0].endswith("<b>✅ 已批准，成员开始干活了</b>")


# --- HaloWebUI client ----------------------------------------------------------------------------

def test_halowebui_client_sends_key_and_owner_and_reads_errors(linked, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen.append((self.path, self.headers.get("X-Hermes-Key"), self.headers.get("X-Halo-Owner"),
                         json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            if self.path.endswith("/approve"):
                body, code = {"detail": "这个计划已经批准过或状态已变化"}, 409
            else:
                body, code = {"id": "abc", "status": "planning"}, 200
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        linked.cfg.write_text(json.dumps({"halowebui": {"url": f"http://127.0.0.1:{server.server_port}"},
                                          "telegram": {"owners": {TG_USER: OWNER}}}))
        os.utime(linked.cfg, (2, 2))
        monkeypatch.setenv("API_SERVER_KEY", "k-test")
        assert linked.link.create(OWNER, "目标", {"platform": "telegram"})["status"] == "planning"
        with pytest.raises(linked.link.HaloError) as err:
            linked.link.approve(OWNER, "abc")
        assert err.value.status == 409 and "已经批准过" in err.value.message
    finally:
        server.shutdown()
    assert seen[0][:3] == ("/api/v1/teams/hermes/teams", "k-test", OWNER)
    assert seen[0][3] == {"goal": "目标", "origin": {"platform": "telegram"}}
