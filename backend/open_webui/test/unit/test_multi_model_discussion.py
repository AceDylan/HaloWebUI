import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import multi_model_discussion as discussion_mod  # noqa: E402


def _request(models):
    return SimpleNamespace(
        state=SimpleNamespace(MODELS=models, MODELS_AMBIGUOUS=set()),
        app=SimpleNamespace(state=SimpleNamespace(MODELS=models)),
    )


def _user(role="admin"):
    return SimpleNamespace(id="user-1", role=role)


def _models(*ids):
    return {model_id: {"id": model_id, "name": model_id} for model_id in ids}


def test_normalize_discussion_config_checks_access_and_clamps_rounds(monkeypatch):
    access_checks = []
    monkeypatch.setattr(discussion_mod, "BYPASS_MODEL_ACCESS_CONTROL", False)
    monkeypatch.setattr(
        discussion_mod,
        "check_model_access",
        lambda user, model: access_checks.append((user.id, model["id"])),
    )

    config = discussion_mod.normalize_discussion_config(
        {
            "participants": ["model-a", "model-b", "model-a"],
            "rounds": 99,
            "finalModel": "model-c",
        },
        _models("model-a", "model-b", "model-c"),
        set(),
        "model-c",
        _user("user"),
    )

    assert [item["request_id"] for item in config["participants"]] == [
        "model-a",
        "model-b",
    ]
    assert config["rounds"] == discussion_mod.MAX_DISCUSSION_ROUNDS
    assert access_checks == [
        ("user-1", "model-a"),
        ("user-1", "model-b"),
        ("user-1", "model-c"),
    ]


def test_normalize_discussion_config_rejects_too_many_models():
    with pytest.raises(HTTPException) as exc_info:
        discussion_mod.normalize_discussion_config(
            {"participants": ["a", "b", "c", "d", "e", "f"], "finalModel": "a"},
            _models("a", "b", "c", "d", "e", "f"),
            set(),
            "a",
            _user(),
        )

    assert exc_info.value.status_code == 400
    assert "at most" in exc_info.value.detail


def test_multi_model_discussion_orchestrates_models_and_events(monkeypatch):
    events = []
    upserts = []
    calls = []
    scheduled = {}
    search_sources = [
        {
            "source": {"name": "Grok 搜索摘要"},
            "document": ["联网搜索阶段已经得到的摘要内容。"],
            "metadata": [{"source": "grok://search/abc", "content": "摘要内容"}],
        }
    ]

    async def event_emitter(event):
        events.append(event)

    async def fake_generate_chat_completion(_request, payload, _user):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": f"answer from {payload['model']}",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )

    async def run():
        result = await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
            [{"sources": search_sources}],
        )
        await scheduled["task"]
        return result

    result = asyncio.run(run())

    assert result == {"status": True, "task_id": "task-1"}
    assert scheduled["chat_id"] == "chat-1"
    assert [payload["model"] for payload in calls] == [
        "model-a",
        "model-b",
        "model-final",
    ]
    assert all(payload["stream"] is False for payload in calls)
    assert all("discussion" not in payload for payload in calls)

    discussion_events = [event for event in events if event["type"] == "discussion"]
    event_types = [event["data"]["type"] for event in discussion_events]
    assert "turn_done" in event_types
    assert "final_start" in event_types
    assert "done" in event_types

    final_start = next(
        event for event in discussion_events if event["data"]["type"] == "final_start"
    )
    assert final_start["data"]["state"]["status"] == "summarizing"

    turn_done = next(
        event for event in discussion_events if event["data"]["type"] == "turn_done"
    )
    assert turn_done["data"]["usage"]["total_tokens"] == 15
    assert (
        turn_done["data"]["state"]["rounds"][0]["turns"][0]["usage"]["total_tokens"]
        == 15
    )

    completion = next(event for event in events if event["type"] == "chat:completion")
    assert completion["data"]["content"] == "answer from model-final"
    assert completion["data"]["discussion"]["status"] == "completed"
    assert completion["data"]["usage"]["prompt_tokens"] == 30
    assert completion["data"]["usage"]["completion_tokens"] == 15
    assert completion["data"]["usage"]["total_tokens"] == 45
    assert len(completion["data"]["usage"]["per_model"]) == 3
    assert completion["data"]["sources"] == search_sources

    final_upsert = upserts[-1][0][2]
    assert final_upsert["content"] == "answer from model-final"
    assert final_upsert["usage"]["total_tokens"] == 45
    assert final_upsert["discussion"]["status"] == "completed"
    assert final_upsert["sources"] == search_sources


