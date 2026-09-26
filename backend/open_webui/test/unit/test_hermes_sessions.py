import asyncio
import json
from types import SimpleNamespace

import pytest

from open_webui.utils.hermes_sessions import (
    HermesSessionsError,
    build_chat_payload,
    fold_transcript,
    resolve_hermes_model,
    unwrap_session,
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


HERMES_SELECTION = "modelref::openai::personal::id:ee5e02db::hermes-agent"
CHAT_SELECTION = "modelref::openai::personal::id:c153e2d2::gpt-chat"


def _user_scoped_registry(monkeypatch):
    """Mirror get_all_models in this fork: fill request.state.MODELS (alias →
    model) and return the list; app.state.MODELS stays empty."""
    hermes = {"id": HERMES_SELECTION, "original_id": "hermes-agent", "name": "hermes-agent"}
    chat = {"id": CHAT_SELECTION, "original_id": "gpt-chat", "name": "gpt-chat"}

    async def fake_get_all_models(request, user=None):
        request.state.MODELS = {chat["id"]: chat, hermes["id"]: hermes, "hermes-agent": hermes}
        request.state.MODELS_AMBIGUOUS = set()
        return [chat, hermes]

    monkeypatch.setattr("open_webui.utils.models.get_all_models", fake_get_all_models)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(MODELS={})), state=SimpleNamespace()
    )
    return request, hermes, chat


def test_resolve_hermes_model_reads_the_user_scoped_registry(monkeypatch):
    request, hermes, _chat = _user_scoped_registry(monkeypatch)

    assert asyncio.run(resolve_hermes_model(request, user=None)) is hermes
    assert asyncio.run(resolve_hermes_model(request, None, model_id=HERMES_SELECTION)) is hermes
    assert asyncio.run(resolve_hermes_model(request, None, model_id="hermes-agent")) is hermes
    assert request.app.state.MODELS == {}  # never written to (cross-user leakage)


def test_resolve_hermes_model_rejects_non_hermes_and_unknown_ids(monkeypatch):
    request, _hermes, _chat = _user_scoped_registry(monkeypatch)

    with pytest.raises(HermesSessionsError) as exc:
        asyncio.run(resolve_hermes_model(request, None, model_id=CHAT_SELECTION))
    assert exc.value.status_code == 422

    with pytest.raises(HermesSessionsError) as exc:
        asyncio.run(resolve_hermes_model(request, None, model_id="nope"))
    assert exc.value.status_code == 422


def test_resolve_hermes_model_is_422_when_the_user_has_no_hermes_model(monkeypatch):
    async def fake_get_all_models(request, user=None):
        request.state.MODELS = {}
        request.state.MODELS_AMBIGUOUS = set()
        return [{"id": CHAT_SELECTION, "original_id": "gpt-chat"}]

    monkeypatch.setattr("open_webui.utils.models.get_all_models", fake_get_all_models)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), state=SimpleNamespace())
    with pytest.raises(HermesSessionsError) as exc:
        asyncio.run(resolve_hermes_model(request, user=None))
    assert exc.value.status_code == 422
    assert "no hermes agent model" in exc.value.detail


def test_unwrap_session_reads_every_envelope_hermes_uses():
    row = {"id": "s1", "source": "telegram"}
    assert unwrap_session({"object": "hermes.session", "session": row}) == row
    assert unwrap_session({"data": row}) == row
    assert unwrap_session(row) == row
    assert unwrap_session(None) == {}


def _stub_import_dependencies(monkeypatch, session_row):
    import open_webui.utils.hermes_sessions as hs

    urls = []

    async def fake_get_json(url, headers, params=None):
        urls.append(url)
        if url.endswith("/messages"):
            return {"object": "list", "data": _telegram_transcript()}
        # exactly what hermes answers GET /api/sessions/{id} with today
        return {"object": "hermes.session", "session": session_row}

    async def fake_resolve(request, user, model_id=None):
        return {"id": "hermes", "original_id": "hermes-agent"}

    inserted = {}

    def fake_insert(user_id, chat_id, payload, meta):
        inserted.update(user_id=user_id, chat_id=chat_id, payload=payload, meta=meta)
        return SimpleNamespace(id=chat_id, title=payload["title"])

    monkeypatch.setattr(hs, "_get_json", fake_get_json)
    monkeypatch.setattr(hs, "resolve_hermes_model", fake_resolve)
    monkeypatch.setattr(hs, "_connection", lambda request, user, model: ("http://hermes", {}))
    monkeypatch.setattr(hs.Chats, "get_chat_by_id_and_user_id", lambda chat_id, user_id: None)
    monkeypatch.setattr(hs.Chats, "get_chat_by_id", lambda chat_id: None)
    monkeypatch.setattr(hs, "_insert_chat_with_id", fake_insert)
    return hs, urls, inserted


