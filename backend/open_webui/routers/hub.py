"""Bookmark Hub embed endpoints.

POST /api/v1/hub/embed — address for the ``/hub`` iframe. Admins only: the
address carries a single-use ticket that the Hub trades for its **admin**
session (see ``open_webui.utils.hub_embed``), so nobody else may mint one.
POST rather than GET because every call issues a fresh credential.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.auth import get_admin_user
from open_webui.utils.hub_embed import (
    build_embed_url,
    ensure_handshake,
    hub_url,
    sso_configured,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

router = APIRouter()


@router.post("/embed")
async def create_hub_embed(response: Response, user=Depends(get_admin_user)):
    base = hub_url()
    if not base:
        raise HTTPException(status_code=404, detail="Bookmark Hub embed is disabled: HUB_URL is empty")

    handshake = await ensure_handshake()
    # A handshake that failed outright (secret mismatch, Hub not configured)
    # means a ticket would be refused; unknown (Hub unreachable from here) does
    # not, because the browser reaches the Hub on its own.
    sso = sso_configured() and handshake["ok"] is not False

    response.headers["Cache-Control"] = "no-store"
    return {
        "hub_url": base,
        "url": build_embed_url(with_ticket=sso),
        "sso": sso,
        "handshake": {
            "ok": handshake["ok"],
            "reason": handshake["reason"],
            "checked_at": handshake["checked_at"],
            "frame_ancestors": handshake["frame_ancestors"],
        },
    }