def test_multi_model_discussion_passes_transcript_to_later_rounds_and_final(
    monkeypatch,
):
    calls = []
    scheduled = {}

    async def event_emitter(_event):
        return None

    async def fake_generate_chat_completion(_request, payload, _user):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": f"{payload['model']} says #{len(calls)}",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: None,
    )

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 2,
                "finalModel": "model-final",
            },
        )
        await scheduled["task"]

    asyncio.run(run())

    assert [payload["model"] for payload in calls] == [
        "model-a",
        "model-b",
        "model-a",
        "model-b",
        "model-final",
    ]

    first_round_prompt = calls[0]["messages"][-1]["content"]
    assert "Give your independent answer" in first_round_prompt

    second_round_first_prompt = calls[2]["messages"][-1]["content"]
    assert "Previous discussion:" in second_round_first_prompt
    assert "model-a says #1" in second_round_first_prompt
    assert "model-b says #2" in second_round_first_prompt

    second_round_second_prompt = calls[3]["messages"][-1]["content"]
    assert "model-a says #3" in second_round_second_prompt

    final_prompt = calls[-1]["messages"][-1]["content"]
    assert "Discussion transcript:" in final_prompt
    assert "model-a says #1" in final_prompt
    assert "model-b says #2" in final_prompt
    assert "model-a says #3" in final_prompt
    assert "model-b says #4" in final_prompt


