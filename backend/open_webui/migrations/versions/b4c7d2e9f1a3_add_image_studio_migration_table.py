"""Add image_studio_migration table

Revision ID: b4c7d2e9f1a3
Revises: 8f2a1c3d4e5b
Create Date: 2026-09-12 00:00:00.000000

One row per user records that the account's one-time upload of browser-local
(legacy localStorage) image studio data is over, so stale browser copies can
never re-create templates that were deleted on the server.
"""

from alembic import op
import sqlalchemy as sa

revision = "b4c7d2e9f1a3"
down_revision = "8f2a1c3d4e5b"
branch_labels = None
depends_on = None

TABLE = "image_studio_migration"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("uploaded", sa.Integer(), nullable=False),
            sa.Column("migrated_at", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("user_id"),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
