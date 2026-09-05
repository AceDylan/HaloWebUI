"""Browse hermes sessions from the other surfaces (Telegram, QQ, CLI) and import
one as a HaloWebUI chat that continues that very session.

The HaloWebUI chat id IS the hermes session id: run_hermes_agent sends
``session_id = chat_id`` to /v1/runs, so a chat created under a hermes session's
id appends to the transcript hermes already keeps for that Telegram/QQ session
(hermes upserts the session row on conflict, source untouched). What is said
here is there when the session is picked up from Telegram again.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, Optional

import aiohttp
from fastapi import HTTPException

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.chats import ChatModel, Chats
from open_webui.utils.hermes_agent import (
    _resolve_hermes_connection,
    _serialize_blocks,
    is_hermes_agent_model,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

# Surfaces a person talks to hermes on. api_server sessions are HaloWebUI chats
# already; subagent/cron/specialist sessions are machinery, not conversations.
SOURCES = ("telegram", "qqbot", "cli")
LIST_LIMIT_DEFAULT = 50
LIST_LIMIT_MAX = 100
IMPORT_MESSAGE_LIMIT = 500
TOOL_PREVIEW_MAX_CHARS = 200
HERMES_SESSION_META_KEY = "hermes_session"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class HermesSessionsError(Exception):
    """A request that cannot be served; carries the HTTP status to answer with."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_RE.match(session_id or ""):
        raise HermesSessionsError(400, "invalid hermes session id")
    return session_id


async def resolve_hermes_model(request, user, model_id: Optional[str] = None) -> dict:
    """The hermes model dict the imported chat answers with.

    Models are user-scoped in this fork: ``get_all_models`` builds the caller's
    list from their own connections, fills ``request.state.MODELS`` (the alias →
    model lookup chat_completion routes with) and returns the list;
    ``app.state.MODELS`` is deliberately never populated. An explicit
    ``model_id`` must resolve to a hermes model; otherwise the first hermes
    model in the caller's list is used (this deployment has exactly one).
    """
    from open_webui.utils.model_identity import resolve_model_from_lookup
    from open_webui.utils.models import get_all_models

    models = await get_all_models(request, user=user) or []
    state = getattr(request, "state", None)
    lookup = getattr(state, "MODELS", None) or {}
    ambiguous = getattr(state, "MODELS_AMBIGUOUS", None) or set()
    if model_id:
        try:
            model = resolve_model_from_lookup(lookup, ambiguous, model_id)
        except HTTPException as e:
            raise HermesSessionsError(e.status_code, str(e.detail))
        if not isinstance(model, dict) or not is_hermes_agent_model(model):
            raise HermesSessionsError(422, f"{model_id} is not a hermes agent model")
        return model
    for model in models:
        if isinstance(model, dict) and is_hermes_agent_model(model):
            return model
    raise HermesSessionsError(422, "no hermes agent model is available")


def _api_root(base_url: str) -> str:
    # _resolve_hermes_connection normalises to .../v1; the session API is /api/...
    return base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url


def _connection(request, user, model) -> tuple[str, dict]:
    base_url, api_key, _ = _resolve_hermes_connection(
        request, user, model, model.get("id")
    )
    if not base_url:
        raise HermesSessionsError(503, "hermes connection is not configured")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return _api_root(base_url), headers


async def _get_json(url: str, headers: dict, params: Optional[dict] = None):
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        async with session.get(
            url, headers=headers, params=params, ssl=AIOHTTP_CLIENT_SESSION_SSL
        ) as resp:
            if resp.status == 404:
                raise HermesSessionsError(404, "hermes session not found")
            if resp.status >= 400:
                body = await resp.text()
                raise HermesSessionsError(
                    502, f"hermes returned {resp.status}: {body[:300]}"
                )
            return await resp.json()


async def list_sessions(
    request,
    user,
    *,
    source: str,
    limit: int = LIST_LIMIT_DEFAULT,
    model_id: Optional[str] = None,
) -> list[dict]:
    if source not in SOURCES:
        raise HermesSessionsError(400, f"source must be one of: {', '.join(SOURCES)}")
    model = await resolve_hermes_model(request, user, model_id)
    root, headers = _connection(request, user, model)
    data = await _get_json(
        f"{root}/api/sessions",
        headers,
        {"source": source, "limit": str(max(1, min(int(limit), LIST_LIMIT_MAX)))},
    )
    sessions = []
    for item in data.get("data") or []:
        session_id = item.get("id")
        if not session_id or not SESSION_ID_RE.match(str(session_id)):
            continue
        # hermes rotates sessions on idle; the empty shells it leaves behind
        # are not conversations.
        if not (item.get("message_count") or 0):
            continue
        sessions.append(
            {
                "id": session_id,
                "source": item.get("source") or source,
                "title": (item.get("title") or "").strip(),
                "preview": (item.get("preview") or "").strip(),
                "message_count": item.get("message_count") or 0,
                "started_at": item.get("started_at"),
                "last_active": item.get("last_active"),
                "model": item.get("model"),
                "imported": Chats.get_chat_by_id_and_user_id(session_id, user.id)
                is not None,
            }
        )
    return sessions


# ---------------------------------------------------------------- transcript


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                parts.append(str(part.get("text") or part.get("content") or ""))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip() if content is not None else ""


def _timestamp(message: dict) -> int:
    raw = message.get("timestamp")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return int(time.time())
    # hermes stores epoch seconds; guard against a millisecond value anyway.
    return int(value / 1000) if value > 1e12 else int(value)


