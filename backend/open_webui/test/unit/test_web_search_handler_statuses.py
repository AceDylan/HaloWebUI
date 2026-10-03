import pathlib
import sys
from types import SimpleNamespace

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import middleware  # noqa: E402


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace())),
        state=SimpleNamespace(metadata={}),
    )


async def _run(monkeypatch, search, queries=None, generated='{"queries": []}'):
    statuses = []
    searched = []

    async def emitter(event):
        if event.get("type") == "status":
            statuses.append(event["data"])

    async def fake_generate_queries(request, form_data, user):
        return {"choices": [{"message": {"content": generated}}]}

    async def fake_process_web_search(request, form_data, user=None):
        searched.append(form_data.query)
        return search(form_data.query)

    monkeypatch.setattr(middleware, "generate_queries", fake_generate_queries)
    monkeypatch.setattr(middleware, "process_web_search", fake_process_web_search)
    form = {"model": "m", "messages": [{"role": "user", "content": "杭州 周末 天气"}]}
    await middleware.chat_web_search_handler(
        _request(), form, {"__event_emitter__": emitter}, SimpleNamespace(role="user"), queries=queries
    )
    return statuses, searched


def _page(url):
    return {"filenames": [url], "docs": [{"content": "body", "metadata": {"source": url}}], "loaded_count": 1}


@pytest.mark.asyncio
async def test_an_empty_keyword_list_still_searches_what_the_user_wrote(monkeypatch):
    statuses, searched = await _run(monkeypatch, lambda q: _page("https://a.example.com/x"))

    assert searched == ["杭州 周末 天气"]
    assert statuses[-1]["description"] == "联网搜索完成，找到 1 个来源。"


@pytest.mark.asyncio
async def test_a_page_two_keywords_found_counts_once(monkeypatch):
    statuses, searched = await _run(
        monkeypatch, lambda q: _page("https://a.example.com/x"), queries=["杭州 天气", "杭州 周末"]
    )

    assert sorted(searched) == ["杭州 周末", "杭州 天气"]
    assert statuses[-1]["count"] == 1
    assert statuses[-1]["urls"] == ["https://a.example.com/x"]


@pytest.mark.asyncio
async def test_a_smart_search_failure_reads_in_chinese(monkeypatch):
    def fail(query):
        raise RuntimeError("smart-search CLI search failed (research: timeout; doctor: timeout)")

    statuses, _ = await _run(monkeypatch, fail, queries=["杭州 天气"])

    assert statuses[-1]["description"] == "联网搜索失败：这个关键词没搜到（等待超时），已跳过。"
