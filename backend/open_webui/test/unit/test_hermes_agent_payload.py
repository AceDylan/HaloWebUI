import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.utils import hermes_agent
from open_webui.utils import middleware
from open_webui.utils.hermes_agent import _build_run_payload
from open_webui.utils.html_visual_prompt import HTML_VISUAL_FALLBACK_MARKER


def test_run_payload_omits_raw_images_from_conversation_history():
    historical_image = "data:image/png;base64," + ("A" * 100_000)
    form_data = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Make this image sharper"},
                    {
                        "type": "image_url",
                        "image_url": {"url": historical_image},
                    },
                ],
            },
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Now change the clothes"},
        ]
    }

    payload = _build_run_payload(form_data, {"chat_id": "chat-1"}, "hermes-agent")

    assert payload["input"] == "Now change the clothes"
    assert payload["conversation_history"][0] == {
        "role": "user",
        "content": "Make this image sharper\n[Image attachment omitted from prior turn]",
    }
    assert historical_image not in str(payload["conversation_history"])


def test_only_current_run_input_is_materialized():
    payload = {
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Edit this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "/api/v1/files/current/content"},
                    },
                ],
            }
        ],
        "conversation_history": [
            {
                "role": "user",
                "content": "Earlier image\n[Image attachment omitted from prior turn]",
            }
        ],
    }
    seen_messages = []

    def fake_materialize(form_data, **_kwargs):
        seen_messages.extend(form_data["messages"])
        materialized = {
            **form_data["messages"][0],
            "content": [
                {"type": "text", "text": "Edit this"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        }
        return {"messages": [materialized]}

    with patch.object(
        hermes_agent,
        "materialize_openai_image_message_refs",
        side_effect=fake_materialize,
    ):
        result = hermes_agent._materialize_run_input_image_refs(
            payload,
            user_id="user-1",
            is_admin=False,
        )

    assert seen_messages == payload["input"]
    assert result["input"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert result["conversation_history"] == payload["conversation_history"]


class _FakeStreamContent:
    def __init__(self, events):
        self.lines = [f"data: {json.dumps(event)}\n".encode() for event in events]

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class _FakeResponse:
    def __init__(self, *, payload=None, events=None, status=200):
        self.payload = payload or {}
        self.status = status
        self.content = _FakeStreamContent(events or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return self.payload

    async def text(self):
        return json.dumps(self.payload)


class _FakeHermesSession:
    def __init__(self, terminal_events):
        self.terminal_events = terminal_events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **_kwargs):
        assert url.endswith("/runs")
        return _FakeResponse(payload={"run_id": "run-1"})

    def get(self, url, **_kwargs):
        assert url.endswith("/runs/run-1/events")
        return _FakeResponse(events=self.terminal_events)


def _run_hermes_terminal_events(monkeypatch, terminal_events):
    emitted = []
    upserts = []
    created = {}

    async def event_emitter(event):
        emitted.append(event)

    async def background_tasks_handler(*_args, **_kwargs):
        return None

    def create_task(coroutine, id=None):
        created["coroutine"] = coroutine
        return "task-1", SimpleNamespace()

    monkeypatch.setattr(
        hermes_agent,
        "_resolve_hermes_connection",
        lambda *_args: ("http://hermes.test/v1", "", "hermes-agent"),
    )
    monkeypatch.setattr(
        hermes_agent,
        "_materialize_run_input_image_refs",
        lambda payload, **_kwargs: payload,
    )
    monkeypatch.setattr(
        hermes_agent, "get_event_emitter", lambda _metadata: event_emitter
    )
    monkeypatch.setattr(hermes_agent, "get_event_call", lambda _metadata: object())
    monkeypatch.setattr(hermes_agent, "create_task", create_task)
    monkeypatch.setattr(
        hermes_agent.aiohttp,
        "ClientSession",
        lambda **_kwargs: _FakeHermesSession(terminal_events),
    )
    monkeypatch.setattr(
        hermes_agent.Chats, "get_chat_title_by_id", lambda _chat_id: "Chat"
    )
    monkeypatch.setattr(
        hermes_agent.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda chat_id, message_id, payload, **_kwargs: upserts.append(
            (chat_id, message_id, payload)
        ),
    )
    monkeypatch.setattr(
        middleware, "background_tasks_handler", background_tasks_handler
    )

    metadata = {
        "server_surface": "halowebui-web",
        "session_id": "session-1",
        "chat_id": "chat-1",
        "message_id": "assistant-1",
        "features": {
            "html_visual_artifacts": "force",
            "html_visual_surface": "halowebui-web",
        },
    }
    result = asyncio.run(
        hermes_agent.run_hermes_agent(
            SimpleNamespace(),
            {
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": "hi"}],
            },
            SimpleNamespace(id="user-1", role="user"),
            metadata,
            {"id": "hermes-agent"},
            [],
            {},
        )
    )
    assert result == {"status": True, "task_id": "task-1"}
    asyncio.run(created["coroutine"])
    return emitted, upserts


def test_hermes_completed_force_mode_finalizes_with_one_fallback(monkeypatch):
    emitted, upserts = _run_hermes_terminal_events(
        monkeypatch,
        [
            {"event": "message.delta", "delta": "Plain <unsafe>"},
            {"event": "tool.started", "tool": "version", "preview": "{}"},
            {"event": "tool.completed", "tool": "version", "duration": 0.1},
            {"event": "run.completed", "output": "Plain <unsafe>"},
        ],
    )

    final_data = [
        event["data"]
        for event in emitted
        if event.get("type") == "chat:completion"
        and event.get("data", {}).get("done") is True
    ][-1]
    assert final_data["content"].startswith("Plain")
    assert "<unsafe>" not in final_data["content"]
    assert '<details type="tool_calls" done="true"' in final_data["content"]
    assert final_data["content"].count(HTML_VISUAL_FALLBACK_MARKER) == 1
    assert upserts[-1][2]["content"] == final_data["content"]


def test_hermes_cancelled_force_mode_does_not_append_fallback(monkeypatch):
    emitted, upserts = _run_hermes_terminal_events(
        monkeypatch,
        [
            {"event": "message.delta", "delta": "Partial plain response"},
            {"event": "run.cancelled"},
        ],
    )

    final_data = [
        event["data"]
        for event in emitted
        if event.get("type") == "chat:completion"
        and event.get("data", {}).get("done") is True
    ][-1]
    assert HTML_VISUAL_FALLBACK_MARKER not in final_data["content"]
    assert HTML_VISUAL_FALLBACK_MARKER not in upserts[-1][2]["content"]


def test_hermes_failed_force_mode_does_not_append_fallback(monkeypatch):
    emitted, upserts = _run_hermes_terminal_events(
        monkeypatch,
        [
            {"event": "message.delta", "delta": "Partial plain response"},
            {"event": "run.failed", "error": "provider unavailable"},
        ],
    )

    final_data = [
        event["data"]
        for event in emitted
        if event.get("type") == "chat:completion"
        and event.get("data", {}).get("done") is True
    ][-1]
    assert final_data["error"] == {"content": "provider unavailable"}
    assert HTML_VISUAL_FALLBACK_MARKER not in final_data["content"]
    assert HTML_VISUAL_FALLBACK_MARKER not in upserts[-1][2]["content"]
