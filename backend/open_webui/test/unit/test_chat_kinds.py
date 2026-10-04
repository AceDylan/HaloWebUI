"""Sidebar marks: which chats are discussions, team chats or image chats."""

import pathlib
import sys
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.models.agent_teams import AgentTeam  # noqa: E402
from open_webui.models.chats import Chat, ChatTitleIdResponse  # noqa: E402
from open_webui.models.image_studio import ImageStudioItem  # noqa: E402
from open_webui.utils import chat_kinds as mod  # noqa: E402


def _db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for model in (Chat, AgentTeam, ImageStudioItem):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with session() as db:
            yield db

    monkeypatch.setattr(mod, "get_db", get_db)
    return session


def _chat(db, chat_id, user="u1", meta=None):
    db.add(Chat(id=chat_id, user_id=user, title=chat_id, chat={}, meta=meta or {}, created_at=1, updated_at=1, archived=False))


def test_marks_discussions_teams_and_image_chats(monkeypatch):
    session = _db(monkeypatch)
    with session() as db:
        _chat(db, "plain")
        _chat(db, "talk", meta={"discussion_room": {"status": "done"}})
        _chat(db, "team")
        _chat(db, "pics")
        _chat(db, "both", meta={"discussion_room": {}})
        _chat(db, "theirs", user="u2", meta={"discussion_room": {}})
        db.add(AgentTeam(id="t1", user_id="u1", chat_id="team", title="t", goal="g", status="done", phase="done", created_at=1, updated_at=1))
        db.add(AgentTeam(id="t2", user_id="u1", chat_id="both", title="t", goal="g", status="done", phase="done", created_at=1, updated_at=1))
        db.add(AgentTeam(id="t3", user_id="u2", chat_id="plain", title="t", goal="g", status="done", phase="done", created_at=1, updated_at=1))
        db.add(ImageStudioItem(id="gallery_chat_r1_0", user_id="u1", kind="gallery", data={"chatId": "pics"}, created_at=1, updated_at=1))
        db.add(ImageStudioItem(id="gallery_x", user_id="u1", kind="gallery", data={"chatId": "plain"}, created_at=1, updated_at=1))
        db.commit()

    kinds = mod.chat_kinds("u1", ["plain", "talk", "team", "pics", "both", "theirs", "missing"])
    assert kinds == {"talk": "discuss", "team": "team", "pics": "image", "both": "discuss"}
    assert mod.chat_kinds("u1", []) == {}

    rows = [ChatTitleIdResponse(id=i, title=i, updated_at=1, created_at=1) for i in ("plain", "team")]
    mod.with_kinds("u1", rows)
    assert [r.kind for r in rows] == [None, "team"]


def test_no_marks_when_the_lookup_fails(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(mod, "get_db", broken)
    assert mod.chat_kinds("u1", ["a"]) == {}
