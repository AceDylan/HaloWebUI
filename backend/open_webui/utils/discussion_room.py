"""讨论台 (multi-model discussion room) engine.

A discussion is an ordinary chat (so it gets an automatic title, folder auto-assignment,
search and a place in the sidebar), marked by ``chat.meta.discussion_room`` and
``chat.chat.discussionRoom``. Each question asked in it is one user message followed by one
assistant message; the assistant message's ``content`` is the moderator's conclusion (what the
normal chat view and search see) and ``discussion_room`` holds the whole exchange: seats,
rounds of turns, interjections and the structured conclusion.

How a question runs: every seat answers in parallel within a round (each sees the earlier
rounds), turns stream token by token to the user's browser over the socket (``chat-events``
with ``type: "discuss"``), then the moderator streams a conclusion with fixed sections
(结论 / 共识 / 分歧 / 各方立场 / 下一步). Live state lives in memory while a question runs
(single worker) and is written to the chat at turn boundaries.

Hermes is deliberately not a seat: an agent turn takes minutes, can burn millions of tokens and
writes into its own memory; the room offers "交给 Hermes" on the result instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, GLOBAL_LOG_LEVEL, SRC_LOG_LEVELS
from open_webui.utils.model_identity import resolve_model_from_lookup

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", GLOBAL_LOG_LEVEL))

META_KEY = "discussion_room"
CHAT_KEY = "discussionRoom"
MESSAGE_KEY = "discussion_room"

MIN_SEATS = 2
MAX_SEATS = 5
MAX_ROUNDS = 4
QUESTION_MAX_CHARS = 8000
ROLE_MAX_CHARS = 40
INTERJECTION_MAX_CHARS = 1000
MAX_INTERJECTIONS = 8
TURN_TIMEOUT_SECONDS = 300
MAX_RUNNING_PER_USER = 2
HISTORY_CONCLUSION_CHARS = 2400
TRANSCRIPT_TURN_CHARS = 6000
DELTA_FLUSH_SECONDS = 0.15
RESEARCH_TIMEOUT_SECONDS = 150
RESEARCH_MAX_SOURCES = 8
RESEARCH_EXCERPT_CHARS = 1600
MAX_FILES = 4
FILE_TEXT_CHARS = 12000

MODES: dict[str, dict] = {
    "roundtable": {
        "label": "圆桌讨论",
        "rounds": 2,
        "roles": [],
        "summary": "Every participant answers independently first, then they respond to each other: "
        "agree or disagree with specifics, correct mistakes, fill gaps.",
    },
    "debate": {
        "label": "正反辩论",
        "rounds": 3,
        "roles": ["正方", "反方", "评审", "正方二辩", "反方二辩"],
        "summary": "Participants argue assigned sides. Round 1 is an opening statement, the middle "
        "rounds are rebuttals of the strongest opposing points, the last round is a closing "
        "statement that concedes what must be conceded.",
    },
    "review": {
        "label": "独立评审",
        "rounds": 2,
        "roles": [],
        "summary": "Everyone answers independently, then reviews the other answers anonymously "
        "(labelled A, B, C...) with strengths, errors and a 1-10 score.",
    },
    "brainstorm": {
        "label": "头脑风暴",
        "rounds": 2,
        "roles": [],
        "summary": "Participants generate many distinct ideas, then build on, combine and improve "
        "each other's ideas and pick the most promising.",
    },
}

SECTION_HEADINGS = {
    "zh": ["结论", "共识", "分歧", "各方立场", "下一步"],
    "en": ["Conclusion", "Agreements", "Disagreements", "Positions", "Next steps"],
}

RUNNING_STATUSES = {"running", "concluding"}
TERMINAL_STATUSES = {"done", "stopped", "error", "interrupted"}


class DiscussError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def now_ms() -> int:
    return int(time.time() * 1000)


def detect_lang(text: str) -> str:
    return "zh" if re.search(r"[㐀-鿿]", text or "") else "en"


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    return text[:limit]


def _model_display_name(model: dict, fallback: str) -> str:
    return str(model.get("name") or model.get("id") or fallback)


def _model_selection_id(model: dict, fallback: str) -> str:
    return str(model.get("selection_id") or model.get("id") or fallback).strip()


def _default_is_excluded(model: dict) -> Optional[str]:
    from open_webui.utils.hermes_agent import is_hermes_agent_model
    from open_webui.utils.task import is_dedicated_image_generation_model

    if is_hermes_agent_model(model):
        return "Hermes 不参加讨论（它是要跑工具的代理，一轮要几分钟）；讨论结束后可以「交给 Hermes」"
    if is_dedicated_image_generation_model(model):
        return "生图模型不能参加讨论"
    return None


def resolve_seat_model(
    requested: Any,
    models_map: dict,
    ambiguous: set,
    user: Any,
    excluded: Callable[[dict], Optional[str]] = _default_is_excluded,
) -> dict:
    requested_id = str(requested or "").strip()
    if not requested_id:
        raise DiscussError(400, "席位缺少模型")
    model = resolve_model_from_lookup(models_map, ambiguous, requested_id)
    if not model:
        raise DiscussError(400, f"找不到模型：{requested_id}")
    reason = excluded(model)
    if reason:
        raise DiscussError(400, reason)
    if not BYPASS_MODEL_ACCESS_CONTROL and getattr(user, "role", None) == "user":
        from open_webui.utils.models import check_model_access

        try:
            check_model_access(user, model)
        except Exception:
            raise DiscussError(403, f"没有使用 {_model_display_name(model, requested_id)} 的权限")
    return {
        "model": _model_selection_id(model, requested_id),
        "name": _model_display_name(model, requested_id),
        "vision": model_sees_images(model),
    }


def model_sees_images(model: dict) -> bool:
    """The app's rule: a model reads images unless its capabilities say it does not."""
    capabilities = ((model.get("info") or {}).get("meta") or {}).get("capabilities") or {}
    return capabilities.get("vision", True) is not False


