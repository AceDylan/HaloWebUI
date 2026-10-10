"""协作台定时: a team that runs again on a schedule (每天 / 每周 / 每月 at a time).

The team itself is the template: each run is a new team with its goal and its plan (see
utils/team_repeat.py). The schedule lives in its own row, not in the team's ``meta``: the
team's meta is rewritten whole by the live sync, which would undo a moved ``next_run_at``
and run the same occurrence twice.
"""

import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Index, Integer, String, Text


class AgentTeamSchedule(Base):
    __tablename__ = "agent_team_schedule"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    team_id = Column(String, nullable=False)
    # daily / weekly / monthly
    freq = Column(String, nullable=False)
    # "HH:MM" in ``tz``
    time = Column(String, nullable=False)
    # weekly: 0 = Monday … 6 = Sunday; monthly: day of the month 1-28
    weekday = Column(Integer, nullable=True)
    day = Column(Integer, nullable=True)
    tz = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False)
    next_run_at = Column(BigInteger, nullable=True)
    last_run_at = Column(BigInteger, nullable=True)
    last_team_id = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_agent_team_schedule_team", "team_id", unique=True),
        Index("ix_agent_team_schedule_due", "enabled", "next_run_at"),
    )


class AgentTeamScheduleModel(BaseModel):
    id: str
    user_id: str
    team_id: str
    freq: str
    time: str
    weekday: Optional[int] = None
    day: Optional[int] = None
    tz: str
    enabled: bool
    next_run_at: Optional[int] = None
    last_run_at: Optional[int] = None
    last_team_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class AgentTeamSchedulesTable:
    def get_for_team(self, team_id: str, user_id: str) -> Optional[AgentTeamScheduleModel]:
        with get_db() as db:
            row = db.query(AgentTeamSchedule).filter_by(team_id=team_id, user_id=user_id).first()
            return AgentTeamScheduleModel.model_validate(row) if row else None

    def list_for_user(self, user_id: str) -> list[AgentTeamScheduleModel]:
        with get_db() as db:
            rows = (db.query(AgentTeamSchedule).filter_by(user_id=user_id)
                    .order_by(AgentTeamSchedule.created_at.asc()).all())
            return [AgentTeamScheduleModel.model_validate(row) for row in rows]

    def due(self, now: int, limit: int = 20) -> list[AgentTeamScheduleModel]:
        with get_db() as db:
            rows = (db.query(AgentTeamSchedule)
                    .filter(AgentTeamSchedule.enabled.is_(True),
                            AgentTeamSchedule.next_run_at.isnot(None),
                            AgentTeamSchedule.next_run_at <= now)
                    .order_by(AgentTeamSchedule.next_run_at.asc()).limit(limit).all())
            return [AgentTeamScheduleModel.model_validate(row) for row in rows]

    def upsert(self, user_id: str, team_id: str, **fields) -> AgentTeamScheduleModel:
        now = int(time.time())
        with get_db() as db:
            row = db.query(AgentTeamSchedule).filter_by(team_id=team_id, user_id=user_id).first()
            if row is None:
                row = AgentTeamSchedule(id=str(uuid.uuid4()), user_id=user_id, team_id=team_id,
                                        created_at=now, updated_at=now, **fields)
                db.add(row)
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                row.updated_at = now
            db.commit()
            db.refresh(row)
            return AgentTeamScheduleModel.model_validate(row)

    def claim(self, schedule_id: str, due_at: int, next_run_at: int) -> bool:
        """Move a due schedule to its next occurrence; False when another sweep (or an edit)
        already moved it — so one occurrence starts one run."""
        with get_db() as db:
            count = (db.query(AgentTeamSchedule)
                     .filter_by(id=schedule_id, enabled=True, next_run_at=due_at)
                     .update({"next_run_at": next_run_at, "updated_at": int(time.time())},
                             synchronize_session=False))
            db.commit()
            return count == 1

    def record(self, schedule_id: str, **fields) -> None:
        fields["updated_at"] = int(time.time())
        with get_db() as db:
            db.query(AgentTeamSchedule).filter_by(id=schedule_id).update(fields, synchronize_session=False)
            db.commit()

    def delete_for_team(self, team_id: str, user_id: str) -> bool:
        with get_db() as db:
            count = (db.query(AgentTeamSchedule).filter_by(team_id=team_id, user_id=user_id)
                     .delete(synchronize_session=False))
            db.commit()
            return count == 1


AgentTeamSchedules = AgentTeamSchedulesTable()
