import pathlib
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.haloclaw import router as haloclaw_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(haloclaw_router.router, prefix="/api/v1/haloclaw")
    return TestClient(app)


def test_runtime_reasoning_effort_is_available_without_admin_token(monkeypatch):
    monkeypatch.setattr(
        haloclaw_router.HALOCLAW_DEFAULT_REASONING_EFFORT, "value", "high"
    )

    response = _client().get("/api/v1/haloclaw/runtime/reasoning-effort")

    assert response.status_code == 200
    assert response.json() == {"reasoning_effort": "high"}


def test_runtime_reasoning_effort_never_returns_an_invalid_value(monkeypatch):
    monkeypatch.setattr(
        haloclaw_router.HALOCLAW_DEFAULT_REASONING_EFFORT,
        "value",
        "not-a-valid-effort",
    )

    response = _client().get("/api/v1/haloclaw/runtime/reasoning-effort")

    assert response.status_code == 200
    assert response.json() == {"reasoning_effort": "xhigh"}
