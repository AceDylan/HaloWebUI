import asyncio
import html
import itertools
import json
from types import SimpleNamespace

import pytest

from open_webui.utils import hermes_agent
from open_webui.utils import middleware


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_agent, "DATA_DIR", tmp_path)
    monkeypatch.setattr(hermes_agent, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(hermes_agent, "RECOVERY_POLL_DELAYS", (0,))
    monkeypatch.setattr(hermes_agent, "START_RETRY_MIN_DELAY", 0)
    monkeypatch.setattr(hermes_agent, "mark_unread", lambda *_args: None)
    monkeypatch.setattr(
        hermes_agent, "_schedule_completion_webhook", lambda *_args, **_kwargs: None
    )

    async def no_design(content, _metadata):
        return content

    monkeypatch.setattr(hermes_agent, "design_html_visual_artifact_with_agy", no_design)
    monkeypatch.setattr(
        hermes_agent, "append_html_visual_fallback", lambda content, _metadata: content
    )
    hermes_agent._HOST_DATA_DIR_CACHE.clear()
    yield
    hermes_agent._HOST_DATA_DIR_CACHE.clear()


# ------------------------------------------------------------ history replay


def test_follow_up_history_drops_the_visual_card_and_keeps_one_line_per_tool():
    card = "````html\n<div style='padding:8px'>" + "x" * 5000 + "</div>\n````"
    result = html.escape(json.dumps({"status": "success", "duration": 21.4}))
    failed = html.escape(json.dumps({"status": "error", "duration": 0.2}))
    assistant = (
        "我先看看仓库。\n"
        f'<tool_calls name="terminal" input="git status" result="{result}"/>\n'
        f'<tool_calls name="read_file" input="README.md" result="{failed}"/>\n'
        f"结论：一切正常。\n\n{card}"
    )
    payload = hermes_agent._build_run_payload(
        {
            "messages": [
                {"role": "user", "content": "看看仓库"},
                {"role": "assistant", "content": assistant},
                {"role": "user", "content": "继续"},
            ]
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )

    replayed = payload["conversation_history"][1]["content"]
    assert "xxxx" not in replayed
    assert hermes_agent.HTML_CARD_PLACEHOLDER in replayed
    assert "[工具调用 ×2]" in replayed
    assert "- terminal: git status（成功，21s）" in replayed
    assert "- read_file: README.md（失败，0.2s）" in replayed
    assert "结论：一切正常。" in replayed
    # The user's own words are never rewritten.
    assert payload["conversation_history"][0]["content"] == "看看仓库"


def test_history_reads_the_command_from_hermes_details_blocks():
    arguments = html.escape(json.dumps({"input": "npm test"}))
    content = (
        f'<details type="tool_calls" done="false" id="h-1" name="terminal" '
        f'arguments="{arguments}">\n<summary>Executing...</summary>\n</details>\n'
        '<details type="reasoning" done="true"><summary>t</summary>secret</details>'
    )
    compact = hermes_agent._compact_assistant_history(content)
    assert "terminal: npm test（未完成）" in compact
    assert "secret" not in compact


def test_long_tool_runs_are_elided_in_the_middle():
    result = html.escape(json.dumps({"status": "success", "duration": 1}))
    content = "\n".join(
        f'<tool_calls name="terminal" input="step {index}" result="{result}"/>'
        for index in range(60)
    )
    compact = hermes_agent._compact_assistant_history(content)
    assert "[工具调用 ×60]" in compact
    assert "step 0（" in compact and "step 59（" in compact
    assert "省略 36 次工具调用" in compact


# ------------------------------------------------------------ run options


def test_dispatch_option_prefixes_the_runner_command():
    payload = hermes_agent._build_run_payload(
        {
            "messages": [{"role": "user", "content": "修复登录页"}],
            "hermes_options": {"dispatch": "reclaude"},
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["input"] == "/reclaude 修复登录页"


def test_a_typed_slash_command_wins_over_the_dispatch_option():
    payload = hermes_agent._build_run_payload(
        {
            "messages": [{"role": "user", "content": "/codex 修复登录页"}],
            "hermes_options": {"dispatch": "reclaude"},
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["input"] == "/codex 修复登录页"


def test_model_option_and_the_chats_thinking_level_reach_hermes():
    payload = hermes_agent._build_run_payload(
        {
            "messages": [{"role": "user", "content": "hi"}],
            # The chat's thinking level, lifted from params by the middleware.
            "reasoning_effort": "HIGH",
            "hermes_options": {
                "model": "claude-opus-5",
                "provider": "anthropic",
                "dispatch": "nonsense",
            },
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["model"] == "claude-opus-5"
    assert payload["provider"] == "anthropic"
    assert payload["model_options"] == {"reasoning_effort": "high"}
    assert payload["input"] == "hi"


def test_thinking_turned_off_in_the_chat_turns_it_off_for_hermes():
    payload = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "none"},
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["model_options"] == {"reasoning_effort": "none"}


def test_the_hermes_panel_no_longer_sets_the_thinking_level():
    # Composer states saved before the panel lost its 思考强度 row.
    payload = hermes_agent._build_run_payload(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "hermes_options": {"reasoning_effort": "low"},
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert "model_options" not in payload


def test_without_options_the_gateway_default_model_is_used():
    payload = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "turbo"},
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["model"] == "hermes-agent"
    assert "provider" not in payload and "model_options" not in payload


def test_attached_documents_are_handed_over_by_host_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_AGENT_HOST_DATA_DIR", "/srv/halo-data")
    record = SimpleNamespace(
        path=f"{tmp_path}/uploads/f1_report.pdf", user_id="user-1", filename="report.pdf"
    )
    other = SimpleNamespace(
        path=f"{tmp_path}/uploads/f2_x.pdf", user_id="someone-else", filename="x.pdf"
    )
    import open_webui.models.files as files_module

    monkeypatch.setattr(
        files_module.Files,
        "get_file_by_id",
        lambda file_id: {"f1": record, "f2": other}.get(file_id),
    )
    payload = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "总结一下"}]},
        {
            "chat_id": "chat-1",
            "files": [
                {"type": "file", "id": "f1", "name": "report.pdf"},
                {"type": "file", "id": "f2", "name": "x.pdf"},
                {
                    "type": "file",
                    "id": "f3",
                    "file": {"meta": {"content_type": "image/png"}},
                },
            ],
        },
        "hermes-agent",
        SimpleNamespace(id="user-1", role="user"),
    )
    assert payload["input"].startswith("总结一下\n\n[附件原文件]")
    assert "- report.pdf: /srv/halo-data/uploads/f1_report.pdf" in payload["input"]
    assert "x.pdf" not in payload["input"]


def test_host_data_dir_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("HERMES_AGENT_HOST_DATA_DIR", "off")
    assert hermes_agent._host_data_dir() is None


# ------------------------------------------------------------ tool settling


def test_unfinished_tools_of_a_failed_run_are_marked_interrupted():
    blocks = [
        {"type": "tool", "id": "h-0", "name": "terminal", "preview": "sleep 99",
         "done": False, "started_at": 100.0},
        {"type": "tool", "id": "h-1", "name": "read_file", "preview": "a",
         "done": True, "duration": 0.5},
    ]
    assert hermes_agent._settle_unfinished_tools(
        blocks, interrupted=True, reason="网关重启"
    ) == 1
    content = hermes_agent._serialize_blocks(blocks)
    assert 'done="false"' not in content
    assert 'started="100.0"' in content
    assert html.escape('"status": "interrupted"') in content
    assert html.escape('"reason": "网关重启"') in content


def test_unfinished_tools_of_a_completed_run_get_no_made_up_status():
    blocks = [{"type": "tool", "id": "h-0", "name": "terminal", "done": False}]
    hermes_agent._settle_unfinished_tools(blocks, interrupted=False)
    content = hermes_agent._serialize_blocks(blocks)
    assert 'done="true"' in content
    assert "status" not in html.unescape(content)


def test_saved_markup_is_settled_after_a_restart():
    content = hermes_agent._serialize_blocks(
        [{"type": "tool", "id": "h-0", "name": "terminal", "preview": "ls", "done": False}]
    )
    settled = hermes_agent._settle_unfinished_tool_markup(content, "重启")
    assert 'done="true"' in settled and "Executing" not in settled
    assert html.escape('"status": "interrupted"') in settled


def test_recovered_answer_replaces_its_streamed_start():
    content = '<details type="tool_calls" done="true"></details>\n结论：部'
    merged = hermes_agent._merge_recovered_output(content, "结论：部署完成。")
    assert merged.endswith("结论：部署完成。")
    assert merged.count("结论") == 1
    assert hermes_agent._merge_recovered_output("开头", "全新的回答").endswith("全新的回答")


def test_approval_descriptions_are_shown_in_chinese():
    assert hermes_agent._approval_description_zh("recursive delete") == "递归删除"
    assert (
        hermes_agent._approval_description_zh("git force push (rewrites remote history)")
        == "git 强制推送（改写远程历史）"
    )
    assert hermes_agent._approval_description_zh("brand new thing") == "危险操作：brand new thing"


def test_start_failure_messages_are_in_chinese():
    body = json.dumps({"error": {"message": "Too many concurrent runs (max 4)"}})
    assert "同时运行的任务已达上限" in hermes_agent._describe_start_failure(429, body)
    assert "HTTP 500" in hermes_agent._describe_start_failure(500, "boom")


def test_generated_files_are_stored_and_linked(monkeypatch):
    stored = []

    def fake_store(_request, _user, _metadata, name, data, content_type):
        stored.append((name, data, content_type))
        return "/api/v1/files/new-id/content"

    monkeypatch.setattr(hermes_agent, "_store_generated_file", fake_store)
    text = "报告在这里：[report.pdf](data:application/pdf;base64,SGVsbG8=)\n![image](data:image/png;base64,AAAA)"
    result = hermes_agent._store_data_url_files(None, None, {}, text)
    assert "[report.pdf](/api/v1/files/new-id/content)" in result
    assert "![image](data:image/png;base64,AAAA)" in result
    assert stored == [("report.pdf", b"Hello", "application/pdf")]


# ------------------------------------------------------------ in-flight registry


def test_inflight_registry_round_trip():
    hermes_agent._remember_inflight("chat-1", {"run_id": "run-1"})
    hermes_agent._remember_inflight("chat-2", {"run_id": "run-2"})
    hermes_agent._forget_inflight("chat-1", "other-run")
    assert set(hermes_agent._load_inflight()) == {"chat-1", "chat-2"}
    hermes_agent._forget_inflight("chat-1", "run-1")
    assert set(hermes_agent._load_inflight()) == {"chat-2"}


# ------------------------------------------------------------ live run harness


class _Content:
    def __init__(self, events, error=None):
        self.lines = [f"data: {json.dumps(event)}\n".encode() for event in events]
        self.error = error

    async def readline(self):
        if self.lines:
            return self.lines.pop(0)
        if self.error is not None:
            raise self.error
        return b""


class _Response:
    def __init__(self, *, payload=None, events=None, status=200, headers=None, error=None):
        self.payload = payload if payload is not None else {}
        self.status = status
        self.headers = headers or {}
        self.content = _Content(events or [], error)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return self.payload

    async def text(self):
        return json.dumps(self.payload)


class _Hermes:
    """A scripted hermes: POST answers, an event stream, then status polls."""

    def __init__(self, *, starts=None, events=None, stream_error=None, statuses=None,
                 session_messages=None):
        self.starts = list(starts or [_Response(payload={"run_id": "run-1"})])
        self.events = events or []
        self.stream_error = stream_error
        self.statuses = list(statuses or [])
        self.session_messages = session_messages
        self.posts = []
        self.gets = []

    def session(self, **_kwargs):
        return _Session(self)


class _Session:
    def __init__(self, hermes):
        self.hermes = hermes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.hermes.posts.append((url, kwargs))
        if url.endswith("/runs"):
            return self.hermes.starts.pop(0)
        return _Response(payload={})

    def get(self, url, **kwargs):
        self.hermes.gets.append(url)
        if url.endswith("/events"):
            return _Response(events=self.hermes.events, error=self.hermes.stream_error)
        if "/api/sessions/" in url:
            return _Response(payload=self.hermes.session_messages or {"data": []})
        status = self.hermes.statuses.pop(0) if self.hermes.statuses else (404, {})
        code, body = status
        return _Response(payload=body, status=code)


def _run(monkeypatch, hermes, content="hi", form_extra=None):
    emitted, upserts, created = [], [], {}

    async def event_emitter(event):
        emitted.append(event)

    async def background_tasks_handler(*_args, **_kwargs):
        return None

    def create_task(coroutine, id=None):
        created["coroutine"] = coroutine
        return "task-1", SimpleNamespace()

    monkeypatch.setattr(
        hermes_agent,
        "_resolve_hermes_connection",
        lambda *_args: ("http://hermes.test/v1", "", "hermes-agent"),
    )
    monkeypatch.setattr(
        hermes_agent, "_materialize_run_input_image_refs", lambda payload, **_kwargs: payload
    )
    monkeypatch.setattr(hermes_agent, "get_event_emitter", lambda _metadata: event_emitter)
    monkeypatch.setattr(hermes_agent, "get_event_call", lambda _metadata: object())
    monkeypatch.setattr(hermes_agent, "create_task", create_task)
    monkeypatch.setattr(hermes_agent.aiohttp, "ClientSession", hermes.session)
    monkeypatch.setattr(hermes_agent.Chats, "get_chat_title_by_id", lambda _chat_id: "Chat")
    monkeypatch.setattr(
        hermes_agent.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda chat_id, message_id, payload, **kwargs: upserts.append(payload),
    )
    monkeypatch.setattr(middleware, "background_tasks_handler", background_tasks_handler)
    metadata = {
        "session_id": "session-1",
        "chat_id": "chat-1",
        "message_id": "assistant-1",
        "features": {},
    }
    asyncio.run(
        hermes_agent.run_hermes_agent(
            SimpleNamespace(),
            {
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": content}],
                **(form_extra or {}),
            },
            SimpleNamespace(id="user-1", role="user"),
            metadata,
            {"id": "hermes-agent"},
            [],
            {},
        )
    )
    asyncio.run(created["coroutine"])
    final = [
        event["data"]
        for event in emitted
        if event.get("type") == "chat:completion" and event["data"].get("done")
    ]
    return final[-1], emitted, upserts


def _statuses(emitted):
    return [event["data"] for event in emitted if event.get("type") == "status"]


def test_a_dropped_stream_waits_for_the_run_and_keeps_the_answer(monkeypatch):
    hermes = _Hermes(
        events=[
            {"event": "tool.started", "tool": "terminal", "preview": "make deploy",
             "timestamp": 1000.0},
        ],
        statuses=[
            (200, {"status": "running"}),
            (200, {"status": "completed", "output": "部署完成。", "usage": {"input_tokens": 3}}),
        ],
    )
    final, emitted, _ = _run(monkeypatch, hermes)

    assert final["content"].endswith("部署完成。")
    assert 'done="false"' not in final["content"]
    assert "error" not in final
    assert final["usage"]["prompt_tokens"] == 3
    descriptions = [status["description"] for status in _statuses(emitted)]
    assert hermes_agent.RECOVERY_MESSAGES["waiting"] in descriptions
    assert hermes.posts[0][1]["headers"]["Idempotency-Key"] == "halowebui-assistant-1"
    # The run is no longer owed to the chat once the reply is closed.
    assert hermes_agent._load_inflight() == {}


def test_a_connection_error_mid_stream_is_not_the_end_of_the_run(monkeypatch):
    hermes = _Hermes(
        events=[{"event": "message.delta", "delta": "结论：部"}],
        stream_error=hermes_agent.aiohttp.ClientPayloadError("payload not completed"),
        statuses=[(200, {"status": "completed", "output": "结论：部署完成。"})],
    )
    final, _, _ = _run(monkeypatch, hermes)
    assert final["content"] == "结论：部署完成。"


def test_a_gateway_restart_reports_the_run_as_interrupted(monkeypatch):
    hermes = _Hermes(
        events=[{"event": "tool.started", "tool": "terminal", "preview": "sleep 60"}],
        statuses=[(None, None), (200, {"status": "interrupted"})],
    )
    final, _, _ = _run(monkeypatch, hermes)
    assert final["error"]["content"] == hermes_agent.RECOVERY_MESSAGES["interrupted"]
    assert html.escape('"status": "interrupted"') in final["content"]


def test_a_forgotten_run_is_recovered_from_its_session(monkeypatch):
    hermes = _Hermes(
        events=[],
        statuses=[(404, {})],
        session_messages={
            "data": [
                {"role": "assistant", "content": "会话里的最终答复", "timestamp": 4102444800},
                {"role": "user", "content": "hi", "timestamp": 1},
            ]
        },
    )
    final, _, _ = _run(monkeypatch, hermes)
    assert final["content"] == "会话里的最终答复"
    assert "error" not in final


def test_a_forgotten_run_without_an_answer_says_so(monkeypatch):
    hermes = _Hermes(events=[], statuses=[(404, {})])
    final, _, _ = _run(monkeypatch, hermes)
    assert final["error"]["content"] == hermes_agent.RECOVERY_MESSAGES["lost"]


def test_a_busy_gateway_is_retried_before_giving_up(monkeypatch):
    hermes = _Hermes(
        starts=[
            _Response(status=429, payload={"error": {"message": "Too many"}},
                      headers={"Retry-After": "0"}),
            _Response(payload={"run_id": "run-1"}),
        ],
        events=[{"event": "run.completed", "output": "ok"}],
    )
    final, emitted, _ = _run(monkeypatch, hermes)
    assert final["content"] == "ok"
    assert len([url for url, _ in hermes.posts if url.endswith("/runs")]) == 2
    assert any("自动重试" in status["description"] for status in _statuses(emitted))


def test_a_refused_start_is_explained_in_chinese(monkeypatch):
    hermes = _Hermes(starts=[_Response(status=500, payload={"error": {"message": "boom"}})])
    final, _, _ = _run(monkeypatch, hermes)
    assert final["error"]["content"] == "Hermes 启动任务失败（HTTP 500）：boom"


def test_an_approval_seen_only_while_polling_is_still_asked(monkeypatch):
    asked = []
    hermes = _Hermes(
        events=[],
        statuses=[
            (200, {"status": "waiting_for_approval",
                   "approval": {"request_id": "req-1", "command": "rm -rf build",
                                "description": "recursive delete", "choices": ["once", "deny"]}}),
            (200, {"status": "completed", "output": "done"}),
        ],
    )
    monkeypatch.setattr(hermes_agent, "_approval_target_sids", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(hermes_agent, "HERMES_AGENT_APPROVAL_TIMEOUT", 0)
    monkeypatch.setattr(hermes_agent, "APPROVAL_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(hermes_agent, "_schedule_approval_webhook",
                        lambda _r, _u, _m, approval: asked.append(approval))
    # 30s minimum timeout inside _request_approval: make time jump.
    clock = itertools.count(1_000_000, 100)
    monkeypatch.setattr(hermes_agent.time, "time", lambda: float(next(clock)))
    final, _, _ = _run(monkeypatch, hermes)
    assert final["content"] == "done"
    assert asked and asked[0]["description"] == "递归删除"
    approval_posts = [kwargs["json"] for url, kwargs in hermes.posts if url.endswith("/approval")]
    assert approval_posts == [{"choice": "deny"}]


def test_a_shutdown_keeps_the_run_for_the_next_start(monkeypatch):
    class _Hang(_Content):
        async def readline(self):
            if self.lines:
                return self.lines.pop(0)
            hermes_agent.begin_shutdown()
            raise asyncio.CancelledError()

    hermes = _Hermes(events=[{"event": "tool.started", "tool": "terminal", "preview": "x"}])
    original_get = _Session.get

    def get(self, url, **kwargs):
        response = original_get(self, url, **kwargs)
        if url.endswith("/events"):
            response.content = _Hang([{"event": "tool.started", "tool": "terminal"}])
        return response

    monkeypatch.setattr(_Session, "get", get)
    with pytest.raises(asyncio.CancelledError):
        _run(monkeypatch, hermes)
    assert not [url for url, _ in hermes.posts if url.endswith("/stop")]
    assert hermes_agent._load_inflight()["chat-1"]["run_id"] == "run-1"


def test_a_restart_finishes_the_reply_it_left_behind(monkeypatch):
    hermes_agent._remember_inflight(
        "chat-1",
        {"run_id": "run-1", "message_id": "assistant-1", "user_id": "user-1",
         "base_url": "http://hermes.test/v1", "started_at": 1.0},
    )
    saved = hermes_agent._serialize_blocks(
        [{"type": "text", "content": "开始"},
         {"type": "tool", "id": "h-1", "name": "terminal", "preview": "ls", "done": False}]
    )
    hermes = _Hermes(statuses=[(200, {"status": "completed", "output": "全部完成"})])
    emitted, upserts, created = [], [], []

    async def event_emitter(event):
        emitted.append(event)

    import open_webui.models.users as users_module

    monkeypatch.setattr(users_module.Users, "get_user_by_id",
                        lambda _id: SimpleNamespace(id="user-1", role="admin"))
    monkeypatch.setattr(hermes_agent.Chats, "get_message_by_id_and_message_id",
                        lambda *_args: {"content": saved, "done": False})
    monkeypatch.setattr(hermes_agent.Chats, "get_chat_title_by_id", lambda _chat_id: "Chat")
    monkeypatch.setattr(
        hermes_agent.Chats,
        "upsert_message_to_chat_by_id_and_message_id",
        lambda chat_id, message_id, payload, **kwargs: upserts.append(payload),
    )
    monkeypatch.setattr(hermes_agent, "get_event_emitter", lambda _metadata: event_emitter)
    monkeypatch.setattr(hermes_agent, "_api_key_for_base_url", lambda *_args: "")
    monkeypatch.setattr(hermes_agent.aiohttp, "ClientSession", hermes.session)
    monkeypatch.setattr(hermes_agent, "create_task",
                        lambda coroutine, id=None: created.append((id, coroutine)) or ("t", None))

    assert hermes_agent.resume_inflight_runs(SimpleNamespace()) == 1
    chat_id, coroutine = created[0]
    assert chat_id == "chat-1"
    asyncio.run(coroutine)

    final = upserts[-1]
    assert final["done"] is True
    assert final["content"].startswith("开始")
    assert final["content"].endswith("全部完成")
    assert 'done="false"' not in final["content"]
    assert final["hermes_run"]["recovered"] is True
    assert hermes_agent._load_inflight() == {}
    assert any(
        event.get("type") == "chat:completion" and event["data"].get("done")
        for event in emitted
    )


# ------------------------------------------------------------ round 2: dispatch, model, tools


def test_a_path_is_not_a_command():
    payload = hermes_agent._build_run_payload(
        {
            "messages": [{"role": "user", "content": "/root/app/x.txt 里的报错看一下"}],
            "hermes_options": {"dispatch": "reclaude"},
        },
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert payload["input"] == "/reclaude /root/app/x.txt 里的报错看一下"
    assert payload["dispatch"] == {"runner": "reclaude"}


def test_a_typed_runner_command_is_sent_as_dispatch(monkeypatch):
    form = {"messages": [{"role": "user", "content": "/codex 修复登录页"}]}
    payload = hermes_agent._build_run_payload(form, {"chat_id": "chat-1"}, "hermes-agent")
    assert payload["dispatch"] == {"runner": "codex"}
    plain = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "/model 看看"}]}, {"chat_id": "c"}, "hermes-agent"
    )
    assert "dispatch" not in plain
    monkeypatch.setattr(hermes_agent, "HERMES_AGENT_FAST_DISPATCH", False)
    payload = hermes_agent._build_run_payload(form, {"chat_id": "chat-1"}, "hermes-agent")
    assert "dispatch" not in payload and payload["input"] == "/codex 修复登录页"


def test_a_runner_launch_records_who_answered_and_gets_no_card(monkeypatch):
    designed = []

    async def design(content, _metadata):
        designed.append(content)
        return content

    monkeypatch.setattr(hermes_agent, "design_html_visual_artifact_with_agy", design)
    hermes = _Hermes(
        events=[
            {"event": "tool.started", "tool": "terminal", "tool_call_id": "c1",
             "preview": "/root/.hermes/scripts/reclaude-run.sh run --detach --cwd /root --task-file t.md"},
            {"event": "tool.completed", "tool": "terminal", "tool_call_id": "c1", "duration": 3.2},
            {"event": "message.delta", "delta": "reclaude 已启动"},
            {"event": "run.completed", "output": "reclaude 已启动", "model_used": "deepseek-chat",
             "provider_used": "custom", "fallback_from": "gemini-chat"},
        ]
    )
    final, _emitted, _ = _run(
        monkeypatch,
        hermes,
        "修复登录页",
        {"hermes_options": {"dispatch": "reclaude", "model": "gemini-chat"}},
    )
    run = final["hermes_run"]
    assert run["dispatch"] == "reclaude"
    assert run["requested_model"] == "gemini-chat"
    assert run["model"] == "deepseek-chat" and run["fallback_from"] == "gemini-chat"
    assert designed == []
    started = json.loads(json.dumps(hermes.posts[0][1]["json"]))
    assert started["dispatch"] == {"runner": "reclaude"}


def test_a_fast_dispatch_is_recorded(monkeypatch):
    hermes = _Hermes(
        events=[
            {"event": "message.delta", "delta": "codex 已启动"},
            {"event": "run.completed", "output": "codex 已启动",
             "dispatch": {"runner": "codex", "run_id": "20260926-1", "fast": True}},
        ]
    )
    final, _emitted, _ = _run(monkeypatch, hermes, "/codex 看看")
    assert final["hermes_run"]["fast_dispatch"] is True
    assert final["hermes_run"]["runner_run_id"] == "20260926-1"
    assert final["hermes_run"]["dispatch"] == "codex"


def test_a_follow_up_goes_back_to_its_run_as_typed():
    run_id = "20260927-005655-f2dd355f"
    options = {"dispatch": "reclaude", "continue_run": run_id}
    payload = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "多久观察一次？"}], "hermes_options": options},
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    # No /reclaude in front: that would be a new task.
    assert payload["input"] == "多久观察一次？"
    assert payload["dispatch"] == {"runner": "reclaude", "continue_run": run_id}
    # A typed command is a new task, whatever the panel said.
    typed = hermes_agent._build_run_payload(
        {"messages": [{"role": "user", "content": "/codex 新任务"}], "hermes_options": options},
        {"chat_id": "chat-1"},
        "hermes-agent",
    )
    assert typed["input"] == "/codex 新任务" and typed["dispatch"] == {"runner": "codex"}
    # Only a run id is passed on; without a dispatch there is nothing to continue.
    for bad in (
        {"dispatch": "reclaude", "continue_run": "../../etc/passwd"},
        {"dispatch": "reclaude", "continue_run": "20260927-005655-f2dd355f; rm -rf /"},
    ):
        assert "continue_run" not in hermes_agent._hermes_run_options({"hermes_options": bad})
    assert hermes_agent._hermes_run_options(
        {"hermes_options": {"continue_run": run_id}}
    ) == {}
    assert hermes_agent._hermes_run_options(
        {"hermes_options": {"dispatch": "codex", "continue_run": f"{run_id}-a1"}}
    ) == {"dispatch": "codex", "continue_run": f"{run_id}-a1"}


