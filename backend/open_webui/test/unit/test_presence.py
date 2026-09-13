"""Presence: when a finished reply goes to the notification webhook. A tab is a
registered socket or the requesting session still connected; a push waits a
grace window for a reconnecting tab and never raises."""

import asyncio
from unittest.mock import MagicMock

from open_webui.utils import presence


class _Manager:
    def __init__(self, connected=()):
        self.connected = set(connected)

    def is_connected(self, sid, namespace):
        assert namespace == "/"
        return sid in self.connected


def _presence(monkeypatch, *, registered=(), connected=()):
    monkeypatch.setattr(
        presence, "get_active_status_by_user_id", lambda uid: uid in registered
    )
    monkeypatch.setattr(presence, "sio", MagicMock(manager=_Manager(connected)))


def test_registered_socket_or_requesting_session_counts_as_a_tab(monkeypatch):
    _presence(monkeypatch, registered={"u1"}, connected={"sid-unregistered"})
    assert presence.has_live_tab("u1")
    # A tab that reconnected with a stale handshake token: streaming, unregistered.
    assert presence.has_live_tab("u2", "sid-unregistered")
    assert not presence.has_live_tab("u2", "sid-gone")
    assert not presence.has_live_tab("u2")
    assert not presence.has_live_tab(None, None)


def test_manager_errors_read_as_no_tab(monkeypatch):
    broken = MagicMock()
    broken.manager.is_connected.side_effect = RuntimeError("boom")
    monkeypatch.setattr(presence, "get_active_status_by_user_id", lambda uid: False)
    monkeypatch.setattr(presence, "sio", broken)
    assert not presence.has_live_tab("u1", "sid")


def test_wait_returns_at_once_for_a_live_tab_and_gives_up_after_the_grace(monkeypatch):
    _presence(monkeypatch, registered={"u1"})
    assert asyncio.run(
        presence.wait_for_live_tab("u1", grace_seconds=5, poll_seconds=0.01)
    )

    async def timed():
        loop = asyncio.get_running_loop()
        started = loop.time()
        ok = await presence.wait_for_live_tab(
            "u2", "sid", grace_seconds=0.05, poll_seconds=0.01
        )
        return ok, loop.time() - started

    ok, elapsed = asyncio.run(timed())
    assert ok is False
    assert elapsed < 1.0
    assert asyncio.run(presence.wait_for_live_tab("u2", grace_seconds=0)) is False


def test_wait_sees_a_tab_that_reconnects_inside_the_grace(monkeypatch):
    registered = set()
    monkeypatch.setattr(
        presence, "get_active_status_by_user_id", lambda uid: uid in registered
    )
    monkeypatch.setattr(presence, "sio", MagicMock(manager=_Manager()))

    async def scenario():
        async def come_back():
            await asyncio.sleep(0.03)
            registered.add("u1")

        asyncio.create_task(come_back())
        return await presence.wait_for_live_tab(
            "u1", grace_seconds=2, poll_seconds=0.01
        )

    assert asyncio.run(scenario()) is True


TELEGRAM = "https://api.telegram.org/botX/sendMessage?chat_id=1"


def _schedule(monkeypatch, *, url=TELEGRAM, grace=0.05):
    posts = []
    monkeypatch.setattr(presence.Users, "get_user_webhook_url_by_id", lambda uid: url)
    monkeypatch.setattr(presence, "post_webhook", lambda *a: posts.append(a) or True)

    async def run():
        task = presence.schedule_away_webhook(
            user_id="u1",
            session_id="sid",
            name="HaloWebUI",
            message="m",
            event_data={"action": "chat"},
            grace_seconds=grace,
            log_tag="test",
        )
        if task is not None:
            await task
        return task

    return run, posts


def test_away_user_gets_the_webhook_after_the_grace(monkeypatch):
    _presence(monkeypatch)
    run, posts = _schedule(monkeypatch)
    assert asyncio.run(run()) is not None
    assert posts == [("HaloWebUI", TELEGRAM, "m", {"action": "chat"})]


def test_connected_tab_suppresses_the_webhook(monkeypatch):
    _presence(monkeypatch, connected={"sid"})
    run, posts = _schedule(monkeypatch)
    asyncio.run(run())
    assert posts == []


def test_no_webhook_url_schedules_nothing(monkeypatch):
    _presence(monkeypatch)
    run, posts = _schedule(monkeypatch, url=None)
    assert asyncio.run(run()) is None
    assert posts == []


def test_webhook_errors_never_escape(monkeypatch):
    _presence(monkeypatch)
    monkeypatch.setattr(
        presence.Users,
        "get_user_webhook_url_by_id",
        lambda uid: "https://hooks.example/x",
    )

    def boom(*a):
        raise RuntimeError("down")

    monkeypatch.setattr(presence, "post_webhook", boom)

    async def run():
        await presence.schedule_away_webhook(
            user_id="u1",
            session_id=None,
            name="n",
            message="m",
            event_data={},
            grace_seconds=0,
        )

    asyncio.run(run())

    def lookup_boom(uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(presence.Users, "get_user_webhook_url_by_id", lookup_boom)

    async def run_lookup():
        return presence.schedule_away_webhook(
            user_id="u1", session_id=None, name="n", message="m", event_data={}
        )

    assert asyncio.run(run_lookup()) is None
