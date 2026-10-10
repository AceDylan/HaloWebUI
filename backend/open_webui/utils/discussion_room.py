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
from open_webui.utils.mode_chats import native_search_failed, sources_from_docs
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
# a seat's duty in this discussion (run-only; what its assistant brings is in the assistant)
DUTY_MAX_CHARS = 120
MATCH_TIMEOUT_SECONDS = 150
# 主持人安排: the moderator reads the question and staffs the discussion (format, rounds, seats)
PLAN_TIMEOUT_SECONDS = 90
PLAN_POOL_MAX = 40
ASSIST_MODES = ("auto", "pick", "generic")
INTERJECTION_MAX_CHARS = 1000
MAX_INTERJECTIONS = 8
TURN_TIMEOUT_SECONDS = 300
MAX_RUNNING_PER_USER = 2
HISTORY_CONCLUSION_CHARS = 2400
TRANSCRIPT_TURN_CHARS = 6000
DELTA_FLUSH_SECONDS = 0.15
RESEARCH_TIMEOUT_SECONDS = 150
RESEARCH_MAX_SOURCES = 8
RESEARCH_EXCERPT_CHARS = 2800
# a seat may ask once per question for one more search (补查: its last line) before the next
# round; the moderator runs up to LOOKUPS_PER_ROUND of them and adds what they find to the notes
LOOKUPS_PER_ROUND = 3
LOOKUP_MAX_SOURCES = 6
LOOKUP_TIMEOUT_SECONDS = 90
RESEARCH_TOTAL_SOURCES = 14
LOOKUP_RE = re.compile(r"(?:^|\n)[ \t>*_-]*(?:补查|lookup)[*_]*\s*[:：][*_]*\s*(.+?)[ \t*_]*\s*$", re.I)
MAX_FILES = 4
FILE_TEXT_CHARS = 12000
# A call the upstream refused for a passing reason (rate limit, overload, a dropped connection)
# is made again after these pauses; a moderator that still fails hands the conclusion to a seat.
RETRY_DELAYS = (8, 20, 45)
RETRY_MAX_WAIT = 90
STAND_IN_RETRY_DELAYS = (10,)
MAX_STAND_INS = 2

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
    "compare": {
        "label": "各自回答",
        "rounds": 1,
        "roles": [],
        "summary": "Each participant answers once, independently, without seeing the others; the moderator "
        "then compares the answers and merges the best of them.",
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


class UpstreamError(ValueError):
    """A model call the upstream answered with an error (its HTTP status when there was one)."""

    def __init__(self, detail: str, status_code: Optional[int] = None):
        super().__init__(detail)
        self.status_code = status_code


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
    """Validate the seats / mode / rounds / moderator of a discussion. ``smart`` (主持人安排): the
    moderator staffs it when the first question starts, so there may be no seats yet."""
    if not isinstance(raw, dict):
        raise DiscussError(400, "设置无效")
    mode = str(raw.get("mode") or "roundtable")
    if mode not in MODES:
        mode = "roundtable"
    spec = MODES[mode]

    smart = bool(raw.get("smart"))
    # the moderator's seats always get assistants matched to the question
    auto_match = smart or bool(raw.get("autoMatch") or raw.get("auto_match"))
    raw_seats = raw.get("seats") if raw.get("seats") is not None or not smart else []
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
        seat = {"id": f"s{index + 1}", **resolved, "role": role, **_seat_assist(item, resolved, models_map, ambiguous, auto_match)}
        seats.append(seat)
    if len(seats) < MIN_SEATS and not (smart and not seats):
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
    elif mode == "compare":
        rounds = 1
    else:
        try:
            rounds = int(raw.get("rounds") or spec["rounds"])
        except (TypeError, ValueError):
            rounds = spec["rounds"]
        rounds = max(1, min(rounds, MAX_ROUNDS))

    moderator_raw = raw.get("moderator") or (seats[0]["model"] if seats else "")
    if not moderator_raw:
        raise DiscussError(400, "主持人安排需要先选主持人")
    moderator = neutral_moderator(resolve_seat_model(moderator_raw, models_map, ambiguous, user, excluded), models_map, ambiguous, user, excluded)

    return {
        "mode": mode,
        "rounds": rounds,
        "seats": seats,
        "moderator": moderator,
        "research": bool(raw.get("research")),
        "autoMatch": auto_match,
        "smart": smart,
    }


def _assistant_base(model_id: str, models_map: dict, ambiguous: set) -> Optional[str]:
    """The base model under a workspace assistant, or None when ``model_id`` is not one."""
    model = resolve_model_from_lookup(models_map, ambiguous, model_id)
    info = (model or {}).get("info") or {}
    return str(info.get("base_model_id") or "") or None


def _seat_assist(item: dict, resolved: dict, models_map: dict, ambiguous: set, auto_match: bool) -> dict:
    """Where a seat's assistant comes from: matched automatically for each question (auto), the
    one the user picked (pick: a library ``model:<id>`` or a ``builtin:<id>`` template), or none
    (generic: the seat's role only). A seat whose model is itself an assistant keeps that one."""
    duty = _clean_text(item.get("duty"), DUTY_MAX_CHARS)
    if _assistant_base(resolved["model"], models_map, ambiguous):
        return {"assist": "self", "duty": duty}
    ref = _clean_text(item.get("assistant"), 200)
    mode = str(item.get("assist") or "").strip()
    if ref.startswith(("model:", "builtin:")) and mode in ("", "pick"):
        return {"assist": "pick", "assistant": ref, "duty": duty}
    if mode not in ASSIST_MODES or mode == "pick":
        mode = "auto" if auto_match else "generic"
    return {"assist": mode, "duty": duty}


def neutral_moderator(moderator: dict, models_map: dict, ambiguous: set, user: Any, excluded=None) -> dict:
    """The moderator summarizes neutrally: an assistant chosen as moderator writes through its base
    model, without the assistant's persona."""
    base = _assistant_base(moderator["model"], models_map, ambiguous)
    if not base:
        return moderator
    try:
        resolved = resolve_seat_model(base, models_map, ambiguous, user, excluded or _default_is_excluded)
    except DiscussError:
        return moderator
    return {**resolved, "persona": moderator["name"]}


def needs_matching(seats: list[dict]) -> bool:
    return any(seat.get("assist") in ("auto", "pick") for seat in seats)


def seat_choice(ask: dict, seat_id: str) -> Optional[dict]:
    """The assistant a seat uses in this question (a snapshot), if any."""
    seat = next((s for s in ask.get("seats") or [] if s.get("id") == seat_id), None)
    choice = (seat or {}).get("assistant_choice")
    return choice if isinstance(choice, dict) and choice.get("action") not in (None, "generic") else None


def seat_duty(ask: dict, seat: dict) -> str:
    asked = next((s for s in ask.get("seats") or [] if s.get("id") == seat.get("id")), None) or {}
    return asked.get("duty") or seat.get("duty") or ""


# ---------------------------------------------------------------------------------------------
# Prompts


def _seat_title(seat: dict, ask: Optional[dict] = None) -> str:
    title = f"{seat['label']}（{seat['role']}）" if seat.get("role") and seat["role"] not in seat["label"] else seat["label"]
    choice = seat_choice(ask, seat["id"]) if ask else None
    if choice and choice.get("name"):
        title += f" [{choice['name']}]"
    return title


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


CONTEXT_MAX_CHARS = 12000


def clean_context(raw: Any) -> Optional[dict]:
    """Background handed over with a new discussion: the conversation it was started from."""
    if not isinstance(raw, dict):
        return None
    text = _clean_text(raw.get("text"), CONTEXT_MAX_CHARS)
    if not text:
        return None
    chat_id = str(raw.get("chat_id") or raw.get("chatId") or "").strip()
    return {
        "text": text,
        "title": _clean_text(raw.get("title"), 120),
        "chatId": chat_id if re.fullmatch(r"[A-Za-z0-9-]{1,64}", chat_id) else None,
    }


def _context_block(ask: dict) -> str:
    context = ask.get("context") or {}
    text = (context.get("text") or "").strip()
    if not text:
        return ""
    title = context.get("title") or ""
    head = f"Background: the user's earlier conversation{f' «{title}»' if title else ''}, which led to this question. Use it to understand what they need; answer the question itself."
    return f"{head}\n\n{text}"


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


def take_lookup(content: str) -> tuple[str, Optional[str]]:
    """A turn's 补查 line (its last line) taken off its text: ``(text, query)``, query None when
    there is none."""
    match = LOOKUP_RE.search((content or "").rstrip())
    if not match:
        return content, None
    # a leading dash would reach the search CLI as an option
    query = match.group(1).strip().strip("`\"'「」“”").strip().lstrip("-").strip()[:200]
    text = content[: match.start()].rstrip()
    if not query or not text:
        return content, None
    return text, query


def may_lookup(ask: dict, seat_id: str, round_index: int) -> bool:
    """Whether a seat may still ask for a 补查 in this round: the question is researched, another
    round follows, and the seat has not asked before."""
    if not ask.get("research") or round_index >= int(ask.get("rounds") or 0):
        return False
    return not any(t.get("lookup") for t in ask.get("turns") or [] if t.get("seat") == seat_id and t.get("round") != round_index)


def _files_block(ask: dict, *, sees_images: bool, gets_images: bool) -> str:
    files = ask.get("files") or []
    if not files:
        return ""
    parts = []
    for item in files:
        if item.get("type") == "image":
            continue
        text = (item.get("text") or "").strip()
        kind = item.get("content_type") or "unknown type"
        parts.append(
            f"Attached file «{item.get('name')}»:\n{text}"
            if text
            else f"Attached file «{item.get('name')}» ({kind}; its content could not be read as text)."
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
    browse: bool = False,
) -> list[dict]:
    """``browse``: the seat's model searches the web itself (native web search) during the turn."""
    mode = setup["mode"]
    seats = setup["seats"]
    total_rounds = int(ask.get("rounds") or setup["rounds"])
    titled = None if mode == "review" else ask
    others = ", ".join(_seat_title(other, titled) for other in seats if other["id"] != seat["id"])
    lang_rule = (
        "Write in Simplified Chinese." if ask.get("lang") == "zh" else "Write in the language of the user's question."
    )
    choice = seat_choice(ask, seat["id"])
    duty = seat_duty(ask, seat)
    identity = f'You are "{seat["label"]}"'
    if seat.get("role"):
        identity += f", playing the role: {seat['role']}"
    profile = []
    if choice and choice.get("system"):
        profile.append(
            f"Your specialist profile for this discussion is above ({choice.get('name') or 'assistant'}): bring that expertise."
        )
    if duty:
        profile.append(f"Your duty in this discussion: {duty}")
    if mode == "debate" and seat.get("role"):
        profile.append(f"Your side ({seat['role']}) is set for this discussion and comes before any view your profile suggests.")
    system = "\n".join(
        [
            f"{identity}. You are one of {len(seats)} AI participants in a structured discussion that a moderator will summarize for the user.",
            *profile,
            f"Other participants: {others}." if others else "",
            f"Format: {MODES[mode]['label']} — {MODES[mode]['summary']}",
            "Rules:",
            f"- {lang_rule}",
            "- Be concrete and specific; prefer short paragraphs and bullets. No preamble, no restating the question, no sign-off.",
            "- Round 1: at most about 350 words. Later rounds: at most about 250 words, only what is new.",
            "- Refer to other participants by name. Never write on their behalf.",
            (
                "- You can search the web yourself when the research notes miss something you need; cite notes as [n] "
                "and pages you found yourself as markdown links. Never invent sources or links."
                if browse
                else "- Beyond the research notes you cannot browse; cite notes as [n], never invent sources or links."
                if research_sources(ask)
                else "- You cannot browse the web; say so when a fact needs checking instead of inventing sources."
            ),
            (
                f"- If a fact you need is missing from the research notes, end your turn with one last line "
                f"`{'补查' if ask.get('lang') == 'zh' else 'Lookup'}: <search keywords>` (once in this discussion). "
                "It is searched before the next round and the results join the notes for everyone."
                if may_lookup(ask, seat["id"], round_index)
                else ""
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
    elif mode == "compare" and round_index == 1:
        task = "Give your own complete, independent answer to the question. The others answer separately; you will not see them."
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
        _context_block(ask),
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
    if choice and choice.get("system"):
        # the assistant's full settings first, then how this discussion works
        system = f"{choice['system']}\n\n---\n\n{system}"
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
        "compare": "the best answer, merging the strongest parts of each; then say plainly how the answers differ and which is more accurate or complete",
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
    participants = ", ".join(_seat_title(seat, ask) for seat in seats)
    moderator_sees = (ask.get("moderator") or {}).get("vision", True) is not False
    gets_images = bool(images) and moderator_sees
    parts = [
        _history_block(history),
        f"Discussion format: {MODES[mode]['label']}. Participants: {participants}.",
        _context_block(ask),
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


# 主持人安排: what each format is for, as the moderator weighs it
PLAN_MODE_GUIDE = {
    "roundtable": "open questions and decisions with trade-offs that gain from several angles (the default)",
    "compare": "questions with a best answer (facts, how-to, code, writing): independent answers merged; always 1 round",
    "debate": "a yes/no or A-vs-B choice, or a contested claim: seats argue assigned sides (roles 正方 / 反方, optionally 评审)",
    "review": "the user gives a plan, text or code to evaluate: answer, then anonymous peer review; always 2 rounds",
    "brainstorm": "generating many ideas, names or options, then picking the best",
}


def build_plan_messages(*, ask: dict, pool: list[dict], history: list[dict]) -> list[dict]:
    """The moderator staffs the discussion: format, rounds, and 2–5 seats (model, role, duty)
    from ``pool`` (``[{"id", "name", "vision"}]``)."""
    lang_rule = "Simplified Chinese" if (ask.get("lang") or "zh") == "zh" else "the language of the user's question"
    images = sum(1 for item in ask.get("files") or [] if item.get("type") == "image")
    documents = [item.get("name") for item in ask.get("files") or [] if item.get("type") != "image"]
    system = (
        "You are the moderator of a multi-model discussion (讨论台). Before it starts you set it up for the user's "
        "question: choose the format, the number of rounds and the participants (seats) from the available models, "
        "and give each seat a role and a duty. Reply with one JSON object only, no prose:\n"
        '{"mode": "<format key>", "rounds": <1-4>, "seats": [{"model": "<model id>", "role": "<short role>", '
        '"duty": "<one sentence>"}], "reason": "<one sentence>"}\n\n'
        "Formats:\n"
        + "\n".join(f"- {key} ({MODES[key]['label']}): {guide}" for key, guide in PLAN_MODE_GUIDE.items())
        + "\n\nRules:\n"
        f"- {MIN_SEATS}–{MAX_SEATS} seats. Use as many as the question has genuinely distinct angles: 2–3 for a simple or "
        "narrow question, 4–5 only for broad, high-stakes or many-sided ones. Every seat costs one model call per round.\n"
        f"- Rounds 1–{MAX_ROUNDS}: 1 when independent answers are enough, 2 for most questions, 3 for debates and "
        "contested questions, 4 only for hard, many-sided ones. compare is always 1, review always 2.\n"
        "- Prefer models of different families (different voices beat three of a kind) and stronger models for hard "
        "reasoning, code or maths. The same model may take two seats only with clearly different roles (e.g. a debate).\n"
        + ("- The question has images: only pick models with \"vision\": true.\n" if images else "")
        + "- role: 2–8 Chinese characters (or 1–3 words), the seat's angle or side, e.g. 架构师, 风险审查, 用户视角, 正方.\n"
        "- duty: one short sentence, what this seat must cover in this discussion.\n"
        f"- role, duty and reason in {lang_rule}. reason: why this format, this many rounds and these seats, in one sentence.\n"
        '- "model" is copied exactly from the "id" of the list.'
    )
    context = ((ask.get("context") or {}).get("text") or "").strip()
    attached = ([f"{images} image(s)"] if images else []) + ([f"files {', '.join(documents)}"] if documents else [])
    parts = [
        _history_block(history),
        f"Background conversation (excerpt):\n{context[:1500]}" if context else "",
        f"User question:\n{ask.get('question') or ''}",
        "Attached: " + "; ".join(attached) if attached else "",
        "Available models:\n" + json.dumps(pool, ensure_ascii=False),
    ]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(part for part in parts if part)},
    ]


def _pool_model(pool: list[dict], wanted: Any) -> Optional[dict]:
    key = str(wanted or "").strip().lower()
    if not key:
        return None
    for entry in pool:
        if key in (entry["id"].lower(), entry["name"].lower()):
            return entry
    # "deepseek" for "conn.deepseek" / "modelref::conn::deepseek"; a longer fragment of a name
    for entry in pool:
        if re.split(r"::|\.", entry["id"].lower())[-1] == key:
            return entry
    if len(key) >= 4:
        return next((entry for entry in pool if key in entry["name"].lower() or key in entry["id"].lower()), None)
    return None


def plan_from(raw: Any, pool: list[dict]) -> dict:
    """The moderator's JSON as a setup draft: ``{"mode", "rounds", "seats": [{"model", "role",
    "duty"}], "reason"}`` with models from ``pool`` only. Raises ValueError when fewer than
    MIN_SEATS seats remain."""
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in MODES:
        mode = "roundtable"
    try:
        rounds = max(1, min(int(raw.get("rounds") or MODES[mode]["rounds"]), MAX_ROUNDS))
    except (TypeError, ValueError):
        rounds = MODES[mode]["rounds"]
    seats = []
    for item in raw.get("seats") or []:
        if not isinstance(item, dict) or len(seats) >= MAX_SEATS:
            continue
        entry = _pool_model(pool, item.get("model"))
        if entry is None:
            continue
        role = _clean_text(item.get("role"), ROLE_MAX_CHARS)
        # one model twice only with different roles
        if any(s["model"] == entry["id"] and s["role"] == role for s in seats):
            continue
        seats.append({"model": entry["id"], "role": role, "duty": _clean_text(item.get("duty"), DUTY_MAX_CHARS)})
    if len(seats) < MIN_SEATS:
        raise ValueError(f"主持人的安排里能用的模型不到 {MIN_SEATS} 个")
    return {"mode": mode, "rounds": rounds, "seats": seats, "reason": _clean_text(raw.get("reason"), 300)}


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


async def iterate_completion(response: Any, status_code: Optional[int] = None):
    """Yield ("content" | "reasoning", text) and ("usage", dict) from a chat completion
    response: an OpenAI-style SSE StreamingResponse, a JSONResponse or a plain dict."""
    if isinstance(response, dict):
        error = _error_text(response)
        if error:
            raise UpstreamError(error, status_code)
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
            status = getattr(response, "status_code", None)
            async for item in iterate_completion(
                parsed if isinstance(parsed, dict) else {}, status if isinstance(status, int) and status >= 400 else None
            ):
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
                raise UpstreamError(error)
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
    context: Optional[dict] = None,
    origin: Optional[dict] = None,
) -> dict:
    """``origin``: the chat whose message started this discussion (派发方式「讨论」,
    utils/mode_dispatch.py): ``{"chatId", "messageId"}`` — the conclusion goes back there."""
    total_rounds = setup["rounds"] if rounds is None else max(1, min(int(rounds), MAX_ROUNDS))
    if setup["mode"] == "review":
        total_rounds = 2
    ask = {
        "v": 1,
        "id": message_id,
        "userMessageId": user_message_id,
        "question": question,
        "lang": detect_lang(question),
        "mode": setup["mode"],
        "rounds": total_rounds,
        "seats": deepcopy(setup["seats"]),
        "moderator": deepcopy(setup["moderator"]),
        # 主持人安排: the moderator staffs the table before anything else (LiveDiscussion._run_plan)
        "planning": {"status": "waiting"} if setup.get("smart") and not setup["seats"] else None,
        # each seat's assistant for this question, chosen when it starts (see LiveDiscussion._run_match)
        "matching": {"status": "waiting"} if needs_matching(setup["seats"]) else None,
        "status": "running",
        "round": 0,
        "turns": [],
        "interjections": [],
        "conclusion": {"status": "waiting", "content": "", "model": setup["moderator"]["model"], "name": setup["moderator"]["name"]},
        "previousConclusions": [],
        "research": {"status": "waiting", "queries": [], "sources": []} if setup.get("research") else None,
        "files": files or [],
        "context": context,
        "startedAt": now_ms(),
        "endedAt": None,
        "usage": {},
        "error": None,
    }
    if origin:
        ask["origin"] = deepcopy(origin)
    return ask


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
        "seats": [
            {
                "model": s["model"],
                "name": s["name"],
                "label": s["label"],
                "role": s.get("role", ""),
                "assistant": (seat_choice(last, s["id"]) or {}).get("name") or "",
            }
            for s in setup["seats"]
        ],
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
    # pick up where a question failed, stopped or was cut off: the last round's unfinished turns,
    # the rounds still to come, then the conclusion
    resume: bool = False
    retry_delays: tuple = RETRY_DELAYS
    stand_in_delays: tuple = STAND_IN_RETRY_DELAYS
    # (ask) -> {"choices": {seat id: choice}, "duties": {seat id: duty}, "error": str|None}: the
    # assistants of the question's seats (writes to the library happen in there, once)
    match: Optional[Callable[[dict], Awaitable[dict]]] = None
    # (queries) -> {"queries": [...], "docs": [...]}: the seats' 补查 between rounds
    lookup: Optional[Callable[[list[str]], Awaitable[dict]]] = None
    # the seat models that search the web themselves (native web search) in their turns, found
    # when the run starts by ``browsers(ask)`` (a researched question only)
    browse: set = field(default_factory=set)
    browsers: Optional[Callable[[dict], Awaitable[set]]] = None
    # 主持人安排: (ask) -> {"setup": a normalized setup, "reason": str, "error": str|None}: the
    # moderator's table for the question (never raises for a bad answer: a default table instead)
    plan: Optional[Callable[[dict], Awaitable[dict]]] = None
    # writes the planned table to the chat, so later questions sit at it
    persist_setup: Optional[Callable[[dict], None]] = None

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

    async def _stream_into(self, target: dict, key: str, model: str, messages: list[dict], browse: bool = False):
        target["status"] = "streaming"
        target["startedAt"] = now_ms()
        target["content"] = ""
        target["thinking"] = False
        target["retry"] = None
        raw = ""
        # with the (empty) content: a second try clears what the first one had streamed
        await self.send("turn", turn=_brief(target, key, with_content=True))
        response = await (self.call_model(model, messages, browse=True) if browse else self.call_model(model, messages))
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

    async def _speak(
        self, target: dict, key: str, model: str, build, sends_images: bool, delays: Optional[tuple] = None, browse: bool = False
    ):
        """One streamed call, made again when it fails for a passing reason (rate limit, overload,
        a dropped connection) after a visible pause. Many models the app treats as image readers
        reject pictures: when a call that carried images fails otherwise, it is made once more
        without them (and says so)."""
        delays = self.retry_delays if delays is None else delays
        blind = False
        tries = 0
        while True:
            try:
                await asyncio.wait_for(self._stream_into(target, key, model, build(blind=blind), browse=browse), TURN_TIMEOUT_SECONDS)
                return
            except (asyncio.CancelledError, asyncio.TimeoutError):
                raise
            except Exception as exc:
                if browse:
                    # the model's own web search is what failed (a relay without it for this
                    # model): say it again without, and stop offering it to this model for a while
                    log.info("discussion %s: %s %s failed with native web search (%s), again without", self.chat_id, key, model, _short_error(exc)[:120])
                    browse = False
                    self.browse.discard(model)
                    native_search_failed(model)
                    continue
                reason = transient_reason(exc)
                if reason and tries < len(delays):
                    wait = retry_wait(exc, delays[tries])
                    tries += 1
                    log.info("discussion %s: %s %s (%s), try %d in %.0fs", self.chat_id, key, model, reason, tries + 1, wait)
                    target.update(
                        {
                            "status": "waiting",
                            "thinking": False,
                            "retry": {"n": tries, "of": len(delays), "reason": reason, "until": now_ms() + int(wait * 1000), "error": _short_error(exc)[:160]},
                        }
                    )
                    await self.send("turn", turn=_brief(target, key))
                    await asyncio.sleep(wait)
                    continue
                if sends_images and not blind and not reason:
                    blind = True
                    target["imagesDropped"] = True
                    continue
                raise

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
                browse=seat["model"] in self.browse,
            )

        sends_images = bool(self.images) and seat.get("vision", True) is not False and turn["round"] == 1
        try:
            allowed = may_lookup(self.ask, seat["id"], turn["round"])
            await self._speak(turn, turn["id"], seat["model"], build, sends_images, browse=seat["model"] in self.browse)
            turn["status"] = "done"
            text, query = take_lookup(turn["content"])
            turn.pop("lookup", None)
            if query:
                turn["content"] = text
                if allowed:
                    turn["lookup"] = {"query": query}
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
            turn["retry"] = None
            await self.flush()
            await self.send("turn", turn=_brief(turn, turn["id"], with_content=True))

    def _stand_ins(self) -> list[dict]:
        """Seats that could write the conclusion when the moderator cannot: distinct models, the
        ones that spoke in the last round first."""
        moderator = self.ask["moderator"]["model"]
        last_round = max([turn.get("round") or 0 for turn in self.ask.get("turns") or []] or [0])
        spoke = {t["seat"] for t in self.ask.get("turns") or [] if t.get("round") == last_round and t.get("status") == "done"}
        seats = sorted(self.setup["seats"], key=lambda seat: seat["id"] not in spoke)
        out, seen = [], {moderator}
        for seat in seats:
            if seat["model"] in seen:
                continue
            seen.add(seat["model"])
            out.append(seat)
        return out[:MAX_STAND_INS]

    async def _run_conclusion(self):
        conclusion = self.ask["conclusion"]
        if conclusion.get("content") and conclusion.get("status") == "done":
            self.ask["previousConclusions"].append(
                {"content": conclusion["content"], "endedAt": conclusion.get("endedAt")}
            )
        moderator = self.ask["moderator"]
        conclusion.update(
            {
                "status": "waiting",
                "content": "",
                "error": None,
                "usage": {},
                "imagesDropped": False,
                "retry": None,
                "standIn": None,
                "model": moderator["model"],
                "name": moderator["name"],
            }
        )
        self.ask["status"] = "concluding"
        await self.send_state()

        def builder(writer: dict):
            def build(blind: bool):
                ask = {**self.ask, "moderator": {**writer, "vision": False} if blind else writer}
                return build_conclusion_messages(
                    setup=self.setup, ask=ask, history=self.history, images=None if blind else self.images
                )

            return build

        def sends_images(writer: dict) -> bool:
            return bool(self.images) and writer.get("vision", True) is not False

        try:
            try:
                await self._speak(conclusion, "conclusion", moderator["model"], builder(moderator), sends_images(moderator))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # the moderator cannot write it now: a seat that took part writes it instead
                failure = exc
                for seat in self._stand_ins():
                    writer = {"model": seat["model"], "name": seat["name"], "vision": seat.get("vision", True)}
                    reason = transient_reason(failure) or ("超时" if isinstance(failure, asyncio.TimeoutError) else "出错")
                    conclusion.update(
                        {
                            "model": writer["model"],
                            "name": writer["name"],
                            "imagesDropped": False,
                            "standIn": {"for": moderator["name"], "reason": reason, "error": _short_error(failure)[:160]},
                        }
                    )
                    log.info("discussion %s: moderator %s failed (%s), %s concludes", self.chat_id, moderator["model"], reason, writer["model"])
                    try:
                        await self._speak(
                            conclusion, "conclusion", writer["model"], builder(writer), sends_images(writer), self.stand_in_delays
                        )
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as stand_in_exc:
                        failure = stand_in_exc
                else:
                    raise exc
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
            conclusion["retry"] = None
            await self.flush()

    async def _run_plan(self):
        planning = self.ask["planning"]
        planning.update({"status": "running", "startedAt": now_ms(), "error": None})
        await self.send_state()
        try:
            if self.plan is None:
                raise ValueError("主持人安排不可用")
            result = await self.plan(self.ask)
            setup = result["setup"]
            for key in ("mode", "rounds", "seats"):
                self.setup[key] = deepcopy(setup[key])
            self.ask.update({"mode": setup["mode"], "rounds": setup["rounds"], "seats": deepcopy(setup["seats"])})
            self.ask["matching"] = {"status": "waiting"} if needs_matching(setup["seats"]) else None
            planning.update(
                {"status": "error" if result.get("error") else "done", "reason": result.get("reason") or "", "error": result.get("error")}
            )
            if self.persist_setup is not None:
                self.persist_setup(self.setup)
        except asyncio.CancelledError:
            planning["status"] = "stopped"
            raise
        except Exception as exc:
            planning.update({"status": "error", "error": f"主持人没能安排席位（{_short_error(exc)[:120]}）"})
            raise ValueError(planning["error"]) from exc
        finally:
            planning["endedAt"] = now_ms()
            self.save()
            await self.send_state()

    async def _run_match(self):
        matching = self.ask["matching"]
        matching.update({"status": "running", "startedAt": now_ms(), "error": None})
        await self.send_state()
        try:
            result = await asyncio.wait_for(self.match(self.ask), MATCH_TIMEOUT_SECONDS)
            choices = (result or {}).get("choices") or {}
            duties = (result or {}).get("duties") or {}
            for seat in self.ask["seats"]:
                if seat["id"] in choices:
                    seat["assistant_choice"] = choices[seat["id"]]
                if duties.get(seat["id"]) and not seat.get("duty"):
                    seat["duty"] = _clean_text(duties[seat["id"]], DUTY_MAX_CHARS)
            matching["status"] = "error" if (result or {}).get("error") else "done"
            matching["error"] = (result or {}).get("error")
        except asyncio.CancelledError:
            matching["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            matching.update({"status": "error", "error": f"超过 {MATCH_TIMEOUT_SECONDS} 秒没匹配完，用各自的角色讨论"})
        except Exception as exc:
            log.warning("discussion %s: matching failed: %s", self.chat_id, exc)
            matching.update({"status": "error", "error": f"匹配助手失败（{_short_error(exc)[:120]}），用各自的角色讨论"})
        finally:
            matching["endedAt"] = now_ms()
            self.save()
            await self.send_state()

    async def _run_research(self):
        research = self.ask["research"]
        research.update({"status": "running", "startedAt": now_ms(), "error": None})
        await self.send_state()
        try:
            if self.search is None:
                raise ValueError("联网搜索不可用")
            found = await asyncio.wait_for(self.search(self.ask["question"], self.history), RESEARCH_TIMEOUT_SECONDS)
            sources = sources_from_docs(found, RESEARCH_MAX_SOURCES, RESEARCH_EXCERPT_CHARS, question=self.ask["question"])
            research["queries"] = [q for q in (found or {}).get("queries") or [] if q][:6]
            research["sources"] = sources
            research["status"] = "skipped" if (found or {}).get("skipped") else "done" if sources else "empty"
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

    async def _run_lookups(self, round_index: int):
        """The 补查 the seats asked for in this round, searched together; what they find joins
        the notes (numbered after the ones there) before the next round."""
        research = self.ask.get("research")
        turns = [
            t
            for t in self.ask["turns"]
            if t.get("round") == round_index and t.get("status") == "done" and (t.get("lookup") or {}).get("query") and not t["lookup"].get("status")
        ]
        if not research or not turns or self.lookup is None:
            return
        queries: list[str] = []
        for turn in turns:
            query = turn["lookup"]["query"]
            if query.lower() not in {q.lower() for q in queries} and len(queries) >= LOOKUPS_PER_ROUND:
                turn["lookup"]["status"] = "skipped"
                continue
            if query.lower() not in {q.lower() for q in queries}:
                queries.append(query)
        entry = {"round": round_index, "queries": queries, "status": "running", "added": 0, "startedAt": now_ms(), "endedAt": None, "error": None}
        research.setdefault("lookups", []).append(entry)
        asking = [t for t in turns if t["lookup"].get("status") != "skipped"]
        for turn in asking:
            turn["lookup"]["status"] = "running"
        await self.send_state()
        try:
            found = await asyncio.wait_for(self.lookup(queries), LOOKUP_TIMEOUT_SECONDS)
            existing = research.get("sources") or []
            room_left = min(LOOKUP_MAX_SOURCES, RESEARCH_TOTAL_SOURCES - len(existing))
            added = (
                sources_from_docs(found, room_left, RESEARCH_EXCERPT_CHARS, question=self.ask["question"], existing=existing)
                if room_left > 0
                else []
            )
            if added:
                research["sources"] = existing + added
                research["status"] = "done"
                research["error"] = None
            entry.update({"status": "done" if added else "empty", "added": len(added)})
        except asyncio.CancelledError:
            entry["status"] = "stopped"
            raise
        except asyncio.TimeoutError:
            entry.update({"status": "error", "error": f"超过 {LOOKUP_TIMEOUT_SECONDS} 秒没查完"})
        except Exception as exc:
            entry.update({"status": "error", "error": _short_error(exc)[:200]})
        finally:
            entry["endedAt"] = now_ms()
            for turn in asking:
                turn["lookup"]["status"] = entry["status"]
                turn["lookup"]["added"] = entry["added"]
            self.save()
            await self.send_state()

    async def _resume_round(self):
        """Run the unfinished turns of the last round reached again; later rounds follow."""
        started = sorted({turn.get("round") or 0 for turn in self.ask["turns"]})
        if not started:
            self.from_round = 1
            return
        last = started[-1]
        redo = [turn for turn in self.ask["turns"] if turn.get("round") == last and turn.get("status") != "done"]
        self.from_round = last + 1
        if not redo:
            return
        self.ask["round"] = last
        for turn in redo:
            turn.update({"status": "waiting", "content": "", "error": None, "usage": {}, "imagesDropped": False, "retry": None})
        await self.send_state()
        await asyncio.gather(*(self._run_turn(turn) for turn in redo))
        self.save()
        if last == 1 and not any(t["status"] == "done" for t in self.ask["turns"] if t.get("round") == 1):
            raise ValueError("第一轮所有参与者都失败了")
        await self._run_lookups(last)

    async def _find_browsers(self):
        if self.browsers is None or not self.ask.get("research"):
            return
        try:
            self.browse = set(await self.browsers(self.ask) or ())
        except Exception as exc:
            log.info("discussion %s: native web search check failed: %s", self.chat_id, exc)

    async def run(self):
        self.flusher = asyncio.create_task(self._flush_loop())
        try:
            if self.retry_turn:
                await self._find_browsers()
                turn = next(t for t in self.ask["turns"] if t["id"] == self.retry_turn)
                turn.update({"status": "waiting", "content": "", "error": None, "usage": {}, "imagesDropped": False})
                await self.send_state()
                await self._run_turn(turn)
                self.save()
            elif not self.conclude_only:
                research = self.ask.get("research")
                fresh_research = bool(
                    research and research.get("status") in {"waiting", "stopped", "running"} and not self.ask["turns"] and self.from_round == 1
                )
                planning = self.ask.get("planning")
                if planning and (planning.get("status") in {"waiting", "running", "stopped"} or not self.setup["seats"]) and not self.ask["turns"]:
                    # the notes do not depend on who sits at the table: looked up meanwhile
                    researching = asyncio.ensure_future(self._run_research()) if fresh_research else None
                    try:
                        await self._run_plan()
                    except BaseException:
                        if researching is not None:
                            researching.cancel()
                            await asyncio.gather(researching, return_exceptions=True)
                        raise
                    if researching is not None:
                        await researching
                matching = self.ask.get("matching")
                if (
                    self.match is not None
                    and matching
                    and matching.get("status") in {"waiting", "running", "stopped"}
                    and not self.ask["turns"]
                ):
                    await self._run_match()
                if research and research.get("status") in {"waiting", "stopped", "running"} and not self.ask["turns"] and self.from_round == 1:
                    await self._run_research()
                await self._find_browsers()
                if self.resume:
                    await self._resume_round()
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
                    await self._run_lookups(round_index)
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
        "retry": target.get("retry"),
    }
    if "standIn" in target:
        out["standIn"] = target.get("standIn")
        out["model"] = target.get("model")
        out["name"] = target.get("name")
    if target.get("lookup"):
        out["lookup"] = target["lookup"]
    if with_content:
        out["content"] = target.get("content") or ""
    return out


def _short_error(exc: BaseException) -> str:
    text = str(getattr(exc, "detail", None) or exc or exc.__class__.__name__).strip()
    return (text or exc.__class__.__name__)[:300]


TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504, 529}
RATE_LIMIT_RE = re.compile(r"rate.?limit|too many requests|\b429\b|限流|频率", re.I)
BUSY_RE = re.compile(
    r"overload|capacity|temporar|unavailable|try again|bad gateway|\b50[0234]\b|internal server error|繁忙",
    re.I,
)
NETWORK_RE = re.compile(
    r"connect|reset by peer|server disconnected|timed? ?out|timeout|\beof\b|incomplete|broken pipe|end of stream",
    re.I,
)
EMPTY_RE = re.compile(r"空内容|empty")
PERMANENT_RE = re.compile(r"insufficient_quota|billing|invalid.?api.?key|unauthori[sz]ed|forbidden|not found|context.?length|too long", re.I)
RETRY_AFTER_RE = re.compile(r"(?:retry|try again)[^0-9]{0,24}(\d+(?:\.\d+)?)\s*(?:s\b|sec|second|秒)", re.I)


def transient_reason(exc: BaseException) -> Optional[str]:
    """Why a failed call is worth making again ("限流", "上游繁忙", ...), or None if it is not."""
    if isinstance(exc, (asyncio.CancelledError, asyncio.TimeoutError)):
        return None
    text = _short_error(exc)
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if PERMANENT_RE.search(text) and not RATE_LIMIT_RE.search(text):
        return None
    if status == 429 or RATE_LIMIT_RE.search(text):
        return "限流"
    if status in TRANSIENT_STATUS or BUSY_RE.search(text):
        return "上游繁忙"
    if NETWORK_RE.search(text) or isinstance(exc, ConnectionError) or type(exc).__module__.split(".")[0] in {"aiohttp", "httpx"}:
        return "连接中断"
    if EMPTY_RE.search(text):
        return "空回复"
    return None


def retry_wait(exc: BaseException, base: float) -> float:
    """The pause before the next try: the planned one, or longer when the upstream names it."""
    match = RETRY_AFTER_RE.search(_short_error(exc))
    asked = float(match.group(1)) + 1 if match else 0
    return min(max(float(base), asked), RETRY_MAX_WAIT)


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
