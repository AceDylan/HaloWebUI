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
