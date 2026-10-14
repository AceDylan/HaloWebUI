"""Durable, user-owned receipts for automatic mode selection and dispatch."""

import time
import uuid

from sqlalchemy import JSON, BigInteger, Column, Index, String, UniqueConstraint, and_, or_
from sqlalchemy.exc import IntegrityError

from open_webui.internal.db import Base, get_db


class AutoRoute(Base):
    __tablename__ = "auto_route"
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    client_key = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False)
    status = Column(String, nullable=False)
    mode = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    data = Column(JSON, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "client_key", name="uq_auto_route_user_key"),
        Index("ix_auto_route_user_created", "user_id", "created_at", "id"),
        Index("ix_auto_route_target", "user_id", "mode", "target_id"),
    )


def _dict(row):
    return {c.name: getattr(row, c.name) for c in AutoRoute.__table__.columns} if row else None


class AutoRoutesTable:
    def create(self, user_id, client_key, fingerprint, data):
        """The unique key arbitrates concurrent submits, including across workers."""
        with get_db() as db:
            row = AutoRoute(id=str(uuid.uuid4()), user_id=user_id, client_key=client_key,
                            fingerprint=fingerprint, status="routing", data=data,
                            created_at=int(time.time()), updated_at=int(time.time()))
            db.add(row)
            try:
                db.commit()
                db.refresh(row)
                return _dict(row), True
            except IntegrityError:
                db.rollback()
                return _dict(db.query(AutoRoute).filter_by(user_id=user_id, client_key=client_key).one()), False

    def get(self, id, user_id):
        with get_db() as db:
            return _dict(db.query(AutoRoute).filter_by(id=id, user_id=user_id).first())

    def by_key(self, user_id, client_key):
        with get_db() as db:
            return _dict(db.query(AutoRoute).filter_by(user_id=user_id, client_key=client_key).first())

    def for_target(self, user_id, mode, target_id):
        with get_db() as db:
            return _dict(db.query(AutoRoute).filter_by(user_id=user_id, mode=mode, target_id=target_id).first())

    def page(self, user_id, offset=0, limit=30, *, before=None, query="", mode=None):
        with get_db() as db:
            stmt = db.query(AutoRoute).filter_by(user_id=user_id)
            if before:
                stamp, id = before
                stmt = stmt.filter(or_(AutoRoute.created_at < stamp,
                    and_(AutoRoute.created_at == stamp, AutoRoute.id < id)))
            if mode:
                stmt = stmt.filter(AutoRoute.mode == mode)
            if query.strip():
                text = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                stmt = stmt.filter(AutoRoute.data["input"]["question"].as_string().ilike(f"%{text}%", escape="\\"))
            rows = stmt.order_by(AutoRoute.created_at.desc(), AutoRoute.id.desc()).offset(0 if before else offset).limit(limit).all()
            return [_dict(row) for row in rows]

    def count_active(self, user_id):
        with get_db() as db:
            return db.query(AutoRoute).filter(AutoRoute.user_id == user_id,
                AutoRoute.status.in_(("routing", "dispatching")),
                AutoRoute.updated_at > int(time.time()) - 600).count()

    def active_for_user(self, user_id, since, limit=10):
        """Requests still choosing a mode or creating their task, updated after ``since``."""
        with get_db() as db:
            rows = (db.query(AutoRoute).filter(AutoRoute.user_id == user_id,
                    AutoRoute.status.in_(("routing", "dispatching")), AutoRoute.updated_at > since)
                    .order_by(AutoRoute.created_at.desc()).limit(limit).all())
            return [_dict(row) for row in rows]

    def update(self, id, user_id, *, expect=None, **fields):
        with get_db() as db:
            query = db.query(AutoRoute).filter_by(id=id, user_id=user_id)
            if expect:
                query = query.filter(AutoRoute.status.in_(expect))
            if not query.update({**fields, "updated_at": int(time.time())}, synchronize_session=False):
                return None
            db.commit()
            return _dict(db.query(AutoRoute).filter_by(id=id, user_id=user_id).one())


AutoRoutes = AutoRoutesTable()
