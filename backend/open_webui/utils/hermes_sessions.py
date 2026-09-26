"""Browse hermes sessions from the other surfaces (Telegram, QQ, CLI) and import
one as a HaloWebUI chat that continues that very session.

The HaloWebUI chat id IS the hermes session id: run_hermes_agent sends
``session_id = chat_id`` to /v1/runs, so a chat created under a hermes session's
id appends to the transcript hermes already keeps for that Telegram/QQ session
(hermes upserts the session row on conflict, source untouched). What is said
here is there when the session is picked up from Telegram again.
"""

import asyncio
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
# hermes clamps its own offset at 1_000_000; asking for more is a 400 waiting
# to happen, so refuse it here where the message can say why.
LIST_OFFSET_MAX = 1_000_000
# One page of ours can need several hermes windows, because the empty shells
# hermes leaves behind are dropped below. Bound the walk so a long stretch of
# them cannot turn one request into an unbounded fan-out: the short page comes
# back with has_more set and the caller asks again.
LIST_MAX_UPSTREAM_ROUNDS = 5
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


def unwrap_session(body: Any) -> dict:
    """The session dict out of whatever envelope hermes answers with.

    ``GET /api/sessions/{id}`` wraps it as ``{"object": "hermes.session",
    "session": {...}}`` (gateway/platforms/api_server.py, _handle_get_session);
    earlier builds answered ``{"data": {...}}``; a bare dict passes through.
    """
    if not isinstance(body, dict):
        return {}
    for key in ("session", "data"):
        inner = body.get(key)
        if isinstance(inner, dict):
            return inner
    return body


async def list_sessions(
    request,
    user,
    *,
    source: str,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
    model_id: Optional[str] = None,
) -> dict:
    """One page of a surface's hermes sessions, newest first.

    Paging is by cursor, not page number: hermes' ``GET /api/sessions`` answers
    ``limit``/``offset``/``has_more`` and no total, so there is no count to
    build a numbered pager from. ``next_offset`` is the hermes offset the page
    stopped at; hand it back to read the next one.

    Two quirks of that endpoint shape the loop below:

    * The empty shells hermes leaves behind when it rotates a session on idle
      are dropped here, so a hermes window of N rows can yield fewer than N
      conversations. We keep reading windows until the page is full rather
      than handing back a page that is short for no visible reason.
    * hermes back-fills every *pinned* conversation the window missed into the
      response (``include_pinned=True`` in its handler), so a pin would repeat
      on every page. They all land on the first page, so later pages drop them
      instead of showing the same conversation twice.
    """
    if source not in SOURCES:
        raise HermesSessionsError(400, f"source must be one of: {', '.join(SOURCES)}")
    limit = max(1, min(int(limit), LIST_LIMIT_MAX))
    offset = int(offset)
    if offset < 0 or offset > LIST_OFFSET_MAX:
        raise HermesSessionsError(400, f"offset must be 0..{LIST_OFFSET_MAX}")
    model = await resolve_hermes_model(request, user, model_id)
    root, headers = _connection(request, user, model)

    kept: list[dict] = []
    seen: set[str] = set()
    cursor = offset
    exhausted = False
    for _ in range(LIST_MAX_UPSTREAM_ROUNDS):
        data = await _get_json(
            f"{root}/api/sessions",
            headers,
            {"source": source, "limit": str(limit), "offset": str(cursor)},
        )
        rows = [row for row in (data.get("data") or []) if isinstance(row, dict)]
        cursor += limit
        for item in rows:
            session_id = item.get("id")
            if not session_id or not SESSION_ID_RE.match(str(session_id)):
                continue
            if session_id in seen:
                continue
            if not (item.get("message_count") or 0):
                continue
            if offset and item.get("pinned"):
                continue
            seen.add(session_id)
            kept.append(item)
        # Back-filled pins arrive past the window, so a *full* response proves
        # nothing; only a short one proves the window ran out. hermes' own
        # has_more discounts pinned rows and can say False while rows remain,
        # so it is read as a hint, never as the only reason to keep going.
        if len(rows) < limit and not data.get("has_more"):
            exhausted = True
            break
        if len(kept) >= limit:
            break

    imported_ids = Chats.get_existing_chat_ids_by_user_id(
        [item["id"] for item in kept], user.id
    )
    sessions = [
        {
            "id": item["id"],
            "source": item.get("source") or source,
            "title": (item.get("title") or "").strip(),
            "preview": (item.get("preview") or "").strip(),
            "message_count": item.get("message_count") or 0,
            "started_at": item.get("started_at"),
            "last_active": item.get("last_active"),
            "model": item.get("model"),
            "imported": item["id"] in imported_ids,
        }
        for item in kept
    ]
    return {
        "sessions": sessions,
        "offset": offset,
        "next_offset": cursor,
        "has_more": not exhausted,
    }


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
    session = unwrap_session(
        await _get_json(f"{root}/api/sessions/{session_id}", headers)
    )
    source = session.get("source")
    if source not in SOURCES:
        raise HermesSessionsError(
            400,
            "only Telegram, QQ and CLI sessions can be imported "
            f"(this one is {source or 'unknown'})",
        )
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


