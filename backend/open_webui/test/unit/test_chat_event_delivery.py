"""Run the production emitter with fake sockets/storage, without loading RAG.

The socket module's import tree initializes optional vector DB dependencies;
extract only its public emitter and file merge helper for this transport test.
"""

import ast
import asyncio
import copy
import json
import pathlib
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, status


@pytest.mark.parametrize(
    "event_type", ["files", "chat:message:files", "message", "replace"]
)
def test_events_are_persisted_before_broadcast_and_sent_once_per_device(event_type):
    path = pathlib.Path(__file__).resolve().parents[2] / "socket" / "main.py"
    source = ast.parse(path.read_text())
    functions = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"get_event_emitter", "_merge_message_files"}
    ]
    saved = {"content": "old", "files": []}
    emitted = []
    data = (
        {"files": [{"type": "image", "url": "/new.png"}]}
        if "files" in event_type
        else {"content": "new"}
    )

    def upsert(_chat_id, _message_id, patch):
        saved.update(copy.deepcopy(patch))

    async def emit(_name, event, to):
        if "files" in event_type:
            assert saved["files"] == data["files"]
        else:
            assert saved["content"] == ("oldnew" if event_type == "message" else "new")
        emitted.append((to, event))

    namespace = {
        "json": json,
        "uuid": uuid,
        "USER_POOL": {
            "owner": ["device-A", "device-A", "device-B"],
            "other": ["device-C"],
        },
        "sio": SimpleNamespace(emit=emit),
        "Chats": SimpleNamespace(
            get_message_by_id_and_message_id=lambda *_: saved,
            upsert_message_to_chat_by_id_and_message_id=upsert,
        ),
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    emitter = namespace["get_event_emitter"](
        {
            "user_id": "owner",
            "chat_id": "chat",
            "message_id": "answer",
            "session_id": "device-A",
        }
    )
    asyncio.run(emitter({"type": event_type, "data": data}))
    assert {to for to, _ in emitted} == {"device-A", "device-B"}
    assert len(emitted) == 2
    assert len({event["event_id"] for _, event in emitted}) == 1
    assert emitted[0][1]["chat_id"] == "chat"


@pytest.mark.parametrize("socket_fails", [False, True])
def test_save_endpoint_passes_snapshot_and_notifies_only_after_persistence(
    socket_fails,
):
    path = pathlib.Path(__file__).resolve().parents[2] / "routers" / "chats.py"
    source = ast.parse(path.read_text())
    endpoint = next(
        node
        for node in source.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_chat_by_id"
    )
    endpoint.decorator_list = []
    previous = {"history": {"messages": {"old": {"content": "old"}}}}
    incoming = {"history": {"messages": {"old": {"content": "edited"}}}}
    stored = []
    notified = []

    async def normalize(chat, _user):
        return chat, []

    def update(chat_id, chat, **options):
        assert options["base_chat"] == previous
        stored.append(chat)
        return SimpleNamespace(id=chat_id, chat=chat)

    def get_emitter(metadata, update_db=True):
        assert metadata == {"user_id": "owner", "chat_id": "chat"}
        assert update_db is False

        async def emit(event):
            assert stored
            notified.append(event)
            if socket_fails:
                raise ConnectionError("test socket offline")

        return emit

    namespace = {
        "Depends": lambda _dependency: None,
        "get_verified_user": lambda: None,
        "Chats": SimpleNamespace(
            get_chat_by_id_and_user_id=lambda _id, _owner: SimpleNamespace(
                chat=copy.deepcopy(previous)
            ),
            update_chat_by_id=update,
        ),
        "_normalize_chat_payload_images": normalize,
        "_chat_response": lambda chat: chat,
        "get_event_emitter": get_emitter,
        "log": SimpleNamespace(warning=Mock()),
        "HTTPException": HTTPException,
        "status": status,
        "ERROR_MESSAGES": SimpleNamespace(ACCESS_PROHIBITED="access prohibited"),
    }
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            endpoint,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    result = asyncio.run(
        namespace["update_chat_by_id"](
            "chat",
            SimpleNamespace(chat=incoming, base_chat=previous),
            SimpleNamespace(id="owner"),
        )
    )
    assert result.chat == incoming
    assert notified == [{"type": "chat:reload", "data": {"reason": "chat_saved"}}]
    assert namespace["log"].warning.call_count == int(socket_fails)

    # The optional snapshot field does not bypass the existing ownership check.
    namespace["Chats"].get_chat_by_id_and_user_id = lambda *_: None
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            namespace["update_chat_by_id"](
                "chat",
                SimpleNamespace(chat=incoming, base_chat=previous),
                SimpleNamespace(id="other"),
            )
        )
    assert error.value.status_code == 401
    assert len(stored) == 1
