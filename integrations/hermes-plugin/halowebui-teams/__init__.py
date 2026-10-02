"""HaloWebUI agent teams (协作台) on the Hermes Kanban. See README.md."""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    from . import api, hooks

    ctx.register_hook("post_tool_call", hooks.on_post_tool_call)
    ctx.register_hook("subagent_start", hooks.on_subagent_start)
    ctx.register_hook("subagent_stop", hooks.on_subagent_stop)
    ctx.register_platform_handler("api_server", api.install)
