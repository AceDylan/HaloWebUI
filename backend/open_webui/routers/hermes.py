"""Hermes integration endpoints.

POST /api/v1/hermes/notifications — a background process started by hermes
(for example a ``reclaude-run.sh`` run) reports its completion. HaloWebUI turns
the notification into a follow-up user turn in the originating chat and starts a
normal hermes run for it, so the report streams into the chat like any reply.

Authentication is a shared bearer token (``HERMES_AGENT_NOTIFY_TOKEN``), not a
user session: the caller is a server-side process, and the chat owner is derived
from the chat itself.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.env import SRC_LOG_LEVELS
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
