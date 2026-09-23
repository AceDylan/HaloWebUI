import json
import subprocess
from types import SimpleNamespace

import pytest
from open_webui.retrieval.web import smart_search


def test_smart_search_maps_sources_and_filters_domains(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "results": [
                        {
                            "url": "https://docs.example.com/one",
                            "title": "One",
                            "description": "First",
                        },
                        {"url": "https://docs.example.com/one", "title": "Duplicate"},
                        {"url": "https://other.example.org/two", "title": "Two"},
                        {"url": "file:///etc/passwd", "title": "Invalid"},
                        {"url": "https://user:pass@docs.example.com/private"},
                    ],
                }
            ),
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    monkeypatch.setenv("SMART_SEARCH_CLI", "/opt/smart-search/bin/smart-search")

    results = smart_search.search_smart_search(
        "release notes; $(echo unsafe)", 2, ["example.com"]
    )

    assert [result.model_dump() for result in results] == [
        {
            "link": "https://docs.example.com/one",
            "title": "One",
            "snippet": "First",
            "favicon": None,
        }
    ]
    argv, kwargs = calls[0]
    assert argv[:3] == [
        "/opt/smart-search/bin/smart-search",
        "zhipu-search",
        "release notes; $(echo unsafe)",
    ]
    assert argv[3:] == ["--count", "2", "--format", "json"]
    assert kwargs["timeout"] == 35
    assert kwargs["check"] is False


def test_smart_search_falls_back_to_exa_when_zhipu_fails(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "zhipu-search":
            return subprocess.CompletedProcess(argv, 4, stdout="private diagnostic")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "results": [
                        {"url": "https://docs.example.com/one", "title": "One"}
                    ],
                }
            ),
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    results = smart_search.search_smart_search("query", 3)

    assert [result.link for result in results] == ["https://docs.example.com/one"]
    assert [argv[1] for argv in calls] == ["zhipu-search", "exa-search"]
    assert calls[1][3:] == ["--num-results", "3", "--format", "json"]


def test_smart_search_falls_back_when_first_provider_has_no_urls(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        results = (
            []
            if argv[1] == "zhipu-search"
            else [{"url": "https://example.org/result", "title": "Result"}]
        )
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"ok": True, "results": results})
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    assert [result.link for result in smart_search.search_smart_search("query", 5)] == [
        "https://example.org/result"
    ]
    assert calls == ["zhipu-search", "exa-search"]


def test_smart_search_uses_model_search_when_source_providers_fail(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if argv[1] != "search":
            return subprocess.CompletedProcess(argv, 3, stdout="")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "sources": [
                        {"url": "https://example.org/result", "title": "Result"}
                    ],
                }
            ),
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    assert [result.link for result in smart_search.search_smart_search("query", 5)] == [
        "https://example.org/result"
    ]
    assert calls == ["zhipu-search", "exa-search", "search"]


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, '{"ok":false,"error":"private diagnostic"}'),
        (0, "not json"),
        (0, '{"ok":false,"sources":[]}'),
    ],
)
def test_smart_search_errors_do_not_expose_cli_output(monkeypatch, returncode, stdout):
    monkeypatch.setattr(
        smart_search.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout=stdout, stderr="private diagnostic"
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        smart_search.search_smart_search("query", 5)

    assert "private diagnostic" not in str(exc_info.value)
    assert "zhipu-search" in str(exc_info.value)
    assert "exa-search" in str(exc_info.value)
    assert "search" in str(exc_info.value)


def test_smart_search_missing_cli_explains_backend_runtime_requirement(monkeypatch):
    monkeypatch.setenv("SMART_SEARCH_CLI", "/missing/smart-search")

    def missing_cli(_argv, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(smart_search.subprocess, "run", missing_cli)

    with pytest.raises(RuntimeError, match="backend environment") as exc_info:
        smart_search.search_smart_search("query", 5)

    assert "/missing/smart-search" in str(exc_info.value)
    assert "SMART_SEARCH_CLI" in str(exc_info.value)


def test_smart_search_is_available_through_shared_dispatch(monkeypatch):
    from open_webui.routers import retrieval

    expected = [object()]
    seen = []
    monkeypatch.setattr(
        retrieval,
        "search_smart_search",
        lambda *args: seen.append(args) or expected,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    WEB_SEARCH_RESULT_COUNT=4,
                    WEB_SEARCH_DOMAIN_FILTER_LIST=["example.com"],
                )
            )
        )
    )

    assert retrieval.search_web(request, "smart_search", "query") is expected
    assert seen == [("query", 4, ["example.com"])]
