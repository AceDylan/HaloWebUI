import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.models import chats as chats_mod  # noqa: E402


def test_update_chat_title_keeps_existing_activity_timestamp(monkeypatch):
    table = chats_mod.ChatTable()
    chat_row = SimpleNamespace(
        id="chat-1",
        user_id="user-1",
        title="Old title",
        chat={"title": "Old title", "history": {"messages": {}}},
        created_at=90,
        updated_at=100,
        share_id=None,
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
        assistant_id=None,
    )

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _id):
            return chat_row

        def commit(self):
            return None

        def refresh(self, _row):
            return None

    def fail_if_timestamp_is_bumped(*_args):
        raise AssertionError("title-only updates must not bump updated_at")

    monkeypatch.setattr(chats_mod, "get_db", lambda: FakeDb())
    monkeypatch.setattr(chats_mod, "flag_modified", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(table, "_next_user_chat_timestamp", fail_if_timestamp_is_bumped)

    result = table.update_chat_title_by_id("chat-1", "New title")

    assert result is not None
    assert result.title == "New title"
    assert result.chat["title"] == "New title"
    assert result.updated_at == 100
    assert chat_row.updated_at == 100


def _fake_chat_row(*, title="Old title", meta=None):
    return SimpleNamespace(
        id="chat-1",
        user_id="user-1",
        title=title,
        chat={"title": title, "history": {"messages": {}}},
        created_at=90,
        updated_at=100,
        share_id=None,
        archived=False,
        pinned=False,
        meta={} if meta is None else meta,
        folder_id=None,
        assistant_id=None,
    )


def _install_fake_db(monkeypatch, chat_row):
    commits = []

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _id):
            return chat_row

        def commit(self):
            commits.append(True)

        def refresh(self, _row):
            return None

    monkeypatch.setattr(chats_mod, "get_db", lambda: FakeDb())
    monkeypatch.setattr(chats_mod, "flag_modified", lambda *_args, **_kwargs: None)
    return commits


def _install_update_chat_db(monkeypatch, table, chat_row):
    class FakeQuery:
        def filter(self, *_args):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return chat_row

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, _model):
            return FakeQuery()

        def commit(self):
            return None

        def refresh(self, _row):
            return None

    monkeypatch.setattr(chats_mod, "get_db", lambda: FakeDb())
    monkeypatch.setattr(chats_mod, "flag_modified", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(table, "_next_user_chat_timestamp", lambda _db, _user_id: 101)


def test_get_chat_title_prefers_canonical_column(monkeypatch):
    table = chats_mod.ChatTable()
    monkeypatch.setattr(
        table,
        "get_chat_by_id",
        lambda _chat_id: SimpleNamespace(
            title="Fresh automatic title",
            chat={"title": "Stale nested title"},
        ),
    )

    assert table.get_chat_title_by_id("chat-1") == "Fresh automatic title"


def test_full_chat_save_without_title_preserves_latest_server_title(monkeypatch):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Fresh automatic title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 3,
            }
        },
    )
    _install_update_chat_db(monkeypatch, table, chat_row)

    result = table.update_chat_by_id(
        "chat-1",
        {"title": "Stale client title", "history": {"messages": {}}},
        update_title=False,
    )

    assert result is not None
    assert result.title == "Fresh automatic title"
    assert result.chat["title"] == "Fresh automatic title"
    assert result.meta["title_generation"]["auto_generated"] is True


def test_full_chat_save_with_changed_title_marks_it_manual(monkeypatch):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Automatic title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 3,
            }
        },
    )
    _install_update_chat_db(monkeypatch, table, chat_row)

    result = table.update_chat_by_id(
        "chat-1",
        {"title": "Manual title", "history": {"messages": {}}},
        update_title=True,
    )

    assert result is not None
    assert result.title == "Manual title"
    assert result.meta["title_generation"] == {
        "auto_generated": False,
        "last_user_message_count": 3,
    }


def test_automatic_title_update_persists_generation_metadata_without_activity_bump(
    monkeypatch,
):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(title="New Chat", meta={"keep": "value"})
    _install_fake_db(monkeypatch, chat_row)

    result = table.update_chat_title_by_id(
        "chat-1",
        "Evolving topic",
        auto_generated=True,
        last_user_message_count=3,
    )

    assert result is not None
    assert result.title == "Evolving topic"
    assert result.meta == {
        "keep": "value",
        "title_generation": {
            "auto_generated": True,
            "last_user_message_count": 3,
        },
    }
    assert result.updated_at == 100


