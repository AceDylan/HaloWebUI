"""Bookmark Hub embed: let the Hub frame HaloWebUI and sign its admin in.

The Bookmark Hub (AICheckIn) is the outer page: its "AI chat" tab holds an
iframe pointing at HaloWebUI. Two things are needed from this side.

1. **Framing.** Every response carries ``Content-Security-Policy:
   frame-ancestors 'self' <origin of HUB_URL>``. Exactly one foreign origin is
   ever listed and it is never a wildcard. With ``HUB_URL`` empty the feature is
   off and no header is added (see ``open_webui.utils.security_headers``).

2. **Sign-in bridge, Hub admin -> HaloWebUI (one way).** The two sites are
   different hosts and cannot read each other's cookies, so the Hub's backend
   signs a short-lived, single-use ticket for its unlocked administrator:

       v2.<purpose>.<expiry>.<nonce>.<issuer>.<audience>.<HMAC-SHA256 hex>

   ``issuer`` is the Hub's origin and ``audience`` is ours, both base64url. The
   key is derived from ``HUB_TRUSTED_EMBED_ADMIN_SECRET``, a random value the
   administrator generates at deploy time and puts in both deployments'
   environment. It never enters a repository, a URL, a log line or a browser.

   The Hub points the iframe at ``/auth#hub_ticket=<ticket>``. The fragment
   never reaches a server log or a Referer header; the sign-in page posts it to
   ``POST /api/v1/hub/session``, which checks, in this order: signature,
   purpose, expiry (and that the lifetime is short), issuer == origin of
   ``HUB_URL``, audience == the ``Origin`` header the browser put on the request,
   and that the nonce is unused. Only then is an ordinary HaloWebUI session
   issued, with a shorter lifetime than a password sign-in.

   ``POST /api/v1/hub/handshake`` takes a ``probe`` ticket and answers only
   "the secrets match" plus the framing allow-list, so the Hub can explain a
   misconfiguration instead of showing a blank frame. A probe ticket can never
   be traded for a session: the purpose is part of what is signed.

Nonces are remembered in process memory until the ticket expires. That is exact
with one worker (the default, ``UVICORN_WORKERS=1``); with N workers a ticket
could be replayed once per worker within its 60 seconds.

Configuration (environment variables):

- HUB_URL: origin of the Hub. Default ``https://best.acedylan.us:5526``; an
  empty string removes the feature (no framing header, both endpoints 404).
- HUB_TRUSTED_EMBED_ADMIN_SECRET: the shared secret, at least 32 characters.
  Unset: the Hub can still frame HaloWebUI, which then asks for its own sign-in.
- HUB_EMBED_USER_EMAIL: account a ticket signs in as. Default: the primary
  admin (the first account created).
- HUB_EMBED_SESSION_TTL: lifetime in seconds of a session opened by a ticket.
  Default 43200 (12 hours), clamped to 5 minutes .. 30 days.
"""

import base64
import binascii
import hashlib
import hmac
import logging
import os
import re
import threading
import time
from collections import deque
from functools import lru_cache
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

HUB_URL_ENV = "HUB_URL"
HUB_SECRET_ENV = "HUB_TRUSTED_EMBED_ADMIN_SECRET"
HUB_USER_EMAIL_ENV = "HUB_EMBED_USER_EMAIL"
HUB_SESSION_TTL_ENV = "HUB_EMBED_SESSION_TTL"
DEFAULT_HUB_URL = "https://best.acedylan.us:5526"

SECRET_MIN_LENGTH = 32
TICKET_VERSION = "v2"
# The Hub signs 60 seconds; anything that claims to live longer than this is refused.
TICKET_MAX_TTL_SECONDS = 120
PURPOSE_CHAT = "chat"
PURPOSE_PROBE = "probe"

DEFAULT_SESSION_TTL_SECONDS = 12 * 3600
MIN_SESSION_TTL_SECONDS = 300
MAX_SESSION_TTL_SECONDS = 30 * 24 * 3600

# Claim carried by a session that was opened with a ticket: its absolute expiry.
# GET /api/v1/auths/ re-issues the token on every page load; with this claim it
# keeps the original expiry instead of growing into a full-length session.
SESSION_EXPIRY_CLAIM = "hub_exp"

