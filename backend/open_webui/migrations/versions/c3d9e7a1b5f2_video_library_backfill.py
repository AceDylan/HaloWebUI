"""Video library: the videos Hermes handed over before the library existed

Revision ID: c3d9e7a1b5f2
Revises: a7d93e5f8102
Create Date: 2026-10-16 00:00:00.000000

From now on a video Hermes or a runner hands over is written into the video library as it
is stored (utils/video_library.py). The ones stored before are added here: every file whose
meta says it came from Hermes (``data.source == "hermes-agent"``) and is a video. The row
shape and id mirror video_library.video_form at this revision (one row per name + size, so
a video fetched again after a reconnect is listed once).
"""

import hashlib
import json
import os
import time

from alembic import op
import sqlalchemy as sa

revision = "c3d9e7a1b5f2"
down_revision = "a7d93e5f8102"
branch_labels = None
depends_on = None

TABLE = "image_studio_item"


def _meta(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def upgrade():
    conn = op.get_bind()
    tables = sa.inspect(conn).get_table_names()
    if TABLE not in tables or "file" not in tables:
        return
    files = sa.table(
        "file",
        sa.column("id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("filename", sa.Text()),
        sa.column("meta", sa.JSON()),
        sa.column("created_at", sa.BigInteger()),
    )
    items = sa.table(
        TABLE,
        sa.column("id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("data", sa.JSON()),
        sa.column("created_at", sa.BigInteger()),
        sa.column("updated_at", sa.BigInteger()),
    )
    rows = {}
    # oldest first: the first copy keeps the date the video was made, the latest copy is shown
    for file in sorted(conn.execute(sa.select(files)).fetchall(), key=lambda f: f.created_at or 0):
        meta = _meta(file.meta)
        data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        content_type = str(meta.get("content_type") or "")
        if data.get("source") != "hermes-agent" or not content_type.startswith("video/"):
            continue
        name = os.path.basename(str(meta.get("name") or file.filename or "").strip()) or "video.mp4"
        size = int(meta.get("size") or 0)
        item_id = "video_" + hashlib.sha1(f"{name}\0{size}".encode("utf-8")).hexdigest()[:24]
        chat_id = str(data.get("chat_id") or "").strip()
        latest = {"fileId": file.id, "url": f"/api/v1/files/{file.id}/content"}
        if chat_id and not chat_id.startswith("local:"):
            latest["chatId"] = chat_id
        key = (file.user_id, item_id)
        if key in rows:
            rows[key]["data"].update(latest)
            continue
        created = int(file.created_at or time.time())
        rows[key] = {
            "created_at": created,
            "data": {
                "id": item_id,
                **latest,
                "name": name,
                "title": os.path.splitext(name)[0] or name,
                "size": size,
                "contentType": content_type,
                "origin": data.get("origin") or "hermes",
                "createdAt": created * 1000,
            },
        }

    if not rows:
        return
    existing = {
        (row.user_id, row.id)
        for row in conn.execute(sa.select(items.c.user_id, items.c.id).where(items.c.kind == "video"))
    }
    now = int(time.time())
    values = [
        {
            "id": item_id,
            "user_id": user_id,
            "kind": "video",
            "data": row["data"],
            "created_at": row["created_at"],
            "updated_at": now,
        }
        for (user_id, item_id), row in rows.items()
        if (user_id, item_id) not in existing
    ]
    if values:
        op.bulk_insert(items, values)


def downgrade():
    conn = op.get_bind()
    if TABLE not in sa.inspect(conn).get_table_names():
        return
    items = sa.table(TABLE, sa.column("kind", sa.String()))
    conn.execute(items.delete().where(items.c.kind == "video"))