def test_multi_model_discussion_isolates_failed_turns_from_transcript(monkeypatch):
    events = []
    calls = []
    upserts = []
    scheduled = {}

    async def event_emitter(event):
        events.append(event)

    async def fake_generate_chat_completion(_request, payload, _user):
        calls.append(payload)
        call_number = len(calls)
        if payload["model"] == "model-b" and call_number == 2:
            raise RuntimeError("model-b exploded #2")
        if payload["model"] == "model-a" and call_number == 3:
            raise RuntimeError("model-a exploded #3")

        return {
            "choices": [
                {
                    "message": {
                        "content": f"{payload['model']} says #{call_number}",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 2,
                "finalModel": "model-final",
            },
        )
        await scheduled["task"]

    asyncio.run(run())

    assert [payload["model"] for payload in calls] == [
        "model-a",
        "model-b",
        "model-a",
        "model-b",
        "model-final",
    ]

    second_round_first_prompt = calls[2]["messages"][-1]["content"]
    assert "model-a says #1" in second_round_first_prompt
    assert "model-b exploded #2" not in second_round_first_prompt
    assert "[failed]" not in second_round_first_prompt

    second_round_second_prompt = calls[3]["messages"][-1]["content"]
    assert "model-a says #1" in second_round_second_prompt
    assert "model-b exploded #2" not in second_round_second_prompt
    assert "model-a exploded #3" not in second_round_second_prompt
    assert "[failed]" not in second_round_second_prompt

    final_prompt = calls[-1]["messages"][-1]["content"]
    assert "Discussion transcript:" in final_prompt
    assert "model-a says #1" in final_prompt
    assert "model-b says #4" in final_prompt
    assert "model-b exploded #2" not in final_prompt
    assert "model-a exploded #3" not in final_prompt
    assert "Failed discussion turns (not evidence):" in final_prompt
    assert "Round 1 - model-b: failed" in final_prompt
    assert "Round 2 - model-a: failed" in final_prompt

    turn_errors = [
        event
        for event in events
        if event["type"] == "discussion" and event["data"]["type"] == "turn_error"
    ]
    assert len(turn_errors) == 2
    assert turn_errors[0]["data"]["state"]["failureCount"] == 1
    assert turn_errors[1]["data"]["state"]["failureCount"] == 2

    completion = next(event for event in events if event["type"] == "chat:completion")
    discussion = completion["data"]["discussion"]
    assert discussion["status"] == "completed"
    assert discussion["successCount"] == 2
    assert discussion["failureCount"] == 2
    assert [failure["modelName"] for failure in discussion["failures"]] == [
        "model-b",
        "model-a",
    ]

    final_upsert = upserts[-1][0][2]
    assert final_upsert["discussion"]["failureCount"] == 2


def test_multi_model_discussion_cancellation_marks_message_stopped(monkeypatch):
    events = []
    upserts = []
    scheduled = {}

    async def event_emitter(event):
        events.append(event)

    async def never_finish(*_args, **_kwargs):
        await asyncio.Event().wait()

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(discussion_mod, "_run_model_once", never_finish)
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
        )
        await asyncio.sleep(0)
        scheduled["task"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await scheduled["task"]

    asyncio.run(run())

    stopped_events = [
        event
        for event in events
        if event["type"] == "discussion" and event["data"]["type"] == "stopped"
    ]
    assert stopped_events
    assert stopped_events[-1]["data"]["state"]["status"] == "stopped"
    assert (
        stopped_events[-1]["data"]["state"]["rounds"][0]["turns"][0]["status"]
        == "stopped"
    )

    stopped_completion = next(
        event
        for event in events
        if event["type"] == "chat:completion" and event["data"].get("stopped") is True
    )
    assert stopped_completion["data"]["done"] is True
    assert stopped_completion["data"]["stoppedByUser"] is True
    assert stopped_completion["data"]["discussion"]["status"] == "stopped"
    assert (
        stopped_completion["data"]["discussion"]["rounds"][0]["turns"][0]["status"]
        == "stopped"
    )

    stopped_upsert = upserts[-1][0][2]
    assert stopped_upsert["done"] is True
    assert stopped_upsert["stoppedByUser"] is True
    assert stopped_upsert["discussion"]["status"] == "stopped"
    assert stopped_upsert["discussion"]["rounds"][0]["turns"][0]["status"] == "stopped"


def test_multi_model_discussion_persists_final_state_when_events_fail(monkeypatch):
    upserts = []
    calls = []
    scheduled = {}

    async def failing_event_emitter(_event):
        raise RuntimeError("socket disconnected")

    async def fake_generate_chat_completion(_request, payload, _user):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": f"answer from {payload['model']}",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
            },
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: failing_event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
        )
        await scheduled["task"]

    asyncio.run(run())

    assert [payload["model"] for payload in calls] == [
        "model-a",
        "model-b",
        "model-final",
    ]
    final_upsert = upserts[-1][0][2]
    assert final_upsert["done"] is True
    assert final_upsert["content"] == "answer from model-final"
    assert final_upsert["discussion"]["status"] == "completed"


def test_multi_model_discussion_persists_error_when_final_model_fails(monkeypatch):
    events = []
    upserts = []
    scheduled = {}

    async def event_emitter(event):
        events.append(event)

    async def fake_run_model_once(_request, _form_data, _user, model_id, _messages):
        if model_id == "model-final":
            raise RuntimeError("final model failed")
        return {
            "content": f"answer from {model_id}",
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(discussion_mod, "_run_model_once", fake_run_model_once)
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "question"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
        )
        await scheduled["task"]

    asyncio.run(run())

    completion = next(event for event in events if event["type"] == "chat:completion")
    assert completion["data"]["done"] is True
    assert completion["data"]["error"]["content"] == "final model failed"
    assert completion["data"]["discussion"]["status"] == "error"

    error_upsert = upserts[-1][0][2]
    assert error_upsert["done"] is True
    assert error_upsert["error"]["content"] == "final model failed"
    assert error_upsert["discussion"]["status"] == "error"


