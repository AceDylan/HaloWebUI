"""Synchronize Hermes LLM requests with HaloWebUI's reasoning-effort setting."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen


DEFAULT_SYNC_URL = "http://127.0.0.1:3000/api/v1/haloclaw/runtime/reasoning-effort"
VALID_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
SUPPORTED_API_MODES = frozenset({"codex_responses", "chat_completions"})
REQUEST_TIMEOUT_SECONDS = 0.75
MAX_RESPONSE_BYTES = 1024


def _reasoning_effort_url() -> str | None:
    url = os.environ.get("HALOWEBUI_REASONING_SYNC_URL", DEFAULT_SYNC_URL).strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _fetch_reasoning_effort() -> str | None:
    """Fetch and validate one fresh value; no result is cached."""
    url = _reasoning_effort_url()
    if url is None:
        return None

    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if getattr(response, "status", 200) != 200:
                return None
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        # Endpoint parsing/network failures must never block the model request.
        return None

    if not isinstance(payload, dict):
        return None
    effort = payload.get("reasoning_effort")
    return effort if effort in VALID_REASONING_EFFORTS else None


def sync_reasoning_effort(**kwargs: Any) -> dict[str, Any] | None:
    """Replace only the outbound request's reasoning-effort field."""
    api_mode = kwargs.get("api_mode")
    if api_mode not in SUPPORTED_API_MODES:
        return None

    request = kwargs.get("request")
    if not isinstance(request, dict):
        return None

    effort = _fetch_reasoning_effort()
    if effort is None:
        return None

    updated_request = dict(request)
    if api_mode == "codex_responses":
        existing_reasoning = request.get("reasoning")
        reasoning = (
            dict(existing_reasoning) if isinstance(existing_reasoning, dict) else {}
        )
        reasoning["effort"] = effort
        updated_request["reasoning"] = reasoning
    else:
        updated_request["reasoning_effort"] = effort

    return {
        "request": updated_request,
        "source": "halowebui-reasoning-sync",
        "reason": "applied current HaloWebUI Message Gateway reasoning effort",
    }


def register(ctx: Any) -> None:
    ctx.register_middleware("llm_request", sync_reasoning_effort)