def normalize_setup(
    raw: dict,
    models_map: dict,
    ambiguous: set,
    user: Any,
    excluded: Callable[[dict], Optional[str]] = _default_is_excluded,
) -> dict:
    """Validate the seats / mode / rounds / moderator of a discussion."""
    if not isinstance(raw, dict):
        raise DiscussError(400, "设置无效")
    mode = str(raw.get("mode") or "roundtable")
    if mode not in MODES:
        mode = "roundtable"
    spec = MODES[mode]

    raw_seats = raw.get("seats")
    if not isinstance(raw_seats, list):
        raise DiscussError(400, "席位必须是列表")
    seats = []
    for index, item in enumerate(raw_seats[: MAX_SEATS + 1]):
        if isinstance(item, str):
            item = {"model": item}
        if not isinstance(item, dict):
            continue
        resolved = resolve_seat_model(item.get("model"), models_map, ambiguous, user, excluded)
        role = _clean_text(item.get("role"), ROLE_MAX_CHARS)
        seats.append({"id": f"s{index + 1}", **resolved, "role": role})
    if len(seats) < MIN_SEATS:
        raise DiscussError(400, f"至少要 {MIN_SEATS} 个席位")
    if len(seats) > MAX_SEATS:
        raise DiscussError(400, f"最多 {MAX_SEATS} 个席位")

    default_roles = spec["roles"]
    for index, seat in enumerate(seats):
        if not seat["role"] and index < len(default_roles):
            seat["role"] = default_roles[index]
    # Two seats with the same model are told apart by their role, or by a number.
    names: dict[str, int] = {}
    for seat in seats:
        names[seat["name"]] = names.get(seat["name"], 0) + 1
    counters: dict[str, int] = {}
    for seat in seats:
        if names[seat["name"]] > 1:
            counters[seat["name"]] = counters.get(seat["name"], 0) + 1
            seat["label"] = (
                f"{seat['name']}·{seat['role']}" if seat["role"] else f"{seat['name']} #{counters[seat['name']]}"
            )
        else:
            seat["label"] = seat["name"]

    if mode == "review":
        rounds = 2
    else:
        try:
            rounds = int(raw.get("rounds") or spec["rounds"])
        except (TypeError, ValueError):
            rounds = spec["rounds"]
        rounds = max(1, min(rounds, MAX_ROUNDS))

    moderator_raw = raw.get("moderator") or seats[0]["model"]
    moderator = resolve_seat_model(moderator_raw, models_map, ambiguous, user, excluded)

    return {
        "mode": mode,
        "rounds": rounds,
        "seats": seats,
        "moderator": moderator,
        "research": bool(raw.get("research")),
    }


# ---------------------------------------------------------------------------------------------
# Prompts


def _seat_title(seat: dict) -> str:
    return f"{seat['label']}（{seat['role']}）" if seat.get("role") and seat["role"] not in seat["label"] else seat["label"]


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    parts = []
    for item in history:
        question = _clean_text(item.get("question"), 1200)
        conclusion = _clean_text(item.get("conclusion"), HISTORY_CONCLUSION_CHARS)
        if question:
            parts.append(f"Earlier question: {question}\nEarlier conclusion:\n{conclusion or '(none)'}")
    if not parts:
        return ""
    return "Earlier in this discussion (for context; the new question is what matters now):\n\n" + "\n\n---\n\n".join(parts)


