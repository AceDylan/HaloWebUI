"""Add image_studio_item table

Revision ID: 8f2a1c3d4e5b
Revises: 4c8d9e0f1a2b
Create Date: 2026-09-12 00:00:00.000000

Workspace image studio templates, gallery and generation history move from
browser localStorage into this per-user table.
"""

from alembic import op
import sqlalchemy as sa

revision = "8f2a1c3d4e5b"
down_revision = "4c8d9e0f1a2b"
branch_labels = None
depends_on = None

TABLE = "image_studio_item"
INDEX = "ix_image_studio_item_user_kind_created"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("id", "user_id"),
        )

    inspector = sa.inspect(conn)
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if INDEX not in existing_indexes:
        op.create_index(INDEX, TABLE, ["user_id", "kind", "created_at"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if TABLE in inspector.get_table_names():
        existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
        if INDEX in existing_indexes:
            op.drop_index(INDEX, table_name=TABLE)
        op.drop_table(TABLE)
