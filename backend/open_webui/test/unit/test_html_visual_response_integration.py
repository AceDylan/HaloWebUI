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
        "server_surface": "halowebui-web",
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
    # Gone from middleware (presence moved to utils/presence.py); kept
    # harmless for older trees.
    monkeypatch.setattr(
        middleware, "get_active_status_by_user_id", lambda _user_id: True, raising=False
    )
    monkeypatch.setattr(
        middleware.Chats, "get_chat_title_by_id", lambda _chat_id: "Chat"
    )
    monkeypatch.setattr(
        middleware.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda chat_id, message_id, payload, **kwargs: upserts.append(
            (chat_id, message_id, payload, kwargs)
        ),
    )


def test_direct_non_streaming_force_mode_gets_no_card_on_its_own(monkeypatch):
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

    # no card on its own: it is made on request (「生成 HTML 卡片」)
    final_content = result["choices"][0]["message"]["content"]
    assert final_content == "Plain <unsafe>"
    assert HTML_VISUAL_FALLBACK_MARKER not in final_content
    assert upserts[-1][2]["content"] == final_content
    assert events[-1]["data"]["content"] == final_content


def test_non_streaming_force_mode_without_session_keeps_the_reply_as_written(monkeypatch):
    monkeypatch.setattr(
        middleware,
        "get_event_emitter",
        lambda _metadata: (_ for _ in ()).throw(
            AssertionError("event emitter should not be requested")
        ),
    )
    metadata = _metadata()
    metadata.pop("session_id")
    response_content = """Explanation remains.
```html
<div style="color:#111">Model source</div>
```"""
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": response_content,
                }
            }
        ]
    }

    result = asyncio.run(
        middleware.process_chat_response(
            _request(),
            response,
            {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            metadata,
            {},
            [],
            {},
        )
    )

    final_content = result["choices"][0]["message"]["content"]
    assert final_content == response_content
    assert HTML_VISUAL_FALLBACK_MARKER not in final_content


async def _sse_stream():
    chunk = {"choices": [{"delta": {"content": "Streamed <unsafe>"}}]}
    yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def test_direct_streaming_force_mode_gets_no_card_on_its_own(monkeypatch):
    events = []
    upserts = []
    created = {}
    _patch_response_dependencies(monkeypatch, events, upserts)
    monkeypatch.setattr(middleware, "ENABLE_REALTIME_CHAT_SAVE", False)

    def create_task(coroutine, id=None, *, blocks_completion=True, **_kwargs):
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

    completion_events = [
        event for event in events if event.get("type") == "chat:completion"
    ]
    done_index = next(
        index
        for index, event in enumerate(completion_events)
        if event.get("data", {}).get("done") is True
    )
    # Done goes out with the plain answer, and nothing follows it: the card is made
    # on request (「生成 HTML 卡片」).
    done_content = completion_events[done_index]["data"]["content"]
    assert done_content.startswith("Streamed <unsafe>")
    assert HTML_VISUAL_FALLBACK_MARKER not in done_content
    assert done_index == len(completion_events) - 1
    assert all("```html" not in str(payload.get("content") or "") for _c, _m, payload, _k in upserts)


def test_streaming_force_mode_without_session_streams_through(monkeypatch):
    async def unsafe_stream():
        content = """Streaming explanation.
```html
<div>Model streamed source</div>
```"""
        chunk = {"choices": [{"delta": {"content": content}}]}
        yield f"data: {json.dumps(chunk)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    async def passthrough_filter(**kwargs):
        return kwargs["form_data"], {}

    monkeypatch.setattr(middleware, "get_sorted_filters", lambda _model: [])
    monkeypatch.setattr(middleware, "process_filter_functions", passthrough_filter)
    metadata = _metadata()
    metadata.pop("session_id")
    response = StreamingResponse(unsafe_stream(), media_type="text/event-stream")

    result = asyncio.run(
        middleware.process_chat_response(
            _request(),
            response,
            {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
            _user(),
            metadata,
            {},
            [],
            {},
        )
    )

    async def consume():
        chunks = []
        async for chunk in result.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    streamed = asyncio.run(consume())
    # streamed through as it comes (no buffering for a card any more)
    assert "Streaming explanation." in streamed
    assert "Model streamed source" in streamed
    assert HTML_VISUAL_FALLBACK_MARKER not in streamed
    assert streamed.rstrip().endswith("data: [DONE]")
