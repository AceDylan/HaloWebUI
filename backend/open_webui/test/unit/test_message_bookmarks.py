"""收藏: a reply is kept once with a short excerpt, listed newest first with
its chat's title, and dropped from the list when its chat is deleted."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import open_webui.config  # noqa: F401  (runs the migrations: the message_bookmark table)
from open_webui.models.chats import ChatForm, Chats
from open_webui.routers import bookmarks


def _user():
    return SimpleNamespace(id=f"bookmark-{uuid.uuid4().hex[:8]}")


def _chat(user_id: str, title: str, content: str) -> str:
    chat = Chats.insert_new_chat(
        user_id,
        ChatForm(
            chat={
                "title": title,
                "history": {
                    "currentId": "a1",
                    "messages": {
                        "u1": {"id": "u1", "parentId": None, "childrenIds": ["a1"], "role": "user", "content": "q"},
                        "a1": {"id": "a1", "parentId": "u1", "childrenIds": [], "role": "assistant", "content": content},
                    },
                },
            }
        ),
    )
    return chat.id


def _run(coro):
    return asyncio.run(coro)


def test_keep_list_and_remove_a_reply():
    user = _user()
    chat_id = _chat(user.id, "部署", '<details type="reasoning">x</details>**用** `docker compose up -d`' + " 字" * 400)

    first = _run(bookmarks.add_bookmark(bookmarks.BookmarkForm(chat_id=chat_id, message_id="a1"), user=user))
    again = _run(bookmarks.add_bookmark(bookmarks.BookmarkForm(chat_id=chat_id, message_id="a1"), user=user))

    assert again.id == first.id
    assert first.role == "assistant"
    assert first.excerpt.startswith("**用** `docker compose up -d`")
    assert first.excerpt.endswith("…") and len(first.excerpt) <= bookmarks.EXCERPT_CHARS + 1
    assert _run(bookmarks.get_chat_bookmarks(chat_id, user=user)) == ["a1"]

    listed = _run(bookmarks.get_bookmarks(user=user))
    assert [(b.chat_id, b.message_id, b.chat_title) for b in listed] == [(chat_id, "a1", "部署")]

    assert _run(bookmarks.delete_bookmark_by_message(chat_id, "a1", user=user)) is True
    assert _run(bookmarks.get_bookmarks(user=user)) == []


def test_a_missing_message_or_someone_elses_chat_is_refused():
    owner, other = _user(), _user()
    chat_id = _chat(owner.id, "t", "a")

    for user, message_id in ((owner, "nope"), (other, "a1")):
        with pytest.raises(HTTPException) as error:
            _run(bookmarks.add_bookmark(bookmarks.BookmarkForm(chat_id=chat_id, message_id=message_id), user=user))
        assert error.value.status_code == 404


def test_a_deleted_chat_drops_out_of_the_list():
    user = _user()
    chat_id = _chat(user.id, "gone", "a")
    kept = _run(bookmarks.add_bookmark(bookmarks.BookmarkForm(chat_id=chat_id, message_id="a1"), user=user))
    Chats.delete_chat_by_id_and_user_id(chat_id, user.id)

    assert _run(bookmarks.get_bookmarks(user=user)) == []
    assert _run(bookmarks.delete_bookmark(kept.id, user=user)) is False
