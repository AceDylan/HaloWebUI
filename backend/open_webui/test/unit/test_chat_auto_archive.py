"""Inactivity auto-archive: per-user opt-in, last-activity cutoff, pinned and
other users untouched, dry run reads only, undo restores just its own work."""

import time
import uuid
from types import SimpleNamespace

import pytest

from open_webui.internal.db import get_db
from open_webui.models.chats import AUTO_ARCHIVE_META_KEY, Chat, ChatForm, Chats
from open_webui.models.users import UserSettings
from open_webui.utils import chat_auto_archive as auto

DAY = auto.SECONDS_PER_DAY
NOW = int(time.time())


def _user(label: str) -> str:
    # The unit DB persists between runs: fresh ids keep earlier runs' rows out.
    return f"auto-archive-{label}-{uuid.uuid4().hex[:8]}"


def _chat(user_id, title, *, age_days, pinned=False):
    chat = Chats.insert_new_chat(user_id, ChatForm(chat={"title": title}))
    assert chat is not None
    with get_db() as db:
        row = db.get(Chat, chat.id)
        row.updated_at = NOW - age_days * DAY
        row.pinned = pinned
        db.commit()
    return chat.id


def _state(chat_id):
    chat = Chats.get_chat_by_id(chat_id)
    return chat.archived, chat.updated_at, (chat.meta or {}).get(AUTO_ARCHIVE_META_KEY)


def test_policy_requires_an_explicit_opt_in_and_a_usable_day_count():
    assert auto.get_auto_archive_policy(None) is None
    assert auto.get_auto_archive_policy({}) is None
    assert auto.get_auto_archive_policy({"ui": {}}) is None
    assert auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": False}}}) is None
    assert auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": "yes"}}}) is None
    assert auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": True}}}) == 30
    assert (
        auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": True, "days": 45}}})
        == 45
    )
    assert (
        auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": True, "days": 0}}})
        is None
    )
    assert (
        auto.get_auto_archive_policy({"ui": {"chatAutoArchive": {"enabled": True, "days": "x"}}})
        is None
    )
    settings = UserSettings(ui={"chatAutoArchive": {"enabled": True, "days": "7"}})
    assert auto.get_auto_archive_policy(settings) == 7


def test_archive_inactive_chats_uses_last_activity_and_skips_pinned_and_other_users():
    user = _user("last-activity")
    old = _chat(user, "old", age_days=40)
    recent = _chat(user, "recent", age_days=2)
    old_pinned = _chat(user, "old pinned", age_days=40, pinned=True)
    someone_elses = _chat(_user("other"), "theirs", age_days=40)

    preview = auto.archive_inactive_chats(user, 30, now=NOW, dry_run=True)
    assert preview["count"] == 1 and preview["chat_ids"] == [old]
    assert _state(old)[0] is False  # a dry run writes nothing

    result = auto.archive_inactive_chats(user, 30, now=NOW)
    assert result["count"] == 1
    archived, updated_at, marker = _state(old)
    assert archived is True
    assert updated_at == NOW - 40 * DAY  # archived list keeps the real order
    assert marker == {"archived_at": NOW, "days": 30, "reason": "inactive"}
    assert _state(recent)[0] is False
    assert _state(old_pinned)[0] is False
    assert _state(someone_elses)[0] is False

    # Idempotent: a second pass finds nothing left to do.
    assert auto.archive_inactive_chats(user, 30, now=NOW)["count"] == 0


def test_restore_undoes_only_the_sweeps_archives_and_counts_as_activity():
    user = _user("restore")
    swept = _chat(user, "swept", age_days=60)
    by_hand = _chat(user, "by hand", age_days=60)
    Chats.toggle_chat_archive_by_id(by_hand)
    assert _state(by_hand)[0] is True

    assert auto.archive_inactive_chats(user, 30, now=NOW)["count"] == 1
    assert _state(swept)[0] is True

    restored = auto.restore_auto_archived_chats(user, now=NOW)
    assert restored == {"count": 1, "chat_ids": [swept]}
    archived, _updated_at, marker = _state(swept)
    assert archived is False
    assert marker["restored_at"] == NOW
    assert _state(by_hand)[0] is True  # manual archive left alone

    # The restore is treated as activity: the next pass leaves the chat alone
    # until the cutoff moves past the restore time.
    assert auto.archive_inactive_chats(user, 30, now=NOW + DAY)["count"] == 0
    assert auto.archive_inactive_chats(user, 30, now=NOW + 31 * DAY)["count"] == 1


def test_archive_rejects_days_out_of_range():
    with pytest.raises(ValueError):
        auto.archive_inactive_chats(_user("range"), 0, now=NOW)


def test_sweep_only_touches_users_who_opted_in(monkeypatch):
    opted_in = _user("opted-in")
    opted_out = _user("opted-out")
    mine = _chat(opted_in, "mine", age_days=20)
    theirs = _chat(opted_out, "theirs", age_days=20)

    monkeypatch.setattr(
        auto.Users,
        "get_users",
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=opted_in,
                settings=UserSettings(ui={"chatAutoArchive": {"enabled": True, "days": 10}}),
            ),
            SimpleNamespace(id=opted_out, settings=UserSettings(ui={})),
            SimpleNamespace(id=_user("no-settings"), settings=None),
        ],
    )

    assert auto.sweep_all_users(now=NOW) == {opted_in: 1}
    assert _state(mine)[0] is True
    assert _state(theirs)[0] is False


# One-question test chats ("你好", "你能做什么") -------------------------------


