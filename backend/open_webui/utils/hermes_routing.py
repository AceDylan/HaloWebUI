"""Hermes 模型路由 (main model, fallback chain, sub-agents, auxiliary tasks, media) for the
「Hermes 模型」 settings page: a thin pass-through to hermes ``/api/admin/routing``.

Plus its 「AGY 优先」 part: the HTML card's first try on the Google account sign-in (offiagy) is a
HaloWebUI setting (the card is designed here); where team UI tasks start and offiagy's model live
in hermes' ``halo-teams-runners.json`` (teams plugin ``/v1/halo-teams/agy-prefs``).

Hermes owns the validation, the history and the write (``hermes_cli/routing_admin.py``):
config.yaml stays its single source of truth, so Telegram and the CLI see the same routing.
Admin only — this changes which model answers everyone.
"""

import logging
import os
import re
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


AGY_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
TEAMS_AGY_PREFS_PATH = "/v1/halo-teams/agy-prefs"
TEAMS_WORK_CONFIG_PATH = "/v1/halo-teams/work-config"


async def _routing_call(
    request, user, method: str, path: str = "", *, json: Optional[dict] = None,
    timeout: float = ROUTING_TIMEOUT_SECONDS, base: str = "/api/admin/routing",
) -> dict:
    model = await resolve_hermes_model(request, user, None)
    root, headers = _connection(request, user, model)
    try:
        async with aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.request(
                method,
                f"{root}{base}{path}",
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
                    feature = "网页配置 /work" if base == TEAMS_WORK_CONFIG_PATH else "网页改模型"
                    raise HermesSessionsError(
                        501, f"这个 Hermes 还不支持{feature}，更新 Hermes 并重载网关后再试"
                    )
                if resp.status in (400, 403, 409):
                    raise HermesSessionsError(resp.status, message or f"HTTP {resp.status}")
                raise HermesSessionsError(
                    502, f"Hermes 返回 {resp.status}：{message or '未知错误'}"
                )
    except (aiohttp.ClientError, TimeoutError) as e:
        raise HermesSessionsError(502, f"连不上 Hermes：{e}")


def _halo_reasoning_effort() -> str:
    try:
        from open_webui.haloclaw.config import (
            HALOCLAW_DEFAULT_REASONING_EFFORT,
            normalize_default_reasoning_effort,
        )

        return normalize_default_reasoning_effort(HALOCLAW_DEFAULT_REASONING_EFFORT.value)
    except Exception:
        return ""


def _sync_halo_reasoning_effort(effort: Optional[str]) -> Optional[dict]:
    """Keep HaloWebUI's Message Gateway reasoning effort in lockstep with Hermes' routing save.

    Hermes' ``halowebui-reasoning-sync`` plugin reads ``HALOCLAW_DEFAULT_REASONING_EFFORT`` on
    every ``codex_responses`` / ``chat_completions`` call, so updating both together means one
    change on 「Hermes 模型」 takes effect everywhere (Codex OAuth, gateway models, Claude, Gemini).
    """
    value = str(effort or "").strip().lower()
    if not value:
        return None
    from open_webui.haloclaw.config import (
        HALOCLAW_DEFAULT_REASONING_EFFORT,
        HALOCLAW_REASONING_EFFORT_VALUES,
        normalize_default_reasoning_effort,
    )

    if value not in HALOCLAW_REASONING_EFFORT_VALUES:
        raise HermesSessionsError(400, f"思考强度不支持：{value}")
    before = normalize_default_reasoning_effort(HALOCLAW_DEFAULT_REASONING_EFFORT.value)
    if before == value:
        return None
    HALOCLAW_DEFAULT_REASONING_EFFORT.value = value
    HALOCLAW_DEFAULT_REASONING_EFFORT.save()
    return {"path": "reasoning_effort", "before": before, "after": value}


def _with_halo_effort(body: dict) -> dict:
    effort = _halo_reasoning_effort()
    if effort:
        body = {**body, "halo_reasoning_effort": effort}
    return body


def _changed(body: dict) -> dict:
    # The composer's per-chat picker caches hermes' default model; drop it so it
    # shows the new one right away.
    if body.get("changes"):
        _MODEL_OPTIONS_CACHE.clear()
    return _with_halo_effort(body)


async def get_routing(request, user, *, refresh: bool = False) -> dict:
    path = "?refresh=1" if refresh else ""
    body = await _routing_call(request, user, "GET", path)
    if refresh:
        _MODEL_OPTIONS_CACHE.clear()
    return _with_halo_effort(body)


async def save_routing(request, user, routing: dict, revision: Optional[str]) -> dict:
    body = await _routing_call(
        request, user, "PUT", json={"routing": routing, "revision": revision, "source": "halowebui"}
    )
    requested_effort = routing.get("reasoning_effort") if isinstance(routing, dict) else None
    if requested_effort:
        halo_change = _sync_halo_reasoning_effort(requested_effort)
        if halo_change and not any(
            isinstance(c, dict) and c.get("path") == "reasoning_effort"
            for c in (body.get("changes") or [])
        ):
            body = {**body, "changes": [*(body.get("changes") or []), halo_change]}
    return _changed(body)


async def rollback_routing(request, user, entry_id: str, revision: Optional[str]) -> dict:
    body = await _routing_call(
        request, user, "POST", "/rollback", json={"id": entry_id, "revision": revision}
    )
    if any(
        isinstance(c, dict) and c.get("path") == "reasoning_effort"
        for c in (body.get("changes") or [])
    ):
        rolled_effort = (body.get("routing") or {}).get("reasoning_effort") or body.get(
            "reasoning_effort"
        )
        if rolled_effort:
            _sync_halo_reasoning_effort(rolled_effort)
    return _changed(body)


async def probe_model(request, user, model: str) -> dict:
    return await _routing_call(
        request, user, "POST", "/probe", json={"model": model}, timeout=PROBE_TIMEOUT_SECONDS
    )


# ---- AGY 优先 ----


def _card_prefs() -> dict:
    from open_webui.config import HTML_VISUAL_AGY_CARD_MODEL
    from open_webui.utils.html_visual_prompt import (
        HTML_VISUAL_AGY_OAUTH_TOKEN_FILE_ENV,
        HTML_VISUAL_AGY_PREFERRED_DEFAULT_MODEL,
    )

    return {
        "model": str(HTML_VISUAL_AGY_CARD_MODEL.value or "").strip(),
        "default": HTML_VISUAL_AGY_PREFERRED_DEFAULT_MODEL,
        # Without the token file the card never tries offiagy, whatever is saved.
        "signed_in": bool(os.environ.get(HTML_VISUAL_AGY_OAUTH_TOKEN_FILE_ENV, "").strip()),
    }


async def get_agy_prefs(request, user, *, refresh: bool = False) -> dict:
    path = "?refresh=1" if refresh else ""
    try:
        teams = await _routing_call(request, user, "GET", path, base=TEAMS_AGY_PREFS_PATH, timeout=60)
    except HermesSessionsError as e:
        teams = {"error": e.detail}
    return {"card": _card_prefs(), "teams": teams}


async def save_agy_prefs(request, user, fields: dict) -> dict:
    if "card_model" in fields:
        model = str(fields["card_model"] or "").strip()
        if model and not AGY_MODEL_RE.fullmatch(model):
            raise HermesSessionsError(400, "回答卡片：不是合法的模型 ID")
        from open_webui.config import HTML_VISUAL_AGY_CARD_MODEL

        HTML_VISUAL_AGY_CARD_MODEL.value = model
        HTML_VISUAL_AGY_CARD_MODEL.save()
    teams_fields = {k: fields[k] for k in ("ui_runner", "offiagy_model") if k in fields}
    if teams_fields:
        await _routing_call(
            request, user, "PUT", base=TEAMS_AGY_PREFS_PATH, json=teams_fields, timeout=60
        )
    return await get_agy_prefs(request, user)


async def get_work_config(request, user) -> dict:
    return await _routing_call(request, user, "GET", base=TEAMS_WORK_CONFIG_PATH)


async def save_work_config(request, user, payload: dict) -> dict:
    return await _routing_call(request, user, "PUT", base=TEAMS_WORK_CONFIG_PATH, json=payload)
