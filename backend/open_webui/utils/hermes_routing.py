"""Hermes 模型路由 (main model, fallback chain, sub-agents, auxiliary tasks, media) for the
「Hermes 模型」 settings page: a thin pass-through to hermes ``/api/admin/routing``.

Hermes owns the validation, the history and the write (``hermes_cli/routing_admin.py``):
config.yaml stays its single source of truth, so Telegram and the CLI see the same routing.
Admin only — this changes which model answers everyone.
"""

import logging
from typing import Optional

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, SRC_LOG_LEVELS
from open_webui.utils.hermes_sessions import (
    _MODEL_OPTIONS_CACHE,
    HermesSessionsError,
    _connection,
    _hermes_error_message,
    resolve_hermes_model,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

ROUTING_TIMEOUT_SECONDS = 30
# A probe is one real model request; claude-chat alone takes ~8s.
PROBE_TIMEOUT_SECONDS = 75


async def _routing_call(
    request, user, method: str, path: str = "", *, json: Optional[dict] = None,
    timeout: float = ROUTING_TIMEOUT_SECONDS,
) -> dict:
    model = await resolve_hermes_model(request, user, None)
    root, headers = _connection(request, user, model)
    try:
        async with aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.request(
                method,
                f"{root}/api/admin/routing{path}",
                json=json,
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {}
                if resp.status < 400:
                    return body if isinstance(body, dict) else {}
                message = _hermes_error_message(body)
                if resp.status == 404 and not message:
                    raise HermesSessionsError(
                        501, "这个 Hermes 还不支持网页改模型，更新 Hermes 并重载网关后再试"
                    )
                if resp.status in (400, 403, 409):
                    raise HermesSessionsError(resp.status, message or f"HTTP {resp.status}")
                raise HermesSessionsError(
                    502, f"Hermes 返回 {resp.status}：{message or '未知错误'}"
                )
    except (aiohttp.ClientError, TimeoutError) as e:
        raise HermesSessionsError(502, f"连不上 Hermes：{e}")


def _changed(body: dict) -> dict:
    # The composer's per-chat picker caches hermes' default model; drop it so it
    # shows the new one right away.
    if body.get("changes"):
        _MODEL_OPTIONS_CACHE.clear()
    return body


async def get_routing(request, user) -> dict:
    return await _routing_call(request, user, "GET")


async def save_routing(request, user, routing: dict, revision: Optional[str]) -> dict:
    body = await _routing_call(
        request, user, "PUT", json={"routing": routing, "revision": revision, "source": "halowebui"}
    )
    return _changed(body)


async def rollback_routing(request, user, entry_id: str, revision: Optional[str]) -> dict:
    body = await _routing_call(
        request, user, "POST", "/rollback", json={"id": entry_id, "revision": revision}
    )
    return _changed(body)


async def probe_model(request, user, model: str) -> dict:
    return await _routing_call(
        request, user, "POST", "/probe", json={"model": model}, timeout=PROBE_TIMEOUT_SECONDS
    )
