"""What the chat's modes that write their own chats (讨论台, 精答) share: the automatic title and
folder an ordinary chat gets, and the numbered web sources their models cite as [n]."""

import json
import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)


def title_from(res: Any) -> str:
    """The title out of a title-generation response (JSON ``{"title": ...}`` or one plain line)."""
    if isinstance(res, dict):
        choices = res.get("choices") or []
        if len(choices) == 1 and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "").strip()
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end > start:
                try:
                    title = str(json.loads(content[start : end + 1]).get("title") or "").strip()
                    if title:
                        return title[:80]
                except Exception:
                    pass
            content = content.strip(" \"'`#*")
            if content and "\n" not in content and len(content) <= 80:
                return content
    return ""


async def auto_title_and_folder(
    request,
    user,
    chat,
    *,
    messages: list[dict],
    model_id: str,
    message_id: str,
    user_message_count: int,
    label: str = "chat",
    folder: bool = True,
) -> tuple[str, Optional[str]]:
    """Title and folder on the same cadence as ordinary chats; returns (title, folder_id) as they
    are afterwards. Never raises: a failed title falls back to the question, a failed folder
    assignment leaves the chat where it is. ``folder=False``: the title only (a run sent from a
    chat: that chat is the one in the history and in a folder)."""
    from open_webui.models.chats import Chats, can_auto_generate_chat_title
    from open_webui.routers.tasks import generate_title
    from open_webui.utils.task import build_fallback_chat_title

    chat_id = chat.id
    config = request.app.state.config
    title = chat.title
    try:
        may_title = getattr(config, "ENABLE_TITLE_GENERATION", True) and can_auto_generate_chat_title(
            chat.title,
            {"title_generation": Chats.get_chat_title_generation_metadata_by_id(chat_id)},
            user_message_count,
            message_id,
        )
    except Exception:
        may_title = False
    if may_title:
        generated = ""
        try:
            generated = title_from(
                await generate_title(request, {"model": model_id, "messages": messages, "chat_id": chat_id}, user)
            )
        except Exception as exc:
            log.info("%s %s: title generation failed: %s", label, chat_id, exc)
        generated = generated or build_fallback_chat_title(messages)
        if generated and Chats.update_chat_title_by_id(
            chat_id,
            generated,
            auto_generated=True,
            last_user_message_count=user_message_count,
            source_message_id=message_id,
        ):
            title = generated

    if not folder:
        return title, chat.folder_id
    folder_id = await auto_folder(
        request,
        user,
        chat,
        messages=messages,
        model_id=model_id,
        message_id=message_id,
        user_message_count=user_message_count,
        title=title,
        label=label,
    )
    return title, folder_id


async def auto_folder(
    request,
    user,
    chat,
    *,
    messages: list[dict],
    model_id: str,
    message_id: str,
    user_message_count: int,
    title: Optional[str],
    label: str = "chat",
) -> Optional[str]:
    """The folder an ordinary chat would be sorted into at this point (the same milestones and
    rules); returns the chat's folder id afterwards. Never raises: a failed assignment leaves the
    chat where it is."""
    from open_webui.routers.tasks import generate_folder_assignment
    from open_webui.utils.folder_assignment import assign_chat_folder, build_default_deps

    folder_id = chat.folder_id
    config = getattr(getattr(getattr(request, "app", None), "state", None), "config", None)
    if not getattr(config, "ENABLE_FOLDER_AUTO_ASSIGNMENT", False):
        return folder_id

    async def call_model(payload: dict):
        return await generate_folder_assignment(request, payload, user)

    try:
        result = await assign_chat_folder(
            chat_id=chat.id,
            user_id=user.id,
            model_id=model_id,
            messages=messages,
            user_message_count=user_message_count,
            message_id=message_id,
            title=title,
            deps=build_default_deps(call_model),
        )
        log.info("%s %s folder assignment: %s %r", label, chat.id, result.status, result.folder_name)
        if result.changed:
            folder_id = result.folder_id
    except Exception as exc:
        log.warning("%s %s: folder assignment failed: %s", label, chat.id, exc)
    return folder_id


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.+#_-]*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
# characters too common to say what a passage is about (a bigram holding one is not a term)
_CJK_FILLER = set("的了吗呢吧啊么是在和与及或也都就还有个这那哪什怎么为")
_EN_STOP = {
    "the", "and", "for", "with", "what", "which", "how", "why", "who", "when", "where", "does", "is", "are",
    "was", "were", "of", "to", "in", "on", "vs", "or", "an", "be", "it", "its", "this", "that", "do",
}
_SENTENCE_RE = re.compile(r"[^\n。！？；!?]*(?:[。！？；!?]+|\n+|$)")
PASSAGE_CHARS = 180
LEAD_CHARS = 200
_IMAGE_RE = re.compile(r"!\s*\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:https?:)?//[^)]*\)")


