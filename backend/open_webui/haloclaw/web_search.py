"""智能联网（auto web search）for HaloClaw 消息网关。

复用页面端「智能联网」的能力：在调用模型之前，先自动判断当前这条消息
是否需要联网，需要时用与页面相同的搜索 / 抓取链路检索，并把检索到的实时
网页资料作为上下文注入到本轮对话里。

与页面的差异：TG / 企业微信 / 飞书等 IM 没有流式状态条与引用卡片 UI，
因此这里把结果以纯文本上下文注入，并要求模型用 [n] 标注来源、直接给出 URL，
而不是依赖前端渲染 source 卡片。

判断与检索逻辑直接复用 open_webui.utils.middleware / routers.retrieval，
保证「该不该联网」「搜什么」「怎么抓」与页面完全一致。
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# 每条消息最多并行的搜索关键词数（与页面 chat_web_search_handler 保持一致）
_QUERY_CONCURRENCY = 3
# 注入上下文里每个来源正文的最大字符数，避免 prompt 过长
_MAX_SOURCE_CHARS = 4000
# 最多注入的来源条数
_MAX_SOURCES = 8


async def maybe_run_auto_web_search(
    fake_request: Any,
    form_data: dict,
    user: Any,
    model_id: str,
) -> Optional[dict]:
    """智能判断并执行联网搜索，把结果注入 form_data['messages']。

    Args:
        fake_request: dispatcher 构造的 _FakeRequest（带真实 app.state）。
        form_data: 已构建好的补全请求体（含 messages）。
        user: 用于模型调用 / 检索的 Halo 用户。
        model_id: 当前对话模型，同时用作智能判断的任务模型。

    Returns:
        状态摘要 dict（用于日志），或 None（全局未开启 / 无消息）。
        {"searched": bool, "reason": str?, "sources": int?, "queries": [...]?}
    """
    config = fake_request.app.state.config

    if not bool(getattr(config, "ENABLE_WEB_SEARCH", False)):
        return None

    messages = form_data.get("messages")
    if not isinstance(messages, list) or not messages:
        return None

    # 1) 智能判断是否需要联网（复用页面逻辑：先启发式规则，再任务模型判断）
    try:
        from open_webui.utils.middleware import _resolve_auto_web_search_decision

        decision = await _resolve_auto_web_search_decision(
            fake_request, form_data, user, model_id
        )
    except Exception as e:
        log.warning(f"HaloClaw 智能联网判断失败: {e}")
        return {"searched": False, "reason": "decision_error"}

    if not decision.get("should_search"):
        return {"searched": False, "reason": decision.get("reason")}

    queries = decision.get("queries") or []
    if not queries:
        return {"searched": False, "reason": "no_queries"}

    # 2) 并行检索（复用页面 process_web_search：同款搜索引擎 + 网页抓取）
    results_list = await _search_queries(fake_request, queries, user)

    # 3) 汇总成 files（镜像 chat_web_search_handler 的 files 结构）
    files = _build_files(queries, results_list)
    if not files:
        return {"searched": True, "sources": 0, "queries": queries}

    # 4) 提取上下文（复用 get_sources_from_files，统一处理 bypass / embedding 两种模式）
    sources = await _extract_sources(fake_request, files, queries, user)

    context_text = _format_sources_context(sources)
    if not context_text:
        return {"searched": True, "sources": 0, "queries": queries}

    # 5) 把实时资料注入到最后一条用户消息（最通用、跨 provider 最稳妥）
    injected = _inject_context(messages, context_text)
    source_count = _count_sources(sources)
    return {
        "searched": injected,
        "sources": source_count if injected else 0,
        "queries": queries,
    }


async def _search_queries(fake_request: Any, queries: list[str], user: Any) -> list:
    """对每个关键词并行调用页面同款的 process_web_search。"""
    from open_webui.routers.retrieval import process_web_search, SearchForm

    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY)

    async def _run(query: str):
        async with semaphore:
            try:
                return await process_web_search(
                    fake_request, SearchForm(query=query), user=user
                )
            except Exception as e:
                log.warning(f"HaloClaw 联网搜索失败（{query}）: {e}")
                return None

    return await asyncio.gather(*[_run(q) for q in queries])


def _build_files(queries: list[str], results_list: list) -> list[dict]:
    """把 process_web_search 的结果转换为 get_sources_from_files 可用的 files。

    与 chat_web_search_handler 的 files 构造逻辑保持一致，兼容
    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL 开 / 关两种情况。
    """
    files: list[dict] = []
    for query, results in zip(queries, results_list):
        if not results:
            continue

        if results.get("collection_names"):
            filenames = results.get("filenames") or []
            for col_idx, collection_name in enumerate(results["collection_names"]):
                files.append(
                    {
                        "collection_name": collection_name,
                        "name": query,
                        "type": "web_search",
                        "urls": [filenames[col_idx]] if col_idx < len(filenames) else [],
                    }
                )
        elif results.get("docs"):
            docs = results["docs"]
            filenames = results.get("filenames") or []
            if filenames and len(docs) == len(filenames):
                for doc_idx, doc in enumerate(docs):
                    files.append(
                        {
                            "docs": [doc],
                            "name": query,
                            "type": "web_search",
                            "urls": [filenames[doc_idx]],
                        }
                    )
            else:
                files.append(
                    {
                        "docs": docs,
                        "name": query,
                        "type": "web_search",
                        "urls": filenames,
                    }
                )
    return files


async def _extract_sources(
    fake_request: Any, files: list[dict], queries: list[str], user: Any
) -> list[dict]:
    """复用 get_sources_from_files 抽取相关上下文（与页面 RAG 注入同款）。"""
    from open_webui.retrieval.utils import get_sources_from_files
    from open_webui.retrieval.runtime import get_safe_reranking_runtime

    config = fake_request.app.state.config

    def _run():
        return get_sources_from_files(
            request=fake_request,
            files=files,
            queries=queries,
            embedding_function=lambda query, prefix: fake_request.app.state.EMBEDDING_FUNCTION(
                query, prefix=prefix, user=user
            ),
            k=config.TOP_K,
            reranking_function=(
                get_safe_reranking_runtime(fake_request.app)
                if config.ENABLE_RAG_HYBRID_SEARCH
                else None
            ),
            k_reranker=config.TOP_K_RERANKER,
            r=config.RELEVANCE_THRESHOLD,
            hybrid_search=config.ENABLE_RAG_HYBRID_SEARCH,
            full_context=config.RAG_FULL_CONTEXT,
            bm25_weight=config.RAG_HYBRID_SEARCH_BM25_WEIGHT,
            enable_enriched_texts=getattr(
                config, "ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS", False
            ),
        )

    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, _run)
    except Exception as e:
        log.warning(f"HaloClaw 联网上下文提取失败: {e}")
        return []


def _count_sources(sources: list[dict]) -> int:
    count = 0
    for src in sources:
        for doc in src.get("document") or []:
            if (doc or "").strip():
                count += 1
    return count


def _format_sources_context(sources: list[dict]) -> str:
    """把检索到的来源渲染为纯文本上下文块（含 [n] 编号与 URL）。"""
    if not sources:
        return ""

    blocks: list[str] = []
    refs: list[str] = []
    n = 0
    for src in sources:
        documents = src.get("document") or []
        metadatas = src.get("metadata") or []
        for i, doc in enumerate(documents):
            text = (doc or "").strip()
            if not text:
                continue
            n += 1
            if n > _MAX_SOURCES:
                break

            md = metadatas[i] if i < len(metadatas) else {}
            url = ""
            if isinstance(md, dict):
                url = md.get("source") or md.get("url") or md.get("name") or ""

            if len(text) > _MAX_SOURCE_CHARS:
                text = text[:_MAX_SOURCE_CHARS] + "…"

            header = f"[{n}] {url}".rstrip()
            blocks.append(f"{header}\n{text}")
            if url:
                refs.append(f"[{n}] {url}")
        if n > _MAX_SOURCES:
            break

    if not blocks:
        return ""

    parts = [
        "以下是联网搜索得到的实时网页资料。请优先依据这些资料回答用户的问题，"
        "在引用具体信息处用 [n] 标注对应来源；若资料不足以回答，再结合你已有的知识，"
        "并说明哪些是实时资料、哪些是你的推断。",
        "",
        "\n\n".join(blocks),
    ]
    if refs:
        parts.append("")
        parts.append("来源链接：")
        parts.append("\n".join(refs))
    return "\n".join(parts)


def _inject_context(messages: list[dict], context_text: str) -> bool:
    """把联网资料拼接到最后一条用户消息之前。

    选择改写最后一条 user 消息（而非新增 system 消息）：
    - 避免在对话中间插入 system 角色，兼容更多 OpenAI 兼容上游；
    - 仅修改内存中的请求体，不影响已落库的历史记录。
    """
    for i in range(len(messages) - 1, -1, -1):
        if not isinstance(messages[i], dict) or messages[i].get("role") != "user":
            continue

        content = messages[i].get("content")
        prefix = f"{context_text}\n\n---\n\n用户问题：\n"

        if isinstance(content, str):
            messages[i]["content"] = prefix + content
        elif isinstance(content, list):
            # 多模态消息：在最前面插入一段文本块，保留原有图片等内容
            messages[i]["content"] = [{"type": "text", "text": prefix}] + content
        else:
            messages[i]["content"] = prefix
        return True

    return False