def research_sources(ask: dict) -> list[dict]:
    research = ask.get("research") or {}
    return research.get("sources") or [] if research.get("status") == "done" else []


def _research_block(ask: dict) -> str:
    sources = research_sources(ask)
    if not sources:
        return ""
    parts = [
        "Research notes gathered from the web for this question, shared with every participant. "
        "Cite them as [n] right after a claim that relies on them. They can be incomplete, outdated or wrong:"
    ]
    for source in sources:
        parts.append(f"[{source['n']}] {source.get('title') or source.get('url')} — {source.get('url')}\n{source.get('excerpt') or ''}")
    return "\n\n".join(parts)


def _files_block(ask: dict, *, sees_images: bool, gets_images: bool) -> str:
    files = ask.get("files") or []
    if not files:
        return ""
    parts = []
    for item in files:
        if item.get("type") == "image":
            continue
        text = (item.get("text") or "").strip()
        parts.append(
            f"Attached file «{item.get('name')}»:\n{text}" if text else f"Attached file «{item.get('name')}» (its text could not be read)."
        )
    images = [item for item in files if item.get("type") == "image"]
    if images:
        if gets_images:
            parts.append(f"The user attached {len(images)} image(s); they are included with this message.")
        elif sees_images:
            parts.append(f"The user attached {len(images)} image(s), shown to everyone in round 1; rely on what was said about them.")
        else:
            parts.append(
                f"The user attached {len(images)} image(s) that you cannot see; rely on what other participants say about them and say so."
            )
    return "\n\n".join(parts)


def _with_images(text: str, images: Optional[list[str]]) -> Any:
    if not images:
        return text
    return [{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": url}} for url in images)]


def _interjection_block(interjections: list[dict], before_round: Optional[int] = None) -> str:
    items = [
        item
        for item in interjections or []
        if before_round is None or int(item.get("afterRound") or 0) < before_round
    ]
    if not items:
        return ""
    lines = [f"- after round {item.get('afterRound') or 0}: {item.get('text')}" for item in items]
    return "The user interjected during the discussion (take this into account):\n" + "\n".join(lines)


def _transcript(ask: dict, seats: list[dict], *, upto_round: int, viewer: Optional[str] = None, anonymize: bool = False) -> str:
    """Successful turns of rounds < upto_round. In review mode the viewer sees the others as A, B, C."""
    by_id = {seat["id"]: seat for seat in seats}
    letters: dict[str, str] = {}
    if anonymize:
        others = [seat["id"] for seat in seats if seat["id"] != viewer]
        letters = {seat_id: chr(ord("A") + index) for index, seat_id in enumerate(others)}
    blocks = []
    for round_index in range(1, upto_round):
        lines = []
        for turn in ask.get("turns") or []:
            if turn.get("round") != round_index or turn.get("status") != "done":
                continue
            content = _clean_text(turn.get("content"), TRANSCRIPT_TURN_CHARS)
            if not content:
                continue
            seat = by_id.get(turn.get("seat"))
            if not seat:
                continue
            if anonymize:
                who = "Your own answer" if seat["id"] == viewer else f"Answer {letters.get(seat['id'], '?')}"
            else:
                who = _seat_title(seat)
            lines.append(f"### {who}\n{content}")
        if lines:
            blocks.append(f"## Round {round_index}\n\n" + "\n\n".join(lines))
    return "\n\n".join(blocks)


def build_turn_messages(
    *,
    setup: dict,
    ask: dict,
    seat: dict,
    round_index: int,
    history: list[dict],
    images: Optional[list[str]] = None,
) -> list[dict]:
    mode = setup["mode"]
    seats = setup["seats"]
    total_rounds = int(ask.get("rounds") or setup["rounds"])
    others = ", ".join(_seat_title(other) for other in seats if other["id"] != seat["id"])
    lang_rule = (
        "Write in Simplified Chinese." if ask.get("lang") == "zh" else "Write in the language of the user's question."
    )
    identity = f'You are "{seat["label"]}"'
    if seat.get("role"):
        identity += f", playing the role: {seat['role']}"
    system = "\n".join(
        [
            f"{identity}. You are one of {len(seats)} AI participants in a structured discussion that a moderator will summarize for the user.",
            f"Other participants: {others}." if others else "",
            f"Format: {MODES[mode]['label']} — {MODES[mode]['summary']}",
            "Rules:",
            f"- {lang_rule}",
            "- Be concrete and specific; prefer short paragraphs and bullets. No preamble, no restating the question, no sign-off.",
            "- Round 1: at most about 350 words. Later rounds: at most about 250 words, only what is new.",
            "- Refer to other participants by name. Never write on their behalf.",
            (
                "- Beyond the research notes you cannot browse; cite notes as [n], never invent sources or links."
                if research_sources(ask)
                else "- You cannot browse the web; say so when a fact needs checking instead of inventing sources."
            ),
        ]
    ).strip()

    question = ask.get("question") or ""
    anonymize = mode == "review" and round_index >= 2
    transcript = _transcript(ask, seats, upto_round=round_index, viewer=seat["id"], anonymize=anonymize)
    interjections = _interjection_block(ask.get("interjections") or [], before_round=round_index)

    if mode == "debate":
        side = seat.get("role") or "your side"
        if round_index == 1:
            task = f"Round 1 of {total_rounds}: give the opening statement for {side}. Lay out your 2-4 strongest arguments."
        elif round_index < total_rounds:
            task = f"Round {round_index} of {total_rounds}: rebuttal for {side}. Attack the strongest opposing points by name and defend yours."
        else:
            task = f"Final round: closing statement for {side}. Your strongest case in brief, and concede what you must."
    elif mode == "review":
        if round_index == 1:
            task = "Give your own complete, independent answer to the question."
        else:
            task = (
                "Review the other answers below (anonymized as A, B, C...). For each: what is right, what is wrong or missing, "
                "and a score from 1 to 10. Then say which answer is best and what you would now change in your own."
            )
    elif mode == "brainstorm":
        if round_index == 1:
            task = "Generate 5-8 distinct ideas. One line each, with a short reason it could work."
        else:
            task = (
                "Build on the ideas so far: combine, improve or extend them, add genuinely new angles, "
                "and name the 3 ideas you now find most promising (whoever proposed them) with one line why."
            )
    else:
        if round_index == 1:
            task = "Give your own independent answer to the question."
        else:
            task = (
                f"Round {round_index} of {total_rounds}: respond to the others. Say where you agree or disagree and why, "
                "correct mistakes, add what is missing. If you changed your mind, say so plainly."
            )

    sees = seat.get("vision", True) is not False
    gets_images = bool(images) and sees and round_index == 1
    user_parts = [
        _history_block(history),
        f"User question:\n{question}",
        _files_block(ask, sees_images=sees, gets_images=gets_images),
        _research_block(ask),
    ]
    if transcript:
        user_parts.append(f"Discussion so far:\n\n{transcript}")
    if interjections:
        user_parts.append(interjections)
    user_parts.append(f"Your task now: {task}")
    text = "\n\n".join(part for part in user_parts if part)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _with_images(text, images if gets_images else None)},
    ]


