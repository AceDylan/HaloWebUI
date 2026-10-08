"""总结后在新对话继续: the transcript keeps the newest messages that fit, and the
new chat starts with the request and the summary on a valid one-branch history."""

from open_webui.utils.chat_handoff import (
    branch_messages,
    build_handoff_chat,
    build_transcript,
    estimate_tokens,
    handoff_request_messages,
)


def _msg(id, parent, role, content, children=()):
    return {"id": id, "parentId": parent, "childrenIds": list(children), "role": role, "content": content}


def _chat():
    return {
        "title": "部署问题",
        "models": ["gpt-x"],
        "params": {"temperature": 0.3},
        "history": {
            "currentId": "a2",
            "messages": {
                "u1": _msg("u1", None, "user", "nginx 起不来", ["a1", "a1b"]),
                "a1": _msg("a1", "u1", "assistant", '<details type="reasoning">想</details>看下日志', ["u2"]),
                "a1b": _msg("a1b", "u1", "assistant", "另一个分支"),
                "u2": _msg("u2", "a1", "user", "端口 80 被占用", ["a2"]),
                "a2": _msg("a2", "u2", "assistant", "停掉 apache2 再启动"),
            },
        },
    }


def test_branch_on_screen_oldest_first():
    assert [m["id"] for m in branch_messages(_chat())] == ["u1", "a1", "u2", "a2"]


def test_transcript_has_the_branch_without_reasoning():
    transcript, omitted = build_transcript(branch_messages(_chat()), 128_000)

    assert omitted == 0
    assert transcript.splitlines()[0] == "用户：nginx 起不来"
    assert "助手：看下日志" in transcript
    assert "想" not in transcript and "另一个分支" not in transcript


def test_oldest_messages_are_left_out_when_they_do_not_fit():
    messages = [
        _msg(f"m{i}", None, "user" if i % 2 == 0 else "assistant", f"{i} " + "字" * 4000)
        for i in range(10)
    ]
    # 0.7 × 20k tokens leaves room for three 4k-token messages.
    transcript, omitted = build_transcript(messages, 20_000)

    assert omitted == 7
    assert transcript.startswith("助手：7 ")
    assert transcript.rstrip().endswith("字")
    assert "用户：0 " not in transcript
    assert "（更早的 7 条消息" in handoff_request_messages(transcript, omitted)[0]["content"]


def test_the_newest_message_is_kept_even_when_it_alone_is_too_long():
    transcript, omitted = build_transcript([_msg("u", None, "user", "x" * 200_000)], 1_000)
    assert omitted == 0
    assert "中间省略" in transcript


def test_estimate_counts_cjk_as_a_token_each():
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("abcd" * 10) == 10


def test_new_chat_starts_with_the_request_and_the_summary():
    chat = build_handoff_chat(_chat(), "src-1", "目标：修 nginx", "gpt-x", now=1_700_000_000)

    history = chat["history"]
    reply = history["messages"][history["currentId"]]
    request = history["messages"][reply["parentId"]]
    assert request["parentId"] is None and request["childrenIds"] == [reply["id"]]
    assert request["role"] == "user" and "「部署问题」" in request["content"]
    assert reply["role"] == "assistant" and reply["content"] == "目标：修 nginx"
    assert reply["model"] == "gpt-x" and reply["done"] is True
    assert [m["id"] for m in chat["messages"]] == [request["id"], reply["id"]]
    assert chat["title"] == "部署问题（续）"
    assert chat["models"] == ["gpt-x"] and chat["params"] == {"temperature": 0.3}
    assert chat["handoffFrom"] == {"chatId": "src-1", "title": "部署问题"}


def test_endpoint_opens_a_new_chat_in_the_same_folder(monkeypatch):
    import asyncio
    import uuid
    from types import SimpleNamespace

    from open_webui.models.chats import ChatForm, Chats
    from open_webui.models.folders import Folders
    from open_webui.routers import tasks

    user_id = f"handoff-{uuid.uuid4().hex[:8]}"
    folder = Folders.insert_new_folder(user_id, "运维")
    source = Chats.insert_new_chat(user_id, ChatForm(chat=_chat()))
    Chats.update_chat_folder_id_by_id_and_user_id(source.id, user_id, folder.id)

    seen = {}

    async def fake_models(request, user):
        return {"gpt-x": {"id": "gpt-x", "name": "gpt-x", "owned_by": "openai"}}

    async def fake_completion(request, form_data, user):
        seen["payload"] = form_data
        return {"choices": [{"message": {"role": "assistant", "content": "目标：修 nginx"}}]}

    monkeypatch.setattr(tasks, "_get_request_models", fake_models)
    monkeypatch.setattr(tasks, "generate_chat_completion", fake_completion)
    request = SimpleNamespace(state=SimpleNamespace(), app=SimpleNamespace(state=SimpleNamespace(config=None)))

    result = asyncio.run(
        tasks.create_chat_handoff(
            request,
            tasks.ChatHandoffForm(chat_id=source.id, model="gpt-x", context_tokens=128_000),
            user=SimpleNamespace(id=user_id),
        )
    )

    assert seen["payload"]["model"] == "gpt-x"
    assert "停掉 apache2 再启动" in seen["payload"]["messages"][0]["content"]
    new_chat = Chats.get_chat_by_id_and_user_id(result["id"], user_id)
    assert new_chat.folder_id == folder.id
    assert new_chat.title == "部署问题（续）"
    current = new_chat.chat["history"]["currentId"]
    assert new_chat.chat["history"]["messages"][current]["content"] == "目标：修 nginx"