def test_new_chat_can_mark_localized_placeholder_as_auto_generated(monkeypatch):
    table = chats_mod.ChatTable()
    added = []

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def add(self, row):
            added.append(row)

        def commit(self):
            return None

        def refresh(self, row):
            row.archived = False
            row.pinned = False

    monkeypatch.setattr(chats_mod, "get_db", lambda: FakeDb())
    monkeypatch.setattr(table, "_next_user_chat_timestamp", lambda _db, _user_id: 100)

    result = table.insert_new_chat(
        "user-1",
        chats_mod.ChatForm(
            chat={"title": "新对话", "history": {"messages": {}}},
            title_auto_generated=True,
        ),
    )

    assert result is not None
    assert added[0].title == "新对话"
    assert result.meta["title_generation"] == {
        "auto_generated": True,
        "last_user_message_count": 0,
    }


def test_manual_title_update_persists_protection_metadata(monkeypatch):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Automatic title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 3,
            }
        },
    )
    _install_fake_db(monkeypatch, chat_row)

    result = table.update_chat_title_by_id("chat-1", "My title", auto_generated=False)

    assert result is not None
    assert result.meta["title_generation"] == {
        "auto_generated": False,
        "last_user_message_count": 3,
    }
    assert result.updated_at == 100


def test_automatic_title_refresh_tracks_branch_tip_instead_of_global_turn_count(
    monkeypatch,
):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Main branch title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 6,
                "last_message_id": "main-assistant-6",
            }
        },
    )
    chat_row.chat["history"] = {
        "currentId": "branch-assistant-3",
        "messages": {"branch-assistant-3": {"childrenIds": []}},
    }
    _install_fake_db(monkeypatch, chat_row)

    result = table.update_chat_title_by_id(
        "chat-1",
        "Branch topic",
        auto_generated=True,
        last_user_message_count=3,
        source_message_id="branch-assistant-3",
    )

    assert result is not None
    assert result.title == "Branch topic"
    assert result.meta["title_generation"] == {
        "auto_generated": True,
        "last_user_message_count": 3,
        "last_message_id": "branch-assistant-3",
    }


def test_automatic_title_refresh_rejects_non_current_branch(monkeypatch):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Current title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 3,
                "last_message_id": "old-assistant-3",
            }
        },
    )
    chat_row.chat["history"] = {
        "currentId": "current-assistant-6",
        "messages": {"branch-assistant-3": {"childrenIds": []}},
    }
    commits = _install_fake_db(monkeypatch, chat_row)

    result = table.update_chat_title_by_id(
        "chat-1",
        "Stale branch title",
        auto_generated=True,
        last_user_message_count=3,
        source_message_id="branch-assistant-3",
    )

    assert result is None
    assert chat_row.title == "Current title"
    assert commits == []


@pytest.mark.parametrize("requested_count", [2, 3])
def test_automatic_title_update_suppresses_stale_or_duplicate_counts(
    monkeypatch, requested_count
):
    table = chats_mod.ChatTable()
    chat_row = _fake_chat_row(
        title="Automatic title",
        meta={
            "title_generation": {
                "auto_generated": True,
                "last_user_message_count": 3,
            }
        },
    )
    commits = _install_fake_db(monkeypatch, chat_row)

    result = table.update_chat_title_by_id(
        "chat-1",
        "Stale replacement",
        auto_generated=True,
        last_user_message_count=requested_count,
    )

    assert result is None
    assert chat_row.title == "Automatic title"
    assert commits == []


@pytest.mark.parametrize(
    ("title", "meta", "expected"),
    [
        ("New Chat", {}, True),
        ("Legacy custom title", {}, False),
        ("New Chat", {"title_generation": {"auto_generated": False}}, False),
        (
            "Automatic title",
            {"title_generation": {"auto_generated": True}},
            True,
        ),
    ],
)
def test_auto_title_eligibility_protects_manual_and_legacy_titles(
    title, meta, expected
):
    assert chats_mod.can_auto_generate_chat_title(title, meta, 3) is expected


def test_manual_title_routes_mark_titles_as_manual(monkeypatch):
    from open_webui.routers import chats as chats_router

    calls = []
    existing = _fake_chat_row(title="Old title")
    monkeypatch.setattr(
        chats_router.Chats,
        "get_chat_by_id_and_user_id",
        lambda _chat_id, _user_id: existing,
    )
    monkeypatch.setattr(
        chats_router.Chats,
        "update_chat_title_by_id",
        lambda *args, **kwargs: calls.append((args, kwargs)) or None,
    )
    user = SimpleNamespace(id="user-1")

    asyncio.run(
        chats_router.update_chat_title_by_id(
            "chat-1", chats_mod.ChatTitleForm(title="Manual one"), user
        )
    )
    asyncio.run(
        chats_router.update_chat_by_id(
            "chat-1", chats_mod.ChatForm(chat={"title": "Manual two"}), user
        )
    )

    assert calls == [
        (("chat-1", "Manual one"), {"auto_generated": False}),
        (("chat-1", "Manual two"), {"auto_generated": False}),
    ]
