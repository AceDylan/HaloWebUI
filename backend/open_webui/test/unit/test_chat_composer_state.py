"""Saving a chat's composer state must not count as activity in the chat."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import chats as chats_mod


STATE = {
    "selected_tool_ids": [],
    "tool_selection_touched": False,
    "selected_skill_ids": [],
    "skill_selection_touched": False,
    "multi_model_discussion_enabled": False,
    "web_search_mode": "auto",
    "web_search_mode_source": "default",
    "image_generation_enabled": False,
    "code_interpreter_enabled": False,
    "reasoning_effort": None,
    "max_thinking_tokens": None,
}


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
        for chat_id, updated_at in (("old", 100), ("newest", 200)):
            db.add(
                chats_mod.Chat(
                    id=chat_id,
                    user_id="owner",
                    title=chat_id,
                    created_at=1,
                    updated_at=updated_at,
                    chat={
                        "title": chat_id,
                        "history": {"currentId": None, "messages": {}},
                        "composer_state": dict(STATE),
                    },
                )
            )
        db.commit()
    yield chats_mod.ChatTable()
    engine.dispose()


def test_changed_composer_state_is_saved_without_touching_updated_at(table):
    result = table.update_chat_composer_state_by_id(
        "old", {**STATE, "web_search_mode": "off", "web_search_mode_source": "user"}
    )

    assert result is not None
    stored = table.get_chat_by_id("old")
    assert stored.chat["composer_state"]["web_search_mode"] == "off"
    assert stored.chat["composer_state"]["web_search_mode_source"] == "user"
    # Still behind "newest": opening or leaving a chat must not reorder the sidebar.
    assert stored.updated_at == 100


def test_unchanged_composer_state_is_not_written(table, monkeypatch):
    calls = []
    original = table.update_chat_by_id

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(table, "update_chat_by_id", spy)

    result = table.update_chat_composer_state_by_id("old", dict(STATE))

    assert result is not None
    assert calls == []
    assert table.get_chat_by_id("old").updated_at == 100


def test_regular_chat_saves_still_move_the_chat_to_the_top(table):
    chat = table.get_chat_by_id("old").chat
    table.update_chat_by_id("old", {**chat, "title": "old"}, update_title=False)

    assert table.get_chat_by_id("old").updated_at > 200
