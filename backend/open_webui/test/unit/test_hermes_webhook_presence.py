"""hermes completion/approval webhooks go through presence: they name the
requesting tab's session id so a reconnected (unregistered) tab still counts,
the approval keeps a short grace, and scheduling errors never break the run."""

from types import SimpleNamespace

from open_webui.utils import hermes_agent, presence


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                WEBUI_NAME="HaloWebUI",
                config=SimpleNamespace(WEBUI_URL="https://halo.example"),
            )
        )
    )


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hermes_agent, "schedule_away_webhook", lambda **kw: calls.append(kw) or "task"
    )
    return calls


def test_completion_webhook_names_the_requesting_tab_and_strips_the_transcript(
    monkeypatch,
):
    calls = _capture(monkeypatch)
    metadata = {"chat_id": "c1", "session_id": "sid-1"}
    content = '<details type="tool_calls" done="true">x</details>\n\n\nThe answer'

    hermes_agent._schedule_completion_webhook(
        _request(), SimpleNamespace(id="u1"), metadata, "Title", content
    )

    (kw,) = calls
    assert kw["user_id"] == "u1"
    assert kw["session_id"] == "sid-1"
    assert kw["name"] == "HaloWebUI"
    assert kw["message"] == "Title - https://halo.example/c/c1\n\nThe answer"
    assert kw["event_data"] == {
        "action": "chat",
        "message": "The answer",
        "title": "Title",
        "url": "https://halo.example/c/c1",
    }
    assert kw.get("grace_seconds") is None  # the default (long) grace


def test_approval_webhook_keeps_a_short_grace(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(hermes_agent.Chats, "get_chat_title_by_id", lambda cid: "Chat")

    hermes_agent._schedule_approval_webhook(
        _request(),
        SimpleNamespace(id="u1"),
        {"chat_id": "c1", "session_id": "sid-1"},
        {"command": "rm -rf /tmp/x", "description": "clean", "timeout": 240},
    )

    (kw,) = calls
    assert kw["session_id"] == "sid-1"
    assert kw["grace_seconds"] == presence.APPROVAL_WEBHOOK_GRACE_SECONDS <= 10
    assert "rm -rf /tmp/x" in kw["message"]
    assert kw["event_data"]["action"] == "approval"
    assert kw["event_data"]["url"] == "https://halo.example/c/c1"


def test_webhook_scheduling_errors_never_break_the_run(monkeypatch):
    def boom(**kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(hermes_agent, "schedule_away_webhook", boom)
    hermes_agent._schedule_completion_webhook(
        _request(), SimpleNamespace(id="u1"), {"chat_id": "c1"}, "T", "body"
    )
    hermes_agent._schedule_approval_webhook(
        _request(), SimpleNamespace(id="u1"), {"chat_id": "c1"}, {"command": "ls"}
    )
