import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.middleware import (  # noqa: E402
    _build_auto_web_search_chat_history,
    _extract_json_object_from_text,
    _normalize_auto_web_search_queries,
    _quick_auto_web_search_decision,
)


def test_quick_auto_web_search_respects_user_opt_out():
    decision = _quick_auto_web_search_decision(
        [{"role": "user", "content": "不要联网，直接根据你知道的解释一下"}]
    )

    assert decision["should_search"] is False
    assert decision["queries"] == []
    assert decision["reason"] == "user_disabled_web_search"


def test_quick_auto_web_search_uses_search_for_urls():
    decision = _quick_auto_web_search_decision(
        [{"role": "user", "content": "帮我看看 https://example.com/docs 这个页面"}]
    )

    assert decision["should_search"] is True
    assert decision["queries"] == ["帮我看看 https://example.com/docs 这个页面"]
    assert decision["reason"] == "user_referenced_url"


def test_quick_auto_web_search_leaves_ambiguous_prompts_to_task_model():
    decision = _quick_auto_web_search_decision(
        [{"role": "user", "content": "今天帮我写一段产品说明"}]
    )

    assert decision is None


def test_quick_auto_web_search_does_not_treat_feature_discussion_as_search_request():
    decision = _quick_auto_web_search_decision(
        [{"role": "user", "content": "智能联网这个逻辑现在是怎么设计的"}]
    )

    assert decision is None


def test_normalize_auto_web_search_queries_deduplicates_and_limits():
    queries = _normalize_auto_web_search_queries(
        ["  GPT-5.5 news  ", "gpt-5.5 news", "", "OpenAI releases", "extra"]
    )

    assert queries == ["GPT-5.5 news", "OpenAI releases", "extra"]


def test_extract_json_object_from_text_accepts_wrapped_model_output():
    parsed = _extract_json_object_from_text(
        'Sure:\n{"should_search": true, "queries": ["latest"], "reason": "current"}'
    )

    assert parsed["should_search"] is True
    assert parsed["queries"] == ["latest"]


def test_build_auto_web_search_history_uses_recent_text_messages():
    history = _build_auto_web_search_chat_history(
        [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": [{"type": "text", "text": "最新问题"}]},
        ]
    )

    assert 'USER: """最新问题"""' in history
    assert 'ASSISTANT: """旧回答"""' in history
