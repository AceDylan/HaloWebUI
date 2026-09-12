"""End-to-end ordering of the background task step and the HTTP glue.

These import the FastAPI routers and the chat middleware, so they need the
same environment as the other middleware tests (a writable DATA_DIR and a
vector DB setting whose client is importable), e.g.::

    VECTOR_DB=milvus DATA_DIR=/tmp/halo-test-data \\
    DATABASE_URL=sqlite:////tmp/halo-test-data/webui.db \\
    python3 -m pytest open_webui/test/unit/test_folder_auto_assignment_pipeline.py
"""

import asyncio
import pathlib
import sys
from types import SimpleNamespace

from fastapi.responses import JSONResponse


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.constants import TASKS  # noqa: E402
from open_webui.models import chats as chats_mod  # noqa: E402
from open_webui.routers import chats as chats_router  # noqa: E402
from open_webui.routers import tasks as tasks_router  # noqa: E402
from open_webui.utils import folder_assignment as fa  # noqa: E402
from open_webui.utils import middleware  # noqa: E402


####################
# Manual move endpoint -> manual marker
####################


def test_manual_folder_endpoint_marks_the_chat_manual(monkeypatch):
    calls = []
    existing = SimpleNamespace(id="chat-1", user_id="user-1", folder_id=None)
    monkeypatch.setattr(chats_router.Chats, "get_chat_by_id_and_user_id", lambda _c, _u: existing)
    monkeypatch.setattr(chats_router.Chats, "get_chats_by_folder_id_and_user_id", lambda *_a, **_k: [])

    def fake_update(chat_id, user_id, folder_id):
        calls.append((chat_id, user_id, folder_id))
        return None

    monkeypatch.setattr(chats_router.Chats, "update_chat_folder_id_by_id_and_user_id", fake_update)
    user = SimpleNamespace(id="user-1")

    asyncio.run(chats_router.update_chat_folder_id_by_id("chat-1", chats_router.ChatFolderIdForm(folder_id="f-1"), user))
    asyncio.run(chats_router.update_chat_folder_id_by_id("chat-1", chats_router.ChatFolderIdForm(folder_id=None), user))

    assert calls == [("chat-1", "user-1", "f-1"), ("chat-1", "user-1", None)]

    # And the model method those calls land on writes the manual marker.
    row = SimpleNamespace(
        id="chat-1", user_id="user-1", title="t", chat={"title": "t", "history": {"messages": {}}},
        created_at=1, updated_at=1, share_id=None, archived=False, pinned=True, meta={"x": 1},
        folder_id=None, assistant_id=None,
    )

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, _m, _i):
            return row

        def commit(self):
            return None

        def refresh(self, _r):
            return None

    table = chats_mod.ChatTable()
    monkeypatch.setattr(chats_mod, "get_db", lambda: FakeDb())
    monkeypatch.setattr(chats_mod, "flag_modified", lambda *_a, **_k: None)
    monkeypatch.setattr(table, "_next_user_chat_timestamp", lambda _db, _u: 2)
    table.update_chat_folder_id_by_id_and_user_id("chat-1", "user-1", "f-1")
    assert row.meta == {"x": 1, "folder_assignment": {"source": "manual", "folder_id": "f-1", "updated_at": row.meta["folder_assignment"]["updated_at"]}}


####################
# Task endpoint: same model resolution as the title
####################


def _task_request(*, external="task-model", template=""):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TASK_MODEL="",
                    TASK_MODEL_EXTERNAL=external,
                    FOLDER_AUTO_ASSIGNMENT_PROMPT_TEMPLATE=template,
                )
            )
        ),
        state=SimpleNamespace(MODELS={}, MODELS_AMBIGUOUS=set()),
    )


_MODELS = {
    "gpt-image-2": {"id": "gpt-image-2", "name": "gpt-image-2", "owned_by": "openai", "info": {"base_model_id": ""}},
    "task-model": {"id": "task-model", "name": "task model", "owned_by": "openai", "info": {"base_model_id": ""}},
}


