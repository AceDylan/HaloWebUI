"""Add agent_team table (协作台)

Revision ID: c3f8a2d6e1b7
Revises: b4c7d2e9f1a3
Create Date: 2026-10-02 00:00:00.000000

One row per collaboration task: owner, originating chat, the lead's plan before approval and
the Hermes Kanban board it runs on afterwards. Tasks and events stay on the Kanban board.
"""

from alembic import op
import sqlalchemy as sa

revision = "c3f8a2d6e1b7"
down_revision = "b4c7d2e9f1a3"
branch_labels = None
depends_on = None

TABLE = "agent_team"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("chat_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("phase", sa.String(), nullable=True),
            sa.Column("plan", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("board", sa.String(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            sa.Column("approved_at", sa.BigInteger(), nullable=True),
            sa.Column("finished_at", sa.BigInteger(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_team_user_updated", TABLE, ["user_id", "updated_at"])
        op.create_index("ix_agent_team_user_chat", TABLE, ["user_id", "chat_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in inspector.get_table_names():
        op.drop_index("ix_agent_team_user_chat", table_name=TABLE)
        op.drop_index("ix_agent_team_user_updated", table_name=TABLE)
        op.drop_table(TABLE)
