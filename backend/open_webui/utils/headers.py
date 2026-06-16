from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from open_webui.env import ENABLE_FORWARD_USER_INFO_HEADERS


# User-Agent strings for outbound LLM requests (spoofing for proxy compatibility)
USER_AGENT_CLAUDE = "claude-cli/2.1.170 (external, cli)"
USER_AGENT_GPT = "codex_vscode/0.140.0-alpha.2 (Windows 10.0.26100; x86_64) unknown (VS Code; 26.609.30741)"
USER_AGENT_GEMINI = "GeminiCLI-tui/0.46.0/gemini-3.1-pro-preview (win32; x64; terminal)"


def set_model_user_agent(headers: dict[str, str], model_id: str) -> dict[str, str]:
    """Set User-Agent header based on model prefix.

    Args:
        headers: Existing headers dict (mutated in place)
        model_id: The upstream model ID (after prefix stripping)

    Returns:
        The same headers dict with User-Agent set if model prefix matches
    """
    if not isinstance(model_id, str):
        return headers

    model_lower = model_id.lower()

    if model_lower.startswith("claude"):
        headers["User-Agent"] = USER_AGENT_CLAUDE
    elif model_lower.startswith("gpt"):
        headers["User-Agent"] = USER_AGENT_GPT
    elif model_lower.startswith("gemini"):
        headers["User-Agent"] = USER_AGENT_GEMINI

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