def test_import_session_accepts_the_hermes_session_envelope(monkeypatch):
    sid = "20260905_085449_dd2e13cd"
    hs, urls, inserted = _stub_import_dependencies(
        monkeypatch, {"id": sid, "source": "telegram", "title": "Halowebui与Hermes新对话映射"}
    )

    result = asyncio.run(
        hs.import_session(SimpleNamespace(), SimpleNamespace(id="u1"), session_id=sid)
    )

    assert result["created"] is True
    assert result["imported_turns"] == 2
    assert inserted["chat_id"] == sid
    assert inserted["meta"][hs.HERMES_SESSION_META_KEY]["source"] == "telegram"
    assert urls[0].endswith(f"/api/sessions/{sid}")


def test_import_session_names_the_source_it_refuses(monkeypatch):
    hs, _urls, inserted = _stub_import_dependencies(
        monkeypatch, {"id": "cron_1", "source": "cron"}
    )

    with pytest.raises(HermesSessionsError) as e:
        asyncio.run(
            hs.import_session(SimpleNamespace(), SimpleNamespace(id="u1"), session_id="cron_1")
        )

    assert e.value.status_code == 400
    assert "cron" in e.value.detail
    assert inserted == {}


def test_model_options_offer_only_the_models_the_config_chooses():
    from open_webui.utils.hermes_sessions import condense_model_options

    relay_catalog = ["(LH)Grok 4.6", "[free]claude-opus-5", "gpt-chat", "zzz"]
    options = condense_model_options(
        {
            "model": "gpt-chat",
            "provider": "custom:relay",
            "providers": [
                {"slug": "nous", "name": "Nous", "authenticated": False, "models": ["x"]},
                # Found through ambient credentials, not configured.
                {"slug": "anthropic", "name": "Anthropic", "authenticated": True,
                 "is_user_defined": False, "models": ["claude-opus-5", "claude-sonnet-5"]},
                {"slug": "moa", "name": "MoA", "authenticated": True, "models": ["default"]},
                # `providers: custom: models: gpt-chat: ...` settings row.
                {"slug": "custom", "name": "custom", "authenticated": True,
                 "is_user_defined": True, "models": ["gpt-chat"]},
                # The current provider's list is re-probed: its whole catalog, sorted.
                {"slug": "custom:relay", "name": "relay", "authenticated": True,
                 "is_user_defined": True, "is_current": True, "models": relay_catalog},
                # Other entries list their selected model first, then the catalog.
                {"slug": "custom:deepseek-chat", "name": "deepseek-chat",
                 "authenticated": True, "is_user_defined": True,
                 "models": [{"id": "deepseek-chat"}, "[次]claude-opus-4-5", "gpt-chat"]},
                {"slug": "custom:claude-chat", "name": "claude-chat",
                 "authenticated": True, "is_user_defined": True, "models": ["claude-chat"]},
                {"slug": "custom:empty", "name": "empty", "authenticated": True,
                 "is_user_defined": True, "models": []},
            ],
        }
    )
    assert options["model"] == "gpt-chat"
    assert options["provider"] == "custom:relay"
    assert [(p["slug"], p["models"], p["current"]) for p in options["providers"]] == [
        ("custom:relay", ["gpt-chat"], True),
        ("custom:claude-chat", ["claude-chat"], False),
        ("custom:deepseek-chat", ["deepseek-chat"], False),
    ]


def test_model_options_keep_a_current_provider_hermes_did_not_mark_as_configured():
    from open_webui.utils.hermes_sessions import condense_model_options

    options = condense_model_options(
        {
            "model": "claude-opus-5",
            "provider": "anthropic",
            "providers": [
                {"slug": "anthropic", "name": "Anthropic", "authenticated": True,
                 "is_current": True, "models": ["claude-sonnet-5", "claude-opus-5"]},
            ],
        }
    )
    assert options["providers"] == [
        {"slug": "anthropic", "name": "Anthropic", "current": True, "models": ["claude-opus-5"]}
    ]
    assert condense_model_options(None) == {"model": "", "provider": "", "providers": []}



def test_model_options_serve_the_last_list_while_one_refresh_runs(monkeypatch):
    from open_webui.utils import hermes_sessions

    calls = []
    gate = asyncio.Event()

    async def fake_fetch(request, user, model_id):
        calls.append(model_id)
        await gate.wait()
        options = {"model": f"m{len(calls)}", "provider": "", "providers": []}
        hermes_sessions._MODEL_OPTIONS_CACHE[user.id] = (10**12, options)
        return options

    monkeypatch.setattr(hermes_sessions, "_fetch_model_options", fake_fetch)
    monkeypatch.setattr(hermes_sessions, "_MODEL_OPTIONS_CACHE", {})
    monkeypatch.setattr(hermes_sessions, "_MODEL_OPTIONS_REFRESH", {})
    user = SimpleNamespace(id="u1")

    async def scenario():
        stale = {"model": "old", "provider": "", "providers": []}
        hermes_sessions._MODEL_OPTIONS_CACHE["u1"] = (0, stale)
        # Expired: answered at once with the old list, one refresh for both calls.
        assert await hermes_sessions.list_model_options(None, user) is stale
        assert await hermes_sessions.list_model_options(None, user) is stale
        await asyncio.sleep(0)
        assert len(calls) == 1
        gate.set()
        await asyncio.sleep(0.01)
        assert (await hermes_sessions.list_model_options(None, user))["model"] == "m1"
        assert hermes_sessions._MODEL_OPTIONS_REFRESH == {}

    asyncio.run(scenario())


