"""协作台 (agent teams): who owns which collaboration task, which chat it came from, the lead's
plan before it is approved, and where it runs once approved.

Tasks, dependencies, attempts, member messages and events are NOT stored here: once a team
is approved they live on its Hermes Kanban board (``board``), and HaloWebUI reads them through
Hermes' ``/v1/halo-teams`` API. This row is the ownership / chat link and the approval record.
"""

import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, String, Text, and_, func, not_, or_

# planning → plan_ready | plan_failed → (approve) starting → running | start_failed; cancelled
TEAM_STATUSES = ("planning", "plan_ready", "plan_failed", "starting", "start_failed", "running", "cancelled")
TEAM_LIST_LIMIT = 100

# The 协作台 list's filters (TeamsHome bucketOf): 进行中 / 待批准 / 已完成 / 已结束.
TEAM_BUCKETS = ("active", "review", "done", "ended")
_ENDED_STATUSES = ("cancelled", "plan_failed", "start_failed", "stopped")


def bucket_of(status: Optional[str], phase: Optional[str]) -> str:
    """Which filter of the list a team is under (a running team by its board's phase)."""
    state = (phase or "running") if status == "running" else (status or "")
    if state == "plan_ready":
        return "review"
    if state == "completed":
        return "done"
    if state in _ENDED_STATUSES:
        return "ended"
    return "active"


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AgentTeam(Base):
    __tablename__ = "agent_team"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    goal = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    # Last live phase seen on the board (running / attention / paused / stopped / completed).
    phase = Column(String, nullable=True)
    plan = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    board = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    approved_at = Column(BigInteger, nullable=True)
    finished_at = Column(BigInteger, nullable=True)
    meta = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_agent_team_user_updated", "user_id", "updated_at"),
        Index("ix_agent_team_user_chat", "user_id", "chat_id"),
    )


class AgentTeamModel(BaseModel):
    id: str
    user_id: str
    chat_id: Optional[str] = None
    title: str
    goal: str
    status: str
    phase: Optional[str] = None
    plan: Optional[dict] = None
    error: Optional[str] = None
    board: Optional[str] = None
    created_at: int
    updated_at: int
    approved_at: Optional[int] = None
    finished_at: Optional[int] = None
    meta: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


def _bucket_condition(bucket: str):
    """bucket_of as SQL."""
    phase = func.coalesce(AgentTeam.phase, "")
    running = AgentTeam.status == "running"
    review = AgentTeam.status == "plan_ready"
    done = or_(AgentTeam.status == "completed", and_(running, phase == "completed"))
    ended = or_(AgentTeam.status.in_(_ENDED_STATUSES), and_(running, phase == "stopped"))
    if bucket == "review":
        return review
    if bucket == "done":
        return done
    if bucket == "ended":
        return ended
    return not_(or_(review, done, ended))


def _search_condition(query: str):
    needle = f"%{_like_escape(query.strip()[:200])}%"
    return or_(AgentTeam.title.ilike(needle, escape="\\"), AgentTeam.goal.ilike(needle, escape="\\"))


