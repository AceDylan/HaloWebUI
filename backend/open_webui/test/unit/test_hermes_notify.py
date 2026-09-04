from open_webui.utils import hermes_notify
from open_webui.utils.hermes_notify import (
    RELOAD_EVENT_TYPE,
    append_follow_up_turn,
    build_conversation_messages,
    build_follow_up_form_data,
    find_chat_model,
    verify_notify_token,
)


def _chat():
    return {
        "history": {
            "currentId": "a1",
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "childrenIds": ["a1"],
                    "role": "user",
                    "content": "全程由 reclaude 实现：查下 gpt-6 什么时候上线",
                    "timestamp": 1,
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "childrenIds": [],
                    "role": "assistant",
                    "content": (
                        '<details type="tool_calls" done="true" id="hermes-0" name="terminal">'
                        "<summary>Tool Executed</summary></details>\n"
                        "已启动 reclaude，运行 ID：20260904-225602"
                    ),
                    "model": "modelref::openai::personal::id:ee5e02db::hermes-agent",
                    "modelName": "hermes-agent | hermes",
                    "model_ref": {"provider": "openai", "connection_id": "ee5e02db"},
                    "modelIdx": 0,
                    "timestamp": 2,
                    "done": True,
                },
            },
        }
    }


def test_verify_notify_token_requires_matching_bearer(monkeypatch):
    monkeypatch.delenv(hermes_notify.HERMES_AGENT_NOTIFY_TOKEN_ENV, raising=False)
    assert hermes_notify.notify_token_configured() is False
    assert verify_notify_token("Bearer anything") is False

    monkeypatch.setenv(hermes_notify.HERMES_AGENT_NOTIFY_TOKEN_ENV, "s3cret")
    assert hermes_notify.notify_token_configured() is True
    assert verify_notify_token("Bearer s3cret") is True
    assert verify_notify_token("bearer s3cret") is True
    assert verify_notify_token("Bearer other") is False
    assert verify_notify_token("Basic s3cret") is False
    assert verify_notify_token(None) is False


def test_find_chat_model_uses_newest_assistant_on_current_branch():
    info = find_chat_model(_chat())

    assert info["model"] == "modelref::openai::personal::id:ee5e02db::hermes-agent"
    assert info["modelName"] == "hermes-agent | hermes"
    assert info["model_ref"]["connection_id"] == "ee5e02db"
    assert find_chat_model({"history": {"currentId": None, "messages": {}}}) is None


def test_append_follow_up_turn_links_messages_like_the_web_client():
    chat = _chat()
    prompt = "[后台任务完成] 运行 20260904-225602 已结束，请读取 result.md 并汇报。"

    user_id, assistant_id = append_follow_up_turn(chat, prompt, find_chat_model(chat), now=42)

    messages = chat["history"]["messages"]
    assert chat["history"]["currentId"] == assistant_id
    assert messages["a1"]["childrenIds"] == [user_id]
    assert messages[user_id] == {
        "id": user_id,
        "parentId": "a1",
        "childrenIds": [assistant_id],
        "role": "user",
        "content": prompt,
        "timestamp": 42,
    }
    placeholder = messages[assistant_id]
    assert placeholder["parentId"] == user_id
    assert placeholder["role"] == "assistant"
    assert placeholder["content"] == ""
    assert placeholder["done"] is False
    assert placeholder["model"] == "modelref::openai::personal::id:ee5e02db::hermes-agent"
    assert placeholder["modelName"] == "hermes-agent | hermes"
    assert placeholder["model_ref"]["connection_id"] == "ee5e02db"


def test_append_follow_up_turn_on_empty_chat_starts_a_root_branch():
    chat = {"history": {"currentId": None, "messages": {}}}

    user_id, assistant_id = append_follow_up_turn(
        chat, "hello", {"model": "hermes-agent"}, now=1
    )

    assert chat["history"]["messages"][user_id]["parentId"] is None
    assert chat["history"]["messages"][assistant_id]["modelName"] == "hermes-agent"
    assert chat["history"]["currentId"] == assistant_id


def test_build_conversation_messages_drops_tool_details_and_placeholder():
    chat = _chat()
    _, assistant_id = append_follow_up_turn(chat, "follow-up", find_chat_model(chat), now=3)

    messages = build_conversation_messages(chat, assistant_id)

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "已启动 reclaude，运行 ID：20260904-225602"
    assert "<details" not in messages[1]["content"]
    assert messages[-1]["content"] == "follow-up"


def test_build_follow_up_form_data_matches_web_client_shape():
    form_data = build_follow_up_form_data(
        model_id="hermes-agent",
        messages=[{"role": "user", "content": "x"}],
        chat_id="chat-1",
        assistant_message_id="msg-1",
    )

    assert form_data["model"] == "hermes-agent"
    assert form_data["chat_id"] == "chat-1"
    assert form_data["id"] == "msg-1"
    assert form_data["stream"] is True
    assert form_data["session_id"].startswith("hermes-notify:")
    assert form_data["features"]["html_visual_surface"] == "halowebui-web"
    assert form_data["background_tasks"] == {
        "title_generation": False,
        "tags_generation": False,
        "follow_up_generation": False,
    }
    assert RELOAD_EVENT_TYPE == "chat:reload"
