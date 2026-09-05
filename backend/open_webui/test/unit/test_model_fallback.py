"""model_fallback decides when a failed chat turn is retried and which model
stands in — from the model's own meta, through the caller's registry, one hop."""
import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from open_webui.utils.model_fallback import (
    configured_fallback_id,
    error_status,
    fallback_eligible,
    resolve_fallback_model,
    transient_reason,
)

CLAUDE = "modelref::anthropic::personal::id:f1c11c94::claude-chat"
GPT = "modelref::openai::personal::id:13c104eb::gpt-chat"
HERMES = "modelref::openai::personal::id:ee5e02db::hermes-agent"


def _model(model_id, name, fallback=None, **extra):
    meta = {"fallback_model_id": fallback} if fallback else {}
    return {"id": model_id, "name": name, "original_id": name, "info": {"meta": meta}, **extra}


def _request(models):
    lookup = {m["id"]: m for m in models}
    return SimpleNamespace(state=SimpleNamespace(MODELS=lookup, MODELS_AMBIGUOUS=set()))


def test_transient_reason_covers_5xx_429_timeouts_and_connection_errors():
    assert transient_reason(HTTPException(status_code=503, detail="upstream")) == "HTTP 503"
    assert transient_reason(HTTPException(status_code=429, detail="slow down")) == "HTTP 429"
    assert transient_reason(asyncio.TimeoutError()) == "超时"

    class ClientConnectorError(Exception):
        pass

    assert transient_reason(ClientConnectorError("refused")) == "连接失败"


def test_transient_reason_refuses_client_errors_and_unknowns():
    assert transient_reason(HTTPException(status_code=400, detail="bad request")) is None
    assert transient_reason(HTTPException(status_code=401, detail="key")) is None
    assert transient_reason(HTTPException(status_code=404, detail="no model")) is None
    assert transient_reason(ValueError("boom")) is None
    assert transient_reason(None) is None


def test_error_status_reads_every_client_shape():
    assert error_status(HTTPException(status_code=502, detail="x")) == 502
    assert error_status(SimpleNamespace(status=503)) == 503
    assert error_status(SimpleNamespace(response=SimpleNamespace(status_code=504))) == 504
    assert error_status(ValueError("no status")) is None


def test_eligibility_excludes_hermes_direct_and_non_chat_calls():
    meta = {"chat_id": "c1", "message_id": "m1"}
    assert fallback_eligible(_model(CLAUDE, "claude-chat"), meta)
    assert not fallback_eligible(_model(HERMES, "hermes-agent"), meta)
    assert not fallback_eligible(_model(CLAUDE, "claude-chat"), {**meta, "direct": True})
    assert not fallback_eligible(_model(CLAUDE, "claude-chat"), {"chat_id": "c1"})
    assert not fallback_eligible("claude-chat", meta)


def test_fallback_resolves_through_the_user_registry_one_hop():
    claude = _model(CLAUDE, "claude-chat", fallback=GPT)
    gpt = _model(GPT, "gpt-chat", fallback=CLAUDE)
    request = _request([claude, gpt])

    assert configured_fallback_id(claude) == GPT
    assert resolve_fallback_model(request, claude) is gpt
    assert resolve_fallback_model(request, gpt) is claude  # one hop each; the caller never chains


def test_fallback_is_none_when_missing_self_or_hermes():
    claude = _model(CLAUDE, "claude-chat")
    assert resolve_fallback_model(_request([claude]), claude) is None

    stale = _model(CLAUDE, "claude-chat", fallback="modelref::openai::personal::id:dead::gone")
    assert resolve_fallback_model(_request([stale]), stale) is None

    selfish = _model(CLAUDE, "claude-chat", fallback=CLAUDE)
    assert resolve_fallback_model(_request([selfish]), selfish) is None

    to_hermes = _model(CLAUDE, "claude-chat", fallback=HERMES)
    hermes = _model(HERMES, "hermes-agent")
    assert resolve_fallback_model(_request([to_hermes, hermes]), to_hermes) is None