def test_folder_task_endpoint_uses_external_task_model_and_default_prompt(monkeypatch):
    captured = []

    async def fake_models(_request, _user):
        return _MODELS

    async def fake_completion(_request, form_data, user):
        captured.append(form_data)
        return {"choices": [{"message": {"content": '{"folder": "图片生成"}'}}]}

    monkeypatch.setattr(tasks_router, "_get_request_models", fake_models)
    monkeypatch.setattr(tasks_router, "generate_chat_completion", fake_completion)
    user = SimpleNamespace(id="user-1", email="u@example.com", name="U", info=None)

    res = asyncio.run(
        tasks_router.generate_folder_assignment(
            _task_request(),
            {
                "model": "gpt-image-2",
                "chat_id": "chat-1",
                "title": "橘猫写真",
                "messages": [{"role": "user", "content": "生成一张橘猫写真"}],
                "folders": [
                    {"name": "图片生成", "description": "出图、写真"},
                    {"name": "生活与闲聊", "description": ""},
                    "garbage",
                ],
                "require_external_task_model": True,
            },
            user,
        )
    )

    assert res["choices"][0]["message"]["content"] == '{"folder": "图片生成"}'
    payload = captured[0]
    assert payload["model"] == "task-model"
    assert payload["stream"] is False and payload["max_completion_tokens"] == 1000
    assert payload["metadata"]["task"] == str(TASKS.FOLDER_ASSIGNMENT)
    assert payload["metadata"]["chat_id"] == "chat-1"
    content = payload["messages"][0]["content"]
    assert "- 图片生成: 出图、写真" in content
    assert "- 生活与闲聊" in content
    assert "橘猫写真" in content
    assert "USER: 生成一张橘猫写真" in content
    assert '{ "folder": null }' in content


def test_folder_task_endpoint_refuses_image_sessions_without_external_task_model(monkeypatch):
    async def fake_models(_request, _user):
        return _MODELS

    async def fail(*_a, **_k):
        raise AssertionError("must not call the model")

    monkeypatch.setattr(tasks_router, "_get_request_models", fake_models)
    monkeypatch.setattr(tasks_router, "generate_chat_completion", fail)
    user = SimpleNamespace(id="user-1", email="u@example.com", name="U", info=None)

    res = asyncio.run(
        tasks_router.generate_folder_assignment(
            _task_request(external=""),
            {"model": "gpt-image-2", "messages": [], "folders": [], "require_external_task_model": True},
            user,
        )
    )

    assert isinstance(res, JSONResponse) and res.status_code == 400
    assert fa.parse_completion_text(res) == ""


def test_task_config_exposes_folder_assignment_fields():
    assert "ENABLE_FOLDER_AUTO_ASSIGNMENT" in tasks_router.TASK_CONFIG_FIELDS
    assert "FOLDER_AUTO_ASSIGNMENT_PROMPT_TEMPLATE" in tasks_router.TASK_CONFIG_FIELDS
    form = tasks_router.TaskConfigForm(ENABLE_FOLDER_AUTO_ASSIGNMENT=False)
    assert form.model_dump(exclude_unset=True) == {"ENABLE_FOLDER_AUTO_ASSIGNMENT": False}


####################
# background_tasks_handler ordering
####################


def _messages():
    return {
        "user-1": {"id": "user-1", "role": "user", "content": "hermes gateway 起不来", "parentId": None},
        "assistant-1": {"id": "assistant-1", "role": "assistant", "content": "看日志", "parentId": "user-1", "model": "gpt-5"},
    }


def _request(enabled=True):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(ENABLE_FOLDER_AUTO_ASSIGNMENT=enabled),
            )
        )
    )


def _wire(monkeypatch, *, title_meta, current_title, title_answer, folder_result, folder_error=None):
    """Patch the handler's collaborators and record the order of DB writes,
    the folder step and emitted events."""
    order = []
    events = []
    folder_calls = []

    async def emitter(event):
        order.append(("emit", event["type"]))
        events.append(event)

    async def fake_generate_title(_request, _form, _user):
        return {"choices": [{"message": {"content": '{"title": "%s"}' % title_answer}}]}

    def fake_update_title(_chat_id, title, **_kwargs):
        order.append(("title_write", title))
        return SimpleNamespace(title=title)

    async def fake_assign(**kwargs):
        folder_calls.append(kwargs)
        order.append(("folder_step", kwargs["title"]))
        if folder_error is not None:
            raise folder_error
        return folder_result

    async def fake_generate_folder_assignment(_request, payload, _user):
        return {"choices": [{"message": {"content": '{"folder": null}'}}]}

    monkeypatch.setattr(middleware, "generate_title", fake_generate_title)
    monkeypatch.setattr(middleware, "generate_folder_assignment", fake_generate_folder_assignment)
    monkeypatch.setattr(middleware, "assign_chat_folder", fake_assign)
    monkeypatch.setattr(middleware.Chats, "get_messages_by_chat_id", lambda _c: _messages())
    monkeypatch.setattr(middleware.Chats, "get_chat_title_by_id", lambda _c: current_title)
    monkeypatch.setattr(middleware.Chats, "get_chat_title_generation_metadata_by_id", lambda _c: title_meta)
    monkeypatch.setattr(middleware.Chats, "update_chat_title_by_id", fake_update_title)
    return order, events, folder_calls, emitter


