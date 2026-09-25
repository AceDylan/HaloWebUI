import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.retrieval.web.main import SearchResult  # noqa: E402
from open_webui.routers.retrieval import _build_direct_docs_from_web_results  # noqa: E402


def test_build_direct_docs_from_web_results_preserves_content_without_urls():
    payload = _build_direct_docs_from_web_results(
        "今天热点",
        [
            SearchResult(
                link="",
                title="Grok Search Result",
                snippet="这是直接传递给主模型的全文内容。",
            )
        ],
        "grok",
    )

    assert payload is not None
    assert payload["loaded_count"] == 1
    assert payload["direct_content_only"] is True
    assert payload["docs"][0]["content"] == "这是直接传递给主模型的全文内容。"
    metadata = payload["docs"][0]["metadata"]
    assert metadata["engine"] == "grok"
    assert metadata["source_type"] == "search_summary"
    assert metadata["internal_source"] is True
    assert metadata["display_source"] == "grok 搜索摘要"
    assert metadata["content"] == "这是直接传递给主模型的全文内容。"
    assert metadata["snippet"] == "这是直接传递给主模型的全文内容。"
    assert "url" not in metadata
    assert payload["filenames"][0].startswith("grok://search/")


def test_build_direct_docs_prefers_prefetched_page_text():
    payload = _build_direct_docs_from_web_results(
        "query",
        [
            SearchResult(
                link="https://example.org/page",
                title="Page",
                snippet="Short excerpt",
                content="Full page text",
            )
        ],
        "smart_search",
    )

    assert payload["docs"][0]["content"] == "Full page text"


def test_web_search_uses_prefetched_pages_and_loads_only_the_rest(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from langchain_core.documents import Document
    from open_webui.routers import retrieval

    async def fake_search(_request, _engine, _query):
        return [
            SearchResult(
                link="https://example.org/fetched",
                title="Fetched",
                snippet="Excerpt",
                content="Research page text",
            ),
            SearchResult(link="https://example.org/other", title="Other", snippet=""),
        ]

    loaded = []
    downloaded = "Downloaded page text, long enough to be a real page body."

    async def fake_loader(_request, urls, **_kwargs):
        loaded.append(list(urls))
        return [
            Document(page_content=downloaded, metadata={"source": url}) for url in urls
        ]

    monkeypatch.setattr(retrieval, "_search_web_async", fake_search)
    monkeypatch.setattr(retrieval, "_load_web_documents_with_loader", fake_loader)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    WEB_SEARCH_ENGINE="smart_search",
                    WEB_LOADER_ENGINE="",
                    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL=True,
                )
            )
        )
    )

    result = asyncio.run(
        retrieval.process_web_search(
            request, retrieval.SearchForm(query="query"), user=None
        )
    )

    assert loaded == [["https://example.org/other"]]
    assert result["filenames"] == [
        "https://example.org/fetched",
        "https://example.org/other",
    ]
    assert [doc["content"] for doc in result["docs"]] == [
        "Research page text",
        downloaded,
    ]
    assert result["docs"][0]["metadata"] == {
        "source": "https://example.org/fetched",
        "title": "Fetched",
    }


def test_unreadable_downloads_fall_back_to_the_snippet_or_are_dropped(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from langchain_core.documents import Document
    from open_webui.routers import retrieval

    page = "A readable page body that is comfortably longer than fifty chars."

    async def fake_search(_request, _engine, _query):
        return [
            SearchResult(link="https://example.org/ok", title="Ok", snippet="x"),
            SearchResult(
                link="https://example.org/blocked",
                title="Blocked",
                snippet="What the search engine saw on the page",
            ),
            SearchResult(link="https://example.org/empty", title="Empty", snippet=""),
        ]

    async def fake_loader(_request, urls, **_kwargs):
        texts = {
            "https://example.org/ok": page,
            "https://example.org/blocked": "403 Forbidden",
            "https://example.org/empty": "",
        }
        return [
            Document(page_content=texts[url], metadata={"source": url}) for url in urls
        ]

    monkeypatch.setattr(retrieval, "_search_web_async", fake_search)
    monkeypatch.setattr(retrieval, "_load_web_documents_with_loader", fake_loader)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    WEB_SEARCH_ENGINE="smart_search",
                    WEB_LOADER_ENGINE="",
                    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL=True,
                )
            )
        )
    )

    result = asyncio.run(
        retrieval.process_web_search(
            request, retrieval.SearchForm(query="query"), user=None
        )
    )

    assert result["filenames"] == [
        "https://example.org/ok",
        "https://example.org/blocked",
    ]
    assert [doc["content"] for doc in result["docs"]] == [
        page,
        "What the search engine saw on the page",
    ]
    assert result["failed_count"] == 1


def test_providers_for_urls_lists_each_search_once_in_page_order():
    from open_webui.routers.retrieval import _providers_for_urls

    results = [
        SearchResult(link="https://a.example/1", title="1", snippet="", provider="tavily"),
        SearchResult(link="https://b.example/2", title="2", snippet="", provider="exa"),
        SearchResult(link="https://c.example/3", title="3", snippet="", provider="tavily"),
        SearchResult(link="https://d.example/4", title="4", snippet=""),
    ]
    assert _providers_for_urls(
        results,
        ["https://c.example/3", "https://b.example/2", "https://a.example/1", "https://d.example/4"],
    ) == ["tavily", "exa"]
    assert _providers_for_urls(results, ["https://d.example/4"]) == []
