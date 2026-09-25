"""Sidebar search covers archived chats: auto-archive moves most of the history
there after 30 days, so a search limited to open chats could not find it. A
tag filter with no results must leave the tag alone."""

import asyncio
import uuid
from types import SimpleNamespace

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat, ChatForm, Chats
from open_webui.models.tags import Tags
from open_webui.routers.chats import search_user_chats


def _user() -> str:
    # The unit DB persists between runs: fresh ids keep earlier runs' rows out.
    return f"search-archived-{uuid.uuid4().hex[:8]}"


def _chat(user_id: str, title: str, *, updated_at: int, archived: bool) -> str:
    chat = Chats.insert_new_chat(user_id, ChatForm(chat={"title": title}))
    assert chat is not None
    with get_db() as db:
        row = db.get(Chat, chat.id)
        row.title = title
        row.archived = archived
        row.updated_at = updated_at
        db.commit()
    return chat.id


def _search(user_id: str, text: str):
    return asyncio.run(search_user_chats(text, page=1, user=SimpleNamespace(id=user_id)))


def test_search_finds_archived_chats_and_marks_them():
    user = _user()
    open_id = _chat(user, "nginx notes open", updated_at=2_000, archived=False)
    archived_id = _chat(user, "nginx notes archived", updated_at=1_000, archived=True)

    results = _search(user, "nginx")

    assert [row.id for row in results] == [open_id, archived_id]
    assert [row.archived for row in results] == [False, True]


def test_a_tag_search_without_results_keeps_the_tag():
    user = _user()
    _chat(user, "untagged", updated_at=1_000, archived=False)
    Tags.insert_new_tag("keepme", user)
    assert Tags.get_tag_by_name_and_user_id("keepme", user) is not None

    assert _search(user, "tag:keepme") == []

    assert Tags.get_tag_by_name_and_user_id("keepme", user) is not None
