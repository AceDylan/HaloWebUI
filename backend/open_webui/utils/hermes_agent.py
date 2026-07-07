"""
Hermes Agent integration.

Routes chats for configured model IDs through hermes's /v1/runs API (instead of
/v1/chat/completions) so that:

- tool activity streams into the chat as native <details type="tool_calls">
  blocks (rendered by the existing frontend, no frontend changes needed);
- command approval requests pop a native confirmation dialog in the web UI
  (socket "confirmation" event) and the user's choice is posted back to
  hermes via POST /v1/runs/{run_id}/approval.

Configuration (environment variables):

- HERMES_AGENT_MODEL_IDS: comma-separated model IDs handled by this
  integration (default: "hermes-agent").
- HERMES_AGENT_BASE_URL / HERMES_AGENT_API_KEY: optional explicit connection
  override. When unset, the connection is resolved from the existing OpenAI
  connections by model ID.
- HERMES_AGENT_APPROVAL_TIMEOUT: seconds to wait for the user's approval
  decision before auto-denying (default: 240; keep below hermes's
  approvals.gateway_timeout which defaults to 300).
"""

import asyncio
import html
import json
import logging
import os
import time
from urllib.parse import urlparse, urlunparse

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.socket.main import get_event_call, get_event_emitter
from open_webui.tasks import create_task

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))


HERMES_AGENT_MODEL_IDS = [
    model_id.strip()
    for model_id in os.environ.get("HERMES_AGENT_MODEL_IDS", "hermes-agent").split(",")
    if model_id.strip()
]

HERMES_AGENT_BASE_URL = os.environ.get("HERMES_AGENT_BASE_URL", "").strip()
HERMES_AGENT_API_KEY = os.environ.get("HERMES_AGENT_API_KEY", "").strip()

try:
    HERMES_AGENT_APPROVAL_TIMEOUT = int(
        os.environ.get("HERMES_AGENT_APPROVAL_TIMEOUT", "240")
    )
except ValueError:
    HERMES_AGENT_APPROVAL_TIMEOUT = 240


def is_hermes_agent_model(model_id) -> bool:
    return isinstance(model_id, str) and model_id in HERMES_AGENT_MODEL_IDS


def _normalize_base_url(url: str) -> str:
    """Return the connection URL normalized to end with /v1 (no endpoint suffix)."""
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


def _resolve_hermes_connection(request, user, model_id):
    """Return (base_url, api_key) for the hermes connection, or (None, None)."""
    if HERMES_AGENT_BASE_URL:
        return _normalize_base_url(HERMES_AGENT_BASE_URL), HERMES_AGENT_API_KEY

    try:
        from open_webui.routers.openai import (
            _get_openai_user_config,
            _normalize_openai_connection_key,
            _resolve_openai_connection_by_model_id,
        )

        connection_user = (
            getattr(getattr(request, "state", None), "connection_user", None) or user
        )
        base_urls, keys, cfgs = _get_openai_user_config(connection_user)
        if not base_urls:
            return None, None

        try:
            idx, url, key, api_config = _resolve_openai_connection_by_model_id(
                model_id,
                base_urls,
                keys,
                cfgs,
                request_models=getattr(getattr(request, "state", None), "MODELS", None),
            )
            key, api_config = _normalize_openai_connection_key(
                key, api_config, url_idx=idx
            )
        except Exception:
            # Single-connection fallback: with exactly one configured OpenAI
            # connection there is nothing ambiguous to resolve.
            usable = [(i, u) for i, u in enumerate(base_urls) if str(u or "").strip()]
            if len(usable) != 1:
                raise
            idx, url = usable[0]
            key = keys[idx] if idx < len(keys) else ""

        if not url:
            return None, None
        return _normalize_base_url(url), key or ""
    except Exception as e:
        log.warning(f"Failed to resolve hermes agent connection for {model_id}: {e}")
        return None, None


def _extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content) if content is not None else ""


def _build_run_payload(form_data, metadata):
    messages = form_data.get("messages") or []

    instructions = None
    history = []
    for message in messages:
        role = message.get("role")
        content = _extract_text_content(message.get("content"))
        if role == "system":
            instructions = f"{instructions}\n{content}" if instructions else content
        else:
            history.append({"role": role, "content": content})

    user_message = ""
    if history and history[-1].get("role") == "user":
        user_message = history.pop()["content"]

    payload = {
        "input": user_message,
        "model": form_data.get("model"),
    }
    if history:
        payload["conversation_history"] = history
    if instructions:
        payload["instructions"] = instructions
    if metadata.get("chat_id"):
        payload["session_id"] = metadata["chat_id"]
    return payload