def build_conclusion_messages(
    *, setup: dict, ask: dict, history: list[dict], images: Optional[list[str]] = None
) -> list[dict]:
    lang = ask.get("lang") or "zh"
    headings = SECTION_HEADINGS["zh" if lang == "zh" else "en"]
    seats = setup["seats"]
    mode = setup["mode"]
    total_rounds = max([turn.get("round") or 0 for turn in ask.get("turns") or []] or [0])
    transcript = _transcript(ask, seats, upto_round=total_rounds + 1)
    failed = [
        _seat_title(next((s for s in seats if s["id"] == turn.get("seat")), {"label": "?"}))
        for turn in ask.get("turns") or []
        if turn.get("status") in {"error", "stopped"}
    ]
    focus = {
        "roundtable": "the best answer to the question, informed by the whole discussion",
        "debate": "your verdict: which side made the stronger case on each point, and the balanced answer to the question",
        "review": "the best possible merged answer (take the strongest parts of each), plus each answer's score as the reviewers gave it",
        "brainstorm": "the most promising ideas ranked, merged where they overlap, each with why and a first step",
    }[mode]
    lang_rule = "Write in Simplified Chinese." if lang == "zh" else "Write in the language of the user's question."
    system = (
        "You moderated a multi-model discussion and now write the final answer for the user. "
        f"{lang_rule} Use Markdown. Use exactly these level-2 headings, in this order, and nothing before the first one:\n"
        f"## {headings[0]}\n— {focus}. This is the answer the user reads first: complete and directly useful, not a summary of who said what.\n"
        f"## {headings[1]}\n— points the participants agreed on (bullets; may be short).\n"
        f"## {headings[2]}\n— each real disagreement as a bullet: the point, who held which view (by name), and your judgment. "
        "Write a single bullet saying there was none if so.\n"
        f"## {headings[3]}\n— one bullet per participant: **name** — their final position in one line, and whether they changed their mind.\n"
        f"## {headings[4]}\n— only if genuinely useful: what the user could verify or do next (bullets). Otherwise omit this section.\n"
        "Do not invent facts that no participant stated; flag claims that need checking."
        + (
            " Keep the [n] citations of the research notes next to the claims that rely on them."
            if research_sources(ask)
            else ""
        )
    )
    participants = ", ".join(_seat_title(seat) for seat in seats)
    moderator_sees = (ask.get("moderator") or {}).get("vision", True) is not False
    gets_images = bool(images) and moderator_sees
    parts = [
        _history_block(history),
        f"Discussion format: {MODES[mode]['label']}. Participants: {participants}.",
        f"User question:\n{ask.get('question') or ''}",
        _files_block(ask, sees_images=moderator_sees, gets_images=gets_images),
        _research_block(ask),
        f"Transcript:\n\n{transcript or '(no participant produced an answer)'}",
    ]
    interjections = _interjection_block(ask.get("interjections") or [])
    if interjections:
        parts.append(interjections)
    if failed:
        parts.append("These turns failed or were stopped (not evidence): " + ", ".join(failed))
    text = "\n\n".join(part for part in parts if part)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _with_images(text, images if gets_images else None)},
    ]


