"""Recover reasoning/answer text from relays that stringify typed content chunks.

Mistral's reasoning models (``mistral-large-latest``, Magistral, ...) stream
``delta.content`` as a *list* of typed chunks instead of a string::

    [{"type": "thinking", "thinking": [{"type": "text", "text": "..."}], "closed": true}]
    [{"type": "thinking", ...}, {"type": "text", "text": "Hello"}]
    "plain text from here on"

Relays that only expect strings (CPA's OpenAI -> Gemini translator, and CCHP
converting that back to OpenAI) ``json.dumps`` the list and pass it on as
ordinary text, so the chat showed raw JSON with the model's thinking mixed in.

``StringifiedChunkDecoder`` peels those leading arrays off a text fragment and
returns the thinking and the answer separately. It only acts on arrays made
entirely of known chunk shapes, and a text-only array is accepted only after
the same stream has already produced a thinking array, so an answer that
merely *talks about* this JSON format is left alone.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_ARRAY_START_RE = re.compile(r'\[\s*\{\s*"type"\s*:\s*"')
_REASONING_TYPES = frozenset({"thinking", "reasoning"})
_TEXT_TYPES = frozenset({"text"})
# Chunk types that carry nothing to show; dropped instead of rejecting the array.
_IGNORED_TYPES = frozenset({"reference"})

_json_decoder = json.JSONDecoder()


def _chunk_text(value: Any) -> Optional[str]:
    """Text inside a chunk's payload: a string, or a list of text chunks."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            if isinstance(item, str):
                pieces.append(item)
                continue
            if not isinstance(item, dict):
                return None
            if item.get("type") not in (None, "text"):
                return None
            text = item.get("text")
            if not isinstance(text, str):
                return None
            pieces.append(text)
        return "".join(pieces)
    return None


def parse_content_chunk_list(value: Any) -> Optional[tuple[str, str, bool]]:
    """Split a typed chunk list into ``(reasoning, text, has_reasoning)``.

    Returns ``None`` unless every item is a recognised chunk, so arbitrary JSON
    lists are never rewritten.
    """
    if not isinstance(value, list) or not value:
        return None

    reasoning: list[str] = []
    text: list[str] = []
    has_reasoning = False
    for item in value:
        if not isinstance(item, dict):
            return None
        item_type = item.get("type")
        if item_type in _REASONING_TYPES:
            payload = item.get(item_type)
            if payload is None:
                payload = item.get("text")
            piece = _chunk_text(payload)
            if piece is None:
                return None
            reasoning.append(piece)
            has_reasoning = True
        elif item_type in _TEXT_TYPES:
            piece = item.get("text")
            if not isinstance(piece, str):
                return None
            text.append(piece)
        elif item_type in _IGNORED_TYPES:
            continue
        else:
            return None
    return "".join(reasoning), "".join(text), has_reasoning


class StringifiedChunkDecoder:
    """Per-response decoder; keep one instance for the whole stream."""

    __slots__ = ("active",)

    def __init__(self) -> None:
        # True once this response has produced a stringified thinking array.
        self.active = False

    def split(self, text: Any) -> tuple[str, str]:
        """Return ``(reasoning, content)`` for one text fragment."""
        if not isinstance(text, str) or not text.startswith("["):
            return "", text if isinstance(text, str) else ""
        if not _ARRAY_START_RE.match(text):
            return "", text

        reasoning: list[str] = []
        content: list[str] = []
        saw_reasoning = False
        pos = 0
        length = len(text)
        while pos < length and _ARRAY_START_RE.match(text, pos):
            try:
                value, end = _json_decoder.raw_decode(text, pos)
            except ValueError:
                break
            parsed = parse_content_chunk_list(value)
            if parsed is None:
                break
            chunk_reasoning, chunk_text, has_reasoning = parsed
            reasoning.append(chunk_reasoning)
            content.append(chunk_text)
            saw_reasoning = saw_reasoning or has_reasoning
            pos = end

        if pos == 0 or not (saw_reasoning or self.active):
            return "", text

        self.active = True
        content.append(text[pos:])
        return "".join(reasoning), "".join(content)


def split_stringified_chunks(text: Any) -> tuple[str, str]:
    """One-shot ``(reasoning, content)`` split for a complete response text."""
    return StringifiedChunkDecoder().split(text)


def _merge_reasoning(target: dict, reasoning: str) -> None:
    if not reasoning:
        return
    existing = target.get("reasoning_content")
    if isinstance(existing, str) and existing:
        target["reasoning_content"] = existing + reasoning
    else:
        target["reasoning_content"] = reasoning


def normalize_chat_message_content(
    message: Any, decoder: Optional[StringifiedChunkDecoder] = None
) -> bool:
    """Rewrite an OpenAI ``delta``/``message`` dict in place.

    Moves stringified or list-typed thinking chunks into ``reasoning_content``
    and leaves plain answer text in ``content``. Returns True when changed.
    """
    if not isinstance(message, dict):
        return False
    content = message.get("content")

    if isinstance(content, list):
        parsed = parse_content_chunk_list(content)
        if parsed is None or not parsed[2]:
            return False
        reasoning, text, _ = parsed
        if decoder is not None:
            decoder.active = True
        message["content"] = text
        _merge_reasoning(message, reasoning)
        return True

    if not isinstance(content, str) or not content.startswith("["):
        return False

    reasoning, text = (decoder or StringifiedChunkDecoder()).split(content)
    if text == content and not reasoning:
        return False
    message["content"] = text
    _merge_reasoning(message, reasoning)
    return True


def normalize_chat_completion_payload(
    payload: Any, decoder: Optional[StringifiedChunkDecoder] = None
) -> bool:
    """Normalize every choice of a chat.completion(.chunk) payload in place."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    changed = False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for key in ("delta", "message"):
            if normalize_chat_message_content(choice.get(key), decoder):
                changed = True
    return changed
