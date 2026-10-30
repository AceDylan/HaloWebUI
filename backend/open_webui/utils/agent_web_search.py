"""HaloWebUI's web search, for Hermes.

When Hermes (Telegram, QQ, a chat in this app) needs the web, its ``halo-search`` command asks
here instead of running a search of its own, so it looks up and reads exactly what a chat with
search on would: the same keywords (``generate_web_search_queries``, at most three), the same
engine and readers per keyword (``process_web_search``), and the same page text the chat model
gets (``get_sources_from_files``). Sources are numbered once per page, as the chat's citations are.
"""

import asyncio
import logging
import time

from fastapi import Request

from open_webui.haloclaw.web_search import _build_files, _extract_sources

log = logging.getLogger(__name__)


async def search_for_agent(request: Request, user, question: str) -> dict:
    from open_webui.routers.retrieval import SearchForm, process_web_search
    from open_webui.utils.middleware import generate_web_search_queries

    config = request.app.state.config
    if not getattr(config, "ENABLE_WEB_SEARCH", False):
        return {"ok": False, "error": "HaloWebUI 的联网搜索没有开启"}

    started = time.monotonic()
    # The task model writes the keywords, whatever model the chat is on.
    model_id = (config.TASK_MODEL_EXTERNAL or config.TASK_MODEL or "").strip()
    queries = await generate_web_search_queries(
        request, model_id, [{"role": "user", "content": question}], user
    )

    async def run(query: str):
        try:
            return await process_web_search(request, SearchForm(query=query), user=user), None
        except Exception as e:
            detail = getattr(e, "detail", None)
            log.warning("Hermes web search failed (%s): %s", query, detail or e)
            return None, str(detail or e)[:300]

    outcomes = await asyncio.gather(*(run(query) for query in queries))
    failed = [
        {"query": query, "reason": reason}
        for query, (_results, reason) in zip(queries, outcomes)
        if reason
    ]
    files = _build_files(queries, [results for results, _reason in outcomes])
    sources = await _extract_sources(request, files, queries, user) if files else []

    items = []
    by_url = {}
    for source in sources:
        query = (source.get("source") or {}).get("name") or ""
        metadatas = source.get("metadata") or []
        for i, document in enumerate(source.get("document") or []):
            text = (document or "").strip()
            if not text:
                continue
            meta = metadatas[i] if i < len(metadatas) and isinstance(metadatas[i], dict) else {}
            url = str(meta.get("source") or meta.get("url") or "").strip()
            known = by_url.get(url) if url else None
            if known is not None:
                if len(text) > len(known["content"]):
                    known["content"] = text
                continue
            item = {
                "n": len(items) + 1,
                "title": str(meta.get("title") or "").strip(),
                "url": url,
                "query": query,
                "content": text,
            }
            items.append(item)
            if url:
                by_url[url] = item

    out = {
        "ok": bool(items),
        "queries": queries,
        "engine": str(getattr(config, "WEB_SEARCH_ENGINE", "") or ""),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "sources": items,
        "failed_queries": failed,
    }
    if not items:
        out["error"] = "没有搜到可用的网页" + (f"（{failed[0]['reason']}）" if failed else "")
    return out