def _readable(text: str) -> str:
    """Page text without what reads as noise to a model: images, and the addresses of links
    (their words stay)."""
    return _LINK_RE.sub(r"\1", _IMAGE_RE.sub("", str(text or "")))


def search_terms(*texts: str) -> dict[str, int]:
    """What a question and its search queries are about, as weighted terms: English words and
    numbers (2), Chinese character pairs (1)."""
    terms: dict[str, int] = {}
    for text in texts:
        lowered = str(text or "").lower()
        for word in _WORD_RE.findall(lowered):
            word = word.strip(".-_")
            if len(word) >= 2 and word not in _EN_STOP:
                terms[word] = 2
        for run in _CJK_RUN_RE.findall(lowered):
            for i in range(len(run) - 1):
                pair = run[i : i + 2]
                if not (_CJK_FILLER & set(pair)):
                    terms.setdefault(pair, 1)
    return terms


def _passages(text: str) -> list[str]:
    """The page cut into passages of about PASSAGE_CHARS at sentence ends (one long sentence is
    one passage)."""
    out, current = [], ""
    for sentence in _SENTENCE_RE.findall(text):
        sentence = re.sub(r"\s+", " ", sentence).strip()
        if not sentence:
            continue
        if current and len(current) + len(sentence) > PASSAGE_CHARS:
            out.append(current)
            current = ""
        current = f"{current} {sentence}".strip() if current else sentence
    if current:
        out.append(current)
    return out


def relevant_excerpt(text: str, terms: dict[str, int], budget: int) -> str:
    """The parts of a page that bear on the question, within ``budget`` characters: the page's
    lead (title, date, what it is) when it is about the question, the passages with the most
    question terms and the text around them, kept in page
    order and joined with " … " where text was left out. A page that fits is kept whole; one
    without any question term is cut from the top. Images and link addresses are left out."""
    text = _readable(text)
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= budget:
        return flat
    passages = _passages(text)
    if not passages or not terms:
        return flat[:budget]

    def score(passage: str) -> float:
        lowered = passage.lower()
        weight = sum(w for term, w in terms.items() if term in lowered)
        return weight / (1 + len(passage) / 600)

    scored = sorted(((score(p), i) for i, p in enumerate(passages[1:], start=1)), key=lambda x: (-x[0], x[1]))
    if not scored or scored[0][0] <= 0:
        return flat[:budget]
    # the lead (title, date, what the page is) when it is about the question, not a menu
    picked = {0} if score(passages[0]) > 0 else set()
    used = min(len(passages[0]), LEAD_CHARS) if picked else 0
    for value, index in scored:
        if value <= 0:
            break
        size = len(passages[index]) + 3
        if used + size > budget:
            continue
        picked.add(index)
        used += size
    # room left: the text right after (then before) each picked passage, for context
    for step in (1, -1):
        for index in sorted(picked):
            near = index + step
            if 0 < near < len(passages) and near not in picked and used + len(passages[near]) + 3 <= budget:
                picked.add(near)
                used += len(passages[near]) + 3
    parts, previous = ([] if 0 in picked else ["… "]), None
    for index in sorted(picked):
        passage = passages[index][:LEAD_CHARS] if index == 0 else passages[index]
        if previous is not None:
            parts.append(" " if index == previous + 1 else " … ")
        parts.append(passage)
        previous = index
    if previous is not None and previous < len(passages) - 1:
        parts.append(" …")
    return "".join(parts)[: budget + 2]


