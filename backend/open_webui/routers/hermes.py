"""Hermes integration endpoints.

POST /api/v1/hermes/steer — inject guidance into the hermes run streaming in a
chat (hermes ``POST /v1/runs/{run_id}/steer``). Signed-in user; the run must be
one of their own chats.

GET /api/v1/hermes/runs — the signed-in user's hermes runs executing right now.

GET /api/v1/hermes/sessions — hermes sessions from another surface (Telegram,
QQ, CLI); POST /api/v1/hermes/sessions/{id}/import turns one into a chat whose
id is the hermes session id, so the chat continues that session.

POST /api/v1/hermes/notifications — a background process started by hermes
(for example a ``reclaude-run.sh`` run) reports its completion. HaloWebUI turns
the notification into a follow-up user turn in the originating chat and starts a
normal hermes run for it, so the report streams into the chat like any reply.

Authentication is a shared bearer token (``HERMES_AGENT_NOTIFY_TOKEN``), not a
user session: the caller is a server-side process, and the chat owner is derived
from the chat itself.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from open_webui.utils.hermes_agent import (
    STEER_TEXT_MAX_CHARS,
    HermesSteerError,
    list_active_runs,
    steer_active_run,
)
from open_webui.utils.hermes_sessions import (
    LIST_LIMIT_DEFAULT,
    HermesSessionsError,
    import_session,
    list_sessions,
    validate_session_id,
)
from open_webui.utils.webhook import post_webhook
from open_webui.utils.hermes_notify import (
    NOTIFICATION_PROMPT_MAX_CHARS,
    HermesNotifyError,
    notify_token_configured,
    start_follow_up_turn,
    verify_notify_token,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

router = APIRouter()


class HermesNotificationForm(BaseModel):
    chat_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=NOTIFICATION_PROMPT_MAX_CHARS)
    source: Optional[str] = Field(default=None, max_length=64)
    run_id: Optional[str] = Field(default=None, max_length=128)


@router.post("/notifications")
async def receive_hermes_notification(request: Request, form_data: HermesNotificationForm):
    if not notify_token_configured():
        raise HTTPException(
            status_code=503,
            detail="hermes notifications are disabled: HERMES_AGENT_NOTIFY_TOKEN is not set",
        )
    if not verify_notify_token(request.headers.get("Authorization")):
        raise HTTPException(status_code=401, detail="invalid notification token")

    try:
        result = await start_follow_up_turn(
            request,
            chat_id=form_data.chat_id,
            prompt=form_data.prompt,
            source=form_data.source or "",
        )
    except HermesNotifyError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f"hermes notification failed for chat {form_data.chat_id}: {e}")
        raise HTTPException(status_code=500, detail="failed to start the follow-up turn")

    return {
        "status": True,
        "chat_id": result["chat_id"],
        "user_message_id": result["user_message_id"],
        "assistant_message_id": result["assistant_message_id"],
        "run_id": form_data.run_id,
    }


class HermesSteerForm(BaseModel):
    chat_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=STEER_TEXT_MAX_CHARS)


@router.post("/steer")
async def steer_hermes_run(form_data: HermesSteerForm, user=Depends(get_verified_user)):
    try:
        return await steer_active_run(
            chat_id=form_data.chat_id, user_id=user.id, text=form_data.text
        )
    except HermesSteerError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/runs")
async def get_active_hermes_runs(user=Depends(get_verified_user)):
    return {"runs": list_active_runs(user.id)}


@router.get("/sessions")
async def list_hermes_sessions(
    request: Request,
    source: str = "telegram",
    limit: int = LIST_LIMIT_DEFAULT,
    model_id: Optional[str] = None,
    user=Depends(get_verified_user),
):
    try:
        sessions = await list_sessions(
            request, user, source=source, limit=limit, model_id=model_id
        )
    except HermesSessionsError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return {"sessions": sessions}


class HermesSessionImportForm(BaseModel):
    model_id: Optional[str] = Field(default=None, max_length=256)


@router.post("/sessions/{session_id}/import")
async def import_hermes_session(
    request: Request,
    session_id: str,
    form_data: Optional[HermesSessionImportForm] = None,
    user=Depends(get_verified_user),
):
    try:
        validate_session_id(session_id)
        return await import_session(
            request,
            user,
            session_id=session_id,
            model_id=form_data.model_id if form_data else None,
        )
    except HermesSessionsError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f"hermes session import failed for {session_id}: {e}")
        raise HTTPException(status_code=500, detail="failed to import the hermes session")


WEBHOOK_TEST_URL_MAX_CHARS = 2048


class HermesWebhookTestForm(BaseModel):
    url: Optional[str] = Field(default=None, max_length=WEBHOOK_TEST_URL_MAX_CHARS)


@router.post("/webhook-test")
async def test_notification_webhook(
    request: Request, form_data: HermesWebhookTestForm, user=Depends(get_verified_user)
):
    """Push one test message through the caller's notification webhook (the URL
    in the form, else the saved one), so a Telegram/Slack/generic target can be
    checked from the settings page before the first long run finishes."""
    if not getattr(request.app.state.config, "ENABLE_USER_WEBHOOKS", True):
        raise HTTPException(status_code=403, detail="user webhooks are disabled")
    url = (form_data.url or "").strip() or (Users.get_user_webhook_url_by_id(user.id) or "")
    if not url:
        raise HTTPException(status_code=400, detail="no webhook url")
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="webhook url must start with http(s)://")
    name = getattr(request.app.state, "WEBUI_NAME", "HaloWebUI")
    delivered = await asyncio.to_thread(
        post_webhook,
        name,
        url,
        f"✅ {name} webhook test\n\n"
        "任务在没有打开页面时完成，会推送到这里。\n"
        "Task completions will be pushed here while no tab is open.",
        {"action": "test", "message": "webhook test", "title": name, "url": "", "user": user.name},
    )
    return {"status": bool(delivered)}
