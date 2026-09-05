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
