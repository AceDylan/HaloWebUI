import asyncio
import json
from types import SimpleNamespace

from starlette.responses import StreamingResponse

from open_webui.utils import middleware
from open_webui.utils.html_visual_prompt import HTML_VISUAL_FALLBACK_MARKER


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                WEBUI_NAME="Halo WebUI",
                config=SimpleNamespace(
                    ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION=False,
                    CUSTOM_REASONING_TAGS="",
                    WEBUI_URL="http://localhost",
                ),
            )
        )
    )


def _user():
    return SimpleNamespace(id="user-1", email="u@example.com", name="User", role="user")


def _metadata(mode="force"):
    return {
        "session_id": "session-1",
        "chat_id": "chat-1",
        "message_id": "assistant-1",
        "features": {
            "html_visual_artifacts": mode,
            "html_visual_surface": "halowebui-web",
        },
    }


def _patch_response_dependencies(monkeypatch, events, upserts):
    async def event_emitter(event):
        events.append(event)

    async def background_tasks_handler(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        middleware, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(middleware, "get_event_call", lambda _metadata: object())
    monkeypatch.setattr(middleware, "get_sorted_filters", lambda _model: [])
    monkeypatch.setattr(middleware, "get_user_native_tools_config", lambda *_args: {})
    monkeypatch.setattr(
        middleware, "background_tasks_handler", background_tasks_handler
    )
    monkeypatch.setattr(
        middleware, "get_active_status_by_user_id", lambda _user_id: True
    )
    monkeypatch.setattr(
        middleware.Chats, "get_chat_title_by_id", lambda _chat_id: "Chat"
    )
    monkeypatch.setattr(
        middleware.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda chat_id, message_id, payload, **_kwargs: upserts.append(
            (chat_id, message_id, payload)
        ),
    )


def test_direct_non_streaming_force_mode_finalizes_with_fallback(monkeypatch):
    events = []
    upserts = []
    _patch_response_dependencies(monkeypatch, events, upserts)
    response = {
        "choices": [{"message": {"role": "assistant", "content": "Plain <unsafe>"}}]
    }

    result = asyncio.run(
        middleware.process_chat_response(
            _request(),
            response,
            {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            _metadata(),
            {},
            [],
            {},
        )
    )

    final_content = result["choices"][0]["message"]["content"]
    assert final_content.startswith("Plain <unsafe>\n\n")
    assert final_content.count(HTML_VISUAL_FALLBACK_MARKER) == 1
    assert upserts[-1][2]["content"] == final_content
    assert events[-1]["data"]["content"] == final_content


async def _sse_stream():
    chunk = {"choices": [{"delta": {"content": "Streamed <unsafe>"}}]}
    yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def test_direct_streaming_force_mode_appends_fallback_only_at_finalization(monkeypatch):
    events = []
    upserts = []
    created = {}
    _patch_response_dependencies(monkeypatch, events, upserts)
    monkeypatch.setattr(middleware, "ENABLE_REALTIME_CHAT_SAVE", False)

    def create_task(coroutine, id=None, *, blocks_completion=True):
        created["coroutine"] = coroutine
        return "task-1", SimpleNamespace()

    monkeypatch.setattr(middleware, "create_task", create_task)
    monkeypatch.setattr(
        middleware, "set_current_task_blocks_completion", lambda _value: None
    )
    response = StreamingResponse(_sse_stream(), media_type="text/event-stream")

    result = asyncio.run(
        middleware.process_chat_response(
            _request(),
            response,
            {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            _metadata(),
            {},
            [],
            {},
        )
    )
    assert result == {"status": True, "task_id": "task-1"}

    asyncio.run(created["coroutine"])

    completions = [
        event
        for event in events
        if event.get("type") == "chat:completion"
        and event.get("data", {}).get("done") is True
    ]
    final_content = completions[-1]["data"]["content"]
    assert final_content.startswith("Streamed <unsafe>\n\n")
    assert final_content.count(HTML_VISUAL_FALLBACK_MARKER) == 1
    assert upserts[-1][2]["content"] == final_content
    assert all(
        HTML_VISUAL_FALLBACK_MARKER not in event.get("data", {}).get("content", "")
        for event in events
        if not event.get("data", {}).get("done")
    )
