"""Durable automatic routing receipts.

Revision ID: a7d93e5f8102
Revises: b8e4c2a7d913
"""
from alembic import op
import sqlalchemy as sa

revision = "a7d93e5f8102"
down_revision = "b8e4c2a7d913"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("auto_route",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("client_key", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("user_id", "client_key", name="uq_auto_route_user_key"))
    op.create_index("ix_auto_route_user_created", "auto_route", ["user_id", "created_at", "id"])
    op.create_index("ix_auto_route_target", "auto_route", ["user_id", "mode", "target_id"])


def downgrade():
    op.drop_index("ix_auto_route_target", table_name="auto_route")
    op.drop_index("ix_auto_route_user_created", table_name="auto_route")
    op.drop_table("auto_route")
