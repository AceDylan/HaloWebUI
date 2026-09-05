"""The unread flag lives in chat.meta, is scoped to the owner, and does not
reorder the chat list."""

from open_webui.models.chats import ChatForm, Chats
from open_webui.utils.hermes_unread import list_unread_chat_ids, mark_read, mark_unread


def _chat(user_id, title):
    chat = Chats.insert_new_chat(user_id, ChatForm(chat={"title": title}))
    assert chat is not None
    return chat


def test_unread_round_trip_is_scoped_to_the_owner():
    mine = _chat("unread-user-1", "long hermes task")
    other = _chat("unread-user-2", "someone else's chat")

    assert list_unread_chat_ids("unread-user-1") == []
    assert mark_unread(mine.id, "unread-user-1")
    assert list_unread_chat_ids("unread-user-1") == [mine.id]
    assert list_unread_chat_ids("unread-user-2") == []

    # Another user can neither mark nor clear it.
    assert not mark_unread(mine.id, "unread-user-2")
    assert not mark_read(mine.id, "unread-user-2")
    assert list_unread_chat_ids("unread-user-1") == [mine.id]

    assert mark_read(mine.id, "unread-user-1")
    assert list_unread_chat_ids("unread-user-1") == []
    assert mark_read(mine.id, "unread-user-1")  # clearing twice is fine
    assert not mark_unread(other.id, "unread-user-1")


def test_unread_keeps_other_meta_and_updated_at():
    chat = _chat("unread-user-3", "tagged")
    before = Chats.get_chat_by_id(chat.id)

    assert mark_unread(chat.id, "unread-user-3")
    after = Chats.get_chat_by_id(chat.id)
    assert after.meta.get("hermes_unread") is True
    assert after.meta.get("hermes_unread_at")
    assert after.updated_at == before.updated_at

    assert mark_read(chat.id, "unread-user-3")
    cleared = Chats.get_chat_by_id(chat.id)
    assert "hermes_unread" not in cleared.meta
    assert "hermes_unread_at" not in cleared.meta
