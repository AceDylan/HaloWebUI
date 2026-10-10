"""Provider completion is observable even without a model tool dispatch."""
import json

from agent.image_gen_provider import error_response, success_response
from hermes_cli import plugins


def test_direct_success_reaches_a_discovered_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("plugins:\n  enabled: [image-observer]\n")
    folder = tmp_path / "plugins" / "image-observer"
    folder.mkdir(parents=True)
    (folder / "plugin.yaml").write_text("name: image-observer\nversion: '1.0.0'\nprovides_hooks: [image_generated]\n")
    (folder / "__init__.py").write_text('''
import json
from pathlib import Path
from hermes_constants import get_hermes_home
def observe(result):
    Path(get_hermes_home(), 'received.json').write_text(json.dumps(result))
    result['success'] = False
def register(ctx):
    ctx.register_hook('image_generated', observe)
''')
    manager = plugins.PluginManager()
    manager.discover_and_load()
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    result = success_response(image="/tmp/image.png", model="gpt-image-2", prompt="a tree",
                              aspect_ratio="square", provider="openai", extra={"actual_size": "1024x1024"})
    receipt = json.loads((tmp_path / "received.json").read_text())
    assert receipt == result and result["success"] is True
    error_response(error="failed")
    assert json.loads((tmp_path / "received.json").read_text()) == receipt


def test_observer_failure_cannot_fail_generation(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("observer offline")

    monkeypatch.setattr(plugins, "invoke_hook", fail)
    result = success_response(image="/tmp/kept.png", model="gpt-image-2", prompt="a tree",
                              aspect_ratio="square", provider="openai")
    assert result["success"] and result["image"] == "/tmp/kept.png"
