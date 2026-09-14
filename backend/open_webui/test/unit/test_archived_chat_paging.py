"""Archived chat list paging: the modal asks for one page at a time, so the
query has to slice in the database, hold a stable order across pages, filter on
the title server-side, and count rows without reading the conversations."""

import uuid

import pytest

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat, ChatForm, ChatTitleIdResponse, Chats


def _user(label: str) -> str:
    # The unit DB persists between runs: fresh ids keep earlier runs' rows out.
    return f"archived-paging-{label}-{uuid.uuid4().hex[:8]}"


def _chat(user_id: str, title: str, *, updated_at: int, archived: bool = True) -> str:
    chat = Chats.insert_new_chat(user_id, ChatForm(chat={"title": title}))
    assert chat is not None
    with get_db() as db:
        row = db.get(Chat, chat.id)
        row.title = title
        row.archived = archived
        row.updated_at = updated_at
        db.commit()
    return chat.id


def _titles(rows) -> list[str]:
    return [row.title for row in rows]


@pytest.fixture
def archived_user() -> str:
    """20 archived chats, newest activity last created, plus rows that must not
    show up: an unarchived chat and another account's archived chat."""
    user = _user("list")
    for index in range(20):
        _chat(user, f"chat {index:02d}", updated_at=1_000 + index)
    _chat(user, "still open", updated_at=9_999, archived=False)
    _chat(_user("other"), "theirs", updated_at=9_999)
    return user


def test_a_page_holds_only_its_own_slice(archived_user):
    first = Chats.get_archived_chat_list_by_user_id(archived_user, 0, 8)
    second = Chats.get_archived_chat_list_by_user_id(archived_user, 8, 8)
    third = Chats.get_archived_chat_list_by_user_id(archived_user, 16, 8)

    assert _titles(first) == [f"chat {i:02d}" for i in range(19, 11, -1)]
    assert _titles(second) == [f"chat {i:02d}" for i in range(11, 3, -1)]
    assert _titles(third) == [f"chat {i:02d}" for i in range(3, -1, -1)]

    ids = [row.id for row in first + second + third]
    assert len(ids) == len(set(ids)) == 20  # every chat once, none skipped


def test_paging_past_the_end_and_a_zero_width_page_are_empty(archived_user):
    assert Chats.get_archived_chat_list_by_user_id(archived_user, 20, 8) == []
    assert Chats.get_archived_chat_list_by_user_id(archived_user, 500, 8) == []
    # A partial last page stops at the real end rather than wrapping.
    assert len(Chats.get_archived_chat_list_by_user_id(archived_user, 18, 8)) == 2


def test_a_negative_skip_reads_from_the_start(archived_user):
    assert _titles(Chats.get_archived_chat_list_by_user_id(archived_user, -5, 3)) == [
        "chat 19",
        "chat 18",
        "chat 17",
    ]


def test_rows_sharing_a_timestamp_still_page_exactly_once():
    user = _user("ties")
    ids = {_chat(user, f"same {index}", updated_at=4_242) for index in range(7)}

    seen = []
    for skip in range(0, 8, 2):
        seen.extend(row.id for row in Chats.get_archived_chat_list_by_user_id(user, skip, 2))

    assert len(seen) == len(set(seen)) == 7
    assert set(seen) == ids


def test_only_the_caller_s_archived_chats_are_listed(archived_user):
    rows = Chats.get_archived_chat_list_by_user_id(archived_user, 0, 200)

    assert len(rows) == 20
    assert "still open" not in _titles(rows)
    assert "theirs" not in _titles(rows)


def test_a_page_carries_list_columns_only(archived_user):
    row = Chats.get_archived_chat_list_by_user_id(archived_user, 0, 1)[0]

    assert isinstance(row, ChatTitleIdResponse)
    # The conversation itself never leaves the database for this list.
    assert not hasattr(row, "chat")
    assert row.title == "chat 19"
    assert row.updated_at == 1_019
    assert row.created_at > 0


def test_the_title_query_filters_and_pages_server_side():
    user = _user("query")
    for index in range(5):
        _chat(user, f"Holiday plan {index}", updated_at=2_000 + index)
    for index in range(3):
        _chat(user, f"Invoice {index}", updated_at=3_000 + index)

    assert _titles(Chats.get_archived_chat_list_by_user_id(user, 0, 2, query="holiday")) == [
        "Holiday plan 4",
        "Holiday plan 3",
    ]
    assert _titles(Chats.get_archived_chat_list_by_user_id(user, 4, 2, query="holiday")) == [
        "Holiday plan 0"
    ]
    assert Chats.get_archived_chat_list_by_user_id(user, 0, 5, query="nothing here") == []
    # Blank and whitespace-only searches mean "no filter", like an empty box.
    assert len(Chats.get_archived_chat_list_by_user_id(user, 0, 50, query="   ")) == 8
    assert len(Chats.get_archived_chat_list_by_user_id(user, 0, 50, query=None)) == 8


def test_the_count_matches_what_the_pages_return(archived_user):
    assert Chats.count_archived_chats_by_user_id(archived_user) == 20
    assert Chats.count_archived_chats_by_user_id(archived_user, query="chat 1") == 10  # 10..19
    assert Chats.count_archived_chats_by_user_id(archived_user, query="still open") == 0
    assert Chats.count_archived_chats_by_user_id(_user("empty")) == 0


def test_unarchiving_moves_a_chat_out_of_the_list_and_the_count(archived_user):
    chat_id = Chats.get_archived_chat_list_by_user_id(archived_user, 0, 1)[0].id

    Chats.toggle_chat_archive_by_id(chat_id)

    assert Chats.count_archived_chats_by_user_id(archived_user) == 19
    assert chat_id not in {
        row.id for row in Chats.get_archived_chat_list_by_user_id(archived_user, 0, 50)
    }


def test_the_endpoint_turns_a_page_number_into_a_slice(archived_user):
    """``GET /chats/archived`` is what the modal calls; ``page`` is 1-based and
    ``limit`` decides how wide a page is."""
    import asyncio
    from types import SimpleNamespace

    from open_webui.routers.chats import (
        get_archived_session_user_chat_count,
        get_archived_session_user_chat_list,
    )

    user = SimpleNamespace(id=archived_user)

    def page(number, limit=8, query=None):
        return asyncio.run(
            get_archived_session_user_chat_list(
                user=user, skip=0, limit=limit, page=number, query=query
            )
        )

    assert _titles(page(1)) == [f"chat {i:02d}" for i in range(19, 11, -1)]
    assert _titles(page(2)) == [f"chat {i:02d}" for i in range(11, 3, -1)]
    assert len(page(3)) == 4  # the last page is short, not padded
    assert page(4) == []  # past the end
    assert _titles(page(1, limit=2, query="chat 0")) == ["chat 09", "chat 08"]

    # No page number still answers with the server's own first page.
    default = asyncio.run(
        get_archived_session_user_chat_list(user=user, skip=0, limit=50, page=None, query=None)
    )
    assert len(default) == 20

    def count(query):
        return asyncio.run(get_archived_session_user_chat_count(user=user, query=query))

    assert count(None) == {"count": 20}
    assert count("chat 0") == {"count": 10}