# ------------------------------------------------------------ model options

MODEL_OPTIONS_CACHE_SECONDS = 300
_MODEL_OPTIONS_CACHE: dict = {}
_MODEL_OPTIONS_REFRESH: dict = {}


def _model_option_id(model: Any) -> str:
    if isinstance(model, dict):
        model = model.get("id") or model.get("name")
    return str(model or "").strip()


def condense_model_options(body: Any) -> dict:
    """hermes' GET /api/model/options, reduced to the models its config
    chooses: hermes' default, and for every provider the user set up
    (custom_providers / providers) the model that entry selects.

    The inventory is hermes' whole picker: providers it found through ambient
    credentials (anthropic, openai-api, moa) and every id an endpoint's
    /v1/models advertises — thousands on a relay — none of which the config
    picked. Hermes lists an entry's selected model first; the current
    provider's list is re-probed and sorted, so its choice is the top-level
    `model`."""
    body = body if isinstance(body, dict) else {}
    default_model = _model_option_id(body.get("model"))
    default_provider = str(body.get("provider") or "").strip()

    def is_current(row: dict) -> bool:
        slug = str(row.get("slug") or "").strip()
        return bool(row.get("is_current")) or bool(slug and slug == default_provider)

    providers = []
    seen = set()
    rows = [row for row in body.get("providers") or [] if isinstance(row, dict)]
    # The current provider first: the model it runs is the one to keep when
    # another row repeats it.
    rows.sort(key=lambda row: not is_current(row))
    for provider in rows:
        slug = str(provider.get("slug") or "").strip()
        if not slug or not provider.get("authenticated"):
            continue
        current = is_current(provider)
        if not current and not provider.get("is_user_defined"):
            continue
        if current and default_model:
            model = default_model
        else:
            model = next(
                (
                    model_id
                    for model_id in map(_model_option_id, provider.get("models") or [])
                    if model_id
                ),
                "",
            )
        # `providers: custom: models:` (per-model settings, no endpoint of its
        # own) repeats the default model under a bare "custom" row.
        if not model or model in seen:
            continue
        seen.add(model)
        providers.append(
            {
                "slug": slug,
                "name": str(provider.get("name") or slug),
                "current": current,
                "models": [model],
            }
        )
    providers.sort(key=lambda item: (not item["current"], item["name"].lower()))
    return {
        "model": default_model,
        "provider": default_provider,
        "providers": providers,
    }


async def _fetch_model_options(request, user, model_id: Optional[str]) -> dict:
    model = await resolve_hermes_model(request, user, model_id)
    root, headers = _connection(request, user, model)
    body = await _get_json(f"{root}/api/model/options", headers)
    options = condense_model_options(body)
    _MODEL_OPTIONS_CACHE[user.id] = (time.time() + MODEL_OPTIONS_CACHE_SECONDS, options)
    return options


