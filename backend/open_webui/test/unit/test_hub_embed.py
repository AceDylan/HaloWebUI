import base64
import hashlib
import hmac
import secrets
import time
from types import SimpleNamespace

import pytest

from open_webui.utils import hub_embed, security_headers

SECRET = "unit-test-embed-secret-" + "0123456789abcdef" * 2
HUB = "https://best.acedylan.us:5526"
HALO = "https://host.acedylan.us:3001"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    for name in (
        hub_embed.HUB_URL_ENV,
        hub_embed.HUB_SECRET_ENV,
        hub_embed.HUB_USER_EMAIL_ENV,
        hub_embed.HUB_SESSION_TTL_ENV,
        "CONTENT_SECURITY_POLICY",
        "XFRAME_OPTIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    hub_embed.reset_state()
    yield
    hub_embed.reset_state()


def _b64(origin: str) -> str:
    return base64.urlsafe_b64encode(origin.encode()).decode().rstrip("=")


def _sign_like_the_hub(
    purpose, *, secret=SECRET, issuer=HUB, audience=HALO, ttl=60, now=None, label="hub-chat-admin|"
):
    """The Hub's signer, re-implemented from the documented format rather than
    imported, so a drift in either implementation fails here."""
    expires = str(int(now if now is not None else time.time()) + ttl)
    message = ".".join(("v2", purpose, expires, secrets.token_urlsafe(18), _b64(issuer), _b64(audience)))
    key = hashlib.sha256((label + secret).encode()).digest()
    return message + "." + hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


# ---- configuration -------------------------------------------------------


def test_hub_origin_defaults_and_can_be_switched_off(monkeypatch):
    assert hub_embed.hub_origin() == HUB
    assert hub_embed.frame_ancestors() == [HUB]

    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "https://Hub.Example:8443/")
    assert hub_embed.hub_origin() == "https://hub.example:8443"

    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "")
    assert hub_embed.hub_origin() is None
    assert hub_embed.frame_ancestors() == []


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.acedylan.us",
        "https://hub.example/path",
        "https://user:pw@hub.example",
        "hub.example",
        "http://hub.example",
        "javascript:alert(1)",
        "https://hub.example https://evil.example",
    ],
)
def test_anything_but_one_exact_origin_means_nobody_may_frame_us(monkeypatch, value):
    monkeypatch.setenv(hub_embed.HUB_URL_ENV, value)
    assert hub_embed.frame_ancestors() == []


def test_a_short_secret_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, "short")
    assert hub_embed.sso_configured() is False
    assert hub_embed.secret_is_too_short() is True
    ticket = _sign_like_the_hub("chat", secret="short")
    assert hub_embed.consume_ticket(ticket, "chat", audience=HALO) == (False, "disabled")


def test_session_ttl_is_clamped(monkeypatch):
    assert hub_embed.session_ttl_seconds() == 12 * 3600
    for raw, expected in (("60", 300), ("7200", 7200), ("999999999", 30 * 24 * 3600), ("soon", 12 * 3600)):
        monkeypatch.setenv(hub_embed.HUB_SESSION_TTL_ENV, raw)
        assert hub_embed.session_ttl_seconds() == expected


# ---- framing header ------------------------------------------------------


def test_every_response_names_the_hub_as_the_only_foreign_framer():
    headers = security_headers.set_security_headers()
    assert headers["Content-Security-Policy"] == f"frame-ancestors 'self' {HUB}"
    assert "*" not in headers["Content-Security-Policy"]


def test_framing_header_is_absent_when_the_feature_is_off(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "")
    assert "Content-Security-Policy" not in security_headers.set_security_headers()


def test_framing_directive_joins_an_operator_policy_and_replaces_x_frame_options(monkeypatch):
    monkeypatch.setenv("CONTENT_SECURITY_POLICY", "default-src 'self';")
    monkeypatch.setenv("XFRAME_OPTIONS", "DENY")
    headers = security_headers.set_security_headers()
    assert headers["Content-Security-Policy"] == f"default-src 'self'; frame-ancestors 'self' {HUB}"
    # DENY would veto the Hub and cannot express an allow-list.
    assert "X-Frame-Options" not in headers


def test_an_operator_who_set_frame_ancestors_keeps_it(monkeypatch):
    monkeypatch.setenv("CONTENT_SECURITY_POLICY", "frame-ancestors 'none'")
    monkeypatch.setenv("XFRAME_OPTIONS", "DENY")
    headers = security_headers.set_security_headers()
    assert headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert headers["X-Frame-Options"] == "DENY"


# ---- tickets -------------------------------------------------------------


