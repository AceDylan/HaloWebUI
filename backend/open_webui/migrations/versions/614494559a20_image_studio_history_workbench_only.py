"""Image studio history: the workbench's own runs only

Revision ID: 614494559a20
Revises: d5e8f1a2b3c4
Create Date: 2026-10-10 00:00:00.000000

Images made in chats used to add a history entry (``history_chat_*``) next to
their gallery pictures. The history now lists only runs started in the
workbench; the pictures stay in the gallery.
"""

from alembic import op
import sqlalchemy as sa

revision = "614494559a20"
down_revision = "d5e8f1a2b3c4"
branch_labels = None
depends_on = None

TABLE = "image_studio_item"


def upgrade():
    conn = op.get_bind()
    if TABLE not in sa.inspect(conn).get_table_names():
        return
    items = sa.table(TABLE, sa.column("id", sa.String()), sa.column("kind", sa.String()))
    conn.execute(
        items.delete().where(
            items.c.kind == "history",
            items.c.id.startswith("history_chat_", autoescape=True),
        )
    )


def downgrade():
    # The removed entries were copies of what the gallery still has.
    pass
