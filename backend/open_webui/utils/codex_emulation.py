"""Codex CLI request emulation for GPT models on the Responses API.

This module makes outbound GPT (model prefix ``gpt``) requests on the Responses
API path look like requests issued by the official Codex CLI (``codex-tui``),
so that upstream relays that special-case the Codex client treat web requests
the same way.

Design constraints (see the conversation that introduced this module):
- Envelope-only: we add Codex-style headers and meta body fields. We DO NOT
  inject the Codex coding-agent system prompt or its ``exec`` tools, and we keep
  the caller's own ``instructions`` / ``input`` untouched. Chat behaviour is
  preserved.
- All additions to the body are additive: a field already present on the payload
  (set by the user/model params/custom_params) always wins.
- Per-request identifiers are generated dynamically as UUIDv7, mirroring the
  Codex CLI. The session/thread id is kept stable per conversation (keyed by
  ``chat_id``) so ``prompt_cache_key`` stays stable across turns, exactly like a
  real Codex session.

Tunables are the module-level constants below.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from open_webui.env import DATA_DIR

# ── Tunables ────────────────────────────────────────────────────────────────
# Static header values copied from the Codex CLI fingerprint.
CODEX_ORIGINATOR = "codex-tui"
CODEX_BETA_FEATURES = "remote_compaction_v2"
# ``sandbox`` reported in x-codex-turn-metadata. The emulated UA is a Windows
# WindowsTerminal codex-tui build, so the matching value is "windows_elevated".
CODEX_SANDBOX = "windows_elevated"
CODEX_REQUEST_KIND = "turn"

# Default GPT-5-family body params, injected ONLY when the payload does not
# already carry them. Set to None to disable injecting that field by default.
CODEX_DEFAULT_REASONING_EFFORT: Optional[str] = "medium"
CODEX_DEFAULT_TEXT_VERBOSITY: Optional[str] = "low"

# Where the stable installation id is persisted (mirrors a per-machine Codex id).
_INSTALLATION_ID_FILE = DATA_DIR / "codex_emulation.json"

# Bounded in-process cache of chat_id -> session_id (stable per conversation).
_SESSION_CACHE_MAX = 5000

_lock = threading.Lock()
_installation_id: Optional[str] = None
_session_by_chat: "OrderedDict[str, str]" = OrderedDict()


def _uuid7() -> str:
    """Generate a UUIDv7 string (time-ordered), not available in the stdlib."""
    unix_ms = int(time.time() * 1000)
    ts = unix_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    b = bytearray(ts + rand)
    b[6] = (b[6] & 0x0F) | 0x70  # version 7
    b[8] = (b[8] & 0x3F) | 0x80  # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(b)))


def _load_installation_id() -> str:
    global _installation_id
    if _installation_id:
        return _installation_id

    with _lock:
        if _installation_id:
            return _installation_id

        value: Optional[str] = None
        try:
            if _INSTALLATION_ID_FILE.exists():
                data = json.loads(_INSTALLATION_ID_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    candidate = data.get("installation_id")
                    if isinstance(candidate, str) and candidate.strip():
                        value = candidate.strip()
        except Exception:
            value = None

        if not value:
            value = str(uuid.uuid4())
            try:
                _INSTALLATION_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
                _INSTALLATION_ID_FILE.write_text(
                    json.dumps({"installation_id": value}), encoding="utf-8"
                )
            except Exception:
                # Persistence is best-effort; a process-stable id is still fine.
                pass

        _installation_id = value
        return _installation_id


def _session_id_for_chat(chat_id: Optional[str]) -> str:
    """Return a UUIDv7 session id, stable per ``chat_id`` while it stays cached."""
    if not chat_id:
        return _uuid7()

    key = str(chat_id)
    with _lock:
        existing = _session_by_chat.get(key)
        if existing is not None:
            _session_by_chat.move_to_end(key)
            return existing

        session_id = _uuid7()
        _session_by_chat[key] = session_id
        while len(_session_by_chat) > _SESSION_CACHE_MAX:
            _session_by_chat.popitem(last=False)
        return session_id


def is_codex_emulation_target(model_id: Optional[str]) -> bool:
    """True when the (prefix-stripped) upstream model should emulate Codex."""
    return isinstance(model_id, str) and model_id.lower().startswith("gpt")


@dataclass
class CodexRequestContext:
    installation_id: str
    session_id: str
    thread_id: str
    turn_id: str
    window_id: str
    turn_started_at_unix_ms: int

    def turn_metadata_json(self) -> str:
        # Key order mirrors the captured Codex CLI x-codex-turn-metadata header.
        return json.dumps(
            {
                "installation_id": self.installation_id,
                "session_id": self.session_id,
                "thread_id": self.thread_id,
                "turn_id": self.turn_id,
                "window_id": self.window_id,
                "request_kind": CODEX_REQUEST_KIND,
                "sandbox": CODEX_SANDBOX,
                "turn_started_at_unix_ms": self.turn_started_at_unix_ms,
            },
            ensure_ascii=False,
        )

    def client_metadata(self) -> dict:
        return {
            "x-codex-installation-id": self.installation_id,
            "x-codex-window-id": self.window_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "x-codex-turn-metadata": self.turn_metadata_json(),
            "turn_id": self.turn_id,
        }


def build_codex_request_context(metadata: Optional[dict]) -> CodexRequestContext:
    chat_id = None
    if isinstance(metadata, dict):
        chat_id = metadata.get("chat_id") or metadata.get("chatId")

    session_id = _session_id_for_chat(chat_id)
    return CodexRequestContext(
        installation_id=_load_installation_id(),
        session_id=session_id,
        # Codex reuses the session id as the thread id within a session.
        thread_id=session_id,
        turn_id=_uuid7(),
        window_id=f"{session_id}:0",
        turn_started_at_unix_ms=int(time.time() * 1000),
    )


def build_codex_headers(
    headers: dict,
    ctx: CodexRequestContext,
    *,
    streaming: bool,
) -> dict:
    """Merge Codex CLI headers into an existing headers dict (mutated in place).

    ``User-Agent``/``Authorization``/``Content-Type`` are left as set by the
    caller (the GPT UA override already produces the codex-tui UA).
    """
    headers["originator"] = CODEX_ORIGINATOR
    headers["session-id"] = ctx.session_id
    headers["session_id"] = ctx.session_id
    headers["thread-id"] = ctx.thread_id
    headers["x-session-id"] = ctx.session_id
    headers["x-client-request-id"] = ctx.session_id
    headers["x-codex-beta-features"] = CODEX_BETA_FEATURES
    headers["x-codex-window-id"] = ctx.window_id
    headers["x-codex-turn-metadata"] = ctx.turn_metadata_json()
    headers["Accept-Encoding"] = "identity"

    # Codex always streams; only claim SSE when we actually stream so non-stream
    # callers (e.g. title generation) still get a JSON body back.
    if streaming:
        headers["Accept"] = "text/event-stream"

    return headers


def augment_codex_responses_payload(
    payload: dict,
    ctx: CodexRequestContext,
) -> dict:
    """Add Codex-style meta fields to a Responses payload (additive only)."""
    if not isinstance(payload, dict):
        return payload

    # Stateless, like Codex (relays forwarding to the ChatGPT backend require it).
    payload.setdefault("store", False)

    include = payload.get("include")
    if not isinstance(include, list):
        include = []
    if "reasoning.encrypted_content" not in include:
        include = [*include, "reasoning.encrypted_content"]
    payload["include"] = include

    if CODEX_DEFAULT_REASONING_EFFORT:
        reasoning = payload.get("reasoning")
        if not isinstance(reasoning, dict):
            reasoning = {}
        if not reasoning.get("effort"):
            reasoning["effort"] = CODEX_DEFAULT_REASONING_EFFORT
        payload["reasoning"] = reasoning

    if CODEX_DEFAULT_TEXT_VERBOSITY:
        text = payload.get("text")
        if not isinstance(text, dict):
            text = {}
        if not text.get("verbosity"):
            text["verbosity"] = CODEX_DEFAULT_TEXT_VERBOSITY
        payload["text"] = text

    # tool_choice / parallel_tool_calls only make sense alongside tools.
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        payload.setdefault("tool_choice", "auto")
        payload.setdefault("parallel_tool_calls", True)

    payload.setdefault("prompt_cache_key", ctx.session_id)
    payload["client_metadata"] = ctx.client_metadata()

    return payload
