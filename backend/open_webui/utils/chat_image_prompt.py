"""Chat image generation on workspace presets ("助手").

A workspace preset only exists inside HaloWebUI: its id is an alias for a base
model plus a system prompt. When the base model is a dedicated image model the
chat image path has to send the *base* model upstream and use the preset's
system prompt as the image brief. Sending the preset id itself makes the
provider answer "No available providers" / model-not-found.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from open_webui.utils.model_identity import parse_selection_id

# Placeholders a preset prompt may use to mark where the user's message goes.
USER_INPUT_PLACEHOLDER = re.compile(
    r"\{\{\s*(?:USER_INPUT|USER_PROMPT|PROMPT|INPUT)\s*\}\}", re.IGNORECASE
)
_LEGACY_CONNECTION_PREFIX = re.compile(r"^([0-9a-f]{8})\.(.+)$", re.IGNORECASE)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _model_info(model: Any) -> dict[str, Any]:
    if not isinstance(model, dict):
        return {}
    info = model.get("info")
    return info if isinstance(info, dict) else {}


def _model_meta(model: Any) -> dict[str, Any]:
    meta = _model_info(model).get("meta")
    return meta if isinstance(meta, dict) else {}


def is_preset_model(model: Any) -> bool:
    """True for workspace presets (custom models that wrap a base model)."""
    if not isinstance(model, dict):
        return False
    if model.get("preset") is True:
        return True
    return bool(_clean(_model_meta(model).get("base_selection_id")))


def get_preset_base_selection(model: Any) -> str:
    """The preset's base model selection (``modelref::...`` when known)."""
    if not is_preset_model(model):
        return ""
    info = _model_info(model)
    return _clean(_model_meta(model).get("base_selection_id")) or _clean(
        info.get("base_model_id")
    )


def resolve_chat_image_model_selection(
    model: Any, fallback_model_id: Any = ""
) -> tuple[str, dict[str, Any]]:
    """Upstream image model id and connection hints for a chat image request.

    Presets resolve to their base model; every other model keeps the previous
    ``model_id`` / ``original_id`` / ``id`` order. ``modelref::`` selection ids
    and the legacy ``<8 hex>.<model>`` connection prefix are unwrapped so the
    provider receives a bare model name plus a ``model_ref``.
    """
    model_ref: dict[str, Any] = {}
    selected = get_preset_base_selection(model)

    if not selected and isinstance(model, dict):
        for key in ("model_id", "original_id", "id"):
            selected = _clean(model.get(key))
            if selected:
                break
    if not selected:
        selected = _clean(fallback_model_id)

    parsed = parse_selection_id(selected)
    if parsed:
        selected = _clean(parsed.get("model_id"))
        for key, value in (parsed.get("model_ref") or {}).items():
            model_ref.setdefault(key, value)

    legacy_match = _LEGACY_CONNECTION_PREFIX.match(selected)
    if legacy_match:
        model_ref.setdefault("connection_id", legacy_match.group(1))
        selected = legacy_match.group(2).strip()

    return selected, model_ref


def get_preset_system_prompt(model: Any) -> str:
    """The preset's own system prompt (never the user's global one)."""
    if not is_preset_model(model):
        return ""
    params = _model_info(model).get("params")
    if not isinstance(params, dict):
        return ""
    return _clean(params.get("system"))


def compose_chat_image_prompt(
    system_prompt: Any,
    user_message: Any,
    variables: Optional[dict[str, Any]] = None,
) -> str:
    """Merge a preset system prompt with the user's message into one image brief.

    ``{{USER_INPUT}}`` (or ``{{PROMPT}}``) inside the system prompt is replaced
    by the message; otherwise the message is appended after a blank line.
    """
    user_text = _clean(user_message)
    system = _clean(system_prompt)
    if not system:
        return user_text

    if isinstance(variables, dict):
        for key, value in variables.items():
            if isinstance(key, str) and key:
                system = system.replace(key, "" if value is None else str(value))

    if USER_INPUT_PLACEHOLDER.search(system):
        return USER_INPUT_PLACEHOLDER.sub(lambda _match: user_text, system).strip()

    if not user_text:
        return system
    return f"{system}\n\n{user_text}"
