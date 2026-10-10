import pytest

from halowebui_teams import gallery, link


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(gallery, "root", lambda: tmp_path / "outbox")
    monkeypatch.setattr(link, "config", lambda: {"image_gallery": {"enabled": True, "default_owner": "alice"}})
    monkeypatch.setattr(link, "configured", lambda: True)
    monkeypatch.setattr(gallery, "context", lambda: {"owner": "alice", "platform": "cli"})
    return tmp_path


def test_provider_completion_survives_cache_deletion_and_failed_delivery(configured, monkeypatch):
    # Real success_response + plugin dispatch, no model request or mocked observer.
    from agent.image_gen_provider import success_response, error_response
    from hermes_cli.plugins import PluginManager
    import hermes_cli.plugins as plugins

    manager = PluginManager()
    manager._discovered = True
    manager._hooks.setdefault("image_generated", []).append(gallery.on_image_generated)
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    source = configured / "generated.png"
    source.write_bytes(b"image bytes")
    result = success_response(image=str(source), model="gpt-image-2", prompt="灯塔",
                              aspect_ratio="landscape", provider="openai")
    assert result["success"] is True
    assert gallery.is_queued(result)
    gallery.on_image_generated(result=result)  # duplicate callback
    error_response(error="failed", model="gpt-image-2")
    gallery.on_image_generated(result={**result, "model": "flux"})
    assert len(list(gallery.root().glob("*/record.json"))) == 1
    source.unlink()
    monkeypatch.setattr(link, "call", lambda *a, **k: (_ for _ in ()).throw(link.HaloError(503, "offline")))
    assert gallery.flush() == 0
    delivered = []
    monkeypatch.setattr(link, "call", lambda *a, **k: delivered.append(a) or {"stored": True})
    assert gallery.flush() == 1
    assert delivered[0][2] == "alice"
    assert delivered[0][3]["prompt"] == "灯塔"
    assert gallery.flush() == 0
    assert not list(gallery.root().glob("*/image"))
    assert gallery.is_queued(result)  # durable delivered receipt for legacy callback
    from halowebui_teams.illustrate import public
    assert public({"status": "ready", "gallery_queued": gallery.is_queued(result)})["gallery_queued"] is True


def test_context_scopes_and_disabled_capture(monkeypatch, tmp_path):
    from gateway.session_context import set_session_vars, clear_session_vars

    monkeypatch.setattr(link, "config", lambda: {"image_gallery": {"enabled": False, "default_owner": "alice"}})
    monkeypatch.setattr(link, "owner_for_telegram", lambda user: {"42": "bob"}.get(user))
    monkeypatch.setattr(gallery, "root", lambda: tmp_path / "outbox")
    tokens = set_session_vars(platform="telegram", user_id="42")
    try:
        assert gallery.context()["owner"] == "bob"
        with gallery.owned_by("charlie", "team-1"):
            assert gallery.context() == {"owner": "charlie", "team_id": "team-1"}
        assert gallery.context()["owner"] == "bob"
    finally:
        clear_session_vars(tokens)
    tokens = set_session_vars(platform="telegram", user_id="unlinked")
    try:
        assert gallery.context()["owner"] == ""
    finally:
        clear_session_vars(tokens)
    gallery.on_image_generated(result={"success": True, "model": "gpt-image-2", "image": str(tmp_path)})
    assert not gallery.root().exists()