def sources_from_docs(
    found: Optional[dict],
    limit: int,
    excerpt_chars: int,
    *,
    question: str = "",
    existing: Optional[list[dict]] = None,
) -> list[dict]:
    """Web search results as numbered sources ``{n, title, url, excerpt}``: one per page, pages
    with next to no text left out. The excerpt is the part of the page about ``question`` and the
    search queries (see relevant_excerpt). With ``existing`` sources, the new ones skip their pages
    and are numbered after them."""
    existing = existing or []
    sources, seen = [], {str(s.get("url") or "") for s in existing}
    terms = search_terms(question, *((found or {}).get("queries") or []))
    for doc in (found or {}).get("docs") or []:
        url = str(doc.get("url") or "").strip()
        raw = str(doc.get("content") or "")
        content = re.sub(r"\s+", " ", raw).strip()
        if not url or url in seen or len(content) < 80:
            continue
        seen.add(url)
        sources.append(
            {
                "n": len(existing) + len(sources) + 1,
                "title": str(doc.get("title") or url).replace("\r\n", "\n").strip()[:160],
                "url": url,
                "excerpt": relevant_excerpt(raw, terms, excerpt_chars),
            }
        )
        if len(sources) >= limit:
            break
    return sources


# models whose native web search call failed lately (model id -> when): not offered it again for
# a while (e.g. a relay that has no Responses API for that model answers 503). Kept in DATA_DIR,
# so a restart or a deploy does not make every such model fail once more.
NATIVE_SEARCH_FAILED: dict = {}
NATIVE_SEARCH_RETRY_SECONDS = 7 * 24 * 3600
NATIVE_SEARCH_FAILED_FILE = "native_search_failed.json"
_native_failed_loaded = False


def _native_failed_path():
    from open_webui.env import DATA_DIR

    return DATA_DIR / "cache" / NATIVE_SEARCH_FAILED_FILE


def _load_native_failed() -> None:
    global _native_failed_loaded
    if _native_failed_loaded:
        return
    _native_failed_loaded = True
    try:
        saved = json.loads(_native_failed_path().read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(saved, dict):
        for model_id, at in saved.items():
            if isinstance(at, (int, float)):
                NATIVE_SEARCH_FAILED.setdefault(str(model_id), float(at))


def native_search_failed(model_id: str) -> None:
    """A call made with native web search failed: answer without it, and stop offering it to
    this model for NATIVE_SEARCH_RETRY_SECONDS (across restarts)."""
    import time

    _load_native_failed()
    NATIVE_SEARCH_FAILED[model_id] = time.time()
    try:
        path = _native_failed_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(NATIVE_SEARCH_FAILED), encoding="utf-8")
    except Exception as exc:
        log.info("could not keep the native web search failures: %s", exc)


async def native_search_models(request, user, model_ids) -> set:
    """The models among ``model_ids`` that may search the web themselves (native web search) in
    讨论台 / 精答: the admin allows it and the model's connection supports it or may (a relay with
    renamed models is "unknown" yet often works), except Hermes and the models whose native call
    failed lately. A call that fails with it is made again without it (see native_search_failed).
    The search is offered, not forced: the model looks things up when the notes miss something.
    Ordinary chats keep their own rule (only a supported connection goes native in 智能联网)."""
    import time

    from open_webui.utils.model_identity import resolve_model_from_lookup

    config = getattr(getattr(getattr(request, "app", None), "state", None), "config", None)
    if not getattr(config, "ENABLE_NATIVE_WEB_SEARCH", False):
        return set()
    from open_webui.utils.hermes_agent import is_hermes_agent_model
    from open_webui.utils.middleware import _resolve_native_web_search_support
    from open_webui.utils.models import get_all_models

    models = getattr(request.state, "MODELS", None) or {}
    if not models:
        await get_all_models(request, user=user)
        models = getattr(request.state, "MODELS", None) or {}
    ambiguous = getattr(request.state, "MODELS_AMBIGUOUS", set()) or set()
    _load_native_failed()
    now = time.time()
    out = set()
    for model_id in {m for m in model_ids if m}:
        if now - NATIVE_SEARCH_FAILED.get(model_id, 0) < NATIVE_SEARCH_RETRY_SECONDS:
            continue
        model = resolve_model_from_lookup(models, ambiguous, model_id)
        if not model or is_hermes_agent_model(model) or is_hermes_agent_model(model_id):
            continue
        try:
            support = _resolve_native_web_search_support(request, user, model, model_id)
        except Exception as exc:
            log.info("native web search support of %s unknown: %s", model_id, exc)
            continue
        if support.get("supported") is True or support.get("can_attempt") is True:
            out.add(model_id)
    return out
