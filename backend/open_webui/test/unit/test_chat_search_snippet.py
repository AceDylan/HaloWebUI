"""A search hit says where it is: the message that matched and the words around
it, first on the branch on screen; nothing for a title-only or tag-only match."""

import asyncio
import uuid
from types import SimpleNamespace

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat, ChatForm, Chats
from open_webui.routers.chats import search_user_chats
from open_webui.utils.chat_search import find_search_match, search_phrase


def _history(*messages, current_id):
    return {
        "history": {
            "currentId": current_id,
            "messages": {m["id"]: m for m in messages},
        }
    }


def _msg(id, parent, role, content, children=(), timestamp=0):
    return {
        "id": id,
        "parentId": parent,
        "childrenIds": list(children),
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }


def test_phrase_drops_tag_words():
    assert search_phrase("  Nginx tag:ops Reload ") == "nginx reload"
    assert search_phrase("tag:ops") == ""


def test_first_match_on_the_branch_on_screen_wins():
    chat = _history(
        _msg("u1", None, "user", "how do I reload nginx?", ["a1", "a1b"], 1),
        _msg("a1", "u1", "assistant", "Run nginx -s reload after editing.", [], 2),
        _msg("a1b", "u1", "assistant", "Older branch: nginx restart.", [], 3),
        current_id="a1",
    )

    match = find_search_match(chat, "NGINX")

    assert match["message_id"] == "u1"
    assert match["role"] == "user"
    assert match["snippet"] == "how do I reload nginx?"


def test_a_match_only_on_another_branch_is_still_found():
    chat = _history(
        _msg("u1", None, "user", "hello", ["a1", "a2"], 1),
        _msg("a1", "u1", "assistant", "hi there", [], 2),
        _msg("a2", "u1", "assistant", "regenerated: use systemctl", [], 3),
        current_id="a1",
    )

    assert find_search_match(chat, "systemctl")["message_id"] == "a2"


def test_excerpt_is_trimmed_and_skips_reasoning_markup():
    long_tail = "x" * 300
    content = (
        '<details type="reasoning"><summary>Thinking</summary>nothing here</details>\n'
        + "a" * 100
        + " the docker compose file "
        + long_tail
    )
    chat = _history(_msg("a1", None, "assistant", content), current_id="a1")

    snippet = find_search_match(chat, "docker compose")["snippet"]

    assert snippet.startswith("…") and snippet.endswith("…")
    assert "docker compose" in snippet
    assert "Thinking" not in snippet and "<" not in snippet
    assert len(snippet) < 200


def test_title_or_tag_only_matches_have_no_message():
    chat = _history(_msg("u1", None, "user", "hello"), current_id="u1")
    assert find_search_match(chat, "tag:ops") is None
    assert find_search_match(chat, "kubernetes") is None


def test_search_rows_carry_the_matched_message():
    user = f"search-snippet-{uuid.uuid4().hex[:8]}"
    chat = Chats.insert_new_chat(
        user,
        ChatForm(
            chat={
                "title": "server notes",
                **_history(
                    _msg("u1", None, "user", "what port does redis use?", ["a1"], 1),
                    _msg("a1", "u1", "assistant", "Redis listens on 6379 by default.", [], 2),
                    current_id="a1",
                ),
            }
        ),
    )
    with get_db() as db:
        db.get(Chat, chat.id).title = "server notes"
        db.commit()

    rows = asyncio.run(search_user_chats("6379", page=1, user=SimpleNamespace(id=user)))

    assert [row.id for row in rows] == [chat.id]
    assert rows[0].message_id == "a1"
    assert "6379" in rows[0].snippet

    title_rows = asyncio.run(search_user_chats("server", page=1, user=SimpleNamespace(id=user)))
    assert title_rows[0].message_id is None and title_rows[0].snippet is None