def _conversation_chat(user_id, prompts, *, age_days, pinned=False, reply="好的"):
    """A chat whose history holds ``prompts`` as user turns, each answered."""
    messages = {}
    parent = None
    for index, prompt in enumerate(prompts):
        user_id_msg = f"u{index}-{uuid.uuid4().hex[:6]}"
        reply_id = f"a{index}-{uuid.uuid4().hex[:6]}"
        messages[user_id_msg] = {
            "id": user_id_msg,
            "parentId": parent,
            "childrenIds": [reply_id],
            "role": "user",
            "content": prompt,
            "timestamp": NOW - age_days * DAY,
        }
        messages[reply_id] = {
            "id": reply_id,
            "parentId": user_id_msg,
            "childrenIds": [],
            "role": "assistant",
            "content": reply,
            "timestamp": NOW - age_days * DAY,
        }
        parent = reply_id
    chat = Chats.insert_new_chat(
        user_id,
        ChatForm(chat={"title": "t", "history": {"messages": messages, "currentId": parent}}),
    )
    assert chat is not None
    with get_db() as db:
        row = db.get(Chat, chat.id)
        row.updated_at = NOW - age_days * DAY
        row.pinned = pinned
        db.commit()
    return chat.id


@pytest.mark.parametrize(
    "prompt",
    [
        "你好",
        "你能做什么",
        "你能做什么？",
        "你能做什么呢",
        "你好 你能做什么？",
        "你是谁 你能做什么呢",
        "你擅长什么？",
        "/codex\n任务：\n你能做什么",
        "Hello!",
        "hi 👋",
        "测试",
    ],
)
def test_test_prompts_are_recognised(prompt):
    assert auto.is_test_prompt(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "",
        "   ",
        "生命的意义是什么",
        "贴吧消息",
        "你好，帮我写一个九九乘法表",
        "tibo是谁",
        "/codex\n任务：\n查下gpt-6什么时候上线",
        "testing the parser",
        "你能做什么" * 20,
        None,
    ],
)
def test_real_questions_are_not_test_prompts(prompt):
    assert auto.is_test_prompt(prompt) is False


def test_test_chat_policy_follows_the_inactivity_switch_until_set():
    assert auto.get_test_chat_policy(None) is False
    assert auto.get_test_chat_policy({"ui": {}}) is False
    assert auto.get_test_chat_policy({"ui": {"chatAutoArchive": {"enabled": True}}}) is True
    assert auto.get_test_chat_policy({"ui": {"chatAutoArchive": {"enabled": False}}}) is False
    assert (
        auto.get_test_chat_policy(
            {"ui": {"chatAutoArchive": {"enabled": True, "testChats": False}}}
        )
        is False
    )
    assert (
        auto.get_test_chat_policy(
            UserSettings(ui={"chatAutoArchive": {"enabled": False, "testChats": True}})
        )
        is True
    )


def test_archive_test_chats_takes_only_idle_one_question_greetings():
    user = _user("test-chats")
    greeting = _conversation_chat(user, ["你能做什么？"], age_days=2)
    fresh = _conversation_chat(user, ["你好"], age_days=0)
    real = _conversation_chat(user, ["今年国庆武夷山有什么好玩的"], age_days=2)
    follow_up = _conversation_chat(user, ["你好", "帮我查下天气"], age_days=2)
    pinned = _conversation_chat(user, ["你好"], age_days=2, pinned=True)
    theirs = _conversation_chat(_user("test-chats-other"), ["你好"], age_days=2)

    preview = auto.archive_test_chats(user, now=NOW, dry_run=True)
    assert preview["chat_ids"] == [greeting]
    assert _state(greeting)[0] is False  # a dry run writes nothing

    result = auto.archive_test_chats(user, now=NOW)
    assert result["count"] == 1
    archived, updated_at, marker = _state(greeting)
    assert archived is True
    assert updated_at == NOW - 2 * DAY
    assert marker == {"archived_at": NOW, "reason": "test"}
    for chat_id in (fresh, real, follow_up, pinned, theirs):
        assert _state(chat_id)[0] is False

    # "Restore auto-archived chats" brings it back as well.
    assert greeting in auto.restore_auto_archived_chats(user, now=NOW)["chat_ids"]


def test_archive_test_chats_skips_shared_chats_and_counts_a_restore_as_activity():
    user = _user("test-chats-shared")
    shared = _conversation_chat(user, ["你好"], age_days=3)
    with get_db() as db:
        db.get(Chat, shared).share_id = f"share-{uuid.uuid4().hex[:8]}"
        db.commit()
    restored = _conversation_chat(user, ["你能做什么"], age_days=3)
    assert auto.archive_test_chats(user, now=NOW)["chat_ids"] == [restored]
    auto.restore_auto_archived_chats(user, now=NOW)
    assert auto.archive_test_chats(user, now=NOW + DAY // 2)["count"] == 0
    assert auto.archive_test_chats(user, now=NOW + 2 * DAY)["chat_ids"] == [restored]


def test_sweep_archives_test_chats_for_users_who_want_it(monkeypatch):
    wants = _user("sweep-test-wants")
    declined = _user("sweep-test-declined")
    mine = _conversation_chat(wants, ["你好"], age_days=3)
    theirs = _conversation_chat(declined, ["你好"], age_days=3)

    monkeypatch.setattr(
        auto.Users,
        "get_users",
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=wants,
                settings=UserSettings(ui={"chatAutoArchive": {"testChats": True}}),
            ),
            SimpleNamespace(
                id=declined,
                settings=UserSettings(
                    ui={"chatAutoArchive": {"enabled": True, "days": 30, "testChats": False}}
                ),
            ),
        ],
    )

    assert auto.sweep_all_users(now=NOW) == {wants: 1}
    assert _state(mine)[0] is True
    assert _state(theirs)[0] is False