def parse_conclusion_sections(content: str) -> list[dict]:
    """Split a conclusion into its ``## `` sections (the UI does the same)."""
    sections: list[dict] = []
    current: Optional[dict] = None
    for line in (content or "").splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = {"title": match.group(1).strip(), "body": ""}
            sections.append(current)
        elif current is not None:
            current["body"] += line + "\n"
        elif line.strip():
            current = {"title": "", "body": line + "\n"}
            sections.append(current)
    for section in sections:
        section["body"] = _trim_rules(section["body"])
    return sections


RULE_LINE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _trim_rules(body: str) -> str:
    """A section without the --- separators models like to put between sections."""
    lines = body.strip().splitlines()
    while lines and (not lines[0].strip() or RULE_LINE.match(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1].strip() or RULE_LINE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


def conclusion_answer(content: str) -> str:
    """The first section (结论) of a conclusion, for previews and history."""
    sections = parse_conclusion_sections(content)
    if not sections:
        return (content or "").strip()
    return sections[0]["body"] or (content or "").strip()


# ---------------------------------------------------------------------------------------------
# Model calls


THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text or "")
    # an unterminated <think> at the start: nothing after it is the answer yet
    if text.lstrip().startswith("<think>"):
        return ""
    return text


def _usage_from(payload: dict) -> dict:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {}
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = int(value)
    return out


def _error_text(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or error)
    if isinstance(error, str) and error.strip():
        return error.strip()
    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip() and not payload.get("choices"):
        return detail.strip()
    return None


