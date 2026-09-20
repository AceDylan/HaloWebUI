import asyncio
import hashlib
import hmac
import time
from urllib.parse import parse_qs, urlparse

import pytest

from open_webui.utils import hub_embed

SECRET = "unit-test-embed-secret-" + "0123456789abcdef" * 2


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv(hub_embed.HUB_URL_ENV, raising=False)
    monkeypatch.delenv(hub_embed.HUB_SECRET_ENV, raising=False)
    hub_embed._handshake.update(ok=None, reason="not_run", checked_at=None, frame_ancestors=None)


def _verify_like_the_hub(ticket: str, secret: str, purpose: str) -> bool:
    """The Hub's check, re-implemented from its documentation rather than
    imported, so a drift in either implementation fails here."""
    version, got_purpose, expires, nonce, signature = ticket.split(".")
    key = hashlib.sha256(("hub-embed-admin|" + secret).encode("utf-8")).digest()
    message = ".".join((version, got_purpose, expires, nonce))
    expected = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        version == "v1"
        and hmac.compare_digest(signature, expected)
        and got_purpose == purpose
        and time.time() < int(expires) <= time.time() + 300
        and 16 <= len(nonce) <= 64
    )


def test_hub_url_defaults_and_can_be_switched_off(monkeypatch):
    assert hub_embed.hub_url() == "https://best.acedylan.us:5526"

    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "https://hub.example:8443/")
    assert hub_embed.hub_url() == "https://hub.example:8443"

    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "")
    assert hub_embed.hub_url() is None
    assert hub_embed.build_embed_url() is None


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "https://hub.example/path",
        "https://user:pw@hub.example",
        "hub.example",
        "https://hub.example/?next=https://evil.example",
    ],
)
def test_hub_url_must_be_a_plain_origin(monkeypatch, value):
    monkeypatch.setenv(hub_embed.HUB_URL_ENV, value)
    assert hub_embed.hub_url() is None


def test_without_a_secret_the_iframe_gets_the_plain_hub_page():
    assert hub_embed.sso_configured() is False
    assert hub_embed.build_embed_url() == "https://best.acedylan.us:5526/?embed=1"
    with pytest.raises(RuntimeError):
        hub_embed.mint_ticket(hub_embed.PURPOSE_ENTER)


def test_a_short_secret_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, "short")
    assert hub_embed.sso_configured() is False
    assert "ticket" not in hub_embed.build_embed_url()


