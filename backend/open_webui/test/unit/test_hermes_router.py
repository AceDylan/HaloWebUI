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
