import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / "integrations"
    / "hermes-plugin"
    / "halowebui-reasoning-sync"
    / "__init__.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "halowebui_reasoning_sync_plugin", _PLUGIN_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
plugin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(plugin)


class _Response:
    status = 200

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, _limit):
        return self._body


def test_codex_responses_replaces_nested_effort_without_changing_messages(monkeypatch):
    monkeypatch.setattr(
        plugin,
        "urlopen",
        lambda url, timeout: _Response({"reasoning_effort": "xhigh"}),
    )
    messages = [{"role": "user", "content": "Keep this exact text"}]
    request = {
        "input": messages,
        "reasoning": {"effort": "low", "summary": "auto"},
    }

    result = plugin.sync_reasoning_effort(request=request, api_mode="codex_responses")

    assert result["request"]["reasoning"] == {
        "effort": "xhigh",
        "summary": "auto",
    }
    assert result["request"]["input"] is messages
    assert request["reasoning"]["effort"] == "low"
    assert messages == [{"role": "user", "content": "Keep this exact text"}]


def test_chat_completions_replaces_top_level_reasoning_effort(monkeypatch):
    monkeypatch.setattr(
        plugin,
        "urlopen",
        lambda url, timeout: _Response({"reasoning_effort": "medium"}),
    )
    messages = [{"role": "system", "content": "Keep this too"}]
    request = {"messages": messages, "reasoning_effort": "high"}

    result = plugin.sync_reasoning_effort(request=request, api_mode="chat_completions")

    assert result["request"]["reasoning_effort"] == "medium"
    assert result["request"]["messages"] is messages
    assert request["reasoning_effort"] == "high"


@pytest.mark.parametrize("api_mode", ["anthropic_messages", "bedrock_converse"])
def test_unsupported_api_modes_do_not_mutate_or_fetch(monkeypatch, api_mode):
    endpoint_calls = []

    def unexpected_urlopen(url, timeout):
        endpoint_calls.append((url, timeout))
        return _Response({"reasoning_effort": "max"})

    monkeypatch.setattr(plugin, "urlopen", unexpected_urlopen)
    request = {
        "messages": [{"role": "user", "content": "Keep provider payload exact"}],
        "reasoning_effort": "provider-owned",
    }
    original_request = deepcopy(request)

    result = plugin.sync_reasoning_effort(request=request, api_mode=api_mode)

    assert result is None
    assert request == original_request
    assert endpoint_calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        "https://relay.example:23001/v1beta",
        "https://relay.example:23001/v1beta/models",
        "https://generativelanguage.googleapis.com/v1beta",
    ],
)
def test_native_gemini_endpoints_are_left_to_the_run_guard(monkeypatch, base_url):
    # llm_request results replace each other, so a request returned here could
    # undo halowebui-run-guard's rewrite; the native client ignores the field.
    endpoint_calls = []
    monkeypatch.setattr(
        plugin,
        "urlopen",
        lambda url, timeout: (
            endpoint_calls.append(url) or _Response({"reasoning_effort": "max"})
        ),
    )

    result = plugin.sync_reasoning_effort(
        request={"messages": []}, api_mode="chat_completions", base_url=base_url
    )

    assert result is None
    assert endpoint_calls == []


def test_openai_compatible_gemini_path_is_still_synced(monkeypatch):
    monkeypatch.setattr(
        plugin, "urlopen", lambda url, timeout: _Response({"reasoning_effort": "low"})
    )

    result = plugin.sync_reasoning_effort(
        request={"messages": []},
        api_mode="chat_completions",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    assert result["request"]["reasoning_effort"] == "low"


def test_every_llm_request_fetches_current_value(monkeypatch):
    responses = iter(
        [
            _Response({"reasoning_effort": "low"}),
            _Response({"reasoning_effort": "max"}),
        ]
    )
    calls = []

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return next(responses)

    monkeypatch.setattr(plugin, "urlopen", fake_urlopen)

    first = plugin.sync_reasoning_effort(request={}, api_mode="chat_completions")
    second = plugin.sync_reasoning_effort(request={}, api_mode="chat_completions")

    assert first["request"]["reasoning_effort"] == "low"
    assert second["request"]["reasoning_effort"] == "max"
    assert calls == [
        (plugin.DEFAULT_SYNC_URL, plugin.REQUEST_TIMEOUT_SECONDS),
        (plugin.DEFAULT_SYNC_URL, plugin.REQUEST_TIMEOUT_SECONDS),
    ]


def test_invalid_value_and_connection_failure_fail_open(monkeypatch):
    monkeypatch.setattr(
        plugin,
        "urlopen",
        lambda url, timeout: _Response({"reasoning_effort": "ultra"}),
    )
    assert plugin.sync_reasoning_effort(request={}, api_mode="chat_completions") is None

    def unavailable(url, timeout):
        raise OSError("endpoint unavailable")

    monkeypatch.setattr(plugin, "urlopen", unavailable)
    assert plugin.sync_reasoning_effort(request={}, api_mode="chat_completions") is None


def test_registers_llm_request_middleware():
    registrations = []
    context = SimpleNamespace(
        register_middleware=lambda kind, callback: registrations.append(
            (kind, callback)
        )
    )

    plugin.register(context)

    assert registrations == [("llm_request", plugin.sync_reasoning_effort)]
