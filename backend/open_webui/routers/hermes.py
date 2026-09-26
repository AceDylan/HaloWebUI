"""Hermes integration endpoints.

POST /api/v1/hermes/steer — inject guidance into the hermes run streaming in a
chat (hermes ``POST /v1/runs/{run_id}/steer``). Signed-in user; the run must be
one of their own chats.

GET /api/v1/hermes/runs — the signed-in user's hermes runs executing right now.

POST /api/v1/hermes/runners/{run_id}/stop — stop a background runner (reclaude /
codex / agy) that one of the user's chats launched (hermes
``POST /v1/runners/{runner}/{run_id}/stop``).

GET /api/v1/hermes/sessions — hermes sessions from another surface (Telegram,
QQ, CLI); POST /api/v1/hermes/sessions/{id}/import turns one into a chat whose
id is the hermes session id, so the chat continues that session.

POST /api/v1/hermes/notifications — a background process started by hermes
(for example a ``reclaude-run.sh`` run) reports its completion. With
``mode=display`` the payload carries the report itself (``content``, plus a short
``notice``) and HaloWebUI shows it as the reply, with no model turn. Otherwise
HaloWebUI turns ``prompt`` into a follow-up user turn in the originating chat and
starts a normal hermes run for it, so the report streams into the chat like any
reply. Runners send both, so an older HaloWebUI still works.

Authentication is a shared bearer token (``HERMES_AGENT_NOTIFY_TOKEN``), not a
user session: the caller is a server-side process, and the chat owner is derived
from the chat itself.
"""

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    LIST_LIMIT_MAX,
    LIST_OFFSET_MAX,
    HermesSessionsError,
    import_session,
    list_model_options,
    list_sessions,
    stop_background_runner,
    validate_session_id,
)
from open_webui.utils.hermes_unread import list_unread_chat_ids, mark_read
from open_webui.utils.hermes_runner_progress import (
    clear_runner_progress,
    list_runner_progress,
    record_runner_progress,
)
from open_webui.utils.webhook import post_webhook
from open_webui.utils.hermes_notify import (
    NOTIFICATION_CONTENT_MAX_CHARS,
    NOTIFICATION_PROMPT_MAX_CHARS,
    HermesNotifyError,
    notify_token_configured,
    show_notification_report,
    start_follow_up_turn,
    verify_notify_token,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

router = APIRouter()


class HermesNotificationForm(BaseModel):
    chat_id: str = Field(min_length=1, max_length=128)
    # Required for a follow-up turn; a progress report carries none.
    prompt: str = Field(default="", max_length=NOTIFICATION_PROMPT_MAX_CHARS)
    source: Optional[str] = Field(default=None, max_length=64)
    run_id: Optional[str] = Field(default=None, max_length=128)
    mode: Optional[Literal["display", "progress"]] = None
    content: Optional[str] = Field(default=None, max_length=NOTIFICATION_CONTENT_MAX_CHARS)
    notice: Optional[str] = Field(default=None, max_length=4000)
    # mode=progress: where a background runner is.
    agent: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=32)
    started_at: Optional[float] = None
    step: Optional[int] = Field(default=None, ge=0)
    last_activity: Optional[str] = Field(default=None, max_length=2000)


@router.post("/notifications")
async def receive_hermes_notification(request: Request, form_data: HermesNotificationForm):
    if not notify_token_configured():
        raise HTTPException(
            status_code=503,
            detail="hermes notifications are disabled: HERMES_AGENT_NOTIFY_TOKEN is not set",
        )
    if not verify_notify_token(request.headers.get("Authorization")):
        raise HTTPException(status_code=401, detail="invalid notification token")

    if form_data.mode == "progress":
        entry = record_runner_progress(
            chat_id=form_data.chat_id,
            run_id=form_data.run_id or "",
            agent=form_data.agent or form_data.source or "",
            status=form_data.status or "running",
            started_at=form_data.started_at,
            step=form_data.step,
            last_activity=form_data.last_activity or "",
        )
        return {
            "status": True,
            "chat_id": form_data.chat_id,
            "run_id": form_data.run_id,
            "mode": "progress",
            "active": entry is not None,
        }
    if not form_data.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt is required")

    try:
        if form_data.mode == "display" and (form_data.content or "").strip():
            clear_runner_progress(form_data.run_id)
            result = await show_notification_report(
                request,
                chat_id=form_data.chat_id,
                content=form_data.content,
                notice=form_data.notice or "",
                source=form_data.source or "",
                run_id=form_data.run_id or "",
            )
        else:
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
        "mode": "display" if form_data.mode == "display" and (form_data.content or "").strip() else "turn",
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
    """Runs executing now, plus the chats whose run finished and has not been
    opened since — one poll feeds both sidebar indicators."""
    return {
        "runs": list_active_runs(user.id),
        "unread": list_unread_chat_ids(user.id),
        # Background runners (reclaude / codex / agy) started from a chat.
        "background": list_runner_progress(user.id),
    }


@router.get("/model-options")
async def get_hermes_model_options(
    request: Request, model_id: Optional[str] = None, user=Depends(get_verified_user)
):
    """The models (by provider) hermes can run a chat with, for the composer's
    per-chat model picker."""
    try:
        return await list_model_options(request, user, model_id)
    except HermesSessionsError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/runners/{run_id}/stop")
async def stop_hermes_background_runner(
    request: Request, run_id: str, user=Depends(get_verified_user)
):
    """Stop a background runner (reclaude / codex / agy) one of the user's chats
    launched; the chat then shows a short "已停止" report."""
    try:
        return await stop_background_runner(request, user, run_id)
    except HermesSessionsError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/chats/{chat_id}/read")
async def mark_hermes_chat_read(chat_id: str, user=Depends(get_verified_user)):
    """Opening a chat clears the unread mark its finished hermes run left."""
    if len(chat_id) > 128 or not mark_read(chat_id, user.id):
        raise HTTPException(status_code=404, detail="chat not found")
    return {"status": True}


@router.get("/sessions")
async def list_hermes_sessions(
    request: Request,
    source: str = "telegram",
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
    offset: int = Query(0, ge=0, le=LIST_OFFSET_MAX),
    model_id: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """One page of hermes sessions for a surface.

    Cursor paging: hermes reports no total, so the answer carries
    ``next_offset``/``has_more`` instead of a page count. ``sessions`` stays
    the list it always was.
    """
    try:
        return await list_sessions(
            request,
            user,
            source=source,
            limit=limit,
            offset=offset,
            model_id=model_id,
        )
    except HermesSessionsError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


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
