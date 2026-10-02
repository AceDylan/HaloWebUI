"""HaloWebUI agent teams (协作台) on the Hermes Kanban. See README.md."""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    from . import api, hooks, tg

    ctx.register_hook("post_tool_call", hooks.on_post_tool_call)
    ctx.register_hook("subagent_start", hooks.on_subagent_start)
    ctx.register_hook("subagent_stop", hooks.on_subagent_stop)
    # Telegram: /team, buttons and replies to team notices (see tg.py, notify.py).
    ctx.register_hook("pre_gateway_dispatch", tg.on_pre_gateway_dispatch)
    # Also a plain command, so it is in Telegram's menu; the hook answers linked users first.
    ctx.register_command("team", tg.command_fallback, description="协作台：/team 目标 交给团队，/team 看最近的")
    ctx.register_platform_handler("telegram", tg.install)
    ctx.register_platform_handler("api_server", api.install)
