"""Bookmark Hub embed endpoints (see ``open_webui.utils.hub_embed``).

POST /api/v1/hub/handshake — the Hub checks that both sides hold the same
secret. Takes a ``probe`` ticket, hands out nothing.

POST /api/v1/hub/session — the sign-in page, framed by the Hub, trades the
single-use ``chat`` ticket from its address fragment for a HaloWebUI session.

Neither endpoint takes a HaloWebUI credential: the signed ticket *is* the
credential, the same way a password is on /auths/signin. Both are 404 while the
feature is not configured.
"""

import datetime
import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from open_webui.env import (
    SRC_LOG_LEVELS,
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
)
from open_webui.models.users import Users
from open_webui.utils import hub_embed
from open_webui.utils.auth import create_token

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

router = APIRouter()


class TicketForm(BaseModel):
    ticket: str


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _refuse(request: Request, reason: str):
    hub_embed.record_failure(_client(request), reason)
    log.warning("hub embed: ticket refused (%s) from %s", reason, _client(request))
    # The reason is a bare word (expired, replayed, audience ...): enough to fix
    # a misconfiguration, useless to someone without the secret.
    raise HTTPException(status_code=401, detail={"error": "ticket_refused", "reason": reason})


def _guard(request: Request) -> None:
    if not hub_embed.sso_configured():
        raise HTTPException(status_code=404, detail="Not Found")
    wait = hub_embed.retry_after(_client(request))
    if wait:
        raise HTTPException(
            status_code=429,
            detail={"error": "too_many_attempts", "retry_after": wait},
            headers={"Retry-After": str(wait)},
        )


def _permissions(request: Request, user) -> dict:
    # Imported here, not at module level: access_control pulls in open_webui.config,
    # which opens the database and runs migrations on import.
    from open_webui.utils.access_control import get_permissions

    return get_permissions(user.id, request.app.state.config.USER_PERMISSIONS)


def _session_user():
    """The account a ticket signs in as, or None when there is no usable one."""
    email = hub_embed.session_user_email()
    user = Users.get_user_by_email(email) if email else Users.get_first_user()
    if user is None:
        return None
    # The default is the primary admin. An explicitly named account may be an
    # ordinary user (a deliberate way to hand the Hub less than admin rights),
    # but never one that is still waiting for approval.
    if user.role == "admin" or (email and user.role == "user"):
        return user
    return None


@router.post("/handshake")
async def hub_handshake(request: Request, response: Response, form_data: TicketForm):
    _guard(request)
    ok, reason = hub_embed.consume_ticket(
        form_data.ticket, hub_embed.PURPOSE_PROBE, audience=None, check_audience=False
    )
    if not ok:
        _refuse(request, reason)
    response.headers["Cache-Control"] = "no-store"
    return {
        "ok": True,
        # Already public (it is in the CSP header of every response); repeated
        # here so the Hub can say "your address is not on the list".
        "frame_ancestors": hub_embed.frame_ancestors(),
        "session_ttl": hub_embed.session_ttl_seconds(),
        "session_user_ready": _session_user() is not None,
    }


@router.post("/session")
async def hub_session(request: Request, response: Response, form_data: TicketForm):
    _guard(request)
    ok, reason = hub_embed.consume_ticket(
        form_data.ticket,
        hub_embed.PURPOSE_CHAT,
        # Set by the browser, not by page script: the ticket only works from a
        # page served by the origin the Hub addressed it to.
        audience=hub_embed.normalize_origin(request.headers.get("origin")),
    )
    if not ok:
        _refuse(request, reason)

    user = _session_user()
    if user is None:
        log.warning("hub embed: ticket accepted but there is no account to sign in as")
        raise HTTPException(status_code=403, detail={"error": "no_session_user"})

    ttl = hub_embed.session_ttl_seconds()
    expires_at = int(time.time()) + ttl
    token = create_token(
        data={"id": user.id, hub_embed.SESSION_EXPIRY_CLAIM: expires_at},
        expires_delta=datetime.timedelta(seconds=ttl),
    )
    response.set_cookie(
        key="token",
        value=token,
        expires=datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc),
        httponly=True,
        samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
        secure=WEBUI_AUTH_COOKIE_SECURE,
    )
    response.headers["Cache-Control"] = "no-store"
    log.info("hub embed: opened a %ss session for user %s from a Hub ticket", ttl, user.id)

    return {
        "token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "profile_image_url": user.profile_image_url,
        "permissions": _permissions(request, user),
    }
