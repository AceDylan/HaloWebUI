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
from sqlalchemy import JSON, BigInteger, Column, Index, String, Text

# planning → plan_ready | plan_failed → (approve) starting → running | start_failed; cancelled
TEAM_STATUSES = ("planning", "plan_ready", "plan_failed", "starting", "start_failed", "running", "cancelled")
TEAM_LIST_LIMIT = 100


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