def test_a_continued_run_is_recorded(monkeypatch):
    hermes = _Hermes(
        events=[
            {"event": "message.delta", "delta": "已交回 reclaude 上次的任务继续"},
            {"event": "run.completed", "output": "已交回 reclaude 上次的任务继续",
             "dispatch": {"runner": "reclaude", "run_id": "20260927-1-a1", "fast": True,
                          "continued_from": "20260927-1"}},
        ]
    )
    final, _emitted, _ = _run(
        monkeypatch,
        hermes,
        "多久观察一次？",
        {"hermes_options": {"dispatch": "reclaude", "continue_run": "20260927-005655-f2dd355f"}},
    )
    run = final["hermes_run"]
    assert run["continued_from"] == "20260927-1" and run["runner_run_id"] == "20260927-1-a1"
    assert run["dispatch"] == "reclaude" and run["fast_dispatch"] is True
    started = json.loads(json.dumps(hermes.posts[0][1]["json"]))
    assert started["input"] == "多久观察一次？"
    assert started["dispatch"] == {
        "runner": "reclaude",
        "continue_run": "20260927-005655-f2dd355f",
    }


def test_parallel_calls_of_one_tool_close_by_their_call_id(monkeypatch):
    hermes = _Hermes(
        events=[
            {"event": "tool.started", "tool": "terminal", "tool_call_id": "a", "preview": "sleep 9"},
            {"event": "tool.started", "tool": "terminal", "tool_call_id": "b", "preview": "false"},
            {"event": "tool.completed", "tool": "terminal", "tool_call_id": "b", "duration": 0.1,
             "error": True},
            {"event": "tool.completed", "tool": "terminal", "tool_call_id": "a", "duration": 9.0},
            {"event": "run.completed", "output": "好了"},
        ]
    )
    final, _emitted, _ = _run(monkeypatch, hermes)
    first, second = final["content"].split("</details>")[:2]
    assert "sleep 9" in first and "&quot;success&quot;" in first
    assert "false" in second and "&quot;error&quot;" in second


