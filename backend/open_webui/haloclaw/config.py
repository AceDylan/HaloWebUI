import os
import logging

from open_webui.config import PersistentConfig

log = logging.getLogger(__name__)

HALOCLAW_REASONING_EFFORT_VALUES = ("none", "low", "medium", "high", "xhigh", "max")
HALOCLAW_DEFAULT_REASONING_EFFORT_VALUE = "xhigh"


def normalize_default_reasoning_effort(value) -> str:
    effort = str(value or "").strip().lower()
    if effort not in HALOCLAW_REASONING_EFFORT_VALUES:
        log.warning(
            "Invalid HALOCLAW_DEFAULT_REASONING_EFFORT=%r, fallback to %s",
            value,
            HALOCLAW_DEFAULT_REASONING_EFFORT_VALUE,
        )
        return HALOCLAW_DEFAULT_REASONING_EFFORT_VALUE
    return effort


def normalize_default_max_thinking_tokens(value) -> int | None:
    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in ("none", "null"):
            return None
        value = stripped

    try:
        tokens = int(value)
    except (TypeError, ValueError):
        log.warning(
            "Invalid HALOCLAW_DEFAULT_MAX_THINKING_TOKENS=%r, fallback to None",
            value,
        )
        return None

    if tokens == 0 or tokens >= 1024:
        return tokens
    return None


ENABLE_HALOCLAW = PersistentConfig(
    "ENABLE_HALOCLAW",
    "haloclaw.enable",
    os.environ.get("ENABLE_HALOCLAW", "False").lower() == "true",
)

HALOCLAW_DEFAULT_MODEL = PersistentConfig(
    "HALOCLAW_DEFAULT_MODEL",
    "haloclaw.default_model",
    os.environ.get("HALOCLAW_DEFAULT_MODEL", ""),
)

HALOCLAW_MAX_HISTORY = PersistentConfig(
    "HALOCLAW_MAX_HISTORY",
    "haloclaw.max_history",
    int(os.environ.get("HALOCLAW_MAX_HISTORY", "20")),
)

HALOCLAW_DEFAULT_REASONING_EFFORT = PersistentConfig(
    "HALOCLAW_DEFAULT_REASONING_EFFORT",
    "haloclaw.default_reasoning_effort",
    normalize_default_reasoning_effort(
        os.environ.get(
            "HALOCLAW_DEFAULT_REASONING_EFFORT",
            HALOCLAW_DEFAULT_REASONING_EFFORT_VALUE,
        )
    ),
)
HALOCLAW_DEFAULT_REASONING_EFFORT.value = normalize_default_reasoning_effort(
    HALOCLAW_DEFAULT_REASONING_EFFORT.value
)

HALOCLAW_DEFAULT_MAX_THINKING_TOKENS = PersistentConfig(
    "HALOCLAW_DEFAULT_MAX_THINKING_TOKENS",
    "haloclaw.default_max_thinking_tokens",
    normalize_default_max_thinking_tokens(
        os.environ.get("HALOCLAW_DEFAULT_MAX_THINKING_TOKENS")
    ),
)
HALOCLAW_DEFAULT_MAX_THINKING_TOKENS.value = normalize_default_max_thinking_tokens(
    HALOCLAW_DEFAULT_MAX_THINKING_TOKENS.value
)

HALOCLAW_RATE_LIMIT = PersistentConfig(
    "HALOCLAW_RATE_LIMIT",
    "haloclaw.rate_limit",
    int(os.environ.get("HALOCLAW_RATE_LIMIT", "10")),
)

# R4: 是否在发往上游的 Anthropic body 顶层附带 reasoning_effort/effort 字段（供中转代理
# 识别并打 anthropic_effort trace）。Anthropic 官方 API 不识别这两个顶层字段；若上游代理
# 透传给官方导致 400，可在管理后台关闭。默认开启。
ANTHROPIC_EFFORT_PASSTHROUGH = PersistentConfig(
    "ENABLE_ANTHROPIC_EFFORT_PASSTHROUGH",
    "haloclaw.anthropic_effort_passthrough",
    os.environ.get("ENABLE_ANTHROPIC_EFFORT_PASSTHROUGH", "True").lower() == "true",
)