async def iterate_completion(response: Any):
    """Yield ("content" | "reasoning", text) and ("usage", dict) from a chat completion
    response: an OpenAI-style SSE StreamingResponse, a JSONResponse or a plain dict."""
    if isinstance(response, dict):
        error = _error_text(response)
        if error:
            raise ValueError(error)
        choices = response.get("choices") or []
        message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
        content = (message or {}).get("content") or ""
        if isinstance(content, list):
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        if content:
            yield ("content", str(content))
        usage = _usage_from(response)
        if usage:
            yield ("usage", usage)
        return

    body = getattr(response, "body_iterator", None)
    if body is None:
        raw = getattr(response, "body", None)
        if isinstance(raw, (bytes, bytearray)):
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            except Exception:
                parsed = {"detail": raw.decode("utf-8", errors="replace")}
            async for item in iterate_completion(parsed if isinstance(parsed, dict) else {}):
                yield item
            return
        raise ValueError("模型没有返回内容")

    buffer = ""
    async for chunk in body:
        if isinstance(chunk, (bytes, bytearray)):
            chunk = chunk.decode("utf-8", errors="replace")
        buffer += str(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            error = _error_text(payload)
            if error:
                raise ValueError(error)
            usage = _usage_from(payload)
            if usage:
                yield ("usage", usage)
            for choice in payload.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") or choice.get("message") or {}
                if not isinstance(delta, dict):
                    continue
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    yield ("reasoning", reasoning)
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield ("content", content)


# ---------------------------------------------------------------------------------------------
# State


def new_ask(
    *,
    question: str,
    setup: dict,
    user_message_id: str,
    message_id: str,
    rounds: Optional[int] = None,
    files: Optional[list[dict]] = None,
) -> dict:
    total_rounds = setup["rounds"] if rounds is None else max(1, min(int(rounds), MAX_ROUNDS))
    if setup["mode"] == "review":
        total_rounds = 2
    return {
        "v": 1,
        "id": message_id,
        "userMessageId": user_message_id,
        "question": question,
        "lang": detect_lang(question),
        "mode": setup["mode"],
        "rounds": total_rounds,
        "seats": deepcopy(setup["seats"]),
        "moderator": deepcopy(setup["moderator"]),
        "status": "running",
        "round": 0,
        "turns": [],
        "interjections": [],
        "conclusion": {"status": "waiting", "content": "", "model": setup["moderator"]["model"], "name": setup["moderator"]["name"]},
        "previousConclusions": [],
        "research": {"status": "waiting", "queries": [], "sources": []} if setup.get("research") else None,
        "files": files or [],
        "startedAt": now_ms(),
        "endedAt": None,
        "usage": {},
        "error": None,
    }


def ask_usage(ask: dict) -> dict:
    totals: dict[str, int] = {}
    for item in [*(ask.get("turns") or []), ask.get("conclusion") or {}]:
        for key, value in (item.get("usage") or {}).items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def public_ask(ask: dict) -> dict:
    out = deepcopy(ask)
    out["usage"] = ask_usage(ask)
    return out


def summary_meta(setup: dict, asks: list[dict]) -> dict:
    last = asks[-1] if asks else {}
    conclusion = (last.get("conclusion") or {}).get("content") or ""
    return {
        "v": 1,
        "mode": setup["mode"],
        "rounds": setup["rounds"],
        "seats": [{"model": s["model"], "name": s["name"], "label": s["label"], "role": s.get("role", "")} for s in setup["seats"]],
        "moderator": deepcopy(setup["moderator"]),
        "research": bool(setup.get("research")),
        "status": last.get("status") or "running",
        "asks": len(asks),
        "question": _clean_text(last.get("question"), 200),
        "preview": _clean_text(_plain(conclusion_answer(conclusion)), 180),
        "updatedAt": now_ms(),
    }


def _plain(markdown: str) -> str:
    """One line of text from Markdown, for list previews."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown or "")
    text = re.sub(r"(\*\*|__|\*|`|~~)", "", text)
    text = re.sub(r"^\s{0,3}(#+|>|[-*+]|\d+\.)\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------------------------
# Runner


Emit = Callable[[dict], Awaitable[None]]
CallModel = Callable[[str, list[dict]], Awaitable[Any]]
Persist = Callable[[dict], None]


@dataclass
class LiveDiscussion:
    chat_id: str
    user_id: str
    setup: dict
    ask: dict
    history: list[dict]
    emit: Emit
    call_model: CallModel
    persist: Persist
    after_done: Optional[Callable[[dict], Awaitable[None]]] = None
    task: Optional[asyncio.Task] = None
    pending: dict = field(default_factory=dict)
    version: int = 0
    flusher: Optional[asyncio.Task] = None
    conclude_only: bool = False
    from_round: int = 1
    # (question, history) -> {"queries": [...], "docs": [{"title", "url", "content"}]}
    search: Optional[Callable[[str, list[dict]], Awaitable[dict]]] = None
    # re-run just this turn (a seat that failed), then conclude again
    retry_turn: Optional[str] = None
    # data URLs of the question's images (round 1 and the moderator get them)
    images: list = field(default_factory=list)

    # -- events --------------------------------------------------------------------------------

    async def send(self, kind: str, **data):
        self.version += 1
        try:
            await self.emit({"type": "discuss", "data": {"kind": kind, "chatId": self.chat_id, "askId": self.ask["id"], "v": self.version, **data}})
        except Exception:
            log.debug("discussion event %s not delivered", kind, exc_info=True)

    async def send_state(self):
        await self.send("state", ask=public_ask(self.ask))

    def queue_delta(self, key: str, offset: int, text: str):
        """Text to append at `offset` of a turn; offset 0 with a pending part replaces it."""
        part = self.pending.get(key)
        if part is None or offset <= part["o"]:
            self.pending[key] = {"t": key, "o": offset, "x": text}
        else:
            # keep the pending text before `offset`, then the new text
            part["x"] = part["x"][: offset - part["o"]] + text

    async def flush(self):
        if not self.pending:
            return
        parts = list(self.pending.values())
        self.pending = {}
        await self.send("delta", parts=parts)

    async def _flush_loop(self):
        try:
            while True:
                await asyncio.sleep(DELTA_FLUSH_SECONDS)
                await self.flush()
        except asyncio.CancelledError:
            pass

    def save(self):
        try:
            self.persist(self.ask)
        except Exception:
            log.exception("could not persist discussion %s", self.chat_id)

    # -- one streamed model call ---------------------------------------------------------------

    async def _stream_into(self, target: dict, key: str, model: str, messages: list[dict]):
        target["status"] = "streaming"
        target["startedAt"] = now_ms()
        target["content"] = ""
        target["thinking"] = False
        raw = ""
        # with the (empty) content: a second try clears what the first one had streamed
        await self.send("turn", turn=_brief(target, key, with_content=True))
        response = await self.call_model(model, messages)
        async for kind, text in iterate_completion(response):
            if kind == "usage":
                target["usage"] = text
            elif kind == "reasoning":
                if not target.get("thinking"):
                    target["thinking"] = True
                    await self.send("turn", turn=_brief(target, key))
            elif kind == "content":
                raw += text
                visible = strip_think(raw)
                previous = target["content"]
                if visible.startswith(previous):
                    added = visible[len(previous):]
                    if added:
                        self.queue_delta(key, len(previous), added)
                else:
                    self.queue_delta(key, 0, visible)
                target["content"] = visible
                if target.get("thinking") and visible:
                    target["thinking"] = False
        target["content"] = strip_think(raw).strip()
        if not target["content"]:
            raise ValueError("模型返回了空内容")

    async def _speak(self, target: dict, key: str, model: str, build, sends_images: bool):
        """One streamed call. Many models the app treats as image readers reject pictures: when a
        call that carried images fails, it is made once more without them (and says so)."""
        try:
            await asyncio.wait_for(self._stream_into(target, key, model, build(blind=False)), TURN_TIMEOUT_SECONDS)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception:
            if not sends_images:
                raise
            target["imagesDropped"] = True
            await asyncio.wait_for(self._stream_into(target, key, model, build(blind=True)), TURN_TIMEOUT_SECONDS)

    async def _run_turn(self, turn: dict):
        seat = next(s for s in self.setup["seats"] if s["id"] == turn["seat"])

        def build(blind: bool):
            return build_turn_messages(
                setup=self.setup,
                ask=self.ask,
                seat={**seat, "vision": False} if blind else seat,
                round_index=turn["round"],
                history=self.history,
                images=None if blind else self.images,
            )

        sends_images = bool(self.images) and seat.get("vision", True) is not False and turn["round"] == 1
        try:
            await self._speak(turn, turn["id"], seat["model"], build, sends_images)
            turn["status"] = "done"
        except asyncio.CancelledError:
            turn["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            turn["status"] = "error"
            turn["error"] = f"超过 {TURN_TIMEOUT_SECONDS // 60} 分钟没有答完"
        except Exception as exc:  # the model's own failure: this seat sits the round out
            turn["status"] = "error"
            turn["error"] = _short_error(exc)
        finally:
            turn["endedAt"] = now_ms()
            turn["thinking"] = False
            await self.flush()
            await self.send("turn", turn=_brief(turn, turn["id"], with_content=True))

    async def _run_conclusion(self):
        conclusion = self.ask["conclusion"]
        if conclusion.get("content") and conclusion.get("status") == "done":
            self.ask["previousConclusions"].append(
                {"content": conclusion["content"], "endedAt": conclusion.get("endedAt")}
            )
        conclusion.update({"status": "waiting", "content": "", "error": None, "usage": {}, "imagesDropped": False})
        self.ask["status"] = "concluding"
        await self.send_state()
        moderator = self.ask["moderator"]

        def build(blind: bool):
            ask = {**self.ask, "moderator": {**moderator, "vision": False}} if blind else self.ask
            return build_conclusion_messages(
                setup=self.setup, ask=ask, history=self.history, images=None if blind else self.images
            )

        sends_images = bool(self.images) and moderator.get("vision", True) is not False
        try:
            await self._speak(conclusion, "conclusion", moderator["model"], build, sends_images)
            conclusion["status"] = "done"
        except asyncio.CancelledError:
            conclusion["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            conclusion["status"] = "error"
            conclusion["error"] = f"主持人超过 {TURN_TIMEOUT_SECONDS // 60} 分钟没有写完"
        except Exception as exc:
            conclusion["status"] = "error"
            conclusion["error"] = _short_error(exc)
        finally:
            conclusion["endedAt"] = now_ms()
            conclusion["thinking"] = False
            await self.flush()

    async def _run_research(self):
        research = self.ask["research"]
        research.update({"status": "running", "startedAt": now_ms(), "error": None})
        await self.send_state()
        try:
            if self.search is None:
                raise ValueError("联网搜索不可用")
            found = await asyncio.wait_for(self.search(self.ask["question"], self.history), RESEARCH_TIMEOUT_SECONDS)
            sources, seen = [], set()
            for doc in (found or {}).get("docs") or []:
                url = str(doc.get("url") or "").strip()
                content = re.sub(r"\s+", " ", str(doc.get("content") or "")).strip()
                if not url or url in seen or len(content) < 80:
                    continue
                seen.add(url)
                sources.append(
                    {
                        "n": len(sources) + 1,
                        "title": _clean_text(doc.get("title") or url, 160),
                        "url": url,
                        "excerpt": content[:RESEARCH_EXCERPT_CHARS],
                    }
                )
                if len(sources) >= RESEARCH_MAX_SOURCES:
                    break
            research["queries"] = [q for q in (found or {}).get("queries") or [] if q][:4]
            research["sources"] = sources
            research["status"] = "done" if sources else "empty"
        except asyncio.CancelledError:
            research["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            research["status"] = "error"
            research["error"] = f"超过 {RESEARCH_TIMEOUT_SECONDS} 秒没查完，讨论照常进行"
        except Exception as exc:
            research["status"] = "error"
            research["error"] = _short_error(exc)
        finally:
            research["endedAt"] = now_ms()
            await self.send_state()

    async def run(self):
        self.flusher = asyncio.create_task(self._flush_loop())
        try:
            if self.retry_turn:
                turn = next(t for t in self.ask["turns"] if t["id"] == self.retry_turn)
                turn.update({"status": "waiting", "content": "", "error": None, "usage": {}, "imagesDropped": False})
                await self.send_state()
                await self._run_turn(turn)
                self.save()
            elif not self.conclude_only:
                research = self.ask.get("research")
                if research and research.get("status") in {"waiting", "stopped"} and self.from_round == 1:
                    await self._run_research()
                for round_index in range(self.from_round, int(self.ask["rounds"]) + 1):
                    self.ask["round"] = round_index
                    turns = [
                        {"id": f"r{round_index}-{seat['id']}", "round": round_index, "seat": seat["id"], "status": "waiting", "content": ""}
                        for seat in self.setup["seats"]
                    ]
                    self.ask["turns"].extend(turns)
                    await self.send_state()
                    await asyncio.gather(*(self._run_turn(turn) for turn in turns))
                    self.save()
                    if round_index == 1 and not any(t["status"] == "done" for t in turns):
                        raise ValueError("第一轮所有参与者都失败了")
            await self._run_conclusion()
            if self.ask["conclusion"]["status"] == "done":
                self.ask["status"] = "done"
            else:
                self.ask["status"] = "error"
                self.ask["error"] = self.ask["conclusion"].get("error") or "主持人没有写出结论"
        except asyncio.CancelledError:
            self.ask["status"] = "stopped"
            for turn in self.ask["turns"]:
                if turn.get("status") in {"waiting", "streaming"}:
                    turn["status"] = "stopped"
            if self.ask["conclusion"].get("status") in {"waiting", "streaming"}:
                self.ask["conclusion"]["status"] = "stopped" if self.ask["conclusion"].get("content") else "waiting"
        except Exception as exc:
            log.exception("discussion %s failed", self.chat_id)
            self.ask["status"] = "error"
            self.ask["error"] = _short_error(exc)
        finally:
            if self.flusher:
                self.flusher.cancel()
            self.ask["endedAt"] = now_ms()
            self.ask["usage"] = ask_usage(self.ask)
            await self.flush()
            self.save()
            await self.send_state()
            await self.send("end", status=self.ask["status"])
            LIVE.pop(self.chat_id, None)
            if self.after_done and self.ask["status"] == "done":
                try:
                    await self.after_done(self.ask)
                except Exception:
                    log.exception("discussion %s after-done hook failed", self.chat_id)


def _brief(target: dict, key: str, with_content: bool = False) -> dict:
    out = {
        "id": key,
        "status": target.get("status"),
        "thinking": bool(target.get("thinking")),
        "startedAt": target.get("startedAt"),
        "endedAt": target.get("endedAt"),
        "usage": target.get("usage") or {},
        "error": target.get("error"),
        "imagesDropped": bool(target.get("imagesDropped")),
    }
    if with_content:
        out["content"] = target.get("content") or ""
    return out


def _short_error(exc: BaseException) -> str:
    text = str(getattr(exc, "detail", None) or exc or exc.__class__.__name__).strip()
    return (text or exc.__class__.__name__)[:300]


LIVE: dict[str, LiveDiscussion] = {}


def running_for_user(user_id: str) -> int:
    return sum(1 for live in LIVE.values() if live.user_id == user_id)


def start_live(live: LiveDiscussion) -> LiveDiscussion:
    from open_webui.tasks import create_task

    LIVE[live.chat_id] = live
    task_id, task = create_task(live.run(), id=live.chat_id, owner_id=live.user_id)
    live.task = task
    return live


async def stop_live(chat_id: str) -> bool:
    live = LIVE.get(chat_id)
    if not live or not live.task:
        return False
    live.task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(live.task), 10)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass
    return True


def new_id() -> str:
    return str(uuid.uuid4())
