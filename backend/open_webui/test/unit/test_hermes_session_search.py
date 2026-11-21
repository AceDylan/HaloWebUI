"""Unit tests for cross-channel Hermes session search (Telegram / QQ / CLI for ⌘K)."""

import asyncio
from types import SimpleNamespace

import pytest

from open_webui.utils import hermes_sessions


def test_search_sessions_matches_across_sources_and_hides_imported_by_default(monkeypatch):
    hermes_sessions._SEARCH_POOL_CACHE.clear()

    async def fake_resolve(request, user, model_id=None):
        return {"id": "hermes-agent"}

    monkeypatch.setattr(hermes_sessions, "resolve_hermes_model", fake_resolve)
    monkeypatch.setattr(hermes_sessions, "_connection", lambda req, user, model: ("http://hermes", {}))

    async def fake_get_json(url, headers, params=None):
        src = (params or {}).get("source")
        if src == "telegram":
            return {
                "data": [
                    {
                        "id": "tg_imported",
                        "source": "telegram",
                        "title": "HaloWebUI 折叠屏适配",
                        "preview": "测一下外屏",
                        "message_count": 5,
                        "last_active": 2000,
                    },
                    {
                        "id": "tg_unimported",
                        "source": "telegram",
                        "title": "折叠屏测试记录",
                        "preview": "X Fold6 回归",
                        "message_count": 3,
                        "last_active": 3000,
                    },
                ]
            }
        if src == "qqbot":
            return {
                "data": [
                    {
                        "id": "qq_hit",
                        "source": "qqbot",
                        "title": "周末计划",
                        "preview": "买台折叠屏手机",
                        "message_count": 2,
                        "last_active": 1500,
                    }
                ]
            }
        return {"data": []}

    monkeypatch.setattr(hermes_sessions, "_get_json", fake_get_json)
    monkeypatch.setattr(
        hermes_sessions.Chats,
        "get_existing_chat_ids_by_user_id",
        lambda ids, uid: {"tg_imported"} & set(ids),
    )

    user = SimpleNamespace(id="u-search")
    req = SimpleNamespace()

    # Default (⌘K): excludes already-imported sessions, newest first across TG + QQ
    res = asyncio.run(hermes_sessions.search_sessions(req, user, query="折叠屏"))
    assert [s["id"] for s in res["sessions"]] == ["tg_unimported", "qq_hit"]
    assert all(s["imported"] is False for s in res["sessions"])

    # include_imported=True includes imported ones too
    res_all = asyncio.run(
        hermes_sessions.search_sessions(req, user, query="折叠屏", include_imported=True)
    )
    assert [s["id"] for s in res_all["sessions"]] == ["tg_unimported", "tg_imported", "qq_hit"]

    # Multi-token search + source filter
    res_tok = asyncio.run(
        hermes_sessions.search_sessions(req, user, query="折叠屏 Fold6", source="telegram")
    )
    assert [s["id"] for s in res_tok["sessions"]] == ["tg_unimported"]


def test_search_sessions_rejects_unknown_source():
    with pytest.raises(hermes_sessions.HermesSessionsError) as exc:
        asyncio.run(
            hermes_sessions.search_sessions(
                SimpleNamespace(), SimpleNamespace(id="u1"), query="hi", source="wechat"
            )
        )
    assert exc.value.status_code == 400
