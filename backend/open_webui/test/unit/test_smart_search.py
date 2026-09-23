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
                    "content": "Answer text is not a search result",
                    "sources": [
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
        "search",
        "release notes; $(echo unsafe)",
    ]
    assert kwargs["timeout"] == 35
    assert kwargs["check"] is False


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