def test_multi_model_discussion_generates_chat_title_via_external_task_model(
    monkeypatch,
):
    from open_webui.constants import TASKS

    events = []
    upserts = []
    title_updates = []
    generate_title_calls = []
    scheduled = {}

    async def event_emitter(event):
        events.append(event)

    async def fake_generate_chat_completion(_request, payload, _user):
        return {
            "choices": [
                {"message": {"content": f"reply from {payload['model']}"}}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def fake_generate_title(_request, form_data, _user):
        generate_title_calls.append(form_data)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"title": "讨论：橘猫吃粮的拍照建议"}',
                    }
                }
            ],
        }

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: upserts.append((args, kwargs)),
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_chat_title_by_id",
        lambda _chat_id: "New Chat",
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "update_chat_title_by_id",
        lambda _chat_id, title, **_kwargs: title_updates.append(title) or True,
    )

    # Patch the lazily-imported router function used by _apply_discussion_chat_title.
    import open_webui.routers.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "generate_title", fake_generate_title)

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [
                    {"role": "user", "content": "讨论一下橘猫吃粮的拍照视角"}
                ],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
            None,
            tasks={TASKS.TITLE_GENERATION: True},
        )
        await scheduled["task"]

    asyncio.run(run())

    assert generate_title_calls, (
        "multi-model discussion should invoke generate_title when "
        "background_tasks request title_generation"
    )
    assert generate_title_calls[0].get("require_external_task_model") is True
    assert title_updates == ["讨论：橘猫吃粮的拍照建议"]
    title_event = next(
        (event for event in events if event["type"] == "chat:title"),
        None,
    )
    assert title_event is not None
    assert title_event["data"] == "讨论：橘猫吃粮的拍照建议"


def test_multi_model_discussion_title_falls_back_when_external_task_model_unavailable(
    monkeypatch,
):
    from fastapi.responses import JSONResponse

    from open_webui.constants import TASKS

    events = []
    title_updates = []
    scheduled = {}

    async def event_emitter(event):
        events.append(event)

    async def fake_generate_chat_completion(_request, payload, _user):
        return {
            "choices": [
                {"message": {"content": f"reply from {payload['model']}"}}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def fake_generate_title(_request, _form_data, _user):
        # Simulate the require_external_task_model guard rejecting the call.
        return JSONResponse(
            status_code=400,
            content={"detail": "no external task model", "skipped": True},
        )

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        scheduled["chat_id"] = id
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_chat_title_by_id",
        lambda _chat_id: "New Chat",
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "update_chat_title_by_id",
        lambda _chat_id, title, **_kwargs: title_updates.append(title) or True,
    )

    import open_webui.routers.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "generate_title", fake_generate_title)

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [
                    {"role": "user", "content": "请帮我分析下英伟达股价走势"}
                ],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
            None,
            tasks={TASKS.TITLE_GENERATION: True},
        )
        await scheduled["task"]

    asyncio.run(run())

    assert title_updates and title_updates[0]
    # Fallback should derive from the user prompt rather than the assistant content.
    assert "英伟达" in title_updates[0]


