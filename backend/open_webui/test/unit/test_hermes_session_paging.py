"""GET /hermes/sessions reads hermes one page at a time.

The list used to ask hermes for a flat `limit=50` with no offset, so a surface
with 400 conversations showed 50 of them and the other 350 were unreachable.
These tests pin the cursor walk against a fake that reproduces the two habits
of hermes' own `_handle_list_sessions`: it back-fills pinned conversations the
window missed into *every* answer, and its `has_more` counts only unpinned rows.
"""

import asyncio
from types import SimpleNamespace

import pytest

import open_webui.utils.hermes_sessions as hs
from open_webui.utils.hermes_sessions import HermesSessionsError


def _row(index: int, *, source="telegram", messages=4, pinned=False, session_id=None):
    return {
        "id": session_id or f"20260101_0000{index:02d}_abcd",
        "source": source,
        "title": f"Session {index}",
        "preview": f"preview {index}",
        "message_count": messages,
        "started_at": 1000 + index,
        "last_active": 2000 + index,
        "model": "hermes",
        "pinned": pinned,
    }


class FakeHermes:
    """hermes' /api/sessions, including the parts that make paging awkward."""

    def __init__(self, rows, *, pinned=()):
        self.rows = rows
        self.pinned = list(pinned)
        self.calls = []

    async def get_json(self, url, headers, params=None):
        assert url.endswith("/api/sessions"), url
        params = params or {}
        limit = int(params["limit"])
        offset = int(params["offset"])
        self.calls.append((params.get("source"), limit, offset))
        rows = [
            row
            for row in self.rows
            if not params.get("source") or row["source"] == params["source"]
        ]
        window = rows[offset : offset + limit]
        # include_pinned=True: pins outside the window are appended to the tail.
        seen = {row["id"] for row in window}
        window = window + [row for row in self.pinned if row["id"] not in seen]
        return {
            "object": "list",
            "data": window,
            "limit": limit,
            "offset": offset,
            "has_more": sum(1 for row in window if not row.get("pinned")) >= limit,
        }


def _install(monkeypatch, fake, *, imported=()):
    monkeypatch.setattr(hs, "_get_json", fake.get_json)

    async def fake_resolve(request, user, model_id=None):
        return {"id": "hermes", "original_id": "hermes-agent"}

    monkeypatch.setattr(hs, "resolve_hermes_model", fake_resolve)
    monkeypatch.setattr(
        hs, "_connection", lambda request, user, model: ("http://hermes", {})
    )
    monkeypatch.setattr(
        hs.Chats,
        "get_existing_chat_ids_by_user_id",
        lambda ids, user_id: {i for i in ids if i in set(imported)},
    )


def _list(source="telegram", **kwargs):
    return asyncio.run(
        hs.list_sessions(
            SimpleNamespace(), SimpleNamespace(id="u1"), source=source, **kwargs
        )
    )


def test_the_first_page_asks_hermes_for_one_page_not_the_whole_surface(monkeypatch):
    fake = FakeHermes([_row(i) for i in range(400)])
    _install(monkeypatch, fake)

    page = _list(limit=20)

    assert fake.calls == [("telegram", 20, 0)]
    assert [s["id"] for s in page["sessions"]] == [_row(i)["id"] for i in range(20)]
    assert page["offset"] == 0
    assert page["next_offset"] == 20
    assert page["has_more"] is True


def test_the_cursor_walks_the_whole_surface_without_repeating_or_skipping(monkeypatch):
    fake = FakeHermes([_row(i) for i in range(45)])
    _install(monkeypatch, fake)

    ids, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 20, "the walk should terminate"
        page = _list(limit=20, offset=offset)
        ids.extend(s["id"] for s in page["sessions"])
        offset = page["next_offset"]
        if not page["has_more"]:
            break

    assert ids == [_row(i)["id"] for i in range(45)]
    assert len(ids) == len(set(ids))


def test_a_short_answer_ends_the_walk(monkeypatch):
    fake = FakeHermes([_row(i) for i in range(25)])
    _install(monkeypatch, fake)

    page = _list(limit=20, offset=20)

    assert [s["title"] for s in page["sessions"]] == [
        f"Session {i}" for i in range(20, 25)
    ]
    assert page["has_more"] is False


