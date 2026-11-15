"""「生成 HTML 卡片」 / 「生成配图」 under a reply (utils/message_card.py): nothing makes a card on its
own; asked for, a reply gets one (a runner report's header stays outside it), a mode's reply goes to
its mode, and the page is told where it stands."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from open_webui.utils import message_card, mode_card

USER = SimpleNamespace(id="u1", role="user")
HTML = '<div class="hv" data-theme="ion"><p>卡片</p></div>'
FENCE = f"````html\n{HTML}\n````"


class _FakeChats:
    def __init__(self, messages):
        self.chat = SimpleNamespace(chat={"history": {"messages": messages}})
        self.upserts = []

    def get_chat_by_id_and_user_id(self, chat_id, user_id):
        return self.chat if (chat_id, user_id) == ("c1", "u1") else None

    def upsert_message_to_chat_by_id_and_message_id(self, chat_id, message_id, update, **kwargs):
        self.upserts.append((message_id, update, kwargs))
        message = self.chat.chat["history"]["messages"].setdefault(message_id, {})
        message.update(update)


@pytest.fixture
def env(monkeypatch):
    events = []

    def emitter(user_id, chat_id, message_id):
        async def emit(event):
            events.append((message_id, event))

        return emit

    monkeypatch.setattr(message_card, "_emitter", emitter)

    def use(messages):
        fake = _FakeChats(messages)
        monkeypatch.setattr(message_card, "Chats", fake)
        return fake

    return SimpleNamespace(events=events, use=use)


def _designer(monkeypatch, *, fail=None):
    seen = []

    async def design_merged(text, *, allow_brief=True):
        seen.append(text)
        if fail:
            return text, {"status": "failed", "reason": fail, "startedAt": 1, "endedAt": 2}
        return f"{text}\n\n{FENCE}", {"status": "ready", "html": HTML, "startedAt": 1, "endedAt": 2}

    monkeypatch.setattr(mode_card, "design_merged", design_merged)
    return seen


def _start(message_id="a1"):
    async def run():
        out = await message_card.start_card(None, USER, "c1", message_id)
        await mode_card.settle()
        return out

    return asyncio.run(run())


def test_a_reply_gets_its_card_when_asked_and_the_page_is_told(env, monkeypatch):
    seen = _designer(monkeypatch)
    chats = env.use({"a1": {"role": "assistant", "content": "短回答。", "done": True}})
    assert _start()["status"] == "designing"
    message = chats.chat.chat["history"]["messages"]["a1"]
    assert seen == ["短回答。"]  # however short: the person asked for it
    assert message["content"] == f"短回答。\n\n{FENCE}"
    assert message["htmlCard"]["status"] == "ready" and "html" not in message["htmlCard"]
    # saved without pulling the chat's current message back here, a stop stays a stop
    assert all(kwargs == {"guard_stopped": True, "set_current": False} for _m, _u, kwargs in chats.upserts)
    kinds = [(e["type"], e["data"].get("status")) for _m, e in env.events]
    assert kinds == [(message_card.EVENT, "designing"), (message_card.EVENT, "ready"), ("chat:completion", None)]
    assert env.events[-1][1]["data"] == {"content": message["content"]}


def test_a_runner_reports_header_stays_outside_its_card(env, monkeypatch):
    seen = _designer(monkeypatch)
    report = "✅ agy 运行 r9 · 已完成\nAGY conversation e87 · 1 轮\n\n正文"
    chats = env.use({"a1": {"role": "assistant", "content": report, "done": True}})
    _start()
    assert seen == ["正文"]
    assert chats.chat.chat["history"]["messages"]["a1"]["content"] == (
        f"✅ agy 运行 r9 · 已完成\nAGY conversation e87 · 1 轮\n\n正文\n\n{FENCE}")


def test_a_card_that_fails_leaves_the_reply_and_says_why(env, monkeypatch):
    _designer(monkeypatch, fail="timeout")
    chats = env.use({"a1": {"role": "assistant", "content": "回答", "done": True}})
    _start()
    message = chats.chat.chat["history"]["messages"]["a1"]
    assert message["content"] == "回答"
    assert message["htmlCard"]["status"] == "failed" and message["htmlCard"]["reason"] == "timeout"
    assert env.events[-1][1] == {"type": message_card.EVENT, "data": message["htmlCard"]}


def test_a_reply_changed_meanwhile_gets_no_card_of_its_old_text(env, monkeypatch):
    chats = env.use({"a1": {"role": "assistant", "content": "旧回答", "done": True}})

    async def design_merged(text, *, allow_brief=True):
        chats.chat.chat["history"]["messages"]["a1"]["content"] = "重新生成的回答"
        return f"{text}\n\n{FENCE}", {"status": "ready", "html": HTML}

    monkeypatch.setattr(mode_card, "design_merged", design_merged)
    _start()
    message = chats.chat.chat["history"]["messages"]["a1"]
    assert message["content"] == "重新生成的回答" and message["htmlCard"]["reason"] == "changed"


def test_one_card_at_a_time_and_only_for_a_finished_reply(env, monkeypatch):
    seen = _designer(monkeypatch)
    busy = {"status": "designing", "startedAt": mode_card.now_ms()}
    env.use({
        "a1": {"role": "assistant", "content": "回答", "done": True, "htmlCard": busy},
        "a2": {"role": "assistant", "content": "还在写", "done": False},
        "a3": {"role": "assistant", "content": "", "done": True},
        "u1": {"role": "user", "content": "问题"},
    })
    assert _start("a1")["status"] == "designing" and seen == []
    for message_id, status in (("a2", 409), ("a3", 409), ("u1", 404), ("nope", 404)):
        with pytest.raises(HTTPException) as exc:
            _start(message_id)
        assert exc.value.status_code == status
    with pytest.raises(HTTPException) as gone:
        asyncio.run(message_card.start_card(None, USER, "other-chat", "a1"))
    assert gone.value.status_code == 404
    monkeypatch.setenv(mode_card.AUTO_ENV, "0")
    with pytest.raises(HTTPException) as off:
        _start("a1")
    assert off.value.status_code == 403


def test_a_modes_reply_goes_to_its_mode(env, monkeypatch):
    from open_webui.routers import answers, discussions

    asked = []
    monkeypatch.setattr(answers, "start_card", lambda user, chat_id, message_id: asked.append(("answer", message_id)) or {"status": "designing", "html": "x"})
    monkeypatch.setattr(discussions, "start_card", lambda user, chat_id, message_id: asked.append(("discuss", message_id)) or {"status": "designing"})
    monkeypatch.setattr(answers, "start_picture", lambda request, user, chat_id, message_id: {"illustration": {"status": "generating"}})
    env.use({
        "a1": {"role": "assistant", "content": "精答", "done": True, "answer_desk": {"id": "a1"}},
        "a2": {"role": "assistant", "content": "结论", "done": True, "discussion_room": {"id": "a2"}},
        "a3": {"role": "assistant", "content": "普通回答", "done": True},
    })
    assert _start("a1") == {"status": "designing"}  # the page reads the card's state, not its HTML
    assert _start("a2") == {"status": "designing"}
    assert asked == [("answer", "a1"), ("discuss", "a2")]
    assert asyncio.run(message_card.start_picture(None, USER, "c1", "a1")) == {"status": "generating"}
    with pytest.raises(HTTPException) as plain:
        asyncio.run(message_card.start_picture(None, USER, "c1", "a3"))
    assert plain.value.status_code == 400


def test_a_teams_reply_is_known_by_its_notice():
    messages = {
        "n1": {"role": "user", "hermes_notice": {"run_id": "team:t-42:1700000123"}},
        "a1": {"role": "assistant", "parentId": "n1"},
        "n2": {"role": "user", "hermes_notice": {"run_id": "discuss:c:1"}},
        "a2": {"role": "assistant", "parentId": "n2"},
    }
    assert message_card.team_of(messages, messages["a1"]) == "t-42"
    assert message_card.team_of(messages, messages["a2"]) is None