def test_a_ticket_signed_by_the_hub_is_accepted_exactly_once(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    ticket = _sign_like_the_hub("chat")
    assert hub_embed.consume_ticket(ticket, "chat", audience=HALO) == (True, "ok")
    assert hub_embed.consume_ticket(ticket, "chat", audience=HALO) == (False, "replayed")


def test_our_own_signer_matches_the_documented_format(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    ticket = hub_embed.sign_ticket("chat", HUB, HALO, nonce="n" * 24, now=1_000_000)
    message = f"v2.chat.1000060.{'n' * 24}.{_b64(HUB)}.{_b64(HALO)}"
    key = hashlib.sha256(("hub-chat-admin|" + SECRET).encode()).digest()
    assert ticket == message + "." + hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


@pytest.mark.parametrize(
    "ticket_kwargs, consume_kwargs, reason",
    [
        ({"secret": "another-secret-" + "f" * 32}, {}, "signature"),
        # The retired HaloWebUI -> Hub direction derived its key with another label.
        ({"label": "hub-embed-admin|"}, {}, "signature"),
        ({"purpose": "probe"}, {}, "purpose"),
        ({"now": time.time() - 3600}, {}, "expired"),
        ({"ttl": 3600}, {}, "ttl"),
        ({"issuer": "https://evil.example"}, {}, "issuer"),
        ({"audience": "https://other.example"}, {}, "audience"),
        ({}, {"audience": "https://evil.example"}, "audience"),
        ({}, {"audience": None}, "origin_missing"),
    ],
)
def test_tickets_that_must_be_refused(monkeypatch, ticket_kwargs, consume_kwargs, reason):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    kwargs = {"purpose": "chat", **ticket_kwargs}
    ticket = _sign_like_the_hub(kwargs.pop("purpose"), **kwargs)
    assert hub_embed.consume_ticket(ticket, "chat", **{"audience": HALO, **consume_kwargs}) == (False, reason)


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: "",
        lambda t: t.replace("v2.", "v1.", 1),
        lambda t: t + ".extra",
        lambda t: ".".join(t.split(".")[:5]),
        lambda t: t[:-1] + ("0" if t[-1] != "0" else "1"),
        lambda t: t.replace(_b64(HUB), _b64("https://evil.example")),
        lambda t: "A" * 2000,
    ],
)
def test_tampered_tickets_are_refused_and_never_burn_a_nonce(monkeypatch, mangle):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    ticket = _sign_like_the_hub("chat")
    ok, reason = hub_embed.consume_ticket(mangle(ticket), "chat", audience=HALO)
    assert ok is False and reason in {"missing", "malformed", "signature"}
    # The untouched ticket still works: a forgery cannot use up a real nonce.
    assert hub_embed.consume_ticket(ticket, "chat", audience=HALO) == (True, "ok")


