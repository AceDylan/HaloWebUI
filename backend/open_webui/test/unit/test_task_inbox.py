"""Unit tests for the unified Task Inbox (attention / running / ended + cross-channel)."""

import asyncio
import time
from types import SimpleNamespace

from open_webui.models import agent_teams, auto_routes
from open_webui.models.chats import Chats
from open_webui.utils import (
    hermes_agent,
    hermes_jobs,
    hermes_runner_progress,
    hermes_sessions,
    hermes_unread,
    task_inbox,
    video_tasks,
    work_activity,
)


def test_task_inbox_aggregates_buckets_recovery_and_cross_channel(monkeypatch):
    now = time.time()

    monkeypatch.setattr(
        hermes_agent,
        "list_active_runs",
        lambda uid: [
            {
                "chat_id": "c-approval",
                "run_id": "h1",
                "title": "危险命令审批",
                "started_at": now - 40,
                "steers": 0,
                "awaiting_approval": True,
                "approval": {"command": "rm -rf /tmp/x", "since": now - 10},
            },
            {
                "chat_id": "c-live",
                "run_id": "h2",
                "title": "写周报",
                "started_at": now - 20,
                "steers": 1,
                "awaiting_approval": False,
            },
        ],
    )
    monkeypatch.setattr(
        hermes_runner_progress,
        "list_runner_progress",
        lambda uid, now=None: [
            {
                "run_id": "20261121-180000-aaaa1111",
                "chat_id": "c-bg",
                "agent": "offiagy",
                "status": "running",
                "started_at": now - 100,
                "updated_at": now - 5,
                "step": 7,
                "last_activity": "跑单测",
                "title": "构建前端",
            }
        ],
    )
    monkeypatch.setattr(
        work_activity,
        "list_work",
        lambda uid, skip: [
            {
                "kind": "team",
                "id": "t-wait",
                "chat_id": "c-team-wait",
                "title": "审批计划",
                "href": "/teams/t-wait",
                "started_at": now - 50,
                "state": "waiting",
                "note": "等你批准",
            }
        ],
    )
    monkeypatch.setattr(hermes_unread, "list_unread_chat_ids", lambda uid, limit=30: ["c-unread"])
    monkeypatch.setattr(
        task_inbox,
        "_chat_summaries",
        lambda ids, uid: {
            "c-unread": {"title": "后台报告好了", "updated_at": now - 300, "unread_at": now - 120, "source": "web"}
        },
    )
    monkeypatch.setattr(
        agent_teams.AgentTeams,
        "list_for_user",
        lambda uid, limit=25: [
            SimpleNamespace(
                id="t-stopped",
                chat_id="c-t-stop",
                title="中断的协作",
                goal="调研",
                status="running",
                phase="stopped",
                error="手动停止",
                created_at=int(now - 500),
                updated_at=int(now - 400),
                finished_at=int(now - 400),
            ),
            SimpleNamespace(
                id="t-plan-fail",
                chat_id=None,
                title="失败的计划",
                goal="重构",
                status="plan_failed",
                phase=None,
                error="超时",
                created_at=int(now - 600),
                updated_at=int(now - 550),
                finished_at=None,
            ),
        ],
    )
    monkeypatch.setattr(
        video_tasks,
        "list_tasks",
        lambda uid, limit=15, since=None: [
            {
                "chatId": "c-vid-reply",
                "title": "待确认分镜",
                "state": "replied",
                "now": "已回复，待确认",
                "startedAt": int(now - 200),
                "endedAt": int(now - 150),
            }
        ],
    )
    monkeypatch.setattr(Chats, "page_chats_with_meta_key", lambda *a, **k: ([], False))
    monkeypatch.setattr(auto_routes.AutoRoutes, "page", lambda *a, **k: [])

    async def fake_list_sessions(req, user, *, source, limit=12, offset=0):
        if source == "telegram":
            return {
                "sessions": [
                    {
                        "id": "tg-yesterday",
                        "source": "telegram",
                        "title": "昨天 Telegram 任务",
                        "preview": "帮我看下 HaloWebUI",
                        "message_count": 4,
                        "last_active": now - 3600,
                        "imported": False,
                    }
                ]
            }
        return {"sessions": []}

    async def fake_runner_stats(req, user, days=7):
        return {
            "days": days,
            "runs": [
                {
                    "run_id": "20261120-210000-bbbb2222",
                    "agent": "offiagy",
                    "status": "question",
                    "origin": "telegram",
                    "project": "HaloWebUI",
                    "title": "TG 问我确认方案",
                    "started_at": now - 7200,
                    "ended_at": now - 7000,
                },
                {
                    "run_id": "20261120-200000-cccc3333",
                    "agent": "reclaude",
                    "status": "ok",
                    "origin": "telegram",
                    "project": "HaloWebUI",
                    "title": "TG 已完成修补",
                    "started_at": now - 9000,
                    "ended_at": now - 8500,
                },
            ],
        }

    monkeypatch.setattr(hermes_sessions, "list_sessions", fake_list_sessions)
    monkeypatch.setattr(hermes_jobs, "runner_stats", fake_runner_stats)

    user = SimpleNamespace(id="u1", role="admin")
    result = asyncio.run(task_inbox.get_task_inbox(SimpleNamespace(), user, days=7))

    att_ids = [i["id"] for i in result["attention"]]
    assert "hermes:c-approval" in att_ids
    assert "team:t-wait" in att_ids
    assert "video:c-vid-reply" in att_ids
    assert "runner-stat:20261120-210000-bbbb2222" in att_ids

    run_ids = [i["id"] for i in result["running"]]
    assert "hermes:c-live" in run_ids
    assert "runner:20261121-180000-aaaa1111" in run_ids

    ended_by_id = {i["id"]: i for i in result["ended"]}
    # Unread item is sorted first in ended
    assert result["ended"][0]["id"] == "unread:c-unread"
    assert result["ended"][0]["unread"] is True
    # Explicit recovery distinction: stopped team -> continue, plan_failed -> restart
    assert ended_by_id["team:t-stopped"]["recovery"] == "continue"
    assert ended_by_id["team:t-plan-fail"]["recovery"] == "restart"
    # Cross-channel Telegram session & runner run both appear
    assert ended_by_id["session:tg-yesterday"]["source"] == "telegram"
    assert ended_by_id["session:tg-yesterday"]["imported"] is False
    assert ended_by_id["runner-stat:20261120-200000-cccc3333"]["source"] == "telegram"