def test_model_options_refresh_failure_keeps_the_old_list(monkeypatch):
    from open_webui.utils import hermes_sessions

    async def failing_fetch(request, user, model_id):
        raise RuntimeError("hermes down")

    monkeypatch.setattr(hermes_sessions, "_fetch_model_options", failing_fetch)
    monkeypatch.setattr(hermes_sessions, "_MODEL_OPTIONS_CACHE", {"u1": (0, {"model": "old"})})
    monkeypatch.setattr(hermes_sessions, "_MODEL_OPTIONS_REFRESH", {})
    user = SimpleNamespace(id="u1")

    async def scenario():
        assert (await hermes_sessions.list_model_options(None, user))["model"] == "old"
        await asyncio.sleep(0.01)
        # Still expired, so the next open tries again (one at a time).
        assert (await hermes_sessions.list_model_options(None, user))["model"] == "old"
        await asyncio.gather(*hermes_sessions._MODEL_OPTIONS_REFRESH.values())
        assert hermes_sessions._MODEL_OPTIONS_REFRESH == {}

    asyncio.run(scenario())


class _StopResponse:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, content_type=None):
        return self.body


class _StopSession:
    def __init__(self, answer, posts):
        self.answer, self.posts = answer, posts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs.get("json")))
        return _StopResponse(*self.answer)


def _stop_world(monkeypatch, answer):
    from open_webui.utils import hermes_notify, hermes_runner_progress, hermes_sessions

    rid = "20260927-005655-f2dd355f"
    monkeypatch.setattr(
        hermes_runner_progress,
        "_PROGRESS",
        {rid: {"run_id": rid, "chat_id": "chat-1", "user_id": "u1", "agent": "reclaude",
               "status": "running", "updated_at": 10**12}},
    )
    posts, shown = [], []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    async def show(request, **kwargs):
        shown.append(kwargs)
        return {"status": True}

    monkeypatch.setattr(hermes_sessions, "resolve_hermes_model", resolve)
    monkeypatch.setattr(
        hermes_sessions, "_connection", lambda *_a: ("http://hermes.test", {"Authorization": "Bearer k"})
    )
    monkeypatch.setattr(
        hermes_sessions.aiohttp, "ClientSession", lambda **_kw: _StopSession(answer, posts)
    )
    monkeypatch.setattr(hermes_notify, "show_notification_report", show)
    return hermes_sessions, hermes_runner_progress, rid, posts, shown


def test_stopping_a_runner_asks_hermes_and_shows_the_notice(monkeypatch):
    sessions, progress, rid, posts, shown = _stop_world(
        monkeypatch,
        (200, {"stopped": True, "notice": "[后台任务完成通知] reclaude 运行 x 已结束，状态：stopped，Claude 会话：s。",
               "report": "⏹️ 已停止"}),
    )
    result = asyncio.run(sessions.stop_background_runner(None, SimpleNamespace(id="u1"), rid))
    assert result["stopped"] is True and result["report_shown"] is True
    assert posts == [(f"http://hermes.test/v1/runners/reclaude/{rid}/stop", {"session_id": "chat-1"})]
    assert shown[0]["chat_id"] == "chat-1" and shown[0]["quiet"] is True
    assert shown[0]["run_id"] == rid and shown[0]["source"] == "reclaude-runner"
    assert progress.get_runner_progress(rid) is None


def test_only_the_owner_stops_a_runner(monkeypatch):
    sessions, _progress, rid, posts, _shown = _stop_world(monkeypatch, (200, {}))
    with pytest.raises(sessions.HermesSessionsError) as error:
        asyncio.run(sessions.stop_background_runner(None, SimpleNamespace(id="someone-else"), rid))
    assert error.value.status_code == 404 and posts == []
    with pytest.raises(sessions.HermesSessionsError):
        asyncio.run(sessions.stop_background_runner(None, SimpleNamespace(id="u1"), "../etc"))


def test_a_runner_that_already_ended_leaves_the_banner(monkeypatch):
    sessions, progress, rid, _posts, shown = _stop_world(
        monkeypatch, (409, {"error": {"message": "reclaude 运行 20260927-005655-f2dd355f 已经结束"}})
    )
    with pytest.raises(sessions.HermesSessionsError) as error:
        asyncio.run(sessions.stop_background_runner(None, SimpleNamespace(id="u1"), rid))
    assert error.value.status_code == 409 and "已经结束" in error.value.detail
    assert progress.get_runner_progress(rid) is None and shown == []


def test_an_older_hermes_says_it_cannot_stop_runners(monkeypatch):
    sessions, progress, rid, _posts, _shown = _stop_world(monkeypatch, (404, {}))
    with pytest.raises(sessions.HermesSessionsError) as error:
        asyncio.run(sessions.stop_background_runner(None, SimpleNamespace(id="u1"), rid))
    assert error.value.status_code == 501 and "重启网关" in error.value.detail
    assert progress.get_runner_progress(rid) is not None