def _run_handler(emitter, *, tasks, enabled=True, metadata_extra=None):
    user = SimpleNamespace(id="user-1", email="u@example.com", name="U", role="user")
    metadata = {"chat_id": "chat-1", "message_id": "assistant-1", "session_id": "s", **(metadata_extra or {})}
    asyncio.run(middleware.background_tasks_handler(_request(enabled), user, metadata, tasks, emitter))


def test_title_is_persisted_then_folder_then_single_refresh_event(monkeypatch):
    order, events, folder_calls, emitter = _wire(
        monkeypatch,
        title_meta={},
        current_title="New Chat",
        title_answer="Hermes 网关故障",
        folder_result=fa.FolderAssignmentResult("assigned", changed=True, folder_name="服务器与 Hermes 运维", evaluations=1),
    )

    _run_handler(emitter, tasks={TASKS.TITLE_GENERATION: True})

    assert order == [
        ("title_write", "Hermes 网关故障"),
        ("folder_step", "Hermes 网关故障"),
        ("emit", "chat:title"),
    ]
    assert events == [{"type": "chat:title", "data": "Hermes 网关故障"}]
    call = folder_calls[0]
    assert call["chat_id"] == "chat-1" and call["user_id"] == "user-1"
    assert call["model_id"] == "gpt-5" and call["user_message_count"] == 1
    assert call["message_id"] == "assistant-1"
    assert call["require_external_task_model"] is False
    assert isinstance(call["deps"], fa.FolderAssignmentDeps)


def test_manual_title_does_not_block_folder_assignment_and_still_refreshes(monkeypatch):
    order, events, folder_calls, emitter = _wire(
        monkeypatch,
        title_meta={"auto_generated": False},
        current_title="我自己改的标题",
        title_answer="should not be used",
        folder_result=fa.FolderAssignmentResult("assigned", changed=True, folder_name="图片生成", evaluations=1),
    )

    _run_handler(emitter, tasks={TASKS.TITLE_GENERATION: True})

    assert order == [("folder_step", "我自己改的标题"), ("emit", "chat:title")]
    assert events == [{"type": "chat:title", "data": "我自己改的标题"}]


def test_no_title_change_and_no_folder_change_emits_nothing(monkeypatch):
    order, events, _calls, emitter = _wire(
        monkeypatch,
        title_meta={"auto_generated": False},
        current_title="我自己改的标题",
        title_answer="x",
        folder_result=fa.FolderAssignmentResult("no_match", changed=False, evaluations=1),
    )

    _run_handler(emitter, tasks={TASKS.TITLE_GENERATION: True})

    assert order == [("folder_step", "我自己改的标题")]
    assert events == []


def test_folder_step_failure_never_blocks_the_title_event(monkeypatch):
    order, events, _calls, emitter = _wire(
        monkeypatch,
        title_meta={},
        current_title="New Chat",
        title_answer="新标题",
        folder_result=None,
        folder_error=RuntimeError("boom"),
    )

    _run_handler(emitter, tasks={TASKS.TITLE_GENERATION: True})

    assert order == [("title_write", "新标题"), ("folder_step", "新标题"), ("emit", "chat:title")]
    assert events == [{"type": "chat:title", "data": "新标题"}]


def test_folder_step_is_skipped_when_disabled_or_off_cadence(monkeypatch):
    order, events, folder_calls, emitter = _wire(
        monkeypatch,
        title_meta={},
        current_title="New Chat",
        title_answer="新标题",
        folder_result=fa.FolderAssignmentResult("assigned", changed=True, evaluations=1),
    )

    _run_handler(emitter, tasks={TASKS.TITLE_GENERATION: True}, enabled=False)
    assert folder_calls == []
    assert order == [("title_write", "新标题"), ("emit", "chat:title")]

    order.clear()
    events.clear()
    _run_handler(emitter, tasks={TASKS.FOLLOW_UP_GENERATION: False})
    assert folder_calls == [] and order == [] and events == []


def test_image_sessions_run_folder_step_with_external_flag_before_returning(monkeypatch):
    order, events, folder_calls, emitter = _wire(
        monkeypatch,
        title_meta={},
        current_title="New Chat",
        title_answer="橘猫写真",
        folder_result=fa.FolderAssignmentResult("assigned", changed=True, folder_name="图片生成", evaluations=1),
    )

    _run_handler(
        emitter,
        tasks={TASKS.TITLE_GENERATION: True, TASKS.TAGS_GENERATION: True},
        metadata_extra={"skip_text_enhancements": True},
    )

    assert folder_calls[0]["require_external_task_model"] is True
    assert order == [("title_write", "橘猫写真"), ("folder_step", "橘猫写真"), ("emit", "chat:title")]
    assert [event["type"] for event in events] == ["chat:title"]
