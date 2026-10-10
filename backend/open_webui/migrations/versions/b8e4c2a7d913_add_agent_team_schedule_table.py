"""Add agent_team_schedule table (协作台定时)

Revision ID: b8e4c2a7d913
Revises: 614494559a20
Create Date: 2026-10-10 00:00:00.000000

One row per team that runs again on a schedule: when (daily / weekly / monthly at a
time in the owner's time zone), when it is due next, and what its last run did.
"""

from alembic import op
import sqlalchemy as sa

revision = "b8e4c2a7d913"
down_revision = "614494559a20"
branch_labels = None
depends_on = None

TABLE = "agent_team_schedule"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("team_id", sa.String(), nullable=False),
            sa.Column("freq", sa.String(), nullable=False),
            sa.Column("time", sa.String(), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=True),
            sa.Column("day", sa.Integer(), nullable=True),
            sa.Column("tz", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("next_run_at", sa.BigInteger(), nullable=True),
            sa.Column("last_run_at", sa.BigInteger(), nullable=True),
            sa.Column("last_team_id", sa.String(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_team_schedule_team", TABLE, ["team_id"], unique=True)
        op.create_index("ix_agent_team_schedule_due", TABLE, ["enabled", "next_run_at"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in inspector.get_table_names():
        op.drop_index("ix_agent_team_schedule_due", table_name=TABLE)
        op.drop_index("ix_agent_team_schedule_team", table_name=TABLE)
        op.drop_table(TABLE)
