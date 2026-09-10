"""Exercise snapshot saves through the real model using a private in-memory DB."""

import copy
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import chats as chats_mod


@pytest.fixture
def table(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats_mod.Chat.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(chats_mod, "get_db", get_db)
    monkeypatch.setattr(
        chats_mod.ChatMessages, "upsert_message", lambda **_kwargs: None
    )
    with get_db() as db:
        db.add(
            chats_mod.Chat(
                id="chat",
                user_id="owner",
                title="Chat",
                created_at=1,
                updated_at=1,
                chat={
                    "title": "Chat",
                    "history": {
                        "currentId": "a",
                        "messages": {
                            "a": {
                                "id": "a",
                                "role": "assistant",
                                "content": "",
                                "done": False,
                                "childrenIds": [],
                            }
                        },
                    },
                },
            )
        )
        db.commit()
    yield chats_mod.ChatTable()
    engine.dispose()


def test_device_save_merges_against_current_database_row(table):
    old = table.get_chat_by_id("chat").chat
    table.upsert_message_to_chat_by_id_and_message_id(
        "chat",
        "a",
        {"content": "final", "done": True, "files": [{"url": "/image.png"}]},
    )
    incoming = copy.deepcopy(old)
    incoming["history"]["messages"]["b"] = {
        "id": "b",
        "parentId": "a",
        "role": "user",
        "content": "next",
    }
    incoming["history"]["messages"]["a"]["childrenIds"] = ["b"]
    incoming["history"]["currentId"] = "b"
    result = table.update_chat_by_id(
        "chat", incoming, update_title=False, base_chat=old
    )
    assert result is not None
    stored = table.get_chat_by_id("chat").chat["history"]
    assert stored["messages"]["a"]["content"] == "final"
    assert stored["messages"]["a"]["files"] == [{"url": "/image.png"}]
    assert stored["messages"]["b"]["content"] == "next"
    assert stored["currentId"] == "b"


def test_stopping_on_one_device_survives_late_stream_and_stale_device_save(table):
    old = table.get_chat_by_id("chat").chat
    table.upsert_message_to_chat_by_id_and_message_id(
        "chat",
        "a",
        {"content": "partial", "done": True, "stopped": True, "stoppedByUser": True},
    )
    table.upsert_message_to_chat_by_id_and_message_id(
        "chat", "a", {"content": "late tokens", "done": False}, guard_stopped=True
    )
    stale = copy.deepcopy(old)
    stale["composer_state"] = {"webSearchMode": "off"}
    assert table.update_chat_by_id("chat", stale, base_chat=old) is not None
    message = table.get_chat_by_id("chat").chat["history"]["messages"]["a"]
    assert message["content"] == "partial"
    assert message["done"] is True
    assert message["stoppedByUser"] is True


@pytest.mark.parametrize("operation", ["message", "composer", "status"])
def test_server_partial_update_cannot_drop_a_concurrently_appended_turn(
    table, monkeypatch, operation
):
    old = table.get_chat_by_id("chat")
    newer = copy.deepcopy(old.chat)
    newer["history"]["messages"]["notification"] = {
        "id": "notification",
        "content": "background result",
    }
    newer["history"]["currentId"] = "notification"
    assert table.update_chat_by_id("chat", newer) is not None
    real_get = table.get_chat_by_id
    monkeypatch.setattr(table, "get_chat_by_id", lambda _id: copy.deepcopy(old))
    if operation == "message":
        result = table.upsert_message_to_chat_by_id_and_message_id(
            "chat", "a", {"content": "stream"}
        )
    elif operation == "composer":
        result = table.update_chat_composer_state_by_id(
            "chat", {"webSearchMode": "off"}
        )
    else:
        result = table.add_message_status_to_chat_by_id_and_message_id(
            "chat", "a", {"done": False}
        )
    assert result is not None
    stored = real_get("chat").chat
    assert (
        stored["history"]["messages"]["notification"]["content"] == "background result"
    )
    assert stored["history"]["currentId"] == "notification"