def test_task_inbox_degrades_gracefully_when_hermes_fails(monkeypatch):
    monkeypatch.setattr(hermes_agent, "list_active_runs", lambda uid: [])
    monkeypatch.setattr(hermes_runner_progress, "list_runner_progress", lambda uid, now=None: [])
    monkeypatch.setattr(work_activity, "list_work", lambda uid, skip: [])
    monkeypatch.setattr(hermes_unread, "list_unread_chat_ids", lambda uid, limit=30: [])
    monkeypatch.setattr(agent_teams.AgentTeams, "list_for_user", lambda uid, limit=25: [])
    monkeypatch.setattr(video_tasks, "list_tasks", lambda uid, limit=15, since=None: [])
    monkeypatch.setattr(Chats, "page_chats_with_meta_key", lambda *a, **k: ([], False))
    monkeypatch.setattr(auto_routes.AutoRoutes, "page", lambda *a, **k: [])

    async def boom(*a, **k):
        raise RuntimeError("hermes offline")

    monkeypatch.setattr(hermes_sessions, "list_sessions", boom)
    monkeypatch.setattr(hermes_jobs, "runner_stats", boom)

    result = asyncio.run(task_inbox.get_task_inbox(SimpleNamespace(), SimpleNamespace(id="u1", role="user")))
    assert result["counts"] == {"attention": 0, "running": 0, "ended": 0}
