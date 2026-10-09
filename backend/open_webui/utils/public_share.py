"""What a shared-chat link shows to someone who is not signed in.

The share snapshot is a full copy of the chat payload: system prompt, composer
draft, hermes run ids and dispatch routing ride along with the messages. A
public link gets the conversation only — the title, the message tree with the
fields the read-only view renders, and file references rewritten to the
share-scoped image route (an anonymous visitor has no session to fetch
``/api/v1/files/<id>/content`` with).
"""

import re
from typing import Any

# Fields of a message the read-only chat view renders. Anything else (hermes run
# ids, dispatch routing, connection refs, user context) stays private.
_MESSAGE_FIELDS = frozenset(
    {
        "id",
        "parentId",
        "childrenIds",
        "role",
        "content",
        "timestamp",
        "model",
        "modelName",
        "modelIdx",
        "models",
        "user",
        "done",
        "completedAt",
        "error",
        "status",
        "statusHistory",
        "sources",
        "citations",
        "usage",
        "files",
        "stopped",
        "stoppedByUser",
        "code_executions",
        "followUps",
        "discussion",
        "instruction",
        "editCount",
        "lastEditAt",
    }
)
_FILE_FIELDS = frozenset({"type", "id", "url", "name", "size", "content_type"})

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# `/api/v1/files/<id>` with an optional origin in front; the rest of the path
# (`/content`) is kept so both link forms keep working.
_FILE_REF_RE = re.compile(rf"(?:https?://[^\s\"'()<>/]+)?/api/v1/files/({_UUID})(?=[/?#\s\"'()<>\]]|$)")
# Bitmap images only: an SVG opened directly runs script on this origin.
_PUBLIC_IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/avif", "image/bmp"}
)


def public_share_file_path(share_id: str, file_id: str) -> str:
    return f"/api/v1/chats/public/share/{share_id}/files/{file_id}"


def is_public_share_image_type(content_type: Any) -> bool:
    return (
        isinstance(content_type, str)
        and content_type.split(";", 1)[0].strip().lower() in _PUBLIC_IMAGE_TYPES
    )


def _pick(source: dict, fields: frozenset) -> dict:
    return {key: value for key, value in source.items() if key in fields}


def _public_message(message: dict) -> dict:
    picked = _pick(message, _MESSAGE_FIELDS)
    if isinstance(picked.get("files"), list):
        picked["files"] = [
            _pick(item, _FILE_FIELDS) for item in picked["files"] if isinstance(item, dict)
        ]
    return picked


def _public_history(chat: dict) -> dict:
    history = chat.get("history") if isinstance(chat.get("history"), dict) else {}
    messages = history.get("messages") if isinstance(history.get("messages"), dict) else {}
    return {
        "messages": {
            str(key): _public_message(message)
            for key, message in messages.items()
            if isinstance(message, dict)
        },
        "currentId": history.get("currentId"),
    }


def _map_strings(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [_map_strings(item, transform) for item in value]
    if isinstance(value, dict):
        return {key: _map_strings(item, transform) for key, item in value.items()}
    return value


def build_public_shared_chat(chat: Any, share_id: str) -> tuple[dict, set[str]]:
    """Return the public view of a share snapshot payload and the file ids it
    references (the only files the share-scoped image route may serve)."""
    chat = chat if isinstance(chat, dict) else {}
    models = chat.get("models")
    payload = {
        "title": chat.get("title") if isinstance(chat.get("title"), str) else "",
        "models": [model for model in models if isinstance(model, str)]
        if isinstance(models, list)
        else [],
        "timestamp": chat.get("timestamp"),
        "history": _public_history(chat),
    }

    file_ids: set[str] = set()

    def rewrite(text: str) -> str:
        def replace(match: re.Match) -> str:
            file_id = match.group(1).lower()
            file_ids.add(file_id)
            return public_share_file_path(share_id, file_id)

        return _FILE_REF_RE.sub(replace, text)

    return _map_strings(payload, rewrite), file_ids
