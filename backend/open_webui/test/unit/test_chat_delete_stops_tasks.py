import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.routers import chats


def _delete(user, chat, tasks):
    stop = AsyncMock()
    with (
        patch.object(chats.Chats, "get_chat_by_id", return_value=chat),
        patch.object(chats.Chats, "delete_chat_by_id", return_value=True),
        patch.object(chats.Chats, "delete_chat_by_id_and_user_id", return_value=True),
        patch.object(chats, "has_permission", return_value=True),
        patch.object(chats, "list_task_ids_by_chat_id", return_value=tasks),
        patch.object(chats, "stop_task", new=stop),
    ):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(USER_PERMISSIONS={})))
        )
        assert asyncio.run(chats.delete_chat_by_id(request, "chat-1", user)) is True
    return stop


def test_deleting_a_chat_stops_the_reply_running_in_it():
    """A hermes task left running kept executing for a chat that was gone."""
    chat = SimpleNamespace(user_id="u1", meta={})
    stop = _delete(SimpleNamespace(id="u1", role="user"), chat, ["task-1"])
    stop.assert_awaited_once_with("task-1")


def test_an_admin_deleting_a_chat_stops_it_too():
    chat = SimpleNamespace(user_id="u2", meta={})
    stop = _delete(SimpleNamespace(id="admin", role="admin"), chat, ["task-1"])
    stop.assert_awaited_once_with("task-1")


def test_someone_elses_chat_is_not_touched():
    chat = SimpleNamespace(user_id="u2", meta={})
    stop = _delete(SimpleNamespace(id="u1", role="user"), chat, ["task-1"])
    stop.assert_not_awaited()
