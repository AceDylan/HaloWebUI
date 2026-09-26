import asyncio
from types import SimpleNamespace

from open_webui import tasks as task_registry


def test_a_task_belongs_to_the_user_it_was_started_for(monkeypatch):
    from open_webui.models import chats

    monkeypatch.setattr(
        chats.Chats,
        "get_chat_by_id",
        lambda chat_id: SimpleNamespace(user_id="owner") if chat_id == "chat-1" else None,
    )

    async def scenario():
        async def idle():
            await asyncio.sleep(10)

        recorded, _ = task_registry.create_task(idle(), id="local", owner_id="alice")
        by_chat, _ = task_registry.create_task(idle(), id="chat-1")
        unknown, _ = task_registry.create_task(idle(), id="local")
        try:
            assert task_registry.task_owner_id(recorded) == "alice"
            # Created without one: the chat's owner.
            assert task_registry.task_owner_id(by_chat) == "owner"
            # A temporary chat's id says nothing about who started it.
            assert task_registry.task_owner_id(unknown) is None
        finally:
            for task_id in (recorded, by_chat, unknown):
                await task_registry.stop_task(task_id)

    asyncio.run(scenario())
