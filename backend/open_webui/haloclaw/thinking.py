from open_webui.haloclaw.config import (
    HALOCLAW_DEFAULT_MAX_THINKING_TOKENS,
    HALOCLAW_DEFAULT_REASONING_EFFORT,
    normalize_default_max_thinking_tokens,
    normalize_default_reasoning_effort,
)

EFFORT_VALUES = ("none", "low", "medium", "high", "xhigh", "max")


def _is_anthropic_model(model_id: str | None, owned_by: str | None) -> bool:
    signature = f"{model_id or ''} {owned_by or ''}".lower()
    return "anthropic" in signature or "claude" in signature


def is_effort_supported(model_id, owned_by, effort) -> bool:
    effort = str(effort or "").strip().lower()
    if effort not in EFFORT_VALUES:
        return False
    if _is_anthropic_model(model_id, owned_by):
        return True
    return True


def resolve_default_thinking(model_id, owned_by) -> dict:
    budget = normalize_default_max_thinking_tokens(
        HALOCLAW_DEFAULT_MAX_THINKING_TOKENS.value
    )
    if budget is not None:
        if budget == 0:
            return {}
        return {"max_thinking_tokens": budget}

    effort = normalize_default_reasoning_effort(
        HALOCLAW_DEFAULT_REASONING_EFFORT.value
    )
    if effort == "none" or not is_effort_supported(model_id, owned_by, effort):
        return {}
    return {"reasoning_effort": effort}
