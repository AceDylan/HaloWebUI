import json
import uuid

from open_webui.utils import codex_emulation as ce


def test_uuid7_is_valid_version_7():
    u = uuid.UUID(ce._uuid7())
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_session_id_is_stable_per_chat():
    a1 = ce._session_id_for_chat("chat-stable-A")
    a2 = ce._session_id_for_chat("chat-stable-A")
    b = ce._session_id_for_chat("chat-stable-B")
    assert a1 == a2
    assert a1 != b
    # No chat id -> fresh id each call.
    assert ce._session_id_for_chat(None) != ce._session_id_for_chat(None)


def test_context_relationships():
    ctx = ce.build_codex_request_context({"chat_id": "chat-ctx"})
    assert ctx.thread_id == ctx.session_id
    assert ctx.window_id == f"{ctx.session_id}:0"
    assert ctx.turn_id != ctx.session_id
    uuid.UUID(ctx.installation_id)  # valid uuid


def test_build_codex_headers_streaming():
    ctx = ce.build_codex_request_context({"chat_id": "chat-h"})
    headers = ce.build_codex_headers(
        {"Accept": "application/json", "Authorization": "Bearer x"},
        ctx,
        streaming=True,
    )
    assert headers["Accept"] == "text/event-stream"
    assert headers["Accept-Encoding"] == "identity"
    assert headers["originator"] == "codex-tui"
    assert (
        headers["session-id"]
        == headers["session_id"]
        == headers["x-session-id"]
        == headers["x-client-request-id"]
        == ctx.session_id
    )
    assert headers["thread-id"] == ctx.thread_id
    assert headers["x-codex-window-id"] == ctx.window_id
    assert headers["x-codex-beta-features"] == ce.CODEX_BETA_FEATURES
    # Authorization left untouched.
    assert headers["Authorization"] == "Bearer x"

    meta = json.loads(headers["x-codex-turn-metadata"])
    assert meta["turn_id"] == ctx.turn_id
    assert meta["session_id"] == ctx.session_id
    assert meta["request_kind"] == "turn"
    assert meta["sandbox"] == ce.CODEX_SANDBOX


def test_build_codex_headers_non_streaming_keeps_json_accept():
    ctx = ce.build_codex_request_context(None)
    headers = ce.build_codex_headers({"Accept": "application/json"}, ctx, streaming=False)
    assert headers["Accept"] == "application/json"
    # codex headers are still added regardless of streaming.
    assert headers["originator"] == "codex-tui"


def test_augment_payload_injects_defaults_when_absent():
    ctx = ce.build_codex_request_context({"chat_id": "chat-p1"})
    payload = {
        "model": "gpt-chat",
        "instructions": "my own prompt",
        "input": [{"type": "message", "role": "user", "content": []}],
        "stream": True,
    }
    ce.augment_codex_responses_payload(payload, ctx)

    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["reasoning"]["effort"] == ce.CODEX_DEFAULT_REASONING_EFFORT
    assert payload["text"]["verbosity"] == ce.CODEX_DEFAULT_TEXT_VERBOSITY
    assert payload["prompt_cache_key"] == ctx.session_id
    assert payload["client_metadata"]["turn_id"] == ctx.turn_id
    # Envelope-only: the caller's own instructions/input are preserved.
    assert payload["instructions"] == "my own prompt"
    # No tools -> no tool_choice / parallel_tool_calls injected.
    assert "tool_choice" not in payload
    assert "parallel_tool_calls" not in payload


def test_augment_payload_is_additive_and_enables_tool_fields():
    ctx = ce.build_codex_request_context({"chat_id": "chat-p2"})
    payload = {
        "model": "gpt-5.5",
        "store": True,
        "include": ["existing.value"],
        "reasoning": {"effort": "high"},
        "text": {"verbosity": "high"},
        "tools": [{"type": "function", "name": "f", "parameters": {}}],
        "prompt_cache_key": "keep-me",
    }
    ce.augment_codex_responses_payload(payload, ctx)

    # Existing values win.
    assert payload["store"] is True
    assert payload["reasoning"]["effort"] == "high"
    assert payload["text"]["verbosity"] == "high"
    assert payload["prompt_cache_key"] == "keep-me"
    # include is unioned, not replaced.
    assert payload["include"] == ["existing.value", "reasoning.encrypted_content"]
    # tools present -> tool fields injected.
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True


def test_is_codex_emulation_target():
    assert ce.is_codex_emulation_target("gpt-chat")
    assert ce.is_codex_emulation_target("GPT-5.5")
    assert not ce.is_codex_emulation_target("claude-3-7")
    assert not ce.is_codex_emulation_target("gemini-3-pro")
    assert not ce.is_codex_emulation_target(None)
