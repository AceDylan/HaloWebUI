"""Bookmark Hub embed: sign-in bridge between HaloWebUI and the Hub iframe.

HaloWebUI embeds the Bookmark Hub (AICheckIn) on its ``/hub`` page. The Hub is
a different host with its own admin password and its own HMAC session cookie,
so a HaloWebUI sign-in does not reach it. This module closes that gap one way
only (HaloWebUI admin -> Hub admin):

1. Both deployments hold the same random secret in the environment variable
   ``HUB_TRUSTED_EMBED_ADMIN_SECRET``. The administrator generates it at deploy
   time; it never enters a repository, a URL, a log line or the browser.
2. When a HaloWebUI **admin** opens ``/hub``, the backend signs a ticket

       v1.<purpose>.<expiry unix time>.<nonce>.<HMAC-SHA256 hex>

   and the page points the iframe at ``<HUB_URL>/embed/enter?ticket=...``.
3. The Hub verifies signature, purpose, expiry and that the nonce is unused,
   then issues its ordinary session cookie and redirects to a clean URL.

Tickets appear in a URL, so they are single-use and live two minutes. Nothing
is fetched from the Hub to build one: the login path has no server-to-server
round trip and keeps working when this container cannot reach the Hub.

The start-up handshake is diagnostic only. It posts a ``probe`` ticket (which
the Hub refuses to trade for a session) to ``/api/embed/handshake`` and records
whether the two secrets match, plus the Hub's iframe allow-list, so the
``/hub`` page can say *why* an embed would fail instead of showing a blank
frame. It never blocks start-up and never raises.

Configuration (environment variables):

- HUB_URL: origin of the Hub. Default ``https://best.acedylan.us:5526``; set it
  to an empty string to remove the feature.
- HUB_TRUSTED_EMBED_ADMIN_SECRET: the shared secret, at least 32 characters.
  Unset: the iframe still loads, the Hub just asks for its own password.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from typing import Any, Optional
from urllib.parse import quote

import aiohttp

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

HUB_URL_ENV = "HUB_URL"
HUB_SECRET_ENV = "HUB_TRUSTED_EMBED_ADMIN_SECRET"
DEFAULT_HUB_URL = "https://best.acedylan.us:5526"

SECRET_MIN_LENGTH = 32
TICKET_VERSION = "v1"
TICKET_TTL_SECONDS = 120
PURPOSE_ENTER = "enter"
PURPOSE_PROBE = "probe"

HANDSHAKE_TIMEOUT_SECONDS = 5
# A failed handshake is retried when an admin opens /hub, at most this often.
HANDSHAKE_RETRY_SECONDS = 60
# A successful one is refreshed in the background this often, so a changed
# allow-list on the Hub shows up without a restart here.
HANDSHAKE_REFRESH_SECONDS = 600

_HUB_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")

# Last handshake outcome; holds no secret material.
_handshake: dict[str, Any] = {
    "ok": None,
    "reason": "not_run",
    "checked_at": None,
    "frame_ancestors": None,
}
_handshake_lock = asyncio.Lock()
_background_tasks: set[asyncio.Task] = set()


def hub_url() -> Optional[str]:
    """The Hub origin without a trailing slash, or None when the feature is off."""
    raw = os.environ.get(HUB_URL_ENV, DEFAULT_HUB_URL).strip().rstrip("/")
    if not raw:
        return None
    if not _HUB_URL_RE.match(raw):
        log.warning("%s is not a plain origin (scheme://host[:port]); hub embed disabled", HUB_URL_ENV)
        return None
    return raw


def _secret() -> str:
    value = os.environ.get(HUB_SECRET_ENV, "").strip()
    return value if len(value) >= SECRET_MIN_LENGTH else ""


def sso_configured() -> bool:
    return bool(hub_url() and _secret())


def _ticket_key(secret: str) -> bytes:
    # Domain-separated key: the Hub derives the same one from the same secret.
    return hashlib.sha256(("hub-embed-admin|" + secret).encode("utf-8")).digest()


def mint_ticket(purpose: str, *, ttl: int = TICKET_TTL_SECONDS, now: Optional[float] = None) -> str:
    """Sign a single-use ticket. Raises RuntimeError when no secret is configured."""
    secret = _secret()
    if not secret:
        raise RuntimeError(f"{HUB_SECRET_ENV} is not configured")
    expires = str(int(now if now is not None else time.time()) + int(ttl))
    nonce = secrets.token_urlsafe(18)
    message = ".".join((TICKET_VERSION, purpose, expires, nonce))
    signature = hmac.new(_ticket_key(secret), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def build_embed_url(*, with_ticket: bool = True) -> Optional[str]:
    """Address for the iframe (or a new tab): through the ticket exchange when
    a secret is configured, the plain Hub home page otherwise.

    Pass ``with_ticket=False`` when the handshake already showed that the Hub
    will refuse our tickets: presenting one anyway only feeds the Hub's
    brute-force counter from the admin's own IP address."""
    base = hub_url()
    if not base:
        return None
    if not with_ticket or not _secret():
        # The query string keeps the Hub's service worker on its network-first path.
        return f"{base}/?embed=1"
    return f"{base}/embed/enter?ticket={quote(mint_ticket(PURPOSE_ENTER), safe='')}"