def test_multi_model_discussion_preserves_user_provided_title(monkeypatch):
    from open_webui.constants import TASKS

    title_updates = []
    generate_title_calls = []
    scheduled = {}

    async def event_emitter(_event):
        return None

    async def fake_generate_chat_completion(_request, payload, _user):
        return {
            "choices": [
                {"message": {"content": f"reply from {payload['model']}"}}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def fake_generate_title(_request, form_data, _user):
        generate_title_calls.append(form_data)
        return {"choices": [{"message": {"content": "新建对话"}}]}

    def fake_create_task(coroutine, id=None):
        task = asyncio.create_task(coroutine)
        scheduled["task"] = task
        return "task-1", task

    monkeypatch.setattr(
        discussion_mod, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(
        discussion_mod,
        "generate_chat_completion",
        fake_generate_chat_completion,
    )
    monkeypatch.setattr(discussion_mod, "create_task", fake_create_task)
    monkeypatch.setattr(
        discussion_mod.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_chat_title_by_id",
        lambda _chat_id: "用户手动起的标题",
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "update_chat_title_by_id",
        lambda _chat_id, title, **_kwargs: title_updates.append(title) or True,
    )

    import open_webui.routers.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "generate_title", fake_generate_title)

    async def run():
        await discussion_mod.generate_multi_model_discussion_completion(
            _request(_models("model-a", "model-b", "model-final")),
            {
                "model": "model-final",
                "messages": [{"role": "user", "content": "继续讨论"}],
                "stream": True,
            },
            _user(),
            {"chat_id": "chat-1", "message_id": "assistant-1"},
            {"id": "model-final"},
            {
                "enabled": True,
                "participants": ["model-a", "model-b"],
                "rounds": 1,
                "finalModel": "model-final",
            },
            None,
            tasks={TASKS.TITLE_GENERATION: True},
        )
        await scheduled["task"]

    asyncio.run(run())

    assert title_updates == [], (
        "must not overwrite an existing non-default chat title"
    )
    assert generate_title_calls == [], (
        "should not waste tokens generating titles when one already exists"
    )


def test_multi_model_discussion_title_refresh_uses_persisted_chain_and_metadata(
    monkeypatch,
):
    from open_webui.constants import TASKS

    message_map = {
        "user-1": {
            "id": "user-1",
            "role": "user",
            "content": "early topic",
            "parentId": None,
        },
        "assistant-1": {
            "id": "assistant-1",
            "role": "assistant",
            "content": "early answer",
            "parentId": "user-1",
        },
        "user-2": {
            "id": "user-2",
            "role": "user",
            "content": "new topic begins",
            "parentId": "assistant-1",
        },
        "assistant-2": {
            "id": "assistant-2",
            "role": "assistant",
            "content": "new topic answer",
            "parentId": "user-2",
        },
        "user-3": {
            "id": "user-3",
            "role": "user",
            "content": "continue new topic",
            "parentId": "assistant-2",
        },
        "assistant-3": {
            "id": "assistant-3",
            "role": "assistant",
            "content": "final discussion answer",
            "parentId": "user-3",
        },
    }
    generated = []
    updates = []
    events = []

    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_messages_by_chat_id",
        lambda _chat_id: message_map,
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_chat_title_by_id",
        lambda _chat_id: "Early automatic title",
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "get_chat_title_generation_metadata_by_id",
        lambda _chat_id: {
            "auto_generated": True,
            "last_user_message_count": 1,
        },
    )
    monkeypatch.setattr(
        discussion_mod.Chats,
        "update_chat_title_by_id",
        lambda chat_id, title, **kwargs: updates.append((chat_id, title, kwargs)) or True,
    )

    import open_webui.routers.tasks as tasks_mod

    async def fake_generate_title(_request, form_data, _user):
        generated.append(form_data)
        return {"choices": [{"message": {"content": '{"title": "New topic"}'}}]}

    async def event_emitter(event):
        events.append(event)

    monkeypatch.setattr(tasks_mod, "generate_title", fake_generate_title)

    asyncio.run(
        discussion_mod._apply_discussion_chat_title(
            request=SimpleNamespace(),
            user=_user(),
            metadata={"model_id": "model-final"},
            chat_id="chat-1",
            message_id="assistant-3",
            user_prompt="continue new topic",
            final_content="final discussion answer",
            event_emitter=event_emitter,
            tasks={TASKS.TITLE_GENERATION: True},
        )
    )

    assert generated[0]["messages"] == list(message_map.values())
    assert updates == [
        (
            "chat-1",
            "New topic",
            {
                "auto_generated": True,
                "last_user_message_count": 3,
                "source_message_id": "assistant-3",
            },
        )
    ]
    assert events == [{"type": "chat:title", "data": "New topic"}]
