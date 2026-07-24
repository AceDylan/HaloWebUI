import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui import config  # noqa: E402
from open_webui.constants import TASKS  # noqa: E402
from open_webui.utils import middleware  # noqa: E402
from open_webui.utils.task import title_generation_template  # noqa: E402


def _message_chain(user_turns: int):
    messages = {}
    parent_id = None
    for turn in range(1, user_turns + 1):
        user_id = f"user-{turn}"
        assistant_id = f"assistant-{turn}"
        messages[user_id] = {
            "id": user_id,
            "role": "user",
            "content": f"question {turn}",
            "parentId": parent_id,
        }
        messages[assistant_id] = {
            "id": assistant_id,
            "role": "assistant",
            "content": f"answer {turn}",
            "parentId": user_id,
            "model": "text-model",
        }
        parent_id = assistant_id
    return messages, parent_id


@pytest.mark.parametrize(
    ("title", "title_generation"),
    [
        ("Legacy custom title", {}),
        ("New Chat", {"auto_generated": False}),
        (
            "Automatic title",
            {"auto_generated": True, "last_user_message_count": 3},
        ),
        (
            "Automatic title",
            {"auto_generated": True, "last_user_message_count": 6},
        ),
    ],
)
def test_background_title_refresh_skips_manual_duplicate_and_stale_requests(
    monkeypatch, title, title_generation
):
    message_map, message_id = _message_chain(3)

    monkeypatch.setattr(
        middleware.Chats, "get_messages_by_chat_id", lambda _chat_id: message_map
    )
    monkeypatch.setattr(
        middleware.Chats, "get_chat_title_by_id", lambda _chat_id: title
    )
    monkeypatch.setattr(
        middleware.Chats,
        "get_chat_title_generation_metadata_by_id",
        lambda _chat_id: title_generation,
    )

    async def fail_generate_title(*_args, **_kwargs):
        raise AssertionError("protected or duplicate titles must skip model generation")

    monkeypatch.setattr(middleware, "generate_title", fail_generate_title)

    asyncio.run(
        middleware.background_tasks_handler(
            SimpleNamespace(),
            SimpleNamespace(),
            {"chat_id": "chat-1", "message_id": message_id},
            {TASKS.TITLE_GENERATION: True},
            lambda _event: None,
        )
    )


def test_background_title_refresh_uses_full_chain_and_marks_automatic_metadata(
    monkeypatch,
):
    message_map, message_id = _message_chain(3)
    generated = []
    updates = []
    events = []

    monkeypatch.setattr(
        middleware.Chats, "get_messages_by_chat_id", lambda _chat_id: message_map
    )
    monkeypatch.setattr(
        middleware.Chats,
        "get_chat_title_by_id",
        lambda _chat_id: "First automatic title",
    )
    monkeypatch.setattr(
        middleware.Chats,
        "get_chat_title_generation_metadata_by_id",
        lambda _chat_id: {
            "auto_generated": True,
            "last_user_message_count": 1,
        },
    )

    async def fake_generate_title(_request, form_data, _user):
        generated.append(form_data)
        return {"choices": [{"message": {"content": '{"title": "Refreshed"}'}}]}

    def fake_update(chat_id, title, **kwargs):
        updates.append((chat_id, title, kwargs))
        return True

    async def event_emitter(event):
        events.append(event)

    monkeypatch.setattr(middleware, "generate_title", fake_generate_title)
    monkeypatch.setattr(middleware.Chats, "update_chat_title_by_id", fake_update)

    asyncio.run(
        middleware.background_tasks_handler(
            SimpleNamespace(),
            SimpleNamespace(),
            {"chat_id": "chat-1", "message_id": message_id},
            {TASKS.TITLE_GENERATION: True},
            event_emitter,
        )
    )

    assert generated[0]["messages"] == list(message_map.values())
    assert updates == [
        (
            "chat-1",
            "Refreshed",
            {
                "auto_generated": True,
                "last_user_message_count": 3,
                "source_message_id": "assistant-3",
            },
        )
    ]
    assert events == [{"type": "chat:title", "data": "Refreshed"}]


def test_default_title_prompt_covers_early_and_recent_history():
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
        for index in range(16)
    ]

    rendered = title_generation_template(
        config.DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE, messages
    )

    assert "latest topic sustained across multiple messages" in rendered
    for index in [0, 5, 10, 15]:
        assert f"turn-{index}" in rendered
    for index in [6, 9]:
        assert f"turn-{index}" not in rendered
    assert "{{MESSAGES:MIDDLETRUNCATE:12}}" not in rendered