def handshake_state() -> dict[str, Any]:
    return dict(_handshake)


def _record(ok: Optional[bool], reason: str, frame_ancestors: Optional[list[str]] = None) -> None:
    _handshake.update(
        ok=ok,
        reason=reason,
        checked_at=int(time.time()),
        frame_ancestors=frame_ancestors,
    )


async def run_handshake() -> dict[str, Any]:
    """Ask the Hub whether it accepts our secret. Never raises."""
    base = hub_url()
    if not base:
        _record(None, "hub_url_unset")
        return handshake_state()
    if not _secret():
        if os.environ.get(HUB_SECRET_ENV, "").strip():
            log.warning("%s is shorter than %d characters and is ignored", HUB_SECRET_ENV, SECRET_MIN_LENGTH)
            _record(False, "secret_too_short")
        else:
            _record(None, "secret_unset")
        return handshake_state()

    async with _handshake_lock:
        try:
            timeout = aiohttp.ClientTimeout(total=HANDSHAKE_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
                async with session.post(
                    f"{base}/api/embed/handshake",
                    json={"ticket": mint_ticket(PURPOSE_PROBE)},
                ) as response:
                    status = response.status
                    try:
                        body = await response.json(content_type=None)
                    except Exception:
                        body = None
        except Exception as exc:
            # Unreachable is not fatal: the browser talks to the Hub directly.
            log.warning("hub embed handshake could not reach %s: %s", base, type(exc).__name__)
            _record(None, "unreachable")
            return handshake_state()

        body = body if isinstance(body, dict) else {}
        if status == 200 and body.get("ok") is True:
            ancestors = body.get("frame_ancestors")
            ancestors = [str(item) for item in ancestors] if isinstance(ancestors, list) else None
            _record(True, "ok", ancestors)
            log.info("hub embed handshake ok: %s accepts our tickets", base)
        elif status == 404:
            # The Hub has no secret configured (or predates the feature).
            log.warning("hub embed handshake: %s has no trusted-embed secret configured", base)
            _record(False, "hub_not_configured")
        elif status == 401:
            # The reason is remote input that ends up in a log line: keep it to a bare word.
            reason = re.sub(r"[^a-z_]", "", str(body.get("reason") or "").lower())[:32] or "rejected"
            log.warning("hub embed handshake rejected by %s (%s)", base, reason)
            _record(False, "secret_mismatch" if reason == "signature" else reason)
        elif status == 429:
            _record(None, "throttled")
        else:
            log.warning("hub embed handshake: unexpected status %s from %s", status, base)
            _record(None, f"http_{status}")
        return handshake_state()


async def ensure_handshake() -> dict[str, Any]:
    """Current handshake state, re-running a handshake that has not succeeded
    yet (rate limited), so fixing the Hub's configuration needs no restart here."""
    state = handshake_state()
    checked_at = state["checked_at"]
    age = None if checked_at is None else time.time() - checked_at
    if state["ok"] is True:
        if age is not None and age >= HANDSHAKE_REFRESH_SECONDS and not _handshake_lock.locked():
            # Still good enough to answer with; do not make the page wait.
            _background_tasks.add(task := asyncio.create_task(run_handshake()))
            task.add_done_callback(_background_tasks.discard)
        return state
    if age is None or age >= HANDSHAKE_RETRY_SECONDS:
        return await run_handshake()
    return state


async def startup_handshake() -> None:
    """Fire-and-forget entry point for the app lifespan."""
    try:
        state = await run_handshake()
        if state["reason"] == "secret_unset":
            log.info("hub embed: %s is unset; the Hub iframe will ask for its own password", HUB_SECRET_ENV)
    except Exception as exc:  # pragma: no cover - defensive, run_handshake does not raise
        log.warning("hub embed handshake failed unexpectedly: %s", type(exc).__name__)