def test_an_exactly_full_last_window_ends_on_the_next_empty_page(monkeypatch):
    fake = FakeHermes([_row(i) for i in range(20)])
    _install(monkeypatch, fake)

    first = _list(limit=20)
    assert len(first["sessions"]) == 20
    assert first["has_more"] is True  # nothing yet proves the window ran out

    second = _list(limit=20, offset=first["next_offset"])
    assert second["sessions"] == []
    assert second["has_more"] is False


def test_empty_shells_are_dropped_and_the_page_is_filled_from_the_next_window(
    monkeypatch,
):
    # hermes rotates sessions on idle; every other row here is one of the empty
    # shells that leaves behind.
    rows = [_row(i, messages=0 if i % 2 else 3) for i in range(80)]
    fake = FakeHermes(rows)
    _install(monkeypatch, fake)

    page = _list(limit=20)

    assert len(page["sessions"]) == 20, "a full page, not a half-empty one"
    assert all(s["message_count"] for s in page["sessions"])
    assert fake.calls == [("telegram", 20, 0), ("telegram", 20, 20)]
    # The cursor counts hermes rows consumed, not rows shown, so the next page
    # resumes where the scan stopped.
    assert page["next_offset"] == 40
    assert [s["title"] for s in page["sessions"]] == [
        f"Session {i}" for i in range(0, 40, 2)
    ]


def test_a_run_of_empty_shells_stops_after_the_round_cap_instead_of_fanning_out(
    monkeypatch,
):
    fake = FakeHermes([_row(i, messages=0) for i in range(400)])
    _install(monkeypatch, fake)

    page = _list(limit=20)

    assert page["sessions"] == []
    assert len(fake.calls) == hs.LIST_MAX_UPSTREAM_ROUNDS
    # Bounded work, but the caller can carry on from where it stopped.
    assert page["next_offset"] == 20 * hs.LIST_MAX_UPSTREAM_ROUNDS
    assert page["has_more"] is True


def test_pinned_conversations_show_once_on_the_first_page_not_on_every_page(
    monkeypatch,
):
    pin = _row(999, pinned=True, session_id="pinned_session_1")
    fake = FakeHermes([_row(i) for i in range(60)], pinned=[pin])
    _install(monkeypatch, fake)

    first = _list(limit=20)
    assert "pinned_session_1" in [s["id"] for s in first["sessions"]]
    assert [s["id"] for s in first["sessions"]].count("pinned_session_1") == 1

    second = _list(limit=20, offset=first["next_offset"])
    assert "pinned_session_1" not in [s["id"] for s in second["sessions"]]
    assert len(second["sessions"]) == 20


def test_a_pin_repeated_across_the_fill_rounds_is_not_listed_twice(monkeypatch):
    pin = _row(999, pinned=True, session_id="pinned_session_1")
    # Empty shells force a second round, so the fake hands the pin over twice.
    rows = [_row(i, messages=0 if i % 2 else 3) for i in range(80)]
    fake = FakeHermes(rows, pinned=[pin])
    _install(monkeypatch, fake)

    page = _list(limit=20)

    ids = [s["id"] for s in page["sessions"]]
    assert len(fake.calls) > 1
    assert ids.count("pinned_session_1") == 1
    assert len(ids) == len(set(ids))


def test_hermes_under_reporting_has_more_does_not_truncate_the_list(monkeypatch):
    """hermes discounts pinned rows from has_more, so a full window can say False."""
    pinned_in_window = _row(0, pinned=True)
    rows = [pinned_in_window] + [_row(i) for i in range(1, 60)]
    fake = FakeHermes(rows)
    _install(monkeypatch, fake)

    page = _list(limit=20)

    assert page["has_more"] is True, "20 rows came back; the window was not short"
    assert len(page["sessions"]) == 20


def test_rows_with_an_unusable_id_are_skipped(monkeypatch):
    rows = [_row(0), {**_row(1), "id": "../../etc/passwd"}, {**_row(2), "id": None}]
    fake = FakeHermes(rows)
    _install(monkeypatch, fake)

    page = _list(limit=20)

    assert [s["title"] for s in page["sessions"]] == ["Session 0"]


