import json
import subprocess
from types import SimpleNamespace

import pytest
from open_webui.retrieval.web import smart_search


def evidence(url, *, title="Result", content="Fetched page content", verified=True):
    return {"url": url, "title": title, "content": content, "verified": verified}


def test_smart_search_uses_research_evidence_and_filters_domains(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "evidence_items": [
                        evidence("https://other.example.org/first"),
                        evidence(
                            "https://docs.example.com/one",
                            title="One",
                            content="First\n page content",
                        ),
                        evidence("https://docs.example.com/one", title="Duplicate"),
                        evidence("file:///etc/passwd"),
                        evidence("https://[invalid"),
                        evidence("https://:pass@docs.example.com/private"),
                        evidence("https://docs.example.com/unverified", verified=False),
                        evidence("https://docs.example.com/empty", content=""),
                    ],
                    "discovery_sources": [
                        {"url": "https://docs.example.com/candidate"}
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
            "snippet": "First page content",
            "favicon": None,
        }
    ]
    assert calls[0][0] == [
        "/opt/smart-search/bin/smart-search",
        "research",
        "release notes; $(echo unsafe)",
        "--budget",
        "quick",
        "--fallback",
        "auto",
        "--format",
        "json",
    ]
    assert calls[0][1]["timeout"] == 90
    assert calls[0][1]["check"] is False
    assert len(calls) == 1


def test_smart_search_falls_back_to_generic_search(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "research":
            return subprocess.CompletedProcess(argv, 3, stdout="private diagnostic")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "sources": [
                        {
                            "url": "https://docs.example.com/one",
                            "title": "One",
                            "description": "Source description",
                        }
                    ],
                }
            ),
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    results = smart_search.search_smart_search("query", 3)

    assert [result.link for result in results] == ["https://docs.example.com/one"]
    assert results[0].snippet == "Source description"
    assert [argv[1] for argv in calls] == ["research", "search"]
    assert calls[1][3:] == [
        "--validation",
        "balanced",
        "--timeout",
        "30",
        "--format",
        "json",
    ]


def test_smart_search_falls_back_when_research_has_no_http_evidence(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if argv[1] == "research":
            payload = {"ok": True, "evidence_items": [evidence("context7:/library")]}
        else:
            payload = {"ok": True, "sources": [{"url": "https://example.org/result"}]}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload))

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    assert [result.link for result in smart_search.search_smart_search("query", 5)] == [
        "https://example.org/result"
    ]
    assert calls == ["research", "search"]


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, '{"ok":false,"error":"private diagnostic"}'),
        (0, "not json"),
        (0, '{"ok":false,"evidence_items":[]}'),
        (0, '{"ok":true,"evidence_items":"private diagnostic"}'),
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
    assert "research" in str(exc_info.value)
    assert "search" in str(exc_info.value)


def test_smart_search_timeout_falls_back_and_sanitizes_error(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            argv, kwargs["timeout"], output="private diagnostic"
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    with pytest.raises(
        RuntimeError, match="research: timeout; search: timeout"
    ) as exc_info:
        smart_search.search_smart_search("query", 3)

    assert "private diagnostic" not in str(exc_info.value)


def test_smart_search_empty_success_returns_no_results(monkeypatch):
    def fake_run(argv, **kwargs):
        key = "evidence_items" if argv[1] == "research" else "sources"
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"ok": True, key: []})
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)

    assert smart_search.search_smart_search("query", 3) == []


def test_smart_search_missing_cli_explains_backend_runtime_requirement(monkeypatch):
    monkeypatch.setenv("SMART_SEARCH_CLI", "/missing/smart-search")

    def missing_cli(_argv, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(smart_search.subprocess, "run", missing_cli)

    with pytest.raises(RuntimeError, match="backend environment") as exc_info:
        smart_search.search_smart_search("query", 5)

    assert "/missing/smart-search" in str(exc_info.value)
    assert "SMART_SEARCH_CLI" in str(exc_info.value)


def test_smart_search_zero_count_skips_cli(monkeypatch):
    monkeypatch.setattr(
        smart_search.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("CLI should not run"),
    )

    assert smart_search.search_smart_search("query", 0) == []


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
