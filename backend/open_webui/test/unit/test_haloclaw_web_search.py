import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.haloclaw.web_search import (  # noqa: E402
    _build_files,
    _count_sources,
    _format_sources_context,
    _inject_context,
)


def test_build_files_from_docs_results():
    """BYPASS 模式：process_web_search 直接返回 docs 时，按 url 一一拆成 web_search file。"""
    results = {
        "docs": [
            {"content": "内容A", "metadata": {"source": "https://a.com"}},
            {"content": "内容B", "metadata": {"source": "https://b.com"}},
        ],
        "filenames": ["https://a.com", "https://b.com"],
    }

    files = _build_files(["关键词"], [results])

    assert len(files) == 2
    assert all(f["type"] == "web_search" for f in files)
    assert files[0]["docs"] == [{"content": "内容A", "metadata": {"source": "https://a.com"}}]
    assert files[0]["urls"] == ["https://a.com"]


def test_build_files_from_collection_results():
    """embedding 模式：返回 collection_names 时，按集合拆成 web_search file。"""
    results = {
        "collection_names": ["col-1", "col-2"],
        "filenames": ["https://a.com", "https://b.com"],
    }

    files = _build_files(["关键词"], [results])

    assert len(files) == 2
    assert files[0]["collection_name"] == "col-1"
    assert files[0]["urls"] == ["https://a.com"]


def test_build_files_skips_empty_results():
    assert _build_files(["q1", "q2"], [None, None]) == []


def test_format_sources_context_numbers_and_links():
    sources = [
        {
            "source": {"type": "web_search"},
            "document": ["实时资料一", "实时资料二"],
            "metadata": [
                {"source": "https://a.com"},
                {"source": "https://b.com"},
            ],
        }
    ]

    text = _format_sources_context(sources)

    assert "[1] https://a.com" in text
    assert "[2] https://b.com" in text
    assert "实时资料一" in text
    assert "来源链接：" in text


def test_format_sources_context_truncates_long_content():
    long_text = "x" * 9000
    sources = [
        {"document": [long_text], "metadata": [{"source": "https://a.com"}]}
    ]

    text = _format_sources_context(sources)

    assert "…" in text
    # 正文被截断到上限以内（远小于原始 9000）
    assert text.count("x") <= 4001


def test_format_sources_context_empty():
    assert _format_sources_context([]) == ""
    assert _format_sources_context([{"document": [], "metadata": []}]) == ""


def test_count_sources_ignores_blank_docs():
    sources = [{"document": ["有内容", "  ", ""], "metadata": [{}, {}, {}]}]
    assert _count_sources(sources) == 1


def test_inject_context_into_string_message():
    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "比特币现在多少钱"},
    ]

    injected = _inject_context(messages, "联网资料块")

    assert injected is True
    assert messages[1]["content"].startswith("联网资料块")
    assert "比特币现在多少钱" in messages[1]["content"]
    # system 消息不应被改动
    assert messages[0]["content"] == "你是助手"


def test_inject_context_into_multimodal_message():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这是什么"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }
    ]

    injected = _inject_context(messages, "联网资料块")

    assert injected is True
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("联网资料块")
    # 原有图片内容保留
    assert content[-1]["type"] == "image_url"


def test_inject_context_targets_last_user_message():
    messages = [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "回复"},
        {"role": "user", "content": "第二轮"},
    ]

    _inject_context(messages, "联网资料块")

    assert messages[0]["content"] == "第一轮"
    assert messages[2]["content"].startswith("联网资料块")


def test_inject_context_no_user_message():
    messages = [{"role": "system", "content": "x"}]
    assert _inject_context(messages, "联网资料块") is False