def _refresh_model_options(request, user, model_id: Optional[str]) -> None:
    """One background refresh per user at a time; a failure keeps the old list."""
    running = _MODEL_OPTIONS_REFRESH.get(user.id)
    if running and not running.done():
        return

    async def refresh():
        try:
            await _fetch_model_options(request, user, model_id)
        except Exception as error:  # the stale list keeps being served
            log.debug("hermes model options refresh failed: %s", error)
        finally:
            _MODEL_OPTIONS_REFRESH.pop(user.id, None)

    _MODEL_OPTIONS_REFRESH[user.id] = asyncio.create_task(refresh())


async def list_model_options(request, user, model_id: Optional[str] = None) -> dict:
    """The models hermes' config offers for a chat (see condense_model_options).

    Hermes answers with its whole picker (~500 KB, 1.5-3 s). After the first
    call the panel gets the last list at once; an expired one is refreshed in
    the background for the next open."""
    cached = _MODEL_OPTIONS_CACHE.get(user.id)
    if cached:
        if cached[0] <= time.time():
            _refresh_model_options(request, user, model_id)
        return cached[1]
    return await _fetch_model_options(request, user, model_id)


# ------------------------------------------------------- background runners

RUNNER_NAMES = ("reclaude", "codex", "agy")
RUNNER_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6,32}(?:-a\d+)*$")
RUNNER_STOP_TIMEOUT_SECONDS = 60


def _hermes_error_message(body: Any) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(error or "")


async def stop_background_runner(request, user, run_id: str) -> dict:
    """Stop a reclaude / codex / agy run one of the user's chats launched.

    The runner is detached (its own scope on the hermes host), so stopping the reply
    that launched it never reached it. Hermes stops it and answers with the notice
    and the short report the chat then shows, like a finished run's; "接着上次" can
    resume its session from there."""
    from open_webui.utils.hermes_notify import HermesNotifyError, show_notification_report
    from open_webui.utils.hermes_runner_progress import (
        clear_runner_progress,
        get_runner_progress,
    )

    entry = get_runner_progress(run_id) if RUNNER_RUN_ID_RE.match(run_id or "") else None
    if not entry or entry.get("user_id") != user.id:
        raise HermesSessionsError(404, "这个后台任务已经结束，或者不是你的对话启动的")
    agent = str(entry.get("agent") or "")
    if agent not in RUNNER_NAMES:
        raise HermesSessionsError(400, f"不认识的后台任务类型：{agent}")
    chat_id = str(entry["chat_id"])
    model = await resolve_hermes_model(request, user, None)
    root, headers = _connection(request, user, model)
    timeout = aiohttp.ClientTimeout(total=RUNNER_STOP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        async with session.post(
            f"{root}/v1/runners/{agent}/{run_id}/stop",
            json={"session_id": chat_id},
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as resp:
            try:
                body = await resp.json(content_type=None)
            except Exception:
                body = {}
            if resp.status == 404:
                raise HermesSessionsError(
                    501, "这个 Hermes 还不能停止后台任务，更新 Hermes 并重启网关后再试"
                )
            if resp.status == 409:
                message = _hermes_error_message(body) or "这个后台任务现在不能停止"
                if "已经结束" in message:
                    clear_runner_progress(run_id)
                raise HermesSessionsError(409, message)
            if resp.status >= 400:
                message = _hermes_error_message(body) or f"HTTP {resp.status}"
                raise HermesSessionsError(502, f"停止失败：{message}")
    clear_runner_progress(run_id)
    shown = True
    try:
        await show_notification_report(
            request,
            chat_id=chat_id,
            content=str(body.get("report") or f"⏹️ {agent} 运行 {run_id} · 已停止"),
            notice=str(body.get("notice") or ""),
            source=f"{agent}-runner",
            run_id=run_id,
            quiet=True,
        )
    except HermesNotifyError as e:
        # A hermes turn is running in that chat: the run is stopped all the same.
        log.info("runner stop report for %s not shown: %s", run_id, e)
        shown = False
    log.info("stopped %s run %s from chat %s", agent, run_id, chat_id)
    return {"stopped": True, "run_id": run_id, "agent": agent, "chat_id": chat_id, "report_shown": shown}