def test_imported_is_resolved_for_the_whole_page_in_one_lookup(monkeypatch):
    rows = [_row(i) for i in range(5)]
    seen = []
    fake = FakeHermes(rows)
    _install(monkeypatch, fake, imported=[_row(2)["id"]])
    real = hs.Chats.get_existing_chat_ids_by_user_id

    def counting(ids, user_id):
        seen.append(list(ids))
        return real(ids, user_id)

    monkeypatch.setattr(hs.Chats, "get_existing_chat_ids_by_user_id", counting)

    page = _list(limit=20)

    assert len(seen) == 1 and len(seen[0]) == 5
    assert [s["imported"] for s in page["sessions"]] == [
        False,
        False,
        True,
        False,
        False,
    ]


def test_only_the_three_client_surfaces_are_listable(monkeypatch):
    fake = FakeHermes([_row(0, source="telegram"), _row(1, source="cron")])
    _install(monkeypatch, fake)

    assert hs.SOURCES == ("telegram", "qqbot", "cli")
    for source in hs.SOURCES:
        _list(source=source, limit=5)
    assert [call[0] for call in fake.calls] == list(hs.SOURCES)

    with pytest.raises(HermesSessionsError) as e:
        _list(source="cron")
    assert e.value.status_code == 400


def test_the_offset_is_refused_past_what_hermes_accepts(monkeypatch):
    fake = FakeHermes([_row(0)])
    _install(monkeypatch, fake)

    for bad in (-1, hs.LIST_OFFSET_MAX + 1):
        with pytest.raises(HermesSessionsError) as e:
            _list(limit=20, offset=bad)
        assert e.value.status_code == 400
    assert fake.calls == [], "a bad offset never reaches hermes"


def test_the_limit_is_clamped_to_what_hermes_will_serve(monkeypatch):
    fake = FakeHermes([_row(i) for i in range(500)])
    _install(monkeypatch, fake)

    _list(limit=10_000)
    _list(limit=0)

    assert fake.calls[0][1] == hs.LIST_LIMIT_MAX
    assert fake.calls[-1][1] == 1


def test_the_router_passes_the_cursor_through_and_answers_the_page(monkeypatch):
    from open_webui.routers import hermes as router_module

    captured = {}

    async def fake_list_sessions(request, user, *, source, limit, offset, model_id):
        captured.update(source=source, limit=limit, offset=offset, model_id=model_id)
        return {
            "sessions": [],
            "offset": offset,
            "next_offset": offset + limit,
            "has_more": True,
        }

    monkeypatch.setattr(router_module, "list_sessions", fake_list_sessions)

    body = asyncio.run(
        router_module.list_hermes_sessions(
            SimpleNamespace(),
            source="cli",
            limit=20,
            offset=40,
            model_id=None,
            user=SimpleNamespace(id="u1"),
        )
    )

    assert captured == {"source": "cli", "limit": 20, "offset": 40, "model_id": None}
    assert body == {"sessions": [], "offset": 40, "next_offset": 60, "has_more": True}


# --------------------------------------------------- the imported-id lookup


def test_get_existing_chat_ids_answers_from_the_real_table():
    """The list only needs "does this id exist for me?" — against a live DB."""
    import uuid

    from open_webui.models.chats import ChatForm, Chats as RealChats

    mine = f"hermes-paging-{uuid.uuid4().hex[:8]}"
    theirs = f"hermes-paging-{uuid.uuid4().hex[:8]}"
    a = RealChats.insert_new_chat(mine, ChatForm(chat={"title": "a"}))
    b = RealChats.insert_new_chat(mine, ChatForm(chat={"title": "b"}))
    other = RealChats.insert_new_chat(theirs, ChatForm(chat={"title": "c"}))

    found = RealChats.get_existing_chat_ids_by_user_id(
        [a.id, b.id, other.id, "never-imported"], mine
    )

    assert found == {a.id, b.id}
    assert RealChats.get_existing_chat_ids_by_user_id([], mine) == set()
    assert RealChats.get_existing_chat_ids_by_user_id([None, ""], mine) == set()
    # Same verdict as the per-id lookup it replaces, without reading the blobs.
    assert (RealChats.get_chat_by_id_and_user_id(other.id, mine) is not None) is (
        other.id in found
    )
