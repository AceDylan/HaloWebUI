"""Archive chats nobody touched for a while — per user, opt-in, reversible.

Each user turns it on in Settings > Interface ("Auto-archive inactive chats")
and picks the number of days; the setting lives in
``user.settings.ui.chatAutoArchive = {"enabled": bool, "days": int}``. Nothing
happens for users who did not opt in.

"Inactive" means the chat's last activity (``updated_at``: last message, rename,
move, unarchive) is older than the cutoff — not its creation date. Pinned chats
are never archived. Archived chats stay in "Archived Chats" and can be brought
back one by one, all at once, or — only the ones this sweep archived — with
:func:`restore_auto_archived_chats`, which leaves manual archives alone.

The sweep runs inside the app (:func:`periodic_chat_auto_archive`, started
from the lifespan) every ``CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL`` seconds; the same
:func:`archive_inactive_chats` also backs the "archive now" button.
"""

import asyncio
import logging
import time
from typing import Optional

from open_webui.env import (
    CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL,
    CHAT_AUTO_ARCHIVE_STARTUP_DELAY,
    SRC_LOG_LEVELS,
)
from open_webui.models.chats import AUTO_ARCHIVE_META_KEY, Chats
from open_webui.models.tags import Tags
from open_webui.models.users import Users

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

SETTINGS_KEY = "chatAutoArchive"
DEFAULT_INACTIVE_DAYS = 30
MIN_INACTIVE_DAYS = 1
MAX_INACTIVE_DAYS = 3650
SECONDS_PER_DAY = 24 * 60 * 60


def normalize_inactive_days(value) -> Optional[int]:
    """A whole number of days within the allowed range, else None."""
    if isinstance(value, bool):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    if days < MIN_INACTIVE_DAYS or days > MAX_INACTIVE_DAYS:
        return None
    return days


def get_auto_archive_policy(settings) -> Optional[int]:
    """Days of inactivity after which the user's chats get archived, or None
    when the user has not opted in (or the stored value is unusable).

    Accepts the ``UserSettings`` model or its dict form."""
    if settings is None:
        return None
    ui = settings.get("ui") if isinstance(settings, dict) else getattr(settings, "ui", None)
    if not isinstance(ui, dict):
        return None
    policy = ui.get(SETTINGS_KEY)
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return None
    return normalize_inactive_days(policy.get("days", DEFAULT_INACTIVE_DAYS))


def _last_activity(chat) -> int:
    meta = chat.meta if isinstance(chat.meta, dict) else {}
    marker = meta.get(AUTO_ARCHIVE_META_KEY)
    restored_at = marker.get("restored_at") if isinstance(marker, dict) else None
    try:
        restored_at = int(restored_at or 0)
    except (TypeError, ValueError):
        restored_at = 0
    return max(int(chat.updated_at or 0), restored_at)


def select_inactive_chat_ids(chats, cutoff: int) -> list[str]:
    """The chats whose last activity — including a restore by this sweep's
    undo — is older than ``cutoff``."""
    return [chat.id for chat in chats if _last_activity(chat) < cutoff]


def _drop_orphaned_tags(chats, archived_ids, user_id: str) -> None:
    # Same bookkeeping as the manual archive route: a tag with no visible
    # chat left disappears from the tag list.
    archived = set(archived_ids)
    tag_names = set()
    for chat in chats:
        if chat.id not in archived:
            continue
        meta = chat.meta if isinstance(chat.meta, dict) else {}
        for tag in meta.get("tags", []) or []:
            tag_names.add(tag)
    for tag in tag_names:
        try:
            if Chats.count_chats_by_tag_name_and_user_id(tag, user_id) == 0:
                Tags.delete_tag_by_name_and_user_id(tag, user_id)
        except Exception as e:
            log.debug(f"auto-archive tag cleanup skipped for {tag!r}: {e}")


def archive_inactive_chats(
    user_id: str, days: int, *, now: Optional[int] = None, dry_run: bool = False
) -> dict:
    """Archive ``user_id``'s chats idle for ``days`` days. ``dry_run`` only
    counts. Returns ``{"days", "cutoff", "count", "chat_ids", "dry_run"}``."""
    days = normalize_inactive_days(days)
    if days is None:
        raise ValueError("days out of range")
    now = int(now if now is not None else time.time())
    cutoff = now - days * SECONDS_PER_DAY
    candidates = Chats.get_inactive_chats_by_user_id(user_id, cutoff)
    chat_ids = select_inactive_chat_ids(candidates, cutoff)
    result = {
        "days": days,
        "cutoff": cutoff,
        "count": len(chat_ids),
        "chat_ids": chat_ids,
        "dry_run": dry_run,
    }
    if dry_run or not chat_ids:
        return result
    archived = Chats.archive_chats_by_ids_and_user_id(
        chat_ids,
        user_id,
        {"archived_at": now, "days": days, "reason": "inactive"},
    )
    result["count"] = archived
    _drop_orphaned_tags(candidates, chat_ids, user_id)
    return result


def restore_auto_archived_chats(user_id: str, *, now: Optional[int] = None) -> dict:
    """Undo the sweep for ``user_id``: unarchive only the chats it archived.
    Returns ``{"count", "chat_ids"}``."""
    now = int(now if now is not None else time.time())
    restored = Chats.restore_auto_archived_chats_by_user_id(user_id, now)
    for item in restored:
        for tag_id in item.get("tags") or []:
            try:
                if Tags.get_tag_by_name_and_user_id(tag_id, user_id) is None:
                    Tags.insert_new_tag(tag_id, user_id)
            except Exception as e:
                log.debug(f"auto-archive tag restore skipped for {tag_id!r}: {e}")
    return {"count": len(restored), "chat_ids": [item["id"] for item in restored]}


def sweep_all_users(now: Optional[int] = None) -> dict:
    """One pass over every user who opted in. Returns ``{user_id: archived}``
    for the users where something was archived."""
    summary = {}
    for user in Users.get_users():
        days = get_auto_archive_policy(getattr(user, "settings", None))
        if days is None:
            continue
        try:
            result = archive_inactive_chats(user.id, days, now=now)
        except Exception:
            log.exception(f"chat auto-archive failed for user {user.id}")
            continue
        if result["count"]:
            summary[user.id] = result["count"]
            log.info(
                f"chat auto-archive: archived {result['count']} chat(s) idle for "
                f"{days} day(s) for user {user.id}"
            )
    return summary


async def periodic_chat_auto_archive() -> None:
    """Background loop started from the app lifespan."""
    interval = CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL
    if interval <= 0:
        log.info("chat auto-archive sweep disabled (CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL=0)")
        return
    await asyncio.sleep(max(0, CHAT_AUTO_ARCHIVE_STARTUP_DELAY))
    while True:
        try:
            await asyncio.to_thread(sweep_all_users)
        except Exception:
            log.exception("chat auto-archive sweep failed")
        await asyncio.sleep(interval)