# https anywhere; http only on loopback, for local development. No wildcards,
# no paths, no credentials: a mistyped value must mean "cannot be framed".
_ORIGIN_RE = re.compile(
    r"^(?:https://(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"|http://(?:localhost|127\.0\.0\.1))(?::[0-9]{1,5})?$"
)
_PURPOSE_RE = re.compile(r"^[a-z]{1,16}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_B64_ORIGIN_RE = re.compile(r"^[A-Za-z0-9_-]{8,400}$")
_TICKET_MAX_LENGTH = 1024

_MAX_NONCES = 4096
_nonce_lock = threading.Lock()
_nonces: dict[str, int] = {}  # nonce -> expiry; only tickets with a valid signature get here

# Failed attempts that look like guessing (bad format, bad signature). An
# HMAC-SHA256 tag cannot be guessed, but nobody gets unlimited tries either.
FAILURE_WINDOW_SECONDS = 300
FAILURE_LIMIT_PER_CLIENT = 10
FAILURE_LIMIT_GLOBAL = 100
GUESSING_REASONS = frozenset({"malformed", "signature"})
_failure_lock = threading.Lock()
_failures_by_client: dict[str, deque] = {}
_failures_global: deque = deque()


def normalize_origin(value: Optional[str]) -> Optional[str]:
    """``scheme://host[:port]`` in lower case, or None when it is anything else."""
    origin = str(value or "").strip().rstrip("/").lower()
    if not origin or len(origin) > 300 or not _ORIGIN_RE.match(origin):
        return None
    return origin


@lru_cache(maxsize=8)
def _parse_hub_url(raw: str) -> Optional[str]:
    # Cached per raw value: this runs for every response (framing header), and
    # a bad value should be reported once, not once per request.
    if not raw.strip():
        return None
    origin = normalize_origin(raw)
    if origin is None:
        log.warning(
            "%s is not a plain origin (https://host[:port], no path, no wildcard); "
            "Bookmark Hub embedding is disabled",
            HUB_URL_ENV,
        )
    return origin


def hub_origin() -> Optional[str]:
    """Origin of the Hub, or None when the feature is off."""
    return _parse_hub_url(os.environ.get(HUB_URL_ENV, DEFAULT_HUB_URL))


def frame_ancestors() -> list[str]:
    """Foreign origins allowed to frame HaloWebUI: the Hub, and nothing else."""
    origin = hub_origin()
    return [origin] if origin else []


def _secret() -> str:
    value = os.environ.get(HUB_SECRET_ENV, "").strip()
    return value if len(value) >= SECRET_MIN_LENGTH else ""


def secret_is_too_short() -> bool:
    value = os.environ.get(HUB_SECRET_ENV, "").strip()
    return bool(value) and len(value) < SECRET_MIN_LENGTH


def sso_configured() -> bool:
    return bool(hub_origin() and _secret())


def session_ttl_seconds() -> int:
    try:
        ttl = int(os.environ.get(HUB_SESSION_TTL_ENV, "") or DEFAULT_SESSION_TTL_SECONDS)
    except ValueError:
        ttl = DEFAULT_SESSION_TTL_SECONDS
    return max(MIN_SESSION_TTL_SECONDS, min(ttl, MAX_SESSION_TTL_SECONDS))


def session_user_email() -> str:
    return os.environ.get(HUB_USER_EMAIL_ENV, "").strip().lower()


def presented_session_expiry(token_payload: Optional[dict]) -> Optional[int]:
    """Expiry a Hub-opened session was issued with, read from its decoded token;
    None for every other kind of session."""
    value = (token_payload or {}).get(SESSION_EXPIRY_CLAIM)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return int(value)


def _ticket_key(secret: str) -> bytes:
    # Domain-separated, and not the label of the retired HaloWebUI -> Hub
    # direction ("hub-embed-admin|"): a ticket minted for that flow never verifies here.
    return hashlib.sha256(("hub-chat-admin|" + secret).encode("utf-8")).digest()


def _b64_origin(origin: str) -> str:
    return base64.urlsafe_b64encode(origin.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64_origin(value: str) -> Optional[str]:
    if not _B64_ORIGIN_RE.match(value):
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    # Must already be in canonical form, so one origin has exactly one spelling.
    return decoded if normalize_origin(decoded) == decoded else None


def sign_ticket(
    purpose: str,
    issuer: str,
    audience: str,
    *,
    ttl: int = 60,
    now: Optional[float] = None,
    nonce: Optional[str] = None,
    secret: Optional[str] = None,
) -> str:
    """Sign a ticket the way the Hub does. Production tickets come from the Hub;
    this exists for the tests and for trying the flow out locally."""
    import secrets as _secrets

    key_material = secret if secret is not None else _secret()
    if not key_material:
        raise RuntimeError(f"{HUB_SECRET_ENV} is not configured")
    expires = str(int(now if now is not None else time.time()) + int(ttl))
    message = ".".join(
        (
            TICKET_VERSION,
            purpose,
            expires,
            nonce or _secrets.token_urlsafe(18),
            _b64_origin(issuer),
            _b64_origin(audience),
        )
    )
    tag = hmac.new(_ticket_key(key_material), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{message}.{tag}"


def consume_ticket(
    ticket: Optional[str],
    purpose: str,
    *,
    audience: Optional[str],
    check_audience: bool = True,
    now: Optional[float] = None,
) -> tuple[bool, str]:
    """Verify a ticket and burn its nonce. Returns ``(ok, reason)``; the reason
    is a bare word for logs and for the page, never anything sensitive.

    ``audience`` is the origin the browser says the exchanging page was served
    from (the ``Origin`` request header). The handshake is server to server and
    has no such header, so it passes ``check_audience=False``.
    """
    secret = _secret()
    expected_issuer = hub_origin()
    if not secret or not expected_issuer:
        return False, "disabled"
    if not ticket:
        return False, "missing"
    ticket = str(ticket)
    parts = ticket.split(".")
    if len(ticket) > _TICKET_MAX_LENGTH or len(parts) != 7:
        return False, "malformed"
    version, got_purpose, expires, nonce, issuer_b64, audience_b64, tag = parts
    if (
        version != TICKET_VERSION
        or not _PURPOSE_RE.match(got_purpose)
        or not expires.isdigit()
        or len(expires) > 12
        or not _NONCE_RE.match(nonce)
        or not re.match(r"^[0-9a-f]{64}$", tag)
    ):
        return False, "malformed"
    issuer = _unb64_origin(issuer_b64)
    ticket_audience = _unb64_origin(audience_b64)
    if issuer is None or ticket_audience is None:
        return False, "malformed"

    # Signature before anything else: without the secret every attempt gets the same answer.
    message = ticket[: -(len(tag) + 1)]
    expected = hmac.new(_ticket_key(secret), message.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(tag.encode("ascii"), expected.encode("ascii")):
        return False, "signature"
    if got_purpose != purpose:
        return False, "purpose"

    current = time.time() if now is None else now
    expires_at = int(expires)
    if expires_at <= current:
        return False, "expired"
    if expires_at > current + TICKET_MAX_TTL_SECONDS:
        return False, "ttl"
    if issuer != expected_issuer:
        return False, "issuer"
    if check_audience:
        if not audience:
            return False, "origin_missing"
        if ticket_audience != audience:
            return False, "audience"

    with _nonce_lock:
        for seen in [n for n, t in _nonces.items() if t <= current]:
            del _nonces[seen]
        if nonce in _nonces:
            return False, "replayed"
        if len(_nonces) >= _MAX_NONCES:
            # Only a holder of the secret can fill this table. Refuse rather
            # than evict: evicting would let an old ticket through again.
            return False, "busy"
        _nonces[nonce] = expires_at
    return True, "ok"


def _prune(window: deque, current: float) -> None:
    while window and window[0] <= current - FAILURE_WINDOW_SECONDS:
        window.popleft()


def retry_after(client: str, now: Optional[float] = None) -> int:
    """Seconds this client has to wait before another attempt, 0 when it may go ahead."""
    current = time.time() if now is None else now
    with _failure_lock:
        _prune(_failures_global, current)
        mine = _failures_by_client.get(client)
        if mine is not None:
            _prune(mine, current)
            if not mine:
                del _failures_by_client[client]
                mine = None
        blocked = None
        if mine is not None and len(mine) >= FAILURE_LIMIT_PER_CLIENT:
            blocked = mine[0]
        elif len(_failures_global) >= FAILURE_LIMIT_GLOBAL:
            # Backstop for an attacker who rotates addresses (or forges X-Forwarded-For).
            blocked = _failures_global[0]
        if blocked is None:
            return 0
        return max(1, int(blocked + FAILURE_WINDOW_SECONDS - current) + 1)


def record_failure(client: str, reason: str, now: Optional[float] = None) -> None:
    """Count an attempt that looks like guessing. A ticket with a good signature
    that is merely expired or already used means the caller does hold the
    secret (clock skew, a double click); counting those would only lock the
    administrator out."""
    if reason not in GUESSING_REASONS:
        return
    current = time.time() if now is None else now
    with _failure_lock:
        _failures_global.append(current)
        if len(_failures_by_client) < 4096 or client in _failures_by_client:
            _failures_by_client.setdefault(client, deque()).append(current)


def log_startup_state() -> None:
    """One line at start-up saying what this deployment will do. No secret material."""
    origin = hub_origin()
    if not origin:
        log.info("hub embed: %s is empty; framing allow-list and ticket sign-in are off", HUB_URL_ENV)
        return
    if secret_is_too_short():
        log.warning(
            "hub embed: %s is shorter than %d characters and is ignored; generate one with "
            "python3 -c \"import secrets; print(secrets.token_hex(32))\"",
            HUB_SECRET_ENV,
            SECRET_MIN_LENGTH,
        )
    log.info(
        "hub embed: %s may frame this site; ticket sign-in is %s",
        origin,
        "on" if sso_configured() else f"off ({HUB_SECRET_ENV} not set)",
    )


def reset_state() -> None:
    """Forget nonces and failure counters. For tests."""
    with _nonce_lock:
        _nonces.clear()
    with _failure_lock:
        _failures_by_client.clear()
        _failures_global.clear()
    _parse_hub_url.cache_clear()
