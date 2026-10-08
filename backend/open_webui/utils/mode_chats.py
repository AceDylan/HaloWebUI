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


def sources_from_docs(found: Optional[dict], limit: int, excerpt_chars: int) -> list[dict]:
    """Web search results as numbered sources ``{n, title, url, excerpt}``: one per page, pages
    with next to no text left out."""
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
                "title": str(doc.get("title") or url).replace("\r\n", "\n").strip()[:160],
                "url": url,
                "excerpt": content[:excerpt_chars],
            }
        )
        if len(sources) >= limit:
            break
    return sources