def _serialize_blocks(blocks) -> str:
    content = ""
    for block in blocks:
        if block["type"] == "text":
            text = str(block.get("content", "")).strip()
            if text:
                content = f"{content}{text}\n"
        elif block["type"] == "reasoning":
            duration = block.get("duration", 0)
            text = str(block.get("content", "")).strip()
            if text:
                content = (
                    f"{content}\n"
                    f'<details type="reasoning" done="true" duration="{duration}">\n'
                    f"<summary>Thought for {duration} seconds</summary>\n"
                    f"{text}\n</details>\n"
                )
        elif block["type"] == "tool":
            arguments = html.escape(
                json.dumps({"input": block.get("preview") or ""}, ensure_ascii=False)
            )
            if block.get("done"):
                result = html.escape(
                    json.dumps(
                        {
                            "status": "error" if block.get("error") else "success",
                            "duration": block.get("duration", 0),
                        }
                    )
                )
                content = (
                    f"{content}\n"
                    f'<details type="tool_calls" done="true" id="{block["id"]}" '
                    f'name="{html.escape(str(block.get("name") or "tool"))}" '
                    f'arguments="{arguments}" result="{result}">\n'
                    f"<summary>Tool Executed</summary>\n</details>\n"
                )
            else:
                content = (
                    f"{content}\n"
                    f'<details type="tool_calls" done="false" id="{block["id"]}" '
                    f'name="{html.escape(str(block.get("name") or "tool"))}" '
                    f'arguments="{arguments}">\n'
                    f"<summary>Executing...</summary>\n</details>\n"
                )
    return content.strip()


