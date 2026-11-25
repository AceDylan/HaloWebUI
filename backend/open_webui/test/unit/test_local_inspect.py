"""Unit tests for read-only local evidence inspection across 精答, 讨论台, and 自动分流."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from open_webui.utils import answer_desk as desk
from open_webui.utils import auto_routing as ar
from open_webui.utils import discussion_room as room
from open_webui.utils import local_inspect as li


ADMIN = SimpleNamespace(id="u-admin", role="admin")
MEMBER = SimpleNamespace(id="u-user", role="user")


def test_may_inspect_is_admin_only_and_env_gated(monkeypatch):
    monkeypatch.delenv(li.MODES_ENV, raising=False)
    assert li.may_inspect(ADMIN) is True
    assert li.may_inspect(MEMBER) is False
    monkeypatch.setenv(li.MODES_ENV, "0")
    assert li.may_inspect(ADMIN) is False


def test_redact_evidence_scrubs_secrets():
    raw = (
        "API_KEY=sk-1234567890abcdefghij\n"
        "HERMES_API_KEY=${HERMES_API_KEY}\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature12345\n"
        "postgres://root:superSecret99@127.0.0.1/db\n"
    )
    cleaned = li.redact_evidence(raw)
    assert "sk-1234567890abcdefghij" not in cleaned
    assert "superSecret99" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "${HERMES_API_KEY}" in cleaned


def test_inspect_block_and_tail_formatting():
    data = {
        "status": "done",
        "summary": "nginx 监听 3001 并反代到 127.0.0.1:3000。",
        "sources": [
            {"kind": "file", "path": "/etc/nginx/sites-enabled/halowebui.conf"},
            {"kind": "command", "path": "docker ps"},
        ],
    }
    block = li.inspect_block(data)
    assert "Live read-only evidence" in block
    assert "/etc/nginx/sites-enabled/halowebui.conf" in block
    assert "nginx 监听 3001" in block
    tail = li.inspect_tail(data)
    assert "**本机取证（只读）**" in tail
    assert "`/etc/nginx/sites-enabled/halowebui.conf`" in tail
    assert "`docker ps`" in tail
    assert li.inspect_block({"status": "error", "summary": "x"}) == ""
    assert li.inspect_tail({"status": "empty", "sources": []}) == ""


def test_answer_desk_runs_local_inspect_and_injects_into_answer():
    captured_messages = []

    async def route(run):
        return (
            {"action": "use", "reason": "运维专家", "change": "", "webSearch": False, "note": ""},
            {"id": "m-ops", "name": "运维专家", "emoji": "🛠", "action": "use", "saved": True, "base": "gpt", "baseName": "GPT"},
        )

    async def inspect(question, bg):
        return {
            "summary": "halowebui 容器健康，监听 127.0.0.1:3000。",
            "sources": [{"kind": "command", "path": "docker ps"}],
            "model": "gpt-chat",
        }

    async def call_model(model_id, messages, browse=False):
        captured_messages.append(messages)
        return {"choices": [{"message": {"content": "根据本机取证，容器正常。"}}]}

    run = desk.new_run(
        question="结合我服务器上的 halowebui 配置讲下端口监听",
        planner={"model": "gpt", "name": "GPT"},
        user_message_id="u1",
        message_id="a1",
        web_allowed=False,
        local_inspect=True,
    )
    events = []

    async def emit(ev):
        events.append(ev)

    live = desk.LiveAnswer(
        chat_id="c1",
        user_id="u1",
        run=run,
        emit=emit,
        call_model=call_model,
        route=route,
        persist=lambda r: None,
        inspect=inspect,
    )
    asyncio.run(live.run_all())
    assert run["status"] == "done"
    assert run["localInspect"]["status"] == "done"
    assert run["localInspect"]["model"] == "gpt-chat"
    assert "halowebui 容器健康" in captured_messages[0][-1]["content"]
    stored = desk.stored_content(run)
    assert "**本机取证（只读）**" in stored and "`docker ps`" in stored


def test_answer_desk_continues_when_local_inspect_fails():
    async def route(run):
        return (
            {"action": "use", "reason": "ok", "change": "", "webSearch": False, "note": ""},
            {"id": "m1", "name": "助手", "emoji": "", "action": "use", "saved": True, "base": "gpt", "baseName": "GPT"},
        )

    async def broken_inspect(q, bg):
        raise RuntimeError("hermes offline")

    async def call_model(model_id, messages, browse=False):
        return {"choices": [{"message": {"content": "照常回答。"}}]}

    run = desk.new_run(
        question="test",
        planner={"model": "gpt", "name": "GPT"},
        user_message_id="u1",
        message_id="a1",
        web_allowed=False,
        local_inspect=True,
    )
    live = desk.LiveAnswer(
        chat_id="c1", user_id="u1", run=run, emit=lambda e: asyncio.sleep(0),
        call_model=call_model, route=route, persist=lambda r: None, inspect=broken_inspect,
    )
    asyncio.run(live.run_all())
    assert run["status"] == "done"
    assert run["localInspect"]["status"] == "error"
    assert "hermes offline" in run["localInspect"]["error"]
    assert run["answer"]["content"] == "照常回答。"


def test_discussion_room_runs_local_inspect_for_seats_and_moderator():
    seen_prompts = []

    async def inspect(question, history):
        return {
            "summary": "nginx 启用了 gzip 与 3001 TLS。",
            "sources": [{"kind": "file", "path": "/etc/nginx/nginx.conf"}],
            "model": "gpt-chat",
        }

    async def call_model(model_id, messages, browse=False):
        seen_prompts.append((model_id, messages[-1]["content"]))
        return {"choices": [{"message": {"content": "## 结论\n已结合实况分析。"}}]}

    setup = {
        "mode": "compare",
        "rounds": 1,
        "seats": [
            {"id": "s1", "model": "m1", "name": "M1", "label": "M1", "role": "", "vision": True},
            {"id": "s2", "model": "m2", "name": "M2", "label": "M2", "role": "", "vision": True},
        ],
        "moderator": {"model": "m1", "name": "M1", "vision": True},
        "research": False,
        "localInspect": True,
        "autoMatch": False,
        "smart": False,
    }
    ask = room.new_ask(question="结合服务器 nginx 配置讨论优化方案", setup=setup, user_message_id="u1", message_id="a1")
    live = room.LiveDiscussion(
        chat_id="d1",
        user_id="u1",
        setup=setup,
        ask=ask,
        history=[],
        emit=lambda e: asyncio.sleep(0),
        call_model=call_model,
        persist=lambda a: None,
        inspect=inspect,
        signoff=False,
    )
    asyncio.run(live.run())
    assert ask["status"] == "done"
    assert ask["localInspect"]["status"] == "done"
    # Every seat + moderator received the redacted local evidence pack.
    assert len(seen_prompts) == 3
    assert all("nginx 启用了 gzip" in content for _m, content in seen_prompts)
    assert "**本机取证（只读）**" in room.stored_content(ask)


def test_auto_routing_enables_local_inspect_for_discuss_and_answer_without_hijacking():
    # Multi-model tradeoff grounded in local configs stays in discuss + local_inspect=True
    d = ar.normalize_selection(
        {"mode": "discuss", "reason": "多模型权衡", "needs_tools": True, "execution_requested": False},
        question="结合我服务器现在的 nginx 和 halowebui 配置，讨论架构怎么优化",
        teams_available=True,
        discussion_available=True,
        hermes_available=True,
        local_inspect_available=True,
    )
    assert d["mode"] == "discuss" and d["local_inspect"] is True

    # Explicit 精答 about local configs stays in answer + local_inspect=True
    a = ar.normalize_selection(
        {"mode": "answer", "reason": "精答分析", "needs_tools": True, "execution_requested": False},
        question="用精答结合我本机的 docker-compose 配置讲清链路",
        teams_available=True,
        discussion_available=True,
        hermes_available=True,
        local_inspect_available=True,
    )
    assert a["mode"] == "answer" and a["local_inspect"] is True

    # Quick local status check mistakenly sent to answer is still routed to Hermes!
    q = ar.normalize_selection(
        {"mode": "answer", "reason": "看状态", "needs_tools": True, "execution_requested": False},
        question="看下 nginx 最近有没有报错",
        teams_available=True,
        discussion_available=True,
        hermes_available=True,
        local_inspect_available=True,
    )
    assert q["mode"] == "hermes" and not q.get("local_inspect")

    # Heuristic fallback also recognizes local tradeoff -> discuss + local_inspect
    raw = ar.heuristic_selection(
        "结合我服务器现在的 nginx 和 halowebui 配置，方案 A 和方案 B 到底选哪个更稳",
        teams_available=True,
        discussion_available=True,
        hermes_available=True,
        local_inspect_available=True,
    )
    norm = ar.normalize_selection(
        raw,
        question="结合我服务器现在的 nginx 和 halowebui 配置，方案 A 和方案 B 到底选哪个更稳",
        teams_available=True,
        discussion_available=True,
        hermes_available=True,
        local_inspect_available=True,
    )
    assert norm["mode"] == "discuss" and norm["local_inspect"] is True
