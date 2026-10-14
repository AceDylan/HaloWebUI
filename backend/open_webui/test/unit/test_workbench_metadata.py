"""Shared title settings apply to workbench dispatches without changing manual titles."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import chats
from open_webui.routers import tasks
from open_webui.utils import mode_chats, team_chats


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats.Chat.__table__.create(engine)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def db():
        with sessions() as session:
            yield session

    monkeypatch.setattr(chats, "get_db", db)
    events, calls = [], []

    async def generate(request, form, user):
        calls.append(form)
        return {"choices": [{"message": {"content": '{"title":"数据库选型"}'}}]}

    async def emit(*args):
        events.append(args)

    monkeypatch.setattr(tasks, "generate_title", generate)
    monkeypatch.setattr(team_chats, "emit_chat_event", emit)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(
        ENABLE_TITLE_GENERATION=True, ENABLE_FOLDER_AUTO_ASSIGNMENT=False))))
    yield request, SimpleNamespace(id="metadata-user"), events, calls
    engine.dispose()


def make_chat(user, title="New Chat", automatic=True):
    return chats.Chats.insert_new_chat(user.id, chats.ChatForm(chat={
        "title": title, "models": ["gpt-chat"],
        "history": {"currentId": "reply", "messages": {
            "question": {"id": "question", "role": "user", "content": "比较数据库", "parentId": None},
            "reply": {"id": "reply", "role": "assistant", "content": "正在处理", "parentId": "question"},
        }},
    }, title_auto_generated=automatic))


def refresh(request, user, chat):
    async def run():
        mode_chats.schedule_chat_metadata(request, user, chat.id,
            messages=[{"role": "user", "content": "比较数据库"}],
            model_id="gpt-chat", message_id="reply")
        await asyncio.gather(*list(mode_chats._metadata_tasks))
    asyncio.run(run())


def test_dispatch_uses_shared_title_generation_and_emits_sidebar_refresh(env):
    request, user, events, calls = env
    chat = make_chat(user)
    refresh(request, user, chat)
    assert chats.Chats.get_chat_title_by_id(chat.id) == "数据库选型"
    assert calls[0]["model"] == "gpt-chat"
    assert events[-1] == (user.id, chat.id, "chat:title", "数据库选型")


def test_dispatch_preserves_manual_title_and_disabled_generation_has_a_fallback(env):
    request, user, events, calls = env
    chat = make_chat(user, "我的项目", False)
    refresh(request, user, chat)
    assert not calls
    assert chats.Chats.get_chat_title_by_id(chat.id) == "我的项目"
    request.app.state.config.ENABLE_TITLE_GENERATION = False
    blank = make_chat(user)
    refresh(request, user, blank)
    assert not calls
    assert chats.Chats.get_chat_title_by_id(blank.id) == "比较数据库"


def test_late_generated_title_does_not_overwrite_manual_rename(env, monkeypatch):
    request, user, _, _ = env
    chat = make_chat(user)

    async def rename_while_generating(*args):
        chats.Chats.update_chat_title_by_id(chat.id, "手动命名", auto_generated=False)
        return {"choices": [{"message": {"content": '{"title":"过期标题"}'}}]}

    monkeypatch.setattr(tasks, "generate_title", rename_while_generating)
    refresh(request, user, chat)
    assert chats.Chats.get_chat_title_by_id(chat.id) == "手动命名"


@pytest.mark.parametrize("title", ["新对话", "新聊天", "New Chat"])
def test_localized_legacy_defaults_are_named_but_explicit_manual_defaults_are_protected(env, title):
    request, user, _, calls = env
    chat = make_chat(user, title, None)
    refresh(request, user, chat)
    assert chats.Chats.get_chat_title_by_id(chat.id) == "数据库选型"
    manual = make_chat(user, title, False)
    refresh(request, user, manual)
    assert chats.Chats.get_chat_title_by_id(manual.id) == title
    assert len(calls) == 1
