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

The same sweep also archives test chats (:func:`archive_test_chats`): a chat
whose only question is a greeting or "what can you do" ("你好", "你能做什么？",
"/codex 任务：你能做什么"), idle for a day — typically a check after a deploy.
It follows ``chatAutoArchive.testChats`` and, while that is unset, the
inactivity switch. Same marker, so "restore" brings these back too.

The sweep runs inside the app (:func:`periodic_chat_auto_archive`, started
from the lifespan) every ``CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL`` seconds; the same
:func:`archive_inactive_chats` also backs the "archive now" button.
"""

import asyncio
import logging
import re
import time
from types import SimpleNamespace
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
TEST_CHATS_KEY = "testChats"
DEFAULT_INACTIVE_DAYS = 30
MIN_INACTIVE_DAYS = 1
MAX_INACTIVE_DAYS = 3650
TEST_CHAT_IDLE_DAYS = 1
SECONDS_PER_DAY = 24 * 60 * 60

# A test question: greetings and "who are you / what can you do", in any
# combination, optionally after a runner command ("/codex 任务：…"). Matched
# against the prompt with whitespace and punctuation removed, lowercased.
_TEST_GREETING = r"(?:你好|您好|哈喽|嗨|hi|hello|hey|在吗|在么|在不在|测试一下|测试|test|ping)"
_TEST_QUESTION = (
    r"(?:你是谁|你叫什么|你能做什么|你能干什么|你可以做什么|你可以干什么|你会做什么|你会干什么"
    r"|你会什么|你擅长什么|你有什么功能|你有哪些功能|你有什么能力|你有哪些能力|你能帮我做什么"
    r"|介绍一下你自己|介绍下你自己|介绍一下自己|自我介绍一下|自我介绍"
    r"|whoareyou|whatcanyoudo)"
)
_TEST_PARTICLE = r"(?:呢|呀|啊|吗|吧|哈|啦)*"
_TEST_PROMPT_RE = re.compile(
    rf"(?:/[a-z][a-z0-9_-]*(?:任务)?)?(?:(?:{_TEST_GREETING}|{_TEST_QUESTION}){_TEST_PARTICLE})+"
)
_PROMPT_NOISE_RE = re.compile(r"[\s\W_]+", re.UNICODE)
TEST_PROMPT_MAX_LENGTH = 80


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


def is_test_prompt(text) -> bool:
    """Whether ``text`` is nothing but a greeting / capability question."""
    if not isinstance(text, str) or not text.strip():
        return False
    if len(text) > TEST_PROMPT_MAX_LENGTH:
        return False
    compact = _PROMPT_NOISE_RE.sub("", text.lower())
    # "/codex" loses its slash with the punctuation; put it back for the regex.
    if text.lstrip().startswith("/"):
        compact = "/" + compact
    return bool(compact) and _TEST_PROMPT_RE.fullmatch(compact) is not None


def get_test_chat_policy(settings) -> bool:
    """Whether the user's one-question test chats get archived: the explicit
    ``chatAutoArchive.testChats`` switch, else the inactivity switch."""
    if settings is None:
        return False
    ui = settings.get("ui") if isinstance(settings, dict) else getattr(settings, "ui", None)
    if not isinstance(ui, dict):
        return False
    policy = ui.get(SETTINGS_KEY)
    if not isinstance(policy, dict):
        return False
    value = policy.get(TEST_CHATS_KEY)
    if isinstance(value, bool):
        return value
    return policy.get("enabled") is True


def _user_prompts(data) -> Optional[list[str]]:
    """The user messages of a chat's saved history, or None when the history
    is unreadable."""
    history = data.get("history") if isinstance(data, dict) else None
    messages = history.get("messages") if isinstance(history, dict) else None
    if not isinstance(messages, dict):
        return None
    prompts = []
    for message in messages.values():
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            prompts.append(content if isinstance(content, str) else "")
    return prompts


def archive_test_chats(
    user_id: str, *, now: Optional[int] = None, dry_run: bool = False
) -> dict:
    """Archive ``user_id``'s one-question test chats idle for a day: exactly
    one user message in the saved history, and that message a test question.
    Pinned and shared chats are kept. Returns ``{"count", "chat_ids",
    "dry_run"}``."""
    now = int(now if now is not None else time.time())
    cutoff = now - TEST_CHAT_IDLE_DAYS * SECONDS_PER_DAY
    chats = []
    for chat_id, data, updated_at, meta in Chats.iter_idle_unshared_chats_by_user_id(
        user_id, cutoff
    ):
        prompts = _user_prompts(data)
        if prompts is None or len(prompts) != 1 or not is_test_prompt(prompts[0]):
            continue
        chat = SimpleNamespace(id=chat_id, updated_at=updated_at, meta=meta)
        # A restore by the undo button counts as activity, as for inactivity.
        if _last_activity(chat) >= cutoff:
            continue
        chats.append(chat)
    chat_ids = [chat.id for chat in chats]
    result = {"count": len(chat_ids), "chat_ids": chat_ids, "dry_run": dry_run}
    if dry_run or not chat_ids:
        return result
    result["count"] = Chats.archive_chats_by_ids_and_user_id(
        chat_ids, user_id, {"archived_at": now, "reason": "test"}
    )
    _drop_orphaned_tags(chats, chat_ids, user_id)
    return result


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
        settings = getattr(user, "settings", None)
        archived = 0
        days = get_auto_archive_policy(settings)
        if days is not None:
            try:
                result = archive_inactive_chats(user.id, days, now=now)
            except Exception:
                log.exception(f"chat auto-archive failed for user {user.id}")
            else:
                archived += result["count"]
                if result["count"]:
                    log.info(
                        f"chat auto-archive: archived {result['count']} chat(s) idle "
                        f"for {days} day(s) for user {user.id}"
                    )
        if get_test_chat_policy(settings):
            try:
                result = archive_test_chats(user.id, now=now)
            except Exception:
                log.exception(f"test chat auto-archive failed for user {user.id}")
            else:
                archived += result["count"]
                if result["count"]:
                    log.info(
                        f"chat auto-archive: archived {result['count']} one-question "
                        f"test chat(s) for user {user.id}"
                    )
        if archived:
            summary[user.id] = archived
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