class AgentTeamsTable:
    def insert(self, user_id: str, goal: str, chat_id: Optional[str], title: str,
               meta: Optional[dict] = None) -> AgentTeamModel:
        now = int(time.time())
        with get_db() as db:
            row = AgentTeam(
                id=str(uuid.uuid4()),
                user_id=user_id,
                chat_id=chat_id or None,
                title=title,
                goal=goal,
                status="planning",
                created_at=now,
                    updated_at=now,
                    meta=meta or {},
                )
            db.add(row)
            db.commit()
            db.refresh(row)
            return AgentTeamModel.model_validate(row)

    def get(self, team_id: str, user_id: str) -> Optional[AgentTeamModel]:
        with get_db() as db:
            row = db.query(AgentTeam).filter_by(id=team_id, user_id=user_id).first()
            return AgentTeamModel.model_validate(row) if row else None

    def list_for_user(self, user_id: str, chat_id: Optional[str] = None,
                      limit: int = TEAM_LIST_LIMIT) -> list[AgentTeamModel]:
        with get_db() as db:
            query = db.query(AgentTeam).filter(AgentTeam.user_id == user_id)
            if chat_id:
                query = query.filter(AgentTeam.chat_id == chat_id)
            rows = query.order_by(AgentTeam.updated_at.desc()).limit(max(1, min(limit, TEAM_LIST_LIMIT))).all()
            return [AgentTeamModel.model_validate(row) for row in rows]

    def page_for_user(self, user_id: str, *, limit: int = 30, before: Optional[tuple[int, str]] = None,
                      query: Optional[str] = None, bucket: Optional[str] = None
                      ) -> tuple[list[AgentTeamModel], bool]:
        """One page of the user's teams, newest first (``updated_at``, then id), after ``before``
        (the last row of the page before), in one filter of the list and matching ``query`` in the
        title or the goal. Returns (teams, whether more follow)."""
        limit = max(1, min(int(limit), TEAM_LIST_LIMIT))
        with get_db() as db:
            q = db.query(AgentTeam).filter(AgentTeam.user_id == user_id)
            if bucket in TEAM_BUCKETS:
                q = q.filter(_bucket_condition(bucket))
            if (query or "").strip():
                q = q.filter(_search_condition(query))
            if before is not None:
                at, last_id = before
                q = q.filter(or_(AgentTeam.updated_at < at, and_(AgentTeam.updated_at == at, AgentTeam.id < last_id)))
            rows = q.order_by(AgentTeam.updated_at.desc(), AgentTeam.id.desc()).limit(limit + 1).all()
            return [AgentTeamModel.model_validate(row) for row in rows[:limit]], len(rows) > limit

    def counts_for_user(self, user_id: str, query: Optional[str] = None) -> dict[str, int]:
        """How many of the user's teams are under each filter (and in all), in one grouped read."""
        counts = {"all": 0, **{bucket: 0 for bucket in TEAM_BUCKETS}}
        with get_db() as db:
            q = db.query(AgentTeam.status, AgentTeam.phase, func.count(AgentTeam.id)).filter(
                AgentTeam.user_id == user_id)
            if (query or "").strip():
                q = q.filter(_search_condition(query))
            for status, phase, n in q.group_by(AgentTeam.status, AgentTeam.phase).all():
                counts[bucket_of(status, phase)] += int(n)
                counts["all"] += int(n)
        return counts

    def list_current_for_user(self, user_id: str, since: int, limit: int = TEAM_LIST_LIMIT) -> list[AgentTeamModel]:
        """The teams the sidebar badge follows: those at work or waiting for approval, and any that
        changed since ``since`` (so it sees a team finish or fail) — never the whole history."""
        with get_db() as db:
            rows = (db.query(AgentTeam)
                    .filter(AgentTeam.user_id == user_id)
                    .filter(or_(_bucket_condition("active"), _bucket_condition("review"), AgentTeam.updated_at >= since))
                    .order_by(AgentTeam.updated_at.desc(), AgentTeam.id.desc())
                    .limit(max(1, min(limit, TEAM_LIST_LIMIT))).all())
            return [AgentTeamModel.model_validate(row) for row in rows]

    def list_without_chat(self, user_id: str, limit: int, exclude: Optional[set] = None) -> list[AgentTeamModel]:
        """Teams from before teams had chats (no ``chat_id``), newest first."""
        with get_db() as db:
            q = db.query(AgentTeam).filter(AgentTeam.user_id == user_id, AgentTeam.chat_id.is_(None))
            if exclude:
                q = q.filter(AgentTeam.id.notin_(list(exclude)))
            rows = q.order_by(AgentTeam.updated_at.desc()).limit(max(1, limit)).all()
            return [AgentTeamModel.model_validate(row) for row in rows]

    def update(self, team_id: str, user_id: str, *, expect_status: Optional[tuple] = None,
               **fields) -> Optional[AgentTeamModel]:
        """Update the user's team; with ``expect_status`` only while its status is one of those
        (None when the team is gone or its status moved on — a concurrent click lost)."""
        with get_db() as db:
            query = db.query(AgentTeam).filter_by(id=team_id, user_id=user_id)
            if expect_status:
                query = query.filter(AgentTeam.status.in_(list(expect_status)))
            fields["updated_at"] = int(time.time())
            if query.update(fields, synchronize_session=False) != 1:
                db.rollback()
                return None
            db.commit()
            row = db.query(AgentTeam).filter_by(id=team_id, user_id=user_id).first()
            return AgentTeamModel.model_validate(row) if row else None

    def delete(self, team_id: str, user_id: str) -> bool:
        with get_db() as db:
            count = db.query(AgentTeam).filter_by(id=team_id, user_id=user_id).delete(synchronize_session=False)
            db.commit()
            return count == 1


AgentTeams = AgentTeamsTable()
