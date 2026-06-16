from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from open_webui.env import ENABLE_FORWARD_USER_INFO_HEADERS


# Built-in default User-Agent strings for outbound LLM requests (spoofing for proxy
# compatibility). These are the fallback values used when the admin-configurable
# overrides (config.USER_AGENT_*) are unset/empty, preserving legacy behavior.
DEFAULT_USER_AGENT_CLAUDE = "claude-cli/2.1.170 (external, cli)"
DEFAULT_USER_AGENT_GPT = "codex_vscode/0.140.0-alpha.2 (Windows 10.0.26100; x86_64) unknown (VS Code; 26.609.30741)"
DEFAULT_USER_AGENT_GEMINI = "GeminiCLI-tui/0.46.0/gemini-3.1-pro-preview (win32; x64; terminal)"


def get_user_agent_config(request=None) -> dict[str, str]:
    """Read the admin-configured per-prefix User-Agent overrides.

    Returns a dict with keys ``claude`` / ``gpt`` / ``gemini``.

    - With a ``request``: read from ``request.app.state.config`` (live values,
      Redis/multi-worker aware) — used on the main chat completion path.
    - Without a ``request`` (health checks, verify, background probes): fall back
      to the module-level PersistentConfig values.
    - On any failure: return ``{}`` so callers use the built-in defaults.
    """
    if request is not None:
        try:
            cfg = request.app.state.config
            return {
                "claude": cfg.USER_AGENT_CLAUDE,
                "gpt": cfg.USER_AGENT_GPT,
                "gemini": cfg.USER_AGENT_GEMINI,
            }
        except Exception:
            pass

    try:
        # Local import to avoid any import cycle at module load time.
        from open_webui.config import (
            USER_AGENT_CLAUDE,
            USER_AGENT_GPT,
            USER_AGENT_GEMINI,
        )

        return {
            "claude": USER_AGENT_CLAUDE.value,
            "gpt": USER_AGENT_GPT.value,
            "gemini": USER_AGENT_GEMINI.value,
        }
    except Exception:
        return {}


def set_model_user_agent(
    headers: dict[str, str],
    model_id: str,
    ua_config: Optional[dict] = None,
) -> dict[str, str]:
    """Set User-Agent header based on model prefix.

    Args:
        headers: Existing headers dict (mutated in place)
        model_id: The upstream model ID (after prefix stripping)
        ua_config: Optional admin overrides ``{"claude"/"gpt"/"gemini": ua}``.
            An empty/missing value for a prefix falls back to the built-in default.

    Returns:
        The same headers dict with User-Agent set if model prefix matches
    """
    if not isinstance(model_id, str):
        return headers

    ua_config = ua_config or {}
    model_lower = model_id.lower()

    if model_lower.startswith("claude"):
        headers["User-Agent"] = ua_config.get("claude") or DEFAULT_USER_AGENT_CLAUDE
    elif model_lower.startswith("gpt"):
        headers["User-Agent"] = ua_config.get("gpt") or DEFAULT_USER_AGENT_GPT
    elif model_lower.startswith("gemini"):
        headers["User-Agent"] = ua_config.get("gemini") or DEFAULT_USER_AGENT_GEMINI

    return headers


def include_user_info_headers(headers: dict[str, str], user) -> dict[str, str]:
    if not ENABLE_FORWARD_USER_INFO_HEADERS or user is None:
        return headers

    return {
        **headers,
        "X-OpenWebUI-User-Name": quote(str(getattr(user, "name", "")), safe=" "),
        "X-OpenWebUI-User-Id": str(getattr(user, "id", "")),
        "X-OpenWebUI-User-Email": str(getattr(user, "email", "")),
        "X-OpenWebUI-User-Role": str(getattr(user, "role", "")),
    }
