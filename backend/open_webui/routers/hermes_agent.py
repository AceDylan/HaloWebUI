import json
import logging
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, AIOHTTP_CLIENT_TIMEOUT, AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST, SRC_LOG_LEVELS
from open_webui.models.users import UserModel
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.model_identity import decorate_provider_model_identity, resolve_provider_connection_by_model_id
from open_webui.utils.user_connections import get_user_connections, set_user_connection_provider_config

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OPENAI"])

router = APIRouter()


def _normalize_base_url(url: str) -> str:
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def _endpoint(base_url: str, path: str) -> str:
    return f"{_normalize_base_url(base_url)}{path}"


def _get_hermes_user_config(connection_user: Optional[UserModel]) -> tuple[bool, list[str], list[str], dict]:
    conns = get_user_connections(connection_user)
    cfg = conns.get("hermes") if isinstance(conns, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}

    enabled = bool(cfg.get("ENABLE_HERMES_AGENT", True))

    base_urls = [_normalize_base_url(url) for url in list(cfg.get("HERMES_AGENT_BASE_URLS") or [])]
    keys = list(cfg.get("HERMES_AGENT_API_KEYS") or [])
    configs = cfg.get("HERMES_AGENT_CONFIGS") or {}
    configs = configs if isinstance(configs, dict) else {}

    if len(keys) > len(base_urls):
        keys = keys[: len(base_urls)]
    elif len(keys) < len(base_urls):
        keys = keys + [""] * (len(base_urls) - len(keys))

    return enabled, base_urls, keys, configs


def _connection_headers(key: str, api_config: Optional[dict] = None) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    custom_headers = (api_config or {}).get("headers")
    if isinstance(custom_headers, dict):
        headers.update({str(k): str(v) for k, v in custom_headers.items() if v is not None})
    if key and "authorization" not in {h.lower() for h in headers}:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _resolve_connection(model_id: str, base_urls: list[str], keys: list[str], cfgs: dict, *, model_ref: Optional[dict] = None, request_models=None):
    return resolve_provider_connection_by_model_id(
        provider="hermes",
        model_id=model_id,
        base_urls=base_urls,
        keys=keys,
        cfgs=cfgs,
        model_ref=model_ref,
        request_models=request_models,
    )


class HermesAgentConfigForm(BaseModel):
    ENABLE_HERMES_AGENT: Optional[bool] = True
    HERMES_AGENT_BASE_URLS: list[str]
    HERMES_AGENT_API_KEYS: list[str]
    HERMES_AGENT_CONFIGS: dict


@router.get("/config")
async def get_config(user=Depends(get_admin_user)):
    enabled, base_urls, keys, cfgs = _get_hermes_user_config(user)
    return {
        "ENABLE_HERMES_AGENT": enabled,
        "HERMES_AGENT_BASE_URLS": base_urls,
        "HERMES_AGENT_API_KEYS": keys,
        "HERMES_AGENT_CONFIGS": cfgs,
    }


@router.post("/config/update")
async def update_config(request: Request, form_data: HermesAgentConfigForm, user=Depends(get_admin_user)):
    payload = {
        "ENABLE_HERMES_AGENT": bool(form_data.ENABLE_HERMES_AGENT),
        "HERMES_AGENT_BASE_URLS": [_normalize_base_url(url) for url in form_data.HERMES_AGENT_BASE_URLS],
        "HERMES_AGENT_API_KEYS": list(form_data.HERMES_AGENT_API_KEYS or []),
        "HERMES_AGENT_CONFIGS": form_data.HERMES_AGENT_CONFIGS or {},
    }
    updated = set_user_connection_provider_config(user.id, "hermes", payload)
    if updated:
        user = updated

    try:
        from open_webui.utils.models import invalidate_base_model_cache

        request.app.state.BASE_MODELS = None
        request.app.state.MODELS = {}
        invalidate_base_model_cache(user.id)
    except Exception:
        pass

    enabled, base_urls, keys, cfgs = _get_hermes_user_config(user)
    return {
        "ENABLE_HERMES_AGENT": enabled,
        "HERMES_AGENT_BASE_URLS": base_urls,
        "HERMES_AGENT_API_KEYS": keys,
        "HERMES_AGENT_CONFIGS": cfgs,
    }


@router.get("/models")
async def get_models(request: Request, user=Depends(get_verified_user)):
    return await get_all_models(request, user=user)