def _map_usage(usage):
    if not isinstance(usage, dict):
        return None
    return {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


async def run_hermes_agent(request, form_data, user, metadata, model, events):
    """
    Execute the chat via hermes's runs API, streaming results over the chat
    socket. Returns a background-task response dict, or None when this path
    cannot handle the request (caller should fall back to the normal flow).
    """
    if not (
        metadata.get("session_id")
        and metadata.get("chat_id")
        and metadata.get("message_id")
    ):
        return None

    model_id = form_data.get("model")
    base_url, api_key = _resolve_hermes_connection(request, user, model_id)
    if not base_url:
        return None

    event_emitter = get_event_emitter(metadata)
    event_caller = get_event_call(metadata)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    run_payload = _build_run_payload(form_data, metadata)

    def upsert_response_message(message: dict):
        return Chats.upsert_message_to_chat_by_id_and_message_id(
            metadata["chat_id"],
            metadata["message_id"],
            message,
            guard_stopped=True,
        )

    upsert_response_message({"model": model_id})

    async def _emit_completion(data: dict):
        await event_emitter({"type": "chat:completion", "data": data})

    async def _emit_status(description: str, done: bool, action: str = "hermes_agent"):
        try:
            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "action": action,
                        "description": description,
                        "done": done,
                    },
                }
            )
        except Exception:
            pass

    async def _request_approval(session, run_id, event):
        command = event.get("command") or ""
        description = event.get("description") or ""
        title = "Hermes 请求执行命令"
        message = "\n".join(
            part
            for part in [
                description,
                f"命令: {command}" if command else "",
                "确认允许执行吗?(取消 = 拒绝)",
            ]
            if part
        )

        await _emit_status("等待你批准命令审批...", False, action="hermes_approval")

        choice = "deny"
        deadline = time.time() + max(HERMES_AGENT_APPROVAL_TIMEOUT, 30)
        while time.time() < deadline:
            try:
                result = await event_caller(
                    {
                        "type": "confirmation",
                        "data": {"title": title, "message": message},
                    }
                )
            except Exception:
                # Socket call timed out (WEBSOCKET_EVENT_CALLER_TIMEOUT);
                # re-show the dialog until the overall deadline passes.
                await asyncio.sleep(2)
                continue
            choice = "once" if result else "deny"
            break

        try:
            async with session.post(
                f"{base_url}/runs/{run_id}/approval",
                json={"choice": choice},
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    log.warning(
                        f"hermes approval post failed ({resp.status}): {body[:500]}"
                    )
        except Exception as e:
            log.warning(f"hermes approval post error: {e}")

        await _emit_status(
            "命令已批准，继续执行..." if choice == "once" else "命令已拒绝",
            True,
            action="hermes_approval",
        )

    async def _post_stop(run_id):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(
                trust_env=True, timeout=timeout
            ) as session:
                await session.post(
                    f"{base_url}/runs/{run_id}/stop",
                    json={},
                    headers=headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                )
        except Exception as e:
            log.debug(f"hermes stop post error: {e}")

    async def _run_handler():
        blocks = []
        run_id = None
        finalized = False

        def current_text_block():
            if not blocks or blocks[-1]["type"] != "text":
                blocks.append({"type": "text", "content": ""})
            return blocks[-1]

        async def _finalize(error=None, usage=None):
            nonlocal finalized
            if finalized:
                return
            finalized = True
            content = _serialize_blocks(blocks)
            completed_at = int(time.time())
            data = {
                "done": True,
                "content": content,
                "completedAt": completed_at,
            }
            mapped_usage = _map_usage(usage)
            if mapped_usage:
                data["usage"] = mapped_usage
            if error:
                data["error"] = {"content": error}
            title = Chats.get_chat_title_by_id(metadata["chat_id"])
            if title:
                data["title"] = title
            try:
                await _emit_completion(data)
            except Exception as e:
                log.warning(f"hermes completion emit failed: {e}")
            try:
                upsert_response_message(
                    {
                        "content": content,
                        "done": True,
                        "completedAt": completed_at,
                        **({"usage": mapped_usage} if mapped_usage else {}),
                        **({"error": {"content": error}} if error else {}),
                    }
                )
            except Exception as e:
                log.warning(f"hermes completion persist failed: {e}")

        try:
            for event in events or []:
                await _emit_completion(event)
                upsert_response_message({**event})

            timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
            async with aiohttp.ClientSession(
                trust_env=True, timeout=timeout
            ) as session:
                async with session.post(
                    f"{base_url}/runs",
                    json=run_payload,
                    headers=headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        await _finalize(
                            error=f"Hermes run start failed ({resp.status}): {body[:500]}"
                        )
                        return
                    run_data = await resp.json()
                    run_id = run_data.get("run_id")
                    if not run_id:
                        await _finalize(error="Hermes did not return a run_id")
                        return

                async with session.get(
                    f"{base_url}/runs/{run_id}/events",
                    headers=headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        await _finalize(
                            error=f"Hermes event stream failed ({resp.status}): {body[:500]}"
                        )
                        return

                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[len("data:") :].strip())
                        except Exception:
                            continue

                        event_type = event.get("event")

                        if event_type == "message.delta":
                            delta = event.get("delta") or ""
                            if delta:
                                current_text_block()["content"] += delta
                                await _emit_completion(
                                    {"choices": [{"delta": {"content": delta}}]}
                                )
                        elif event_type == "tool.started":
                            blocks.append(
                                {
                                    "type": "tool",
                                    "id": f"hermes-{len(blocks)}",
                                    "name": event.get("tool") or "tool",
                                    "preview": event.get("preview") or "",
                                    "done": False,
                                }
                            )
                            await _emit_completion(
                                {"content": _serialize_blocks(blocks)}
                            )
                        elif event_type == "tool.completed":
                            tool_name = event.get("tool")
                            for block in reversed(blocks):
                                if (
                                    block["type"] == "tool"
                                    and not block.get("done")
                                    and (
                                        block.get("name") == tool_name
                                        or tool_name is None
                                    )
                                ):
                                    block["done"] = True
                                    block["duration"] = event.get("duration", 0)
                                    block["error"] = bool(event.get("error"))
                                    break
                            await _emit_completion(
                                {"content": _serialize_blocks(blocks)}
                            )
                        elif event_type == "reasoning.available":
                            text = event.get("text") or ""
                            if text:
                                blocks.append(
                                    {
                                        "type": "reasoning",
                                        "content": text,
                                        "duration": 0,
                                    }
                                )
                                await _emit_completion(
                                    {"content": _serialize_blocks(blocks)}
                                )
                        elif event_type == "approval.request":
                            await _request_approval(session, run_id, event)
                        elif event_type == "approval.responded":
                            pass
                        elif event_type == "run.completed":
                            output = event.get("output") or ""
                            has_text = any(
                                block["type"] == "text"
                                and str(block.get("content", "")).strip()
                                for block in blocks
                            )
                            if output and not has_text:
                                blocks.append({"type": "text", "content": output})
                            await _finalize(usage=event.get("usage"))
                        elif event_type == "run.failed":
                            await _finalize(
                                error=event.get("error") or "Hermes run failed"
                            )
                        elif event_type == "run.cancelled":
                            await _finalize()

            if not finalized:
                # Stream closed without a terminal event; poll final status.
                error = None
                usage = None
                try:
                    timeout = aiohttp.ClientTimeout(total=15)
                    async with aiohttp.ClientSession(
                        trust_env=True, timeout=timeout
                    ) as session:
                        async with session.get(
                            f"{base_url}/runs/{run_id}",
                            headers=headers,
                            ssl=AIOHTTP_CLIENT_SESSION_SSL,
                        ) as resp:
                            if resp.status < 400:
                                status_data = await resp.json()
                                usage = status_data.get("usage")
                                if status_data.get("status") == "failed":
                                    error = status_data.get("error") or "run failed"
                                output = status_data.get("output") or ""
                                has_text = any(
                                    block["type"] == "text"
                                    and str(block.get("content", "")).strip()
                                    for block in blocks
                                )
                                if output and not has_text:
                                    blocks.append(
                                        {"type": "text", "content": output}
                                    )
                except Exception:
                    pass
                await _finalize(error=error, usage=usage)
        except asyncio.CancelledError:
            if run_id:
                try:
                    await asyncio.shield(_post_stop(run_id))
                except Exception:
                    pass
            try:
                content = _serialize_blocks(blocks)
                upsert_response_message(
                    {
                        "content": content,
                        "done": True,
                        "completedAt": int(time.time()),
                    }
                )
            except Exception:
                pass
            raise
        except Exception as e:
            log.exception("hermes agent run failed")
            await _finalize(error=f"Hermes agent error: {e}")

    task_id, _ = create_task(_run_handler(), id=metadata["chat_id"])
    return {"status": True, "task_id": task_id}
