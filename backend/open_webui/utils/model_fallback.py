"""Retry once, then answer with a configured stand-in model, when an upstream
chat model fails before it starts answering.

Every chat-model failure in the last 30 days of this deployment was an upstream
HTTP 503 (claude-chat, grok-search, deepseek-chat), each ending as a red error
bubble the person had to notice and re-send by hand. Those failures are
transient and arrive before any token streamed, so they are safe to retry and,
if the model stays down, to hand to another model.

Configuration lives on the model: ``info.meta.fallback_model_id`` (a selection
id, set in the model editor). No fallback is ever guessed. Only one hop is made,
hermes runs and direct connections are left alone, and mid-stream failures are
not retried (the upstream may already have answered and billed).
"""

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from open_webui.utils.hermes_agent import is_hermes_agent_model
from open_webui.utils.model_identity import resolve_model_from_lookup

log = logging.getLogger(__name__)

RETRY_DELAY_SECONDS = 1.5
TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
FALLBACK_META_KEY = "fallback_model_id"

# Connection-level failures by class name, so this module does not import every
# HTTP client the routers use (aiohttp, httpx, stdlib).
_CONNECTION_ERROR_NAMES = frozenset(
    {
        "ClientConnectorError",
        "ClientConnectionError",
        "ClientOSError",
        "ServerDisconnectedError",
        "ServerTimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutError",
    }
)


def error_status(error) -> Optional[int]:
    """HTTP status carried by an exception (FastAPI, aiohttp, httpx shapes)."""
    for candidate in (
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _response_lost(error) -> bool:
    """The fork's "upstream answered but the relay dropped it" family: retrying
    could bill twice, so it is never retried here."""
    try:
        from open_webui.utils.middleware import _is_api_response_disconnected_error
    except Exception:
        return False
    try:
        detail = getattr(error, "detail", None)
        return bool(
            _is_api_response_disconnected_error(str(detail if detail is not None else error))
        )
    except Exception:
        return False


def transient_reason(error) -> Optional[str]:
    """Why this failure is worth another attempt ("HTTP 503", "超时", "连接失败"),
    or None when it is not (4xx client errors, auth, response lost, unknown)."""
    if error is None or _response_lost(error):
        return None
    status = error_status(error)
    if status is not None:
        return f"HTTP {status}" if status in TRANSIENT_STATUSES else None
    if isinstance(error, asyncio.TimeoutError):
        return "超时"
    if type(error).__name__ in _CONNECTION_ERROR_NAMES:
        return "连接失败"
    return None


def model_display_name(model) -> str:
    model = model if isinstance(model, dict) else {}
    return str(model.get("name") or model.get("id") or "?")


def configured_fallback_id(model) -> Optional[str]:
    if not isinstance(model, dict):
        return None
    meta = ((model.get("info") or {}).get("meta") or {}) if isinstance(model.get("info"), dict) else {}
    value = meta.get(FALLBACK_META_KEY)
    value = str(value).strip() if value is not None else ""
    return value or None


def fallback_eligible(model, metadata: dict) -> bool:
    """A normal chat turn on a provider model: not hermes (an agent run is not a
    completion), not a direct connection, and only real chat messages."""
    if not isinstance(model, dict) or is_hermes_agent_model(model):
        return False
    metadata = metadata or {}
    if metadata.get("direct"):
        return False
    return bool(metadata.get("chat_id") and metadata.get("message_id"))


def resolve_fallback_model(request, model) -> Optional[dict]:
    """The model dict to answer with instead, resolved through the caller's own
    registry (request.state.MODELS), or None when nothing usable is configured."""
    fallback_id = configured_fallback_id(model)
    if not fallback_id:
        return None
    state = getattr(request, "state", None)
    lookup = getattr(state, "MODELS", None) or {}
    ambiguous = getattr(state, "MODELS_AMBIGUOUS", None) or set()
    try:
        fallback = resolve_model_from_lookup(lookup, ambiguous, fallback_id)
    except HTTPException:
        return None
    if not isinstance(fallback, dict):
        log.warning(
            "fallback model %s for %s is not available to this user", fallback_id, model.get("id")
        )
        return None
    if fallback.get("id") == model.get("id") or is_hermes_agent_model(fallback):
        return None
    return fallback
