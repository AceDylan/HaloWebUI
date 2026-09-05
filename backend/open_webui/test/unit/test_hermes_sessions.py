import json

import pytest

from open_webui.utils.hermes_sessions import (
    HermesSessionsError,
    build_chat_payload,
    fold_transcript,
    validate_session_id,
)


def _telegram_transcript():
    return [
        {"role": "system", "content": "you are hermes", "timestamp": 1000.0},
        {"role": "user", "content": "查一下今天的新闻", "timestamp": 1001.5},
        {
            "role": "assistant",
            "content": "",
            "timestamp": 1002.0,
            "tool_calls": json.dumps(
                [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": '{"q": "news"}'},
                    }
                ]
            ),
        },
        {"role": "tool", "tool_name": "web_search", "content": "<huge>", "timestamp": 1003.0},
        {"role": "assistant", "content": "今天的要闻有三条……", "timestamp": 1004.0},
        {"role": "user", "content": "第二条展开说", "timestamp": 1100.0},
        {"role": "assistant", "content": "第二条是……", "timestamp": 1101.0},
    ]


def test_fold_transcript_makes_one_turn_per_user_message():
    turns = fold_transcript(_telegram_transcript())

    assert [turn["user"] for turn in turns] == ["查一下今天的新闻", "第二条展开说"]
    first = "\n\n".join(turns[0]["assistant"])
    # the tool call renders as the same card a live run produces ...
    assert '<details type="tool_calls" done="true" id="hermes-import-1" name="web_search"' in first
    # ... the tool result and the system prompt are not part of the chat
    assert "<huge>" not in first
    assert "you are hermes" not in first
    assert first.endswith("今天的要闻有三条……")
    assert turns[0]["timestamp"] == 1001
    assert turns[0]["completed_at"] == 1004


def test_fold_transcript_drops_empty_turns_and_tolerates_bad_tool_json():
    turns = fold_transcript(
        [
            {"role": "user", "content": "   ", "timestamp": 1},
            {"role": "user", "content": "hi", "timestamp": 2},
            {"role": "assistant", "content": "hello", "tool_calls": "{not json", "timestamp": 3},
            {"role": "user", "content": "", "timestamp": 4},
        ]
    )

    assert [turn["user"] for turn in turns] == ["hi"]
    assert turns[0]["assistant"] == ["hello"]


def test_build_chat_payload_links_a_linear_branch_with_the_hermes_model():
    turns = fold_transcript(_telegram_transcript())
    model = {
        "id": "modelref::openai::personal::id:ee5e02db::hermes-agent",
        "name": "hermes-agent",
        "model_ref": {"provider": "openai", "model_id": "hermes-agent"},
    }

    payload = build_chat_payload(
        {"id": "20260905_090253_c047653d", "title": "今日新闻"}, turns, model
    )

    assert payload["id"] == "20260905_090253_c047653d"
    assert payload["title"] == "今日新闻"
    assert payload["models"] == [model["id"]]
    history = payload["history"]
    messages = history["messages"]
    assert len(messages) == 4
    leaf = messages[history["currentId"]]
    assert leaf["role"] == "assistant" and leaf["done"] is True
    assert leaf["model"] == model["id"]
    assert leaf["model_ref"] == model["model_ref"]
    # walk parentId links back to the root: assistant <- user <- assistant <- user
    chain = []
    current = leaf
    while current is not None:
        chain.append(current["role"])
        current = messages.get(current["parentId"]) if current["parentId"] else None
    assert chain == ["assistant", "user", "assistant", "user"]
    root = next(message for message in messages.values() if message["parentId"] is None)
    assert root["content"] == "查一下今天的新闻"
    assert root["childrenIds"] == [messages[root["childrenIds"][0]]["id"]]
    # the first assistant links forward to the second user turn
    first_assistant = messages[root["childrenIds"][0]]
    assert [messages[child]["role"] for child in first_assistant["childrenIds"]] == ["user"]
    assert payload["messages"][0]["id"] == root["id"]


def test_build_chat_payload_titles_from_the_first_user_line_when_untitled():
    turns = fold_transcript(
        [
            {"role": "user", "content": "first line\nsecond line", "timestamp": 1},
            {"role": "assistant", "content": "ok", "timestamp": 2},
        ]
    )

    payload = build_chat_payload({"id": "s1", "title": ""}, turns, {"id": "m"})

    assert payload["title"] == "first line"


def test_validate_session_id_rejects_path_tricks():
    assert validate_session_id("20260905_090253_c047653d") == "20260905_090253_c047653d"
    for bad in ("", "../x", "a/b", "a b", "?x=1", "." * 3):
        with pytest.raises(HermesSessionsError) as exc:
            validate_session_id(bad)
        assert exc.value.status_code == 400
