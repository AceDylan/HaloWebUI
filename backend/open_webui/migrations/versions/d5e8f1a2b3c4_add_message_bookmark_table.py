"""Add message_bookmark table (收藏)

Revision ID: d5e8f1a2b3c4
Revises: c3f8a2d6e1b7
Create Date: 2026-10-08 00:00:00.000000

One row per reply a person keeps: the chat and message it points at and a short
excerpt taken when it was saved.
"""

from alembic import op
import sqlalchemy as sa

revision = "d5e8f1a2b3c4"
down_revision = "c3f8a2d6e1b7"
branch_labels = None
depends_on = None

TABLE = "message_bookmark"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("chat_id", sa.String(), nullable=False),
            sa.Column("message_id", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("excerpt", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_message_bookmark_user_created", TABLE, ["user_id", "created_at"])
        op.create_index(
            "ix_message_bookmark_user_chat_message",
            TABLE,
            ["user_id", "chat_id", "message_id"],
            unique=True,
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in inspector.get_table_names():
        op.drop_index("ix_message_bookmark_user_chat_message", table_name=TABLE)
        op.drop_index("ix_message_bookmark_user_created", table_name=TABLE)
        op.drop_table(TABLE)
