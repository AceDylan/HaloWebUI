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


@pytest.fixture
def folder_env(env, monkeypatch):
    from open_webui.utils import folder_assignment as fa
    request, user, events, calls = env
    request.app.state.config.ENABLE_FOLDER_AUTO_ASSIGNMENT = True
    folder = SimpleNamespace(id="owned-folder", name="编程", parent_id=None, meta={}, created_at=1)
    folder_calls = []

    def deps(call_model):
        return fa.FolderAssignmentDeps(
            call_model=call_model, get_chat=chats.Chats.get_chat_by_id_and_user_id,
            get_folders=lambda uid: [folder], get_folder=lambda fid, uid: folder,
            insert_folder=lambda *args: None, count_folder_chats=lambda *args: 0,
            commit_assignment=chats.Chats.update_chat_folder_assignment_by_id_and_user_id,
            get_user_info=lambda uid: {fa.USER_INFO_KEY: {"presets_initialized_at": 1}},
            patch_user_info=lambda *args: None,
        )

    async def generate(request, form, user):
        folder_calls.append(form)
        return {"choices": [{"message": {"content": '{"folder":"编程"}'}}]}

    monkeypatch.setattr(fa, "build_default_deps", deps)
    monkeypatch.setattr(tasks, "generate_folder_assignment", generate)
    return request, user, events, calls, folder_calls


def test_observed_slow_title_and_folder_responses_finish_with_independent_budgets(folder_env, monkeypatch):
    request, user, events, _, _ = folder_env
    chat = make_chat(user)
    real_wait_for = asyncio.wait_for

    async def scaled(awaitable, timeout):
        return await real_wait_for(awaitable, timeout / 1000)

    async def title(*args):
        await asyncio.sleep(0.064)
        return {"choices": [{"message": {"content": '{"title":"慢响应标题"}'}}]}

    async def folder(*args):
        assert (user.id, chat.id, "chat:title", "慢响应标题") in events
        await asyncio.sleep(0.070)
        return {"choices": [{"message": {"content": '{"folder":"编程"}'}}]}

    monkeypatch.setattr(asyncio, "wait_for", scaled)
    monkeypatch.setattr(tasks, "generate_title", title)
    monkeypatch.setattr(tasks, "generate_folder_assignment", folder)
    refresh(request, user, chat)
    stored = chats.Chats.get_chat_by_id_and_user_id(chat.id, user.id)
    assert stored.title == "慢响应标题" and stored.folder_id == "owned-folder"


@pytest.mark.parametrize("kind", ["answer", "discuss"])
@pytest.mark.parametrize("protection", [None, "manual", "branch", "disabled", "other_user"])
def test_completion_recovers_original_metadata_using_its_generated_child_title(
    folder_env, monkeypatch, kind, protection
):
    from open_webui.routers import answers, discussions
    from open_webui.utils import mode_dispatch
    request, user, _, calls, folder_calls = folder_env
    original = make_chat(user)
    chats.Chats.update_chat_title_by_id(original.id, "比较数据库", auto_generated=True,
        last_user_message_count=1, source_message_id="reply", generation_status="fallback")
    chats.Chats.update_chat_folder_assignment_by_id_and_user_id(original.id, user.id, None,
        apply_folder=False, evaluations=1, last_user_message_count=1,
        last_message_id="reply", last_status="timeout")
    child_user = SimpleNamespace(id="another-user") if protection == "other_user" else user
    child = make_chat(child_user)
    chats.Chats.update_chat_title_by_id(child.id, "子任务生成的主题", auto_generated=True,
        last_user_message_count=1, source_message_id="reply")
    chats.Chats.set_chat_meta_value_by_id(child.id, chats.DISPATCHED_FROM_META_KEY, original.id)
    if protection == "manual":
        chats.Chats.update_chat_title_by_id(original.id, "手动标题", auto_generated=False)
        chats.Chats.update_chat_folder_id_by_id_and_user_id(original.id, user.id, None)
    elif protection == "branch":
        data = chats.Chats.get_chat_by_id(original.id).chat
        data["history"]["messages"]["new-reply"] = {"id": "new-reply", "role": "assistant", "parentId": "question"}
        data["history"]["currentId"] = "new-reply"
        chats.Chats.update_chat_by_id(original.id, data, update_title=False)
    elif protection == "disabled":
        request.app.state.config.ENABLE_TITLE_GENERATION = False
        request.app.state.config.ENABLE_FOLDER_AUTO_ASSIGNMENT = False
    forwarded = []
    monkeypatch.setattr(mode_dispatch, "report_back_later", lambda *args: forwarded.append(args))
    run = {"id": "reply", "question": "比较数据库", "origin": {"chatId": original.id, "messageId": "reply"},
           "planner": {"model": "gpt-chat"}, "moderator": {"model": "gpt-chat"},
           "answer": {"content": "比较结论"}, "conclusion": {"content": "比较结论"}}

    async def finish():
        api = answers if kind == "answer" else discussions
        await api._report_done(request, user, child.id, run, "子任务生成的主题")
        await asyncio.gather(*list(mode_chats._metadata_tasks))

    asyncio.run(finish())
    stored = chats.Chats.get_chat_by_id(original.id)
    assert len(forwarded) == 1
    assert not calls  # The generated child title is reused, without another title-model call.
    if protection is None:
        assert stored.title == "子任务生成的主题" and stored.folder_id == "owned-folder"
        assert stored.meta["folder_assignment"]["successful_evaluations"] == 1
        assert len(folder_calls) == 1
    else:
        assert stored.title == ("手动标题" if protection == "manual" else "比较数据库")
        assert stored.folder_id is None and not folder_calls
    assert chats.Chats.get_chat_by_id(child.id).meta[chats.DISPATCHED_FROM_META_KEY] == original.id


def test_completion_waits_for_pending_dispatch_metadata_instead_of_calling_the_model_twice(folder_env, monkeypatch):
    request, user, _, _, _ = folder_env
    chat = make_chat(user)
    calls = []

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def folder(*args):
            calls.append(True)
            started.set()
            await release.wait()
            return {"choices": [{"message": {"content": '{"folder":"编程"}'}}]}

        monkeypatch.setattr(tasks, "generate_folder_assignment", folder)
        kwargs = dict(messages=[{"role": "user", "content": "比较数据库"}],
                      model_id="gpt-chat", message_id="reply")
        mode_chats.schedule_chat_metadata(request, user, chat.id, **kwargs)
        await started.wait()
        mode_chats.schedule_chat_metadata(request, user, chat.id, **kwargs, retry_failed_folder=True)
        release.set()
        await asyncio.gather(*list(mode_chats._metadata_tasks))

    asyncio.run(scenario())
    assert len(calls) == 1
    assert chats.Chats.get_chat_by_id(chat.id).folder_id == "owned-folder"