def _tool_calls(raw: Any) -> list[dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [call for call in raw if isinstance(call, dict)]


def _tool_block(index: int, call: dict) -> str:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = function.get("name") or call.get("name") or "tool"
    arguments = function.get("arguments") or call.get("arguments") or ""
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    # Same renderer as live runs, so imported tool cards look identical.
    return _serialize_blocks(
        [
            {
                "type": "tool",
                "id": f"hermes-import-{index}",
                "name": str(name),
                "preview": arguments[:TOOL_PREVIEW_MAX_CHARS],
                "done": True,
                "duration": 0,
            }
        ]
    )


def fold_transcript(messages: list[dict]) -> list[dict]:
    """One chat turn per user message.

    hermes stores a row per model call and per tool result. The chat wants a
    user message followed by a single assistant message, so assistant text and
    tool calls are appended to the current turn in order; tool results and
    system rows are dropped (live runs show tool cards as "Tool Executed" too).
    """
    turns: list[dict] = []
    current: Optional[dict] = None
    tool_index = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            current = {
                "user": _text(message.get("content")),
                "assistant": [],
                "timestamp": _timestamp(message),
                "completed_at": None,
            }
            turns.append(current)
        elif role == "assistant":
            if current is None:
                current = {
                    "user": "",
                    "assistant": [],
                    "timestamp": _timestamp(message),
                    "completed_at": None,
                }
                turns.append(current)
            text = _text(message.get("content"))
            if text:
                current["assistant"].append(text)
            for call in _tool_calls(message.get("tool_calls")):
                tool_index += 1
                current["assistant"].append(_tool_block(tool_index, call))
            current["completed_at"] = _timestamp(message)
    return [turn for turn in turns if turn["user"] or turn["assistant"]]


def build_chat_payload(session: dict, turns: list[dict], model: dict) -> dict:
    """The chat JSON the web client would have produced for these turns."""
    model_id = model["id"]
    model_name = model.get("name") or model_id
    messages: dict[str, dict] = {}
    order: list[str] = []
    parent_id: Optional[str] = None
    for turn in turns:
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        messages[user_id] = {
            "id": user_id,
            "parentId": parent_id,
            "childrenIds": [assistant_id],
            "role": "user",
            "content": turn["user"],
            "timestamp": turn["timestamp"],
            "models": [model_id],
        }
        assistant = {
            "id": assistant_id,
            "parentId": user_id,
            "childrenIds": [],
            "role": "assistant",
            "content": "\n\n".join(turn["assistant"]),
            "model": model_id,
            "modelName": model_name,
            "modelIdx": 0,
            "timestamp": turn["timestamp"],
            "done": True,
        }
        if turn.get("completed_at"):
            assistant["completedAt"] = turn["completed_at"]
        if model.get("model_ref") is not None:
            assistant["model_ref"] = model["model_ref"]
        messages[assistant_id] = assistant
        if parent_id is not None:
            messages[parent_id]["childrenIds"].append(user_id)
        parent_id = assistant_id
        order.extend([user_id, assistant_id])

    title = (session.get("title") or "").strip()
    if not title and turns:
        first_line = turns[0]["user"].strip().splitlines()
        title = first_line[0][:60] if first_line else ""
    return {
        "id": session["id"],
        "title": title or "Hermes session",
        "models": [model_id],
        "params": {},
        "files": [],
        "history": {"messages": messages, "currentId": parent_id},
        "messages": [messages[message_id] for message_id in order],
        "tags": [],
        "timestamp": int(time.time() * 1000),
    }


def _insert_chat_with_id(user_id: str, chat_id: str, payload: dict, meta: dict) -> ChatModel:
    # Same row builder as Chats.import_chat; only the id is ours.
    with get_db() as db:
        row = Chats._build_chat_row(
            user_id=user_id,
            chat_payload=payload,
            meta=meta,
            now=Chats._next_user_chat_timestamp(db, user_id),
        )
        row.id = chat_id
        db.add(row)
        db.commit()
        db.refresh(row)
        return ChatModel.model_validate(row)


async def import_session(
    request, user, *, session_id: str, model_id: Optional[str] = None
) -> dict:
    validate_session_id(session_id)
    existing = Chats.get_chat_by_id_and_user_id(session_id, user.id)
    if existing is not None:
        return {
            "chat_id": existing.id,
            "title": existing.title,
            "created": False,
            "imported_turns": 0,
        }
    if Chats.get_chat_by_id(session_id) is not None:
        raise HermesSessionsError(409, "this hermes session is already another user's chat")

    model = await resolve_hermes_model(request, user, model_id)
    root, headers = _connection(request, user, model)
    session = await _get_json(f"{root}/api/sessions/{session_id}", headers)
    if isinstance(session.get("data"), dict):
        session = session["data"]
    if session.get("source") not in SOURCES:
        raise HermesSessionsError(400, "only Telegram, QQ and CLI sessions can be imported")
    page = await _get_json(
        f"{root}/api/sessions/{session_id}/messages",
        headers,
        {"order": "oldest", "limit": str(IMPORT_MESSAGE_LIMIT), "offset": "0"},
    )
    turns = fold_transcript(page.get("data") or [])
    if not turns:
        raise HermesSessionsError(422, "hermes session has no conversation to import")

    payload = build_chat_payload({**session, "id": session_id}, turns, model)
    meta = {
        HERMES_SESSION_META_KEY: {
            "session_id": session_id,
            "source": session.get("source"),
            "imported_at": int(time.time()),
            "imported_turns": len(turns),
        }
    }
    chat = _insert_chat_with_id(user.id, session_id, payload, meta)
    log.info(
        f"imported hermes {session.get('source')} session {session_id} "
        f"as chat for user {user.id} ({len(turns)} turns)"
    )
    return {
        "chat_id": chat.id,
        "title": chat.title,
        "created": True,
        "imported_turns": len(turns),
    }