def test_a_model_fallback_is_said_while_the_run_goes(monkeypatch):
    hermes = _Hermes(
        events=[
            {"event": "run.model_fallback", "from_model": "gemini-chat", "to_model": "deepseek-chat",
             "to_provider": "custom"},
            {"event": "run.completed", "output": "答复"},
        ]
    )
    final, emitted, _ = _run(monkeypatch, hermes)
    assert "gemini-chat 不可用，已改用 deepseek-chat" in [
        status["description"] for status in _statuses(emitted)
    ]
    assert final["hermes_run"]["fallback_from"] == "gemini-chat"
    assert final["hermes_run"]["model"] == "deepseek-chat"


def test_streamed_text_is_coalesced_but_complete(monkeypatch):
    monkeypatch.setattr(hermes_agent, "HERMES_AGENT_STREAM_EMIT_INTERVAL", 60.0)
    deltas = [{"event": "message.delta", "delta": f"{index} "} for index in range(50)]
    hermes = _Hermes(events=[*deltas, {"event": "run.completed", "output": ""}])
    final, emitted, _ = _run(monkeypatch, hermes)
    content_updates = [
        event for event in emitted
        if event.get("type") == "chat:completion" and set(event["data"]) == {"content"}
    ]
    # The first delta goes out at once, the other 49 wait for the next interval,
    # which the end of the run closes: the final reply carries all of them.
    assert len(content_updates) == 1
    assert final["content"] == " ".join(str(index) for index in range(50))
