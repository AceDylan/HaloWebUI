"""A reply the upstream cut off at its output limit (finish_reason=length) says so.

glm-5.3 through CCHP's Claude Messages conversion got max_tokens=4096 and spent
all of it thinking: the reply was a thinking block and nothing else.
"""

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

from starlette.responses import StreamingResponse

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import middleware  # noqa: E402


def _frame(delta, finish_reason=None):
    event = {"choices": [{"delta": delta, "finish_reason": finish_reason, "index": 0}]}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


def _stream(*frames):
    async def body():
        for frame in frames:
            yield frame
        yield b"data: [DONE]\n\n"

    return body()


def _final_reply(monkeypatch, body):
    events, created = [], {}

    async def fake_event_emitter(event):
        events.append(event)

    async def passthrough_filters(**kwargs):
        return kwargs["form_data"], {}

    def fake_create_task(coroutine, id=None, *, blocks_completion=True, **_kwargs):
        created["coroutine"] = coroutine
        return "task-1", SimpleNamespace()

    monkeypatch.setattr(middleware, "get_event_emitter", lambda _metadata: fake_event_emitter)
    monkeypatch.setattr(middleware, "get_event_call", lambda _metadata: object())
    monkeypatch.setattr(middleware, "get_sorted_filters", lambda _model: [])
    monkeypatch.setattr(middleware, "process_filter_functions", passthrough_filters)
    monkeypatch.setattr(middleware, "create_task", fake_create_task)
    monkeypatch.setattr(middleware, "set_current_task_blocks_completion", lambda _value: True)
    monkeypatch.setattr(
        middleware.Chats, "upsert_message_to_chat_by_id_and_message_id", lambda *_a, **_k: None
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                WEBUI_NAME="Halo WebUI",
                config=SimpleNamespace(
                    ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION=False,
                    WEBUI_URL="http://localhost",
                ),
            )
        )
    )
    user = SimpleNamespace(id="user-1", email="u@example.com", name="User", role="user")
    metadata = {"session_id": "s-1", "chat_id": "chat-1", "message_id": "a-1", "features": {}}
    ref = "modelref::openai::personal::id:c153e2d2::glm-chat"

    asyncio.run(
        middleware.process_chat_response(
            request,
            StreamingResponse(body, media_type="text/event-stream"),
            {"model": ref, "messages": [{"role": "user", "content": "hi"}]},
            user,
            metadata,
            {"id": ref, "name": "glm-chat"},
            [],
            {},
        )
    )
    asyncio.run(created["coroutine"])
    return [
        event["data"]
        for event in events
        if event.get("type") == "chat:completion" and event.get("data", {}).get("done")
    ][-1]


def test_thinking_only_reply_cut_at_the_limit_says_there_is_no_answer(monkeypatch):
    final = _final_reply(
        monkeypatch,
        _stream(
            _frame({"reasoning_content": "先梳理一下上下文……"}),
            _frame({}, finish_reason="length"),
        ),
    )

    assert "error" not in final
    assert 'type="reasoning"' in final["content"]
    assert '<details type="warning" done="true">' in final["content"]
    assert "只有思考没有回答" in final["content"]
    assert "finish_reason=length" in final["content"]


def test_answer_cut_at_the_limit_says_it_is_incomplete(monkeypatch):
    final = _final_reply(
        monkeypatch,
        _stream(
            _frame({"reasoning_content": "想一想"}),
            _frame({"content": "第一章 光的散射"}),
            _frame({}, finish_reason="length"),
        ),
    )

    assert final["content"].index("第一章 光的散射") < final["content"].index(
        "回答不完整"
    )
    assert "只有思考没有回答" not in final["content"]


def test_reply_that_stops_normally_has_no_notice(monkeypatch):
    final = _final_reply(
        monkeypatch,
        _stream(
            _frame({"reasoning_content": "想一想"}),
            _frame({"content": "天空是蓝色的。"}),
            _frame({}, finish_reason="stop"),
        ),
    )

    assert "天空是蓝色的。" in final["content"]
    assert 'type="warning"' not in final["content"]
