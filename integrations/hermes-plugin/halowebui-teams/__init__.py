"""HaloWebUI agent teams (协作台) on the Hermes Kanban. See README.md."""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    from . import api, hooks, remote, tg, gallery

    ctx.register_hook("image_generated", gallery.on_image_generated)

    ctx.register_hook("post_tool_call", hooks.on_post_tool_call)
    ctx.register_hook("subagent_start", hooks.on_subagent_start)
    ctx.register_hook("subagent_stop", hooks.on_subagent_stop)
    # Telegram: /team, buttons and replies to team notices (see tg.py, notify.py).
    ctx.register_hook("pre_gateway_dispatch", tg.on_pre_gateway_dispatch)
    # Also a plain command, so it is in Telegram's menu; the hook answers linked users first.
    ctx.register_command("team", tg.command_fallback, description="协作台：/team 目标 交给团队，/team 看最近的")
    ctx.register_platform_handler("telegram", tg.install)
    # Telegram and QQ: /answer, /discuss, /auto (and QQ's /team) — HaloWebUI runs, results back (remote.py).
    ctx.register_hook("pre_gateway_dispatch", remote.on_pre_gateway_dispatch)
    for name, description in (("answer", "精答：/answer 问题，挑最合适的助手回答"),
                              ("discuss", "讨论：/discuss 问题，几个模型讨论出结论"),
                              ("auto", "自动分流：/auto 问题，自动交给精答/讨论/协作台")):
        ctx.register_command(name, remote.command_fallback, description=description)
    ctx.register_platform_handler("telegram", remote.install)
    ctx.register_platform_handler("qqbot", remote.install)
    ctx.register_platform_handler("api_server", api.install)
