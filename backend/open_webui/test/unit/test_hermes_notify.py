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


def test_append_report_turn_is_a_finished_reply():
    chat = _chat()
    model_info = find_chat_model(chat)
    user_id, assistant_id = hermes_notify.append_report_turn(
        chat, "[后台任务完成通知] reclaude 运行 r1 已结束", "✅ 报告正文", model_info, now=10
    )
    messages = chat["history"]["messages"]
    assert chat["history"]["currentId"] == assistant_id
    assert messages[user_id]["parentId"] == "a1"
    assert messages[user_id]["content"] == "[后台任务完成通知] reclaude 运行 r1 已结束"
    assert messages[assistant_id]["content"] == "✅ 报告正文"
    assert messages[assistant_id]["done"] is True
    assert messages[assistant_id]["completedAt"] == 10
    assert messages[assistant_id]["model"] == messages["a1"]["model"]
    # Shown as a system line, not as something the person said.
    assert messages[user_id]["hermes_notice"] == {"source": "runner"}


def test_report_notice_keeps_its_runner_and_run_id():
    chat = _chat()
    user_id, _ = hermes_notify.append_report_turn(
        chat, "[后台任务完成通知] codex 运行 r2 已结束", "✅", find_chat_model(chat),
        source="codex-runner", run_id="r2",
    )
    assert chat["history"]["messages"][user_id]["hermes_notice"] == {
        "source": "codex-runner",
        "run_id": "r2",
    }


def _patch_report_stack(monkeypatch, *, busy=False):
    import asyncio
    from types import SimpleNamespace

    from open_webui.utils import hermes_agent, hermes_unread, html_visual_prompt

    calls = {"saved": [], "events": [], "unread": [], "webhook": [], "designed": []}
    chat_row = SimpleNamespace(id="chat-1", user_id="user-1", chat=_chat())
    monkeypatch.setattr(hermes_notify.Chats, "get_chat_by_id", lambda _id: chat_row)
    monkeypatch.setattr(hermes_notify.Chats, "get_chat_title_by_id", lambda _id: "标题")
    monkeypatch.setattr(
        hermes_notify.Chats,
        "update_chat_by_id",
        lambda chat_id, chat, **_kw: calls["saved"].append(chat) or chat_row,
    )
    monkeypatch.setattr(
        hermes_notify.Users, "get_user_by_id", lambda _id: SimpleNamespace(id="user-1")
    )
    # Only blocking tasks count: a finished reply's post-processing must not hold a notice.
    monkeypatch.setattr(
        hermes_notify,
        "list_task_ids_by_chat_id",
        lambda _id, blocks_completion_only=False: (
            ["task"] if busy or not blocks_completion_only else []
        ),
    )

    async def emitter(event):
        calls["events"].append(event)

    monkeypatch.setattr(hermes_notify, "get_event_emitter", lambda _meta, update_db=True: emitter)
    monkeypatch.setattr(hermes_unread, "mark_unread", lambda chat_id, user_id: calls["unread"].append(chat_id))
    monkeypatch.setattr(
        hermes_agent,
        "_schedule_completion_webhook",
        lambda request, user, metadata, title, content: calls["webhook"].append((title, content)),
    )

    async def fake_design(content, metadata):
        calls["designed"].append(metadata)
        return content

    monkeypatch.setattr(html_visual_prompt, "design_html_visual_artifact_with_agy", fake_design)
    monkeypatch.setattr(html_visual_prompt, "append_html_visual_fallback", lambda content, _m: content)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("display mode must not start a model turn")

    monkeypatch.setattr(hermes_notify, "start_follow_up_turn", forbidden)
    return calls, asyncio


def test_show_notification_report_saves_announces_and_starts_no_turn(monkeypatch):
    calls, asyncio = _patch_report_stack(monkeypatch)

    async def run():
        result = await hermes_notify.show_notification_report(
            object(), chat_id="chat-1", content="✅ 报告", notice="[后台任务完成通知] x", source="reclaude-runner"
        )
        await asyncio.sleep(0)  # let the design task run
        await asyncio.gather(*hermes_notify._REPORT_DESIGN_TASKS)
        return result

    result = asyncio.run(run())
    saved = calls["saved"][-1]["history"]
    assert saved["messages"][result["assistant_message_id"]]["content"] == "✅ 报告"
    assert saved["messages"][result["user_message_id"]]["content"] == "[后台任务完成通知] x"
    assert calls["events"][0]["type"] == RELOAD_EVENT_TYPE
    assert calls["unread"] == ["chat-1"]
    assert calls["webhook"] == [("标题", "✅ 报告")]
    assert calls["designed"][0]["server_surface"] == "halowebui-web"


def test_show_notification_report_respects_a_busy_chat(monkeypatch):
    import pytest

    calls, asyncio = _patch_report_stack(monkeypatch, busy=True)
    with pytest.raises(hermes_notify.HermesNotifyError) as error:
        asyncio.run(hermes_notify.show_notification_report(object(), chat_id="chat-1", content="x"))
    assert error.value.status_code == 409
    assert calls["saved"] == []
