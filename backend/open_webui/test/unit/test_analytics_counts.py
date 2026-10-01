"""Admin analytics views count the same rows and the daily series has no gaps."""

import asyncio
import time
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import chats as chats_mod
from open_webui.routers import analytics

DAY = 86400
MODEL = "modelref::openai::personal::id:ee5e02db::hermes-agent"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    chats_mod.Chat.__table__.create(engine)
    chats_mod.ChatMessage.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(analytics, "get_db", get_db)
    monkeypatch.setattr(analytics, "ENABLE_ADMIN_ANALYTICS", True)

    now = int(time.time())
    rows = [
        # (role, model, created_at, prompt, completion)
        ("user", None, now - 1 * DAY, None, None),
        ("assistant", MODEL, now - 1 * DAY, 100, 10),
        ("assistant", MODEL, now - 5 * DAY, 200, 20),
        ("assistant", "modelref::openai::personal::id:c1::gpt-chat", now, 5, 1),
    ]
    with get_db() as s:
        for i, (role, model, created_at, prompt, completion) in enumerate(rows):
            s.add(
                chats_mod.ChatMessage(
                    id=f"m{i}",
                    chat_id="chat",
                    user_id="owner",
                    role=role,
                    content="",
                    model=model,
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        s.commit()
    yield
    engine.dispose()


def _run(coro):
    return asyncio.run(coro)


def test_every_view_counts_the_same_replies(db):
    models = _run(analytics.get_model_usage_stats(user=None, days=7, group_id=None))
    users = _run(analytics.get_user_activity_stats(user=None, days=7, group_id=None))
    daily = _run(
        analytics.get_daily_stats(user=None, days=7, model=None, timezone_name="UTC")
    )

    totals = [
        sum(r["message_count"] for r in rows) for rows in (models, users, daily)
    ]
    assert totals == [3, 3, 3]
    assert sum(r["total_tokens"] for r in daily) == 336


def test_daily_series_has_a_bucket_for_every_day(db):
    daily = _run(
        analytics.get_daily_stats(user=None, days=7, model=MODEL, timezone_name="UTC")
    )

    # 7 days back to today inclusive; idle days are zeros, not missing.
    assert len(daily) == 8
    assert [r["date"] for r in daily] == sorted(r["date"] for r in daily)
    assert sum(1 for r in daily if r["message_count"]) == 2
    assert sum(r["message_count"] for r in daily) == 2