def test_a_refused_audience_does_not_burn_the_nonce_either(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    ticket = _sign_like_the_hub("chat")
    assert hub_embed.consume_ticket(ticket, "chat", audience="https://evil.example")[1] == "audience"
    assert hub_embed.consume_ticket(ticket, "chat", audience=HALO) == (True, "ok")


def test_a_full_nonce_table_refuses_instead_of_forgetting(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    monkeypatch.setattr(hub_embed, "_MAX_NONCES", 2)
    first = _sign_like_the_hub("chat")
    assert hub_embed.consume_ticket(first, "chat", audience=HALO)[0]
    assert hub_embed.consume_ticket(_sign_like_the_hub("chat"), "chat", audience=HALO)[0]
    assert hub_embed.consume_ticket(_sign_like_the_hub("chat"), "chat", audience=HALO) == (False, "busy")
    assert hub_embed.consume_ticket(first, "chat", audience=HALO) == (False, "replayed")


# ---- throttle ------------------------------------------------------------


def test_guessing_is_throttled_but_honest_mistakes_are_not():
    for _ in range(hub_embed.FAILURE_LIMIT_PER_CLIENT):
        hub_embed.record_failure("203.0.113.9", "expired")
        hub_embed.record_failure("203.0.113.9", "replayed")
    assert hub_embed.retry_after("203.0.113.9") == 0

    for _ in range(hub_embed.FAILURE_LIMIT_PER_CLIENT):
        hub_embed.record_failure("203.0.113.9", "signature")
    assert hub_embed.retry_after("203.0.113.9") > 0
    assert hub_embed.retry_after("198.51.100.7") == 0
    # ... and it wears off.
    later = time.time() + hub_embed.FAILURE_WINDOW_SECONDS + 1
    assert hub_embed.retry_after("203.0.113.9", now=later) == 0


def test_rotating_addresses_hits_the_global_backstop():
    for index in range(hub_embed.FAILURE_LIMIT_GLOBAL):
        hub_embed.record_failure(f"203.0.113.{index}", "malformed")
    assert hub_embed.retry_after("192.0.2.1") > 0


# ---- short session -------------------------------------------------------


def test_only_a_hub_opened_session_reports_an_expiry_to_keep():
    assert hub_embed.presented_session_expiry({"id": "u1", "hub_exp": 1_900_000_000}) == 1_900_000_000
    for payload in (None, {}, {"id": "u1"}, {"hub_exp": "1900000000"}, {"hub_exp": True}, {"hub_exp": -5}):
        assert hub_embed.presented_session_expiry(payload) is None


# ---- router --------------------------------------------------------------


def _client(monkeypatch, users=None, by_email=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from open_webui.routers import hub

    users = users if users is not None else [_user("admin")]
    fake_users = SimpleNamespace(
        get_first_user=lambda: users[0] if users else None,
        get_user_by_email=lambda email: (by_email or {}).get(email),
    )
    monkeypatch.setattr(hub, "Users", fake_users)
    monkeypatch.setattr(hub, "_permissions", lambda request, user: {"chat": {"controls": True}})
    app = FastAPI()
    app.include_router(hub.router, prefix="/api/v1/hub")
    return TestClient(app)


def _user(role, id="u-admin", email="owner@example.com"):
    return SimpleNamespace(id=id, email=email, name="Owner", role=role, profile_image_url="/user.png")


def _exchange(client, ticket, origin=HALO):
    headers = {"Origin": origin} if origin else {}
    return client.post("/api/v1/hub/session", json={"ticket": ticket}, headers=headers)


def test_endpoints_do_not_exist_until_a_secret_is_configured(monkeypatch):
    client = _client(monkeypatch)
    assert _exchange(client, "anything").status_code == 404
    assert client.post("/api/v1/hub/handshake", json={"ticket": "anything"}).status_code == 404


def test_a_hub_ticket_opens_a_short_admin_session(monkeypatch):
    from open_webui.utils.auth import decode_token

    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    monkeypatch.setenv(hub_embed.HUB_SESSION_TTL_ENV, "3600")
    response = _exchange(_client(monkeypatch), _sign_like_the_hub("chat"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["id"], body["role"], body["token_type"]) == ("u-admin", "admin", "Bearer")
    assert abs(body["expires_at"] - (time.time() + 3600)) < 5
    assert response.headers["cache-control"] == "no-store"
    assert "token=" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]

    claims = decode_token(body["token"])
    assert claims["id"] == "u-admin"
    # The marker that keeps GET /auths/ from renewing this into a full-length session.
    assert claims["hub_exp"] == body["expires_at"] == claims["exp"]
    assert SECRET not in response.text


def test_the_same_ticket_cannot_open_a_second_session(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    client, ticket = _client(monkeypatch), _sign_like_the_hub("chat")
    assert _exchange(client, ticket).status_code == 200
    replay = _exchange(client, ticket)
    assert replay.status_code == 401
    assert replay.json()["detail"] == {"error": "ticket_refused", "reason": "replayed"}
    assert "token" not in replay.json()


@pytest.mark.parametrize("origin, reason", [("https://evil.example", "audience"), (None, "origin_missing")])
def test_the_exchange_must_come_from_a_page_on_the_addressed_origin(monkeypatch, origin, reason):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    response = _exchange(_client(monkeypatch), _sign_like_the_hub("chat"), origin=origin)
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == reason


def test_a_probe_ticket_never_opens_a_session_and_a_chat_ticket_is_no_probe(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    client = _client(monkeypatch)
    assert _exchange(client, _sign_like_the_hub("probe")).json()["detail"]["reason"] == "purpose"
    wrong = client.post("/api/v1/hub/handshake", json={"ticket": _sign_like_the_hub("chat")})
    assert wrong.json()["detail"]["reason"] == "purpose"


def test_handshake_confirms_the_secret_and_hands_out_nothing(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    client = _client(monkeypatch)
    response = client.post("/api/v1/hub/handshake", json={"ticket": _sign_like_the_hub("probe")})
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "frame_ancestors": [HUB],
        "session_ttl": 12 * 3600,
        "session_user_ready": True,
    }
    assert "set-cookie" not in response.headers

    mismatch = client.post(
        "/api/v1/hub/handshake",
        json={"ticket": _sign_like_the_hub("probe", secret="not-the-same-secret-" + "0" * 32)},
    )
    assert mismatch.status_code == 401
    assert mismatch.json()["detail"]["reason"] == "signature"


def test_only_an_admin_is_signed_in_by_default(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    for users in ([], [_user("user")], [_user("pending")]):
        response = _exchange(_client(monkeypatch, users=users), _sign_like_the_hub("chat"))
        assert response.status_code == 403
        assert "token" not in response.text


def test_a_named_account_may_be_an_ordinary_user_but_never_a_pending_one(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    monkeypatch.setenv(hub_embed.HUB_USER_EMAIL_ENV, "Limited@Example.com")
    accounts = {"limited@example.com": _user("user", id="u-limited", email="limited@example.com")}
    response = _exchange(_client(monkeypatch, by_email=accounts), _sign_like_the_hub("chat"))
    assert response.status_code == 200 and response.json()["id"] == "u-limited"

    accounts = {"limited@example.com": _user("pending", id="u-limited")}
    assert _exchange(_client(monkeypatch, by_email=accounts), _sign_like_the_hub("chat")).status_code == 403
    # A typo in the address must not fall back to the primary admin.
    assert _exchange(_client(monkeypatch, by_email={}), _sign_like_the_hub("chat")).status_code == 403


def test_repeated_forgeries_get_a_429(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    client = _client(monkeypatch)
    forged = _sign_like_the_hub("chat", secret="guess-" + "x" * 40)
    for _ in range(hub_embed.FAILURE_LIMIT_PER_CLIENT):
        assert _exchange(client, forged).status_code == 401
    locked = _exchange(client, _sign_like_the_hub("chat"))
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
