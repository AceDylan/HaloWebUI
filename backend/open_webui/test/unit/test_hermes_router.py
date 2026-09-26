"""Import-time smoke test: the hermes router wires every endpoint without a
circular import between routers.hermes, utils.hermes_agent, utils.hermes_sessions
and utils.hermes_notify."""

from open_webui.routers import hermes as hermes_router


def test_hermes_router_exposes_every_endpoint():
    routes = {
        (method, route.path)
        for route in hermes_router.router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("POST", "/notifications") in routes
    assert ("POST", "/steer") in routes
    assert ("GET", "/runs") in routes
    assert ("GET", "/sessions") in routes
    assert ("POST", "/sessions/{session_id}/import") in routes
    assert ("POST", "/webhook-test") in routes
    assert ("POST", "/chats/{chat_id}/read") in routes


def test_notification_display_mode_shows_the_report_and_prompt_mode_starts_a_turn(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from open_webui.routers import hermes as hermes_router

    called = []

    async def show(request, **kwargs):
        called.append(("display", kwargs))
        return {"chat_id": kwargs["chat_id"], "user_message_id": "u", "assistant_message_id": "a"}

    async def turn(request, **kwargs):
        called.append(("turn", kwargs))
        return {"chat_id": kwargs["chat_id"], "user_message_id": "u", "assistant_message_id": "a"}

    monkeypatch.setattr(hermes_router, "notify_token_configured", lambda: True)
    monkeypatch.setattr(hermes_router, "verify_notify_token", lambda _auth: True)
    monkeypatch.setattr(hermes_router, "show_notification_report", show)
    monkeypatch.setattr(hermes_router, "start_follow_up_turn", turn)
    request = SimpleNamespace(headers={"Authorization": "Bearer t"})

    form = hermes_router.HermesNotificationForm(
        chat_id="c1", prompt="读取 result.md", mode="display", content="✅ 报告", notice="[后台任务完成通知] x"
    )
    result = asyncio.run(hermes_router.receive_hermes_notification(request, form))
    assert result["mode"] == "display"
    assert called[-1] == ("display", {"chat_id": "c1", "content": "✅ 报告", "notice": "[后台任务完成通知] x", "source": ""})

    form = hermes_router.HermesNotificationForm(chat_id="c1", prompt="读取 result.md")
    result = asyncio.run(hermes_router.receive_hermes_notification(request, form))
    assert result["mode"] == "turn"
    assert called[-1][0] == "turn"


def test_progress_reports_show_as_background_runs_until_the_report(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from open_webui.routers import hermes as hermes_router
    from open_webui.utils import hermes_runner_progress as progress

    monkeypatch.setattr(progress, "_PROGRESS", {})
    monkeypatch.setattr(
        progress.Chats, "get_chat_by_id", lambda chat_id: SimpleNamespace(user_id="u1")
    )
    monkeypatch.setattr(progress.Chats, "get_chat_title_by_id", lambda chat_id: "标题")
    monkeypatch.setattr(hermes_router, "notify_token_configured", lambda: True)
    monkeypatch.setattr(hermes_router, "verify_notify_token", lambda _auth: True)

    async def show(request, **kwargs):
        return {"chat_id": kwargs["chat_id"], "user_message_id": "u", "assistant_message_id": "a"}

    monkeypatch.setattr(hermes_router, "show_notification_report", show)
    request = SimpleNamespace(headers={"Authorization": "Bearer t"})

    form = hermes_router.HermesNotificationForm(
        chat_id="c1", run_id="r1", mode="progress", agent="reclaude",
        started_at=1000.0, step=198, last_activity="Bash: npm   test",
    )
    result = asyncio.run(hermes_router.receive_hermes_notification(request, form))
    assert result == {"status": True, "chat_id": "c1", "run_id": "r1", "mode": "progress", "active": True}
    runs = progress.list_runner_progress("u1")
    assert runs[0]["agent"] == "reclaude" and runs[0]["step"] == 198
    assert runs[0]["last_activity"] == "Bash: npm test"
    assert progress.list_runner_progress("someone-else") == []

    # The final report clears it.
    form = hermes_router.HermesNotificationForm(
        chat_id="c1", run_id="r1", prompt="x", mode="display", content="✅"
    )
    asyncio.run(hermes_router.receive_hermes_notification(request, form))
    assert progress.list_runner_progress("u1") == []


def test_progress_entries_expire_and_end_on_a_terminal_status(monkeypatch):
    from types import SimpleNamespace

    from open_webui.utils import hermes_runner_progress as progress

    monkeypatch.setattr(progress, "_PROGRESS", {})
    monkeypatch.setattr(
        progress.Chats, "get_chat_by_id", lambda chat_id: SimpleNamespace(user_id="u1")
    )
    monkeypatch.setattr(progress.Chats, "get_chat_title_by_id", lambda chat_id: "标题")
    progress.record_runner_progress(chat_id="c1", run_id="r1", now=0)
    assert progress.list_runner_progress("u1", now=60)
    assert progress.list_runner_progress("u1", now=progress.PROGRESS_STALE_SECONDS + 1) == []
    progress.record_runner_progress(chat_id="c1", run_id="r2", now=0)
    progress.record_runner_progress(chat_id="c1", run_id="r2", status="failed", now=1)
    assert progress.list_runner_progress("u1", now=2) == []


def test_a_follow_up_turn_still_needs_a_prompt(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from open_webui.routers import hermes as hermes_router

    monkeypatch.setattr(hermes_router, "notify_token_configured", lambda: True)
    monkeypatch.setattr(hermes_router, "verify_notify_token", lambda _auth: True)
    form = hermes_router.HermesNotificationForm(chat_id="c1")
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            hermes_router.receive_hermes_notification(
                SimpleNamespace(headers={"Authorization": "Bearer t"}), form
            )
        )
    assert error.value.status_code == 422