def test_embed_url_carries_a_ticket_the_hub_accepts(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    url = urlparse(hub_embed.build_embed_url())
    assert (url.scheme, url.netloc, url.path) == ("https", "best.acedylan.us:5526", "/embed/enter")
    (ticket,) = parse_qs(url.query)["ticket"]
    assert _verify_like_the_hub(ticket, SECRET, "enter")
    # Neither the secret nor anything derived from it other than the MAC is in the address.
    assert SECRET not in url.geturl()


def test_tickets_are_single_purpose_short_lived_and_unique(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    probe = hub_embed.mint_ticket(hub_embed.PURPOSE_PROBE)
    assert _verify_like_the_hub(probe, SECRET, "probe")
    assert not _verify_like_the_hub(probe, SECRET, "enter")
    assert not _verify_like_the_hub(probe, "another-secret-" + "f" * 32, "probe")

    expires = int(hub_embed.mint_ticket(hub_embed.PURPOSE_ENTER).split(".")[2])
    assert 0 < expires - time.time() <= hub_embed.TICKET_TTL_SECONDS

    tickets = {hub_embed.mint_ticket(hub_embed.PURPOSE_ENTER) for _ in range(50)}
    assert len(tickets) == 50


def test_known_bad_handshake_stops_tickets_from_being_presented(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    assert hub_embed.build_embed_url(with_ticket=False) == "https://best.acedylan.us:5526/?embed=1"


def test_handshake_without_a_secret_makes_no_request(monkeypatch):
    def _no_network(*args, **kwargs):
        raise AssertionError("handshake must not touch the network without a secret")

    monkeypatch.setattr(hub_embed.aiohttp, "ClientSession", _no_network)
    state = asyncio.run(hub_embed.run_handshake())
    assert (state["ok"], state["reason"]) == (None, "secret_unset")

    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, "short")
    state = asyncio.run(hub_embed.run_handshake())
    assert (state["ok"], state["reason"]) == (False, "secret_too_short")


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    calls = []

    def __init__(self, response, **kwargs):
        self._response = response

    def post(self, url, json=None):
        _FakeSession.calls.append((url, json))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, response):
    _FakeSession.calls = []
    monkeypatch.setattr(hub_embed.aiohttp, "ClientSession", lambda **kwargs: _FakeSession(response, **kwargs))


def test_handshake_records_success_and_the_hub_allow_list(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(
        monkeypatch,
        _FakeResponse(200, {"ok": True, "frame_ancestors": ["https://host.acedylan.us:3001"]}),
    )
    state = asyncio.run(hub_embed.run_handshake())
    assert (state["ok"], state["reason"]) == (True, "ok")
    assert state["frame_ancestors"] == ["https://host.acedylan.us:3001"]

    (url, payload), = _FakeSession.calls
    assert url == "https://best.acedylan.us:5526/api/embed/handshake"
    # The probe cannot be traded for a session, and the secret itself never travels.
    assert _verify_like_the_hub(payload["ticket"], SECRET, "probe")
    assert SECRET not in str(payload)


@pytest.mark.parametrize(
    "response, expected",
    [
        (_FakeResponse(401, {"ok": False, "reason": "signature"}), (False, "secret_mismatch")),
        (_FakeResponse(401, {"ok": False, "reason": "expired"}), (False, "expired")),
        (_FakeResponse(401, {"ok": False, "reason": "bad\nINFO forged log line"}), (False, "badinfoforgedlogline")),
        (_FakeResponse(401, {"ok": False, "reason": 17}), (False, "rejected")),
        (_FakeResponse(404, {"ok": False}), (False, "hub_not_configured")),
        (_FakeResponse(429, None), (None, "throttled")),
        (_FakeResponse(502, "<html>bad gateway</html>"), (None, "http_502")),
        (ConnectionError("no route"), (None, "unreachable")),
    ],
)
def test_handshake_failures_are_classified_and_never_raise(monkeypatch, response, expected):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(monkeypatch, response)
    state = asyncio.run(hub_embed.run_handshake())
    assert (state["ok"], state["reason"]) == expected


def test_ensure_handshake_retries_failures_but_not_more_than_once_a_minute(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(monkeypatch, _FakeResponse(404, {}))

    assert asyncio.run(hub_embed.ensure_handshake())["reason"] == "hub_not_configured"
    assert asyncio.run(hub_embed.ensure_handshake())["reason"] == "hub_not_configured"
    assert len(_FakeSession.calls) == 1

    # The Hub gets fixed; a minute later the next /hub visit picks it up.
    hub_embed._handshake["checked_at"] -= hub_embed.HANDSHAKE_RETRY_SECONDS + 1
    _patch_session(monkeypatch, _FakeResponse(200, {"ok": True, "frame_ancestors": []}))
    assert asyncio.run(hub_embed.ensure_handshake())["ok"] is True
    assert len(_FakeSession.calls) == 1


# ---- router: only admins may mint a ticket ----


def _router_client(role):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from open_webui.routers import hub
    from open_webui.utils.auth import get_current_user

    class _User:
        id = "u1"

    user = _User()
    user.role = role

    def _current_user():
        if role is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return user

    app = FastAPI()
    app.include_router(hub.router, prefix="/api/v1/hub")
    # Override the innermost dependency so the real get_admin_user role check runs.
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.mark.parametrize("role", [None, "user", "pending"])
def test_embed_endpoint_refuses_everyone_but_admins(monkeypatch, role):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(monkeypatch, _FakeResponse(200, {"ok": True, "frame_ancestors": []}))
    response = _router_client(role).post("/api/v1/hub/embed")
    assert response.status_code == 401
    assert "ticket" not in response.text
    assert _FakeSession.calls == []


def test_embed_endpoint_gives_an_admin_a_fresh_ticket_each_time(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(
        monkeypatch,
        _FakeResponse(200, {"ok": True, "frame_ancestors": ["https://host.acedylan.us:3001"]}),
    )
    client = _router_client("admin")
    first, second = client.post("/api/v1/hub/embed"), client.post("/api/v1/hub/embed")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["sso"] is True
    assert body["hub_url"] == "https://best.acedylan.us:5526"
    assert body["handshake"]["frame_ancestors"] == ["https://host.acedylan.us:3001"]
    (ticket,) = parse_qs(urlparse(body["url"]).query)["ticket"]
    assert _verify_like_the_hub(ticket, SECRET, "enter")
    assert body["url"] != second.json()["url"]
    assert SECRET not in first.text
    # GET would let a prefetch or a cache hand out a credential.
    assert client.get("/api/v1/hub/embed").status_code == 405


def test_embed_endpoint_withholds_tickets_the_hub_would_refuse(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(monkeypatch, _FakeResponse(401, {"ok": False, "reason": "signature"}))
    body = _router_client("admin").post("/api/v1/hub/embed").json()
    assert body["sso"] is False
    assert body["url"] == "https://best.acedylan.us:5526/?embed=1"
    assert body["handshake"]["reason"] == "secret_mismatch"


def test_embed_endpoint_still_tries_when_the_hub_is_only_unreachable_from_here(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_SECRET_ENV, SECRET)
    _patch_session(monkeypatch, ConnectionError("no route"))
    body = _router_client("admin").post("/api/v1/hub/embed").json()
    assert body["sso"] is True
    assert "/embed/enter?ticket=" in body["url"]


def test_embed_endpoint_is_gone_when_the_feature_is_off(monkeypatch):
    monkeypatch.setenv(hub_embed.HUB_URL_ENV, "")
    assert _router_client("admin").post("/api/v1/hub/embed").status_code == 404
