"""Where a search hit is inside a chat: the message and a short excerpt around it.

The search query (models/chats.py `get_chats_by_user_id_and_search_text`)
already matched the words somewhere in the title or a message; this finds the
message again so the sidebar can show the words in context and open the chat
at that message. The rows are already loaded, so this costs no extra query.

The first match on the branch on screen wins (where the topic started); a
match only on another branch is used when the branch on screen has none.
"""

import re
from typing import Any, Optional

SNIPPET_BEFORE = 36
SNIPPET_AFTER = 84

# Reasoning and tool-call blocks are markup around the answer, not what the
# person remembers reading; the excerpt drops them unless the match is inside.
_DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>\n]{1,500}>")
_WS_RE = re.compile(r"\s+")


def search_phrase(raw: str) -> str:
    """The text part of a search, as the query matches it (lower case, no `tag:` words)."""
    words = (raw or "").lower().strip().split(" ")
    return " ".join(word for word in words if not word.startswith("tag:")).strip()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _excerpt(content: str, phrase: str) -> Optional[str]:
    for text in (_TAG_RE.sub(" ", _DETAILS_RE.sub(" ", content)), _TAG_RE.sub(" ", content)):
        flat = _WS_RE.sub(" ", text).strip()
        index = flat.lower().find(phrase)
        if index < 0:
            continue
        start = max(0, index - SNIPPET_BEFORE)
        end = min(len(flat), index + len(phrase) + SNIPPET_AFTER)
        return (
            ("…" if start > 0 else "")
            + flat[start:end].strip()
            + ("…" if end < len(flat) else "")
        )
    return None


def _ordered_messages(chat: dict) -> list[dict]:
    history = chat.get("history") if isinstance(chat.get("history"), dict) else None
    messages = history.get("messages") if history else None
    if not isinstance(messages, dict):
        legacy = chat.get("messages")
        return [m for m in legacy if isinstance(m, dict)] if isinstance(legacy, list) else []

    branch: list[dict] = []
    seen: set[str] = set()
    current = history.get("currentId")
    while isinstance(current, str) and current in messages and current not in seen:
        seen.add(current)
        message = messages[current]
        if not isinstance(message, dict):
            break
        branch.append({**message, "id": message.get("id") or current})
        current = message.get("parentId")
    branch.reverse()

    others = sorted(
        (
            {**message, "id": message.get("id") or message_id}
            for message_id, message in messages.items()
            if message_id not in seen and isinstance(message, dict)
        ),
        key=lambda message: message.get("timestamp") or 0,
    )
    return branch + others


def find_search_match(chat: Any, raw_search: str) -> Optional[dict]:
    """``{"message_id", "role", "snippet"}`` for the first message containing the
    search phrase, or None (a title-only or tag-only match)."""
    phrase = search_phrase(raw_search)
    if not phrase or not isinstance(chat, dict):
        return None

    for message in _ordered_messages(chat):
        content = _text(message.get("content"))
        if phrase not in content.lower():
            continue
        snippet = _excerpt(content, phrase)
        if snippet:
            return {
                "message_id": message.get("id"),
                "role": message.get("role"),
                "snippet": snippet,
            }
    return None
