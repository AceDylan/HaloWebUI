"""Command approvals for hermes runs: the choices offered, how the browser's
answer maps to what hermes accepts, which tabs get asked, and how a run waiting
on an approval shows up in the sidebar listing."""

import asyncio

import aiohttp
import pytest

from open_webui.utils import hermes_agent
from open_webui.utils.hermes_agent import (
    APPROVAL_CHOICES,
    _approval_choices,
    _approval_target_sids,
    _describe_run_error,
    _normalize_approval_choice,
    list_active_runs,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    hermes_agent._ACTIVE_RUNS.clear()
    yield
    hermes_agent._ACTIVE_RUNS.clear()


def test_approval_choices_follow_what_hermes_offers_in_dialog_order():
    assert _approval_choices({"choices": ["deny", "always", "session", "once"]}) == list(
        APPROVAL_CHOICES
    )
    assert _approval_choices({"choices": ["once", "session", "deny"]}) == [
        "once",
        "session",
        "deny",
    ]
    # Smart-denied / session-less requests only allow once or deny.
    assert _approval_choices({"choices": ["once", "deny"]}) == ["once", "deny"]


def test_approval_choices_always_include_once_and_deny_and_drop_unknowns():
    assert _approval_choices({}) == ["once", "deny"]
    assert _approval_choices({"choices": None}) == ["once", "deny"]
    assert _approval_choices({"choices": ["ALWAYS", "bogus"]}) == ["once", "always", "deny"]
    assert _approval_choices("not a dict") == ["once", "deny"]


def test_normalize_choice_accepts_offered_strings_and_legacy_booleans_only():
    choices = ["once", "session", "deny"]
    assert _normalize_approval_choice("session", choices) == "session"
    assert _normalize_approval_choice(" Once ", choices) == "once"
    assert _normalize_approval_choice({"choice": "deny"}, choices) == "deny"
    assert _normalize_approval_choice(True, choices) == "once"
    assert _normalize_approval_choice(False, choices) == "deny"
    # Never widen a grant on input hermes did not offer or we cannot read.
    assert _normalize_approval_choice("always", choices) == "deny"
    assert _normalize_approval_choice(None, choices) == "deny"
    assert _normalize_approval_choice(42, choices) == "deny"
    assert _normalize_approval_choice({"choice": None}, choices) == "deny"


def test_target_sids_prefer_the_originating_tab_then_the_users_live_tabs_newest_first():
    session_pool = {"sid-old": {}, "sid-new": {}, "sid-origin": {}}
    user_pool = {"user-1": ["sid-old", "sid-origin", "sid-new"]}

    assert _approval_target_sids(
        "user-1", "sid-origin", session_pool=session_pool, user_pool=user_pool
    ) == ["sid-origin", "sid-new", "sid-old"]


def test_target_sids_skip_a_reloaded_origin_tab_and_other_users():
    session_pool = {"sid-a": {}}
    user_pool = {"user-1": ["sid-gone", "sid-a"], "user-2": ["sid-b"]}

    assert _approval_target_sids(
        "user-1", "sid-gone", session_pool=session_pool, user_pool=user_pool
    ) == ["sid-a"]
    assert _approval_target_sids("user-3", None, session_pool=session_pool, user_pool=user_pool) == []


def test_list_active_runs_reports_a_pending_approval(monkeypatch):
    monkeypatch.setattr(hermes_agent.Chats, "get_chat_title_by_id", lambda chat_id: "T")
    hermes_agent._register_run(
        "chat-1",
        {
            "user_id": "user-1",
            "message_id": "msg-1",
            "run_id": "run-1",
            "started_at": 100.0,
            "steers": 0,
            "approval": {
                "request_id": "req-1",
                "command": "rm -rf build",
                "description": "clean",
                "since": 120.0,
            },
        },
    )
    hermes_agent._register_run(
        "chat-2",
        {
            "user_id": "user-1",
            "message_id": "msg-2",
            "run_id": "run-2",
            "started_at": 90.0,
            "steers": 1,
        },
    )

    runs = list_active_runs("user-1")

    assert [run["chat_id"] for run in runs] == ["chat-2", "chat-1"]
    assert runs[1]["awaiting_approval"] is True
    assert runs[1]["approval"] == {
        "request_id": "req-1",
        "command": "rm -rf build",
        "description": "clean",
        "since": 120.0,
    }
    assert runs[0]["awaiting_approval"] is False
    assert runs[0]["approval"] is None


def test_describe_run_error_names_the_gateway_for_connection_failures():
    connect_error = aiohttp.ClientConnectorError(
        aiohttp.client_reqrep.ConnectionKey("host.docker.internal", 8642, False, None, None, None, None),
        OSError(111, "Connection refused"),
    )
    text = _describe_run_error(connect_error, "http://host.docker.internal:8642/v1")
    assert text.startswith("无法连接 Hermes 网关 (http://host.docker.internal:8642/v1)")

    assert _describe_run_error(asyncio.TimeoutError(), "http://h/v1").startswith(
        "等待 Hermes 网关响应超时"
    )
    assert _describe_run_error(ValueError("boom"), "http://h/v1") == "Hermes agent error: boom"
