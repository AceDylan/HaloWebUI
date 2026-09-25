import json
import subprocess
from types import SimpleNamespace

import pytest
from open_webui.retrieval.web import smart_search


def completed(argv, payload, code=0):
    return subprocess.CompletedProcess(
        argv, code, stdout=json.dumps(payload), stderr="private diagnostic"
    )


def doctor(*, web=(), docs=(), vertical=()):
    return {
        "ok": True,
        "capability_status": {
            "web_search": {"configured": list(web)},
            "docs_search": {"configured": list(docs)},
            "vertical_search": {"configured": list(vertical)},
        },
    }


def test_research_uses_verified_evidence_and_filters_domains(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        return completed(
            argv,
            {
                "ok": True,
                "evidence_items": [
                    {
                        "url": "https://other.example.org/first",
                        "verified": True,
                        "content": "Other",
                    },
                    {
                        "url": "https://docs.example.com/one",
                        "title": "One",
                        "content": "First\n page content",
                        "verified": True,
                    },
                    {
                        "url": "https://docs.example.com/one",
                        "content": "Duplicate",
                        "verified": True,
                    },
                    {"url": "file:///etc/passwd", "content": "Local", "verified": True},
                    {"url": "https://[invalid", "content": "Bad", "verified": True},
                    {
                        "url": "https://:pass@docs.example.com/private",
                        "content": "Secret",
                        "verified": True,
                    },
                    {
                        "url": "https://docs.example.com/unverified",
                        "content": "No",
                        "verified": False,
                    },
                    {
                        "url": "https://docs.example.com/empty",
                        "content": "",
                        "verified": True,
                    },
                ],
                "discovery_sources": [],
            },
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    monkeypatch.setenv("SMART_SEARCH_CLI", "/opt/smart-search/bin/smart-search")
    results = smart_search.search_smart_search(
        "release notes; $(echo unsafe)", 1, ["example.com"]
    )

    assert [result.model_dump() for result in results] == [
        {
            "link": "https://docs.example.com/one",
            "title": "One",
            "snippet": "First page content",
            "favicon": None,
            "content": "First\n page content",
            "provider": None,
        }
    ]
    assert calls[0][0] == ["/opt/smart-search/bin/smart-search", "research", "--help"]
    assert calls[1][0] == [
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
    assert calls[1][1]["timeout"] == 90
    assert calls[1][1]["check"] is False
    assert len(calls) == 2


def test_old_cli_routes_across_configured_source_providers(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        stage = argv[1]
        if stage == "research":
            return subprocess.CompletedProcess(
                argv, 2, stdout="", stderr="private diagnostic"
            )
        if stage == "doctor":
            return completed(
                argv,
                doctor(
                    web=("zhipu", "tavily", "firecrawl"),
                    docs=("exa",),
                    vertical=("anysearch",),
                ),
            )
        if stage == "zhipu-search":
            return completed(
                argv,
                {
                    "ok": False,
                    "error_type": "provider_error",
                    "error": "private diagnostic",
                },
                4,
            )
        if stage == "exa-search":
            return completed(
                argv,
                {
                    "ok": True,
                    "results": [
                        {"url": "https://docs.example.com/one", "title": "One"}
                    ],
                },
            )
        if stage == "anysearch-search":
            return completed(
                argv,
                {
                    "ok": True,
                    "results": [
                        {
                            "url": "https://news.example.com/two",
                            "title": "Two",
                            "description": "Second source",
                        }
                    ],
                },
            )
        pytest.fail(f"Unexpected command: {stage}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 2)

    assert [result.link for result in results] == [
        "https://docs.example.com/one",
        "https://news.example.com/two",
    ]
    assert results[1].snippet == "Second source"
    assert [argv[1] for argv in calls] == [
        "research",
        "doctor",
        "zhipu-search",
        "exa-search",
        "anysearch-search",
    ]
    assert calls[2][3:] == ["--count", "2", "--format", "json"]
    assert calls[3][3:] == [
        "--num-results",
        "2",
        "--include-text",
        "--format",
        "json",
    ]
    assert calls[4][3:] == ["--max-results", "2", "--format", "json"]


def research_with_one_page(argv, *, web=("zhipu",), docs=("exa",)):
    payload = doctor(web=web, docs=docs)
    payload.update(
        evidence_items=[
            {
                "url": "https://example.org/fetched",
                "title": "Fetched",
                "content": "  Full page text  ",
                "verified": True,
            }
        ],
        discovery_sources=[
            {"url": "https://example.org/fetched"},
            {"url": "https://example.org/unfetched"},
        ],
    )
    return completed(argv, payload)


def test_thin_research_evidence_is_topped_up_with_exa_page_text(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["timeout"]))
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            return research_with_one_page(argv)
        if argv[1] == "exa-search":
            return completed(
                argv,
                {
                    "ok": True,
                    "results": [
                        {"url": "https://example.org/fetched/", "text": "Same page"},
                        {"url": "https://example.org/no-text", "title": "No text"},
                        {
                            "url": "https://news.example.com/exa",
                            "title": "Exa",
                            "text": " Exa page text ",
                        },
                    ],
                },
            )
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 5)

    # Discovery candidates, the research duplicate and Exa results without
    # page text would all need a download; only page text tops up evidence.
    assert [(result.link, result.content) for result in results] == [
        ("https://example.org/fetched", "Full page text"),
        ("https://news.example.com/exa", "Exa page text"),
    ]
    assert results[1].snippet == "Exa page text"
    assert [argv[1] for argv, _ in calls] == ["research", "research", "exa-search"]
    assert calls[2] == (
        [
            "smart-search",
            "exa-search",
            "query",
            "--num-results",
            "5",
            "--include-text",
            "--format",
            "json",
        ],
        20,
    )


def test_enough_research_evidence_runs_nothing_else(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            return research_with_one_page(argv)
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 1)
    assert [result.link for result in results] == ["https://example.org/fetched"]
    assert results[0].content == "Full page text"
    assert calls == ["research", "research"]


@pytest.mark.parametrize("exa_outcome", ["failure", "timeout", "not configured"])
def test_thin_research_evidence_stands_when_no_top_up(monkeypatch, exa_outcome):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            docs = () if exa_outcome == "not configured" else ("exa",)
            return research_with_one_page(argv, web=("zhipu", "tavily"), docs=docs)
        if argv[1] == "exa-search" and exa_outcome == "failure":
            return completed(argv, {"ok": False, "error_type": "network_error"}, 4)
        if argv[1] == "exa-search" and exa_outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 5)
    assert [result.link for result in results] == ["https://example.org/fetched"]
    # zhipu-search would only return pages to download; doctor is never needed.
    assert "zhipu-search" not in calls and "doctor" not in calls


def test_research_page_text_is_capped(monkeypatch):
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        return completed(
            argv,
            {
                "ok": True,
                "evidence_items": [
                    {
                        "url": "https://example.org/long",
                        "content": "x" * 100_050,
                        "verified": True,
                    }
                ],
            },
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    [result] = smart_search.search_smart_search("query", 1)
    assert len(result.content) == 100_000


def test_research_without_evidence_uses_discovery_then_providers(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            payload = doctor(docs=("exa",))
            payload.update(
                evidence_items=[
                    {
                        "url": "context7:/library",
                        "verified": True,
                        "content": "Docs",
                    }
                ],
                discovery_sources=[
                    {"url": "https://example.org/discovered", "title": "Candidate"}
                ],
            )
            return completed(argv, payload)
        if argv[1] == "exa-search":
            return completed(
                argv,
                {
                    "ok": True,
                    "results": [
                        {"url": "https://example.org/discovered"},
                        {
                            "url": "https://example.org/exa",
                            "description": "Exa source",
                            "text": "Exa page",
                        },
                    ],
                },
            )
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 2)
    assert [result.link for result in results] == [
        "https://example.org/discovered",
        "https://example.org/exa",
    ]
    # The candidate is downloaded by the web loader; Exa brought its page text.
    assert [result.content for result in results] == [None, "Exa page"]
    assert results[1].snippet == "Exa source"
    assert calls == ["research", "research", "exa-search"]


def test_search_result_pages_and_encoded_duplicates_are_dropped(monkeypatch):
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        return completed(
            argv,
            {
                "ok": True,
                "evidence_items": [
                    {"url": url, "content": "Page", "verified": True}
                    for url in (
                        "https://duckduckgo.com/html/?q=%E6%96%B0%E9%97%BB",
                        "https://www.google.com/search?q=news",
                        "https://www.baidu.com/s?wd=news",
                        "https://example.org/%E6%96%B0%E9%97%BB/",
                        "http://example.org/新闻#top",
                        "https://www.google.com/about",
                    )
                ],
            },
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    assert [result.link for result in smart_search.search_smart_search("q", 5)] == [
        "https://example.org/%E6%96%B0%E9%97%BB/",
        "https://www.google.com/about",
    ]


def test_mirror_gateway_pages_are_dropped(monkeypatch):
    # big5.<site>.gov.cn/gate/big5/<any host>/... re-serves other sites; spam is
    # indexed through it and the page itself answers 403.
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        return completed(
            argv,
            {
                "ok": True,
                "evidence_items": [
                    {"url": url, "content": "Page", "verified": True}
                    for url in (
                        "https://big5.locpg.gov.cn/gate/big5/www.8zz.org.cn/n3N8/x.phtml",
                        "http://big5.www.gov.cn/gate/GB/www.gov.cn/zhengce/a.htm",
                        "https://www.gov.cn/zhengce/a.htm",
                        "https://example.org/gate/big5-guide",
                    )
                ],
            },
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    assert [result.link for result in smart_search.search_smart_search("q", 5)] == [
        "https://www.gov.cn/zhengce/a.htm",
        "https://example.org/gate/big5-guide",
    ]


def test_results_name_the_search_that_found_them(monkeypatch):
    # Research evidence reports the search that found the page (tavily), not
    # the service that fetched it (firecrawl); a top-up names its command.
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            payload = doctor(web=("tavily",), docs=("exa",))
            payload.update(
                evidence_items=[
                    {
                        "url": "https://example.org/a",
                        "content": "A",
                        "verified": True,
                        "provider": "firecrawl",
                    },
                    {
                        "url": "https://example.org/b",
                        "content": "B",
                        "verified": True,
                        "provider": "tavily",
                    },
                ],
                discovery_sources=[
                    {"url": "https://example.org/a/", "provider": "tavily"},
                ],
            )
            return completed(argv, payload)
        if argv[1] == "exa-search":
            return completed(
                argv,
                {"ok": True, "results": [{"url": "https://example.org/c", "text": "C"}]},
            )
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("q", 5)
    assert [(result.link, result.provider) for result in results] == [
        ("https://example.org/a", "tavily"),
        ("https://example.org/b", "tavily"),
        ("https://example.org/c", "exa"),
    ]


@pytest.mark.parametrize(
    "provider,command,options",
    [
        ("zhipu-mcp", "zhipu-mcp-search", ["--count", "1"]),
        ("zhipu", "zhipu-search", ["--count", "1"]),
        ("exa", "exa-search", ["--num-results", "1", "--include-text"]),
        ("anysearch", "anysearch-search", ["--max-results", "1"]),
    ],
)
def test_direct_provider_json_results(monkeypatch, provider, command, options):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "research":
            return subprocess.CompletedProcess(argv, 2, stdout="")
        if argv[1] == "doctor":
            return completed(
                argv, doctor(web=(provider,), docs=(provider,), vertical=(provider,))
            )
        return completed(
            argv,
            {
                "ok": True,
                "results": [
                    {
                        "url": "https://example.org/result",
                        "title": "Result",
                        "description": "Source text",
                    }
                ],
            },
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 1)
    assert [result.link for result in results] == ["https://example.org/result"]
    assert results[0].snippet == "Source text"
    assert results[0].provider == provider
    assert calls[-1] == ["smart-search", command, "query", *options, "--format", "json"]
    assert len(calls) == 3


def test_research_failure_capability_status_routes_sources_without_doctor(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            payload = doctor(web=("zhipu", "tavily"), docs=("exa",))
            payload.update(
                ok=False, error_type="network_error", error="private diagnostic"
            )
            return completed(argv, payload, 4)
        if argv[1] == "doctor":
            pytest.fail("doctor must not run when research already reported capabilities")
        if argv[1] == "zhipu-search":
            return completed(
                argv,
                {
                    "ok": True,
                    "results": [
                        {"url": "https://news.example.com/one", "description": "Direct"}
                    ],
                },
            )
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 1)
    assert [result.link for result in results] == ["https://news.example.com/one"]
    assert results[0].snippet == "Direct"
    assert calls == ["research", "research", "zhipu-search"]


def test_thin_research_capability_status_routes_sources_without_doctor(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1])
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            payload = doctor(docs=("exa",))
            payload.update(evidence_items=[], discovery_sources=[])
            return completed(argv, payload)
        if argv[1] == "doctor":
            pytest.fail("doctor must not run when research already reported capabilities")
        if argv[1] == "exa-search":
            return completed(
                argv, {"ok": True, "results": [{"url": "https://docs.example.com/one"}]}
            )
        pytest.fail(f"Unexpected command: {argv[1]}")

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    results = smart_search.search_smart_search("query", 1)
    assert [result.link for result in results] == ["https://docs.example.com/one"]
    assert calls == ["research", "research", "exa-search"]


def test_incomplete_doctor_profile_still_routes_configured_source(monkeypatch):
    def fake_run(argv, **kwargs):
        if argv[1] == "research":
            return subprocess.CompletedProcess(argv, 2, stdout="")
        if argv[1] == "doctor":
            payload = doctor(docs=("exa",))
            payload.update(
                ok=False, error_type="config_error", error="private diagnostic"
            )
            return completed(argv, payload, 3)
        return completed(
            argv, {"ok": True, "results": [{"url": "https://example.org/doc"}]}
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    assert [result.link for result in smart_search.search_smart_search("query", 1)] == [
        "https://example.org/doc"
    ]


@pytest.mark.parametrize(
    "source_response,expected",
    [
        (
            subprocess.CompletedProcess(
                [], 0, stdout="private diagnostic https://example.org"
            ),
            "invalid JSON",
        ),
        (
            subprocess.CompletedProcess(
                [], 0, stdout='{"ok":true,"results":"private diagnostic"}'
            ),
            "unsuccessful response",
        ),
        (
            subprocess.CompletedProcess(
                [],
                4,
                stdout='{"ok":false,"error_type":"provider_error","error":"private diagnostic"}',
            ),
            "exit 4 (provider_error)",
        ),
    ],
)
def test_text_malformed_and_failed_provider_outputs_are_sanitized(
    monkeypatch, source_response, expected
):
    def fake_run(argv, **kwargs):
        if argv[1] == "research":
            return subprocess.CompletedProcess(argv, 2, stdout="")
        if argv[1] == "doctor":
            return completed(argv, doctor(web=("zhipu",)))
        return source_response

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc_info:
        smart_search.search_smart_search("query", 5)
    message = str(exc_info.value)
    assert "private diagnostic" not in message
    assert "research: unavailable in installed CLI" in message
    assert f"zhipu-search: {expected}" in message


def test_empty_success_does_not_hide_other_failures(monkeypatch):
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        if argv[1] == "research":
            payload = doctor(web=("zhipu",))
            payload.update(evidence_items=[])
            return completed(argv, payload)
        return completed(argv, {"ok": False, "error_type": "network_error"}, 4)

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="zhipu-search: exit 4"):
        smart_search.search_smart_search("query", 3)


def test_all_valid_empty_responses_return_no_results(monkeypatch):
    def fake_run(argv, **kwargs):
        if argv[1] == "research":
            return subprocess.CompletedProcess(argv, 2, stdout="")
        if argv[1] == "doctor":
            return completed(argv, doctor(web=("zhipu",)))
        return completed(argv, {"ok": True, "results": []})

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    assert smart_search.search_smart_search("query", 3) == []


def test_timeout_errors_are_sanitized(monkeypatch):
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="usage")
        raise subprocess.TimeoutExpired(
            argv, kwargs["timeout"], output="private diagnostic"
        )

    monkeypatch.setattr(smart_search.subprocess, "run", fake_run)
    with pytest.raises(
        RuntimeError, match="research: timeout; doctor: timeout"
    ) as exc_info:
        smart_search.search_smart_search("query", 3)
    assert "private diagnostic" not in str(exc_info.value)


def test_missing_cli_explains_backend_runtime_requirement(monkeypatch):
    monkeypatch.setenv("SMART_SEARCH_CLI", "/missing/smart-search")

    def missing_cli(_argv, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(smart_search.subprocess, "run", missing_cli)
    with pytest.raises(RuntimeError, match="backend environment") as exc_info:
        smart_search.search_smart_search("query", 5)
    assert "/missing/smart-search" in str(exc_info.value)
    assert "SMART_SEARCH_CLI" in str(exc_info.value)


def test_zero_count_skips_cli(monkeypatch):
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
