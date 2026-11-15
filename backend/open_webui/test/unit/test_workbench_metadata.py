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


def test_title_is_visible_before_a_slow_folder_finishes(env, monkeypatch):
    request, user, events, _ = env
    chat = make_chat(user)
    visible = []

    async def folder(*args, **kwargs):
        visible.append((user.id, chat.id, "chat:title", "数据库选型") in events)
        raise TimeoutError("folder timed out")

    monkeypatch.setattr(mode_chats, "auto_folder", folder)
    refresh(request, user, chat)
    assert visible == [True]
    assert chats.Chats.get_chat_title_by_id(chat.id) == "数据库选型"


def test_title_timeout_still_runs_folder_and_fallback_can_be_retried(env, monkeypatch):
    request, user, events, _ = env
    chat = make_chat(user)
    folders = []
    real_wait_for = asyncio.wait_for

    async def bounded(awaitable, timeout):
        return await real_wait_for(awaitable, min(timeout, 0.01))

    async def slow(*args):
        await asyncio.sleep(1)

    async def folder(*args, **kwargs):
        folders.append(kwargs)
        return "folder-1"

    monkeypatch.setattr(asyncio, "wait_for", bounded)
    monkeypatch.setattr(tasks, "generate_title", slow)
    monkeypatch.setattr(mode_chats, "auto_folder", folder)
    refresh(request, user, chat)
    assert len(folders) == 1
    assert chats.Chats.get_chat_title_by_id(chat.id) == "比较数据库"

    async def recovered(*args):
        return {"choices": [{"message": {"content": '{"title":"恢复标题"}'}}]}

    monkeypatch.setattr(tasks, "generate_title", recovered)
    refresh(request, user, chat)
    assert chats.Chats.get_chat_title_by_id(chat.id) == "恢复标题"


def test_dispatched_child_only_gets_a_title_and_keeps_origin(env, monkeypatch):
    request, user, _, _ = env
    chat = make_chat(user)
    chats.Chats.set_chat_meta_value_by_id(chat.id, chats.DISPATCHED_FROM_META_KEY, {"chat_id": "origin"})
    called = []

    async def forbidden(*args, **kwargs):
        called.append(True)

    monkeypatch.setattr(mode_chats, "auto_folder", forbidden)
    title, folder = asyncio.run(mode_chats.auto_title_and_folder(
        request, user, chat, messages=[{"role": "user", "content": "比较数据库"}],
        model_id="gpt-chat", message_id="reply", user_message_count=1, folder=False))
    assert title == "数据库选型" and folder is None and not called
    stored = chats.Chats.get_chat_by_id_and_user_id(chat.id, user.id)
    assert stored.meta[chats.DISPATCHED_FROM_META_KEY] == {"chat_id": "origin"}


def test_real_folder_timeout_keeps_generated_title_and_a_retryable_marker(env, monkeypatch):
    from open_webui.utils import folder_assignment as fa
    request, user, events, _ = env
    request.app.state.config.ENABLE_FOLDER_AUTO_ASSIGNMENT = True
    chat = make_chat(user)
    folder = SimpleNamespace(id="owned-folder", name="编程", parent_id=None, meta={}, created_at=1)

    def deps(call_model):
        return fa.FolderAssignmentDeps(
            call_model=call_model, get_chat=chats.Chats.get_chat_by_id_and_user_id,
            get_folders=lambda uid: [folder], get_folder=lambda fid, uid: folder,
            insert_folder=lambda *args: None, count_folder_chats=lambda *args: 0,
            commit_assignment=chats.Chats.update_chat_folder_assignment_by_id_and_user_id,
            get_user_info=lambda uid: {fa.USER_INFO_KEY: {"presets_initialized_at": 1}},
            patch_user_info=lambda *args: None, timeout=0.01,
        )

    async def slow(*args):
        assert (user.id, chat.id, "chat:title", "数据库选型") in events
        await asyncio.sleep(1)

    monkeypatch.setattr(fa, "build_default_deps", deps)
    monkeypatch.setattr(tasks, "generate_folder_assignment", slow)
    refresh(request, user, chat)
    stored = chats.Chats.get_chat_by_id_and_user_id(chat.id, user.id)
    assert stored.title == "数据库选型" and stored.folder_id is None
    assert stored.meta["folder_assignment"]["last_status"] == "timeout"
    assert stored.meta["folder_assignment"]["successful_evaluations"] == 0
    assert fa.can_auto_assign_folder(None, stored.meta, 2, "next-reply")


def test_manual_rename_while_grouping_is_the_final_announced_title(env, monkeypatch):
    request, user, events, _ = env
    chat = make_chat(user)

    async def folder(*args, **kwargs):
        chats.Chats.update_chat_title_by_id(chat.id, "手动标题", auto_generated=False)
        return chat.folder_id

    monkeypatch.setattr(mode_chats, "auto_folder", folder)
    refresh(request, user, chat)
    assert chats.Chats.get_chat_title_by_id(chat.id) == "手动标题"
    assert events[-1] == (user.id, chat.id, "chat:title", "手动标题")