async def get_all_models(request: Request, user: UserModel) -> dict:
    enabled, base_urls, keys, cfgs = _get_hermes_user_config(user)
    if not enabled:
        return {"data": []}
    models: list[dict] = []

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)) as session:
        for idx, base_url in enumerate(base_urls):
            if not base_url:
                continue
            api_config = cfgs.get(str(idx), cfgs.get(base_url, {})) or {}
            key = keys[idx] if idx < len(keys) else ""
            try:
                async with session.get(
                    _endpoint(base_url, "/models"),
                    headers=_connection_headers(key, api_config),
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    body = await response.text()
                    if response.status != 200:
                        default_model = str(api_config.get("default_model") or "hermes-agent").strip()
                        if default_model:
                            upstream_models = [{"id": default_model, "object": "model"}]
                        else:
                            log.warning("Hermes Agent /models failed: %s %s", response.status, body[:300])
                            continue
                    else:
                        try:
                            data = json.loads(body or "{}")
                        except json.JSONDecodeError:
                            data = {}
                        upstream_models = data.get("data") if isinstance(data, dict) else data
                        if not isinstance(upstream_models, list):
                            upstream_models = []
            except Exception as e:
                default_model = str(api_config.get("default_model") or "hermes-agent").strip()
                if default_model:
                    upstream_models = [{"id": default_model, "object": "model"}]
                else:
                    log.warning("Hermes Agent models fetch failed: %s", e)
                    continue

            connection_name = str(api_config.get("name") or "Hermes Agent").strip() or "Hermes Agent"
            for model in upstream_models:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("id") or model.get("name") or "").strip()
                if not model_id:
                    continue
                entry = {
                    **model,
                    "id": model_id,
                    "name": model.get("name") or model_id,
                    "object": model.get("object") or "model",
                    "created": model.get("created") or int(time.time()),
                    "owned_by": "hermes",
                    "hermes": model,
                    "urlIdx": idx,
                    "connection_name": connection_name,
                    "connection_icon": api_config.get("icon") or "/favicon.png",
                }
                decorate_provider_model_identity(
                    entry,
                    provider="hermes",
                    model_id=model_id,
                    source="personal",
                    connection_index=idx,
                    connection_id=api_config.get("prefix_id"),
                    legacy_ids=[model_id],
                )
                models.append(entry)

    return {"data": models}


async def _upstream_error(response: aiohttp.ClientResponse) -> HTTPException:
    try:
        body = await response.json()
    except Exception:
        body = await response.text()
    return HTTPException(status_code=response.status, detail=body)


async def _proxy_upstream_json(base_url: str, path: str, key: str, api_config: dict, payload: dict):
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT))
    try:
        response = await session.post(
            _endpoint(base_url, path),
            headers=_connection_headers(key, api_config),
            json=payload,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        )
        if response.status >= 400:
            error = await _upstream_error(response)
            response.release()
            await session.close()
            raise error

        if payload.get("stream"):
            headers = {"content-type": response.headers.get("content-type", "text/event-stream")}

            async def close_upstream():
                response.release()
                await session.close()

            return StreamingResponse(
                response.content.iter_any(),
                status_code=response.status,
                headers=headers,
                background=BackgroundTask(close_upstream),
            )

        body = await response.read()
        content_type = response.headers.get("content-type", "application/json")
        response.release()
        await session.close()
        try:
            return JSONResponse(content=json.loads(body.decode("utf-8")), status_code=response.status)
        except Exception:
            return JSONResponse(
                content={"content": body.decode("utf-8", errors="replace")},
                status_code=response.status,
                headers={"content-type": content_type},
            )
    except Exception:
        if not session.closed:
            await session.close()
        raise


def _resolve_upstream_for_payload(request: Request, user: UserModel, payload: dict):
    connection_user = getattr(getattr(request, "state", None), "connection_user", None) or user
    enabled, base_urls, keys, cfgs = _get_hermes_user_config(connection_user)
    if not enabled:
        raise HTTPException(status_code=404, detail="Hermes Agent provider is disabled")
    if not base_urls:
        raise HTTPException(status_code=404, detail="No Hermes Agent connections configured")

    model = getattr(getattr(request, "state", None), "model", None) or {}
    model_ref = model.get("model_ref") if isinstance(model, dict) else None
    requested_model_id = str(payload.get("model") or "")
    idx, base_url, key, api_config = _resolve_connection(
        requested_model_id,
        base_urls,
        keys,
        cfgs,
        model_ref=model_ref,
        request_models=getattr(getattr(request, "state", None), "MODELS", None),
    )
    upstream_model = model.get("original_id") or model.get("model_id") or payload.get("model")
    return idx, base_url, key, api_config, {**payload, "model": upstream_model}


@router.post("/v1/chat/completions")
@router.post("/chat/completions")
async def chat_completions(request: Request, user=Depends(get_verified_user)):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    return await generate_chat_completion(request, payload, user=user)


@router.post("/v1/responses")
@router.post("/responses")
async def responses(request: Request, user=Depends(get_verified_user)):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    _, base_url, key, api_config, upstream_payload = _resolve_upstream_for_payload(request, user, payload)
    return await _proxy_upstream_json(base_url, "/responses", key, api_config, upstream_payload)


async def generate_chat_completion(request: Request, form_data: dict, user: UserModel, bypass_filter: bool = False):
    _, base_url, key, api_config, payload = _resolve_upstream_for_payload(request, user, form_data)
    return await _proxy_upstream_json(base_url, "/chat/completions", key, api_config, payload)
