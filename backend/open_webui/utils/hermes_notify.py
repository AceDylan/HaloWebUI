"""Hermes background-task notifications for HaloWebUI Web Chat.

Hermes's API server is stateless: once a ``/v1/runs`` turn ends it has no channel
back to the browser, so a background process that finishes later (for example a
``reclaude-run.sh`` run launched by hermes) cannot be reported into the chat.
This module closes the loop from the other side: the finished process POSTs to
``/api/v1/hermes/notifications`` and HaloWebUI appends a follow-up user turn to
the chat and starts a normal hermes run for it, so the report streams into the
chat exactly like any other reply (tool chain, AGY post-pass, socket updates,
persistence).

Configuration (environment variables):

- HERMES_AGENT_NOTIFY_TOKEN: shared bearer token the notifier must present.
  The endpoint answers 503 while it is unset.
"""

import asyncio
import hmac
import logging
import os
import re
import time
import uuid
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.models.users import Users
from open_webui.socket.main import get_event_emitter
from open_webui.tasks import list_task_ids_by_chat_id

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

HERMES_AGENT_NOTIFY_TOKEN_ENV = "HERMES_AGENT_NOTIFY_TOKEN"
NOTIFICATION_PROMPT_MAX_CHARS = 8000
# mode=display: the runner's own report, shown as the reply (runner caps it near 6000).
NOTIFICATION_CONTENT_MAX_CHARS = 20000
NOTIFICATION_NOTICE_MAX_CHARS = 1000
DEFAULT_REPORT_NOTICE = "[后台任务完成通知]"
CONVERSATION_MESSAGE_LIMIT = 20
RELOAD_EVENT_TYPE = "chat:reload"
# Give the browser a moment to reload the chat (and register the placeholder
# message) before the run starts streaming into it.
RELOAD_SETTLE_SECONDS = 1.0

_DETAILS_BLOCK_RE = re.compile(r"<details\b[^>]*>.*?</details\s*>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")

# The away push of a runner report (usually into the same Telegram chat hermes talks in).
# The report's "↩️ 直接回复…" is for this web chat: a reply to the push never reaches the
# run. The push is cut near 1200 characters from the top, which for a QUESTION report
# was all preamble and no question.
_REPLY_HINT_LINE_RE = re.compile(r"^↩️.*(?:\n|$)", re.MULTILINE)
_QUOTA_FOOTER_LINE_RE = re.compile(r"^\*\*reclaude 额度\*\*.*(?:\n|$)", re.MULTILINE)
_QUESTION_START_RE = re.compile(r"^\s*(?:\*\*)?QUESTION(?:\*\*)?\s*[:：]", re.MULTILINE)
_QUESTION_END_RE = re.compile(r"\n\s*(?:---+|\*\*Obsidian 归档|\*\*runner 提示\*\*)")
PUSH_QUESTION_MAX_CHARS = 900
PUSH_REPLY_HINT = "↩️ 要回复请打开上面的链接，在网页的这个对话里直接说（回复这条推送，它收不到）。"


class HermesNotifyError(Exception):
    """Notification could not be turned into a follow-up turn."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def notify_token_configured() -> bool:
    return bool(os.environ.get(HERMES_AGENT_NOTIFY_TOKEN_ENV, "").strip())


def verify_notify_token(authorization: Optional[str]) -> bool:
    """Constant-time check of ``Authorization: Bearer <token>``."""
    expected = os.environ.get(HERMES_AGENT_NOTIFY_TOKEN_ENV, "").strip()
    if not expected or not authorization:
        return False
    scheme, _, presented = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(presented.strip(), expected)


def _history(chat_dict: dict[str, Any]) -> dict[str, Any]:
    history = chat_dict.get("history")
    if not isinstance(history, dict):
        history = {}
        chat_dict["history"] = history
    messages = history.get("messages")
    if not isinstance(messages, dict):
        history["messages"] = {}
    return history


def message_chain(chat_dict: dict[str, Any], leaf_id: Optional[str]) -> list[dict[str, Any]]:
    """Messages from the root down to ``leaf_id`` following ``parentId`` links."""
    messages = _history(chat_dict)["messages"]
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = leaf_id
    while current and current not in seen:
        message = messages.get(current)
        if not isinstance(message, dict):
            break
        seen.add(current)
        chain.append(message)
        current = message.get("parentId")
    chain.reverse()
    return chain


def find_chat_model(chat_dict: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Model fields of the newest assistant message on the current branch."""
    history = _history(chat_dict)
    for message in reversed(message_chain(chat_dict, history.get("currentId"))):
        if message.get("role") == "assistant" and message.get("model"):
            info = {"model": message["model"]}
            for key in ("modelName", "model_ref", "modelIdx"):
                if message.get(key) is not None:
                    info[key] = message[key]
            return info
    return None


def _plain_text(content: Any) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        content = "\n".join(parts)
    text = _DETAILS_BLOCK_RE.sub("", str(content or ""))
    return _WHITESPACE_RUN_RE.sub(" ", text).strip()


def build_conversation_messages(
    chat_dict: dict[str, Any], leaf_id: str, limit: int = CONVERSATION_MESSAGE_LIMIT
) -> list[dict[str, str]]:
    """OpenAI-style ``messages`` for the branch ending at ``leaf_id``.

    Mirrors what the web client sends: the branch's user/assistant turns as
    text. Tool-call ``<details>`` blocks are dropped; hermes keeps its own
    session history and only needs the conversational text.
    """
    chain = message_chain(chat_dict, leaf_id)
    messages = []
    for message in chain:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _plain_text(message.get("content"))
        if role == "assistant" and not text:
            continue
        messages.append({"role": role, "content": text})
    if limit and len(messages) > limit:
        messages = messages[-limit:]
    return messages


def append_follow_up_turn(
    chat_dict: dict[str, Any],
    prompt: str,
    model_info: dict[str, Any],
    *,
    now: Optional[int] = None,
) -> tuple[str, str]:
    """Append a user message plus an empty assistant placeholder to the chat.

    Both messages hang off the current branch leaf (``history.currentId``), and
    ``currentId`` moves to the placeholder, exactly like the web client does when
    the user sends a prompt. Returns ``(user_message_id, assistant_message_id)``.
    """
    history = _history(chat_dict)
    messages = history["messages"]
    timestamp = int(now if now is not None else time.time())
    leaf_id = history.get("currentId")
    leaf = messages.get(leaf_id) if leaf_id else None

    user_id = str(uuid.uuid4())
    assistant_id = str(uuid.uuid4())

    messages[user_id] = {
        "id": user_id,
        "parentId": leaf_id if isinstance(leaf, dict) else None,
        "childrenIds": [assistant_id],
        "role": "user",
        "content": prompt,
        "timestamp": timestamp,
    }
    assistant: dict[str, Any] = {
        "id": assistant_id,
        "parentId": user_id,
        "childrenIds": [],
        "role": "assistant",
        "content": "",
        "model": model_info["model"],
        "modelName": model_info.get("modelName") or model_info["model"],
        "modelIdx": model_info.get("modelIdx", 0),
        "timestamp": timestamp,
        "done": False,
    }
    if model_info.get("model_ref") is not None:
        assistant["model_ref"] = model_info["model_ref"]
    messages[assistant_id] = assistant

    if isinstance(leaf, dict):
        children = leaf.get("childrenIds")
        if not isinstance(children, list):
            children = []
        if user_id not in children:
            children.append(user_id)
        leaf["childrenIds"] = children

    history["currentId"] = assistant_id
    return user_id, assistant_id


def append_report_turn(
    chat_dict: dict[str, Any],
    notice: str,
    content: str,
    model_info: dict[str, Any],
    *,
    now: Optional[int] = None,
    source: str = "",
    run_id: str = "",
) -> tuple[str, str]:
    """Append the notice as a user message and the report as a finished reply.

    Same branch handling as :func:`append_follow_up_turn`; the assistant message is
    complete (``done``) instead of a placeholder for a model turn to fill. The notice
    stays a user message (hermes reads the run id and session from it on the next
    turn) but carries ``hermes_notice``, so the page shows it as a system line
    instead of something the person said.
    """
    timestamp = int(now if now is not None else time.time())
    user_id, assistant_id = append_follow_up_turn(chat_dict, notice, model_info, now=timestamp)
    messages = _history(chat_dict)["messages"]
    messages[user_id]["hermes_notice"] = {
        key: value for key, value in {"source": source, "run_id": run_id}.items() if value
    } or {"source": "runner"}
    messages[assistant_id].update({"content": content, "done": True, "completedAt": timestamp})
    return user_id, assistant_id


def build_follow_up_form_data(
    *,
    model_id: str,
    messages: list[dict[str, str]],
    chat_id: str,
    assistant_message_id: str,
) -> dict[str, Any]:
    """Request body equivalent to the web client's chat completion call."""
    return {
        "stream": True,
        "model": model_id,
        "messages": messages,
        "params": {},
        "features": {
            "html_visual_artifacts": "force",
            "html_visual_surface": "halowebui-web",
        },
        "chat_id": chat_id,
        "id": assistant_message_id,
        # A truthy socket session id is required by the hermes path; events are
        # fanned out to every live socket of the chat owner anyway.
        "session_id": f"hermes-notify:{uuid.uuid4()}",
        "background_tasks": {
            "title_generation": False,
            "tags_generation": False,
            "follow_up_generation": False,
        },
    }


async def start_follow_up_turn(
    request, *, chat_id: str, prompt: str, source: str = ""
) -> dict[str, Any]:
    """Append the notification as a user turn and run hermes for it.

    Raises :class:`HermesNotifyError` with an HTTP status when the chat is
    unknown, has no model to answer with, or is still busy with another run.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise HermesNotifyError(422, "prompt is empty")
    if len(prompt) > NOTIFICATION_PROMPT_MAX_CHARS:
        raise HermesNotifyError(422, "prompt is too long")

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        raise HermesNotifyError(404, "chat not found")
    user = Users.get_user_by_id(chat.user_id)
    if user is None:
        raise HermesNotifyError(404, "chat owner not found")

    # Only a turn that is still producing its reply makes the chat busy. A finished
    # reply's post-processing (the AGY design pass, title/tags) runs as a
    # non-blocking task and used to hold every notice back until it ended (a 409
    # per 30 s retry: about a minute for runs that finish right after launching).
    running = list_task_ids_by_chat_id(chat_id, blocks_completion_only=True)
    if running:
        raise HermesNotifyError(409, "chat is busy with another run; retry later")

    chat_dict = dict(chat.chat or {})
    model_info = find_chat_model(chat_dict)
    if not model_info:
        raise HermesNotifyError(422, "chat has no assistant model to continue with")

    user_message_id, assistant_message_id = append_follow_up_turn(
        chat_dict, prompt, model_info
    )
    if Chats.update_chat_by_id(chat_id, chat_dict, update_title=False) is None:
        raise HermesNotifyError(500, "failed to persist the follow-up turn")

    emitter = get_event_emitter(
        {
            "user_id": user.id,
            "chat_id": chat_id,
            "message_id": assistant_message_id,
        },
        update_db=False,
    )
    try:
        await emitter(
            {
                "type": RELOAD_EVENT_TYPE,
                "data": {
                    "reason": "hermes_notification",
                    "source": source or "",
                    "user_message_id": user_message_id,
                    "message_id": assistant_message_id,
                },
            }
        )
    except Exception as e:  # the turn still runs; the chat is reloaded on next open
        log.warning(f"hermes notification reload event failed for chat {chat_id}: {e}")
    await asyncio.sleep(RELOAD_SETTLE_SECONDS)

    form_data = build_follow_up_form_data(
        model_id=model_info["model"],
        messages=build_conversation_messages(chat_dict, assistant_message_id),
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
    )

    # Imported lazily: open_webui.main imports the routers at import time.
    from open_webui.main import chat_completion

    result = await chat_completion(request, form_data, user)
    log.info(
        "hermes notification started follow-up turn chat=%s source=%s message=%s",
        chat_id,
        source or "",
        assistant_message_id,
    )
    return {
        "status": True,
        "chat_id": chat_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "result": result,
    }



_REPORT_DESIGN_TASKS: set = set()


def _delivered_report_turn(chat_dict: dict[str, Any], run_id: str) -> Optional[tuple[str, str]]:
    """(notice id, report id) of the report already shown for `run_id`, if any."""
    run_id = (run_id or "").strip()[:128]
    if not run_id:
        return None
    messages = _history(chat_dict).get("messages") or {}
    for message_id, message in messages.items():
        notice = message.get("hermes_notice") if isinstance(message, dict) else None
        if isinstance(notice, dict) and notice.get("run_id") == run_id:
            children = message.get("childrenIds") or []
            return message_id, (children[0] if children else "")
    return None


def report_push_text(content: str) -> str:
    """A runner report as the away push shows it: the status lines, then the QUESTION
    itself when the run is waiting for an answer, and where to answer."""
    text = _QUOTA_FOOTER_LINE_RE.sub("", _REPLY_HINT_LINE_RE.sub("", content or "")).strip()
    # The headline says who finished and how; the details line (model, session, cost, turns)
    # only took room from the 1200 characters a push has.
    header, body = split_report_header(text)
    if header:
        text = f"{header.splitlines()[0]}\n\n{body}".strip()
    questions = list(_QUESTION_START_RE.finditer(text))
    if not questions:
        return text
    head = "\n".join(text.split("\n", 2)[:2]).strip()
    question = text[questions[-1].start():].strip()
    end = _QUESTION_END_RE.search(question)
    question = question[: end.start()].strip() if end else question
    if len(question) > PUSH_QUESTION_MAX_CHARS:
        question = question[:PUSH_QUESTION_MAX_CHARS].rstrip() + "…"
    return f"{head}\n\n{question}\n\n{PUSH_REPLY_HINT}"


async def show_notification_report(
    request,
    *,
    chat_id: str,
    content: str,
    notice: str = "",
    source: str = "",
    run_id: str = "",
    quiet: bool = False,
    push: bool = True,
    design: bool = True,
    max_chars: int = NOTIFICATION_CONTENT_MAX_CHARS,
) -> dict[str, Any]:
    """mode=display: show a finished background run's report as the reply, no model turn.

    The runner already wrote the report (its result.md plus a status line), so a hermes
    turn that only reads the file and retypes it (about two minutes) adds nothing. The
    chat gets the notice as a user message and the report as a finished assistant
    reply; open tabs reload, the chat is marked unread and the away webhook fires, as
    for a finished hermes run. The HTML design pass runs afterwards and swaps its
    artifact in, like a normal reply. Same errors as :func:`start_follow_up_turn`.

    ``push=False``: no away push (the sender already told the person elsewhere, e.g. a team's
    Telegram notice). ``design=False``: no HTML design pass (a team's conclusion has its own page).
    ``max_chars``: in-process callers with longer content (a team's complete result).
    """
    content = (content or "").strip()
    notice = (notice or "").strip() or DEFAULT_REPORT_NOTICE
    if not content:
        raise HermesNotifyError(422, "content is empty")
    if len(content) > max_chars:
        raise HermesNotifyError(422, "content is too long")
    if len(notice) > NOTIFICATION_NOTICE_MAX_CHARS:
        notice = notice[:NOTIFICATION_NOTICE_MAX_CHARS]

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        raise HermesNotifyError(404, "chat not found")
    user = Users.get_user_by_id(chat.user_id)
    if user is None:
        raise HermesNotifyError(404, "chat owner not found")
    chat_dict = dict(chat.chat or {})
    delivered = _delivered_report_turn(chat_dict, run_id)
    if delivered:
        # The notifier re-posts after a timeout even when the report was saved;
        # the second copy would show the same report twice.
        log.info("hermes report for run %s already in chat %s", run_id, chat_id)
        return {
            "status": True,
            "chat_id": chat_id,
            "user_message_id": delivered[0],
            "assistant_message_id": delivered[1],
            "duplicate": True,
        }
    if list_task_ids_by_chat_id(chat_id, blocks_completion_only=True):
        raise HermesNotifyError(409, "chat is busy with another run; retry later")
    model_info = find_chat_model(chat_dict)
    if not model_info:
        raise HermesNotifyError(422, "chat has no assistant model to continue with")

    user_message_id, assistant_message_id = append_report_turn(
        chat_dict,
        notice,
        content,
        model_info,
        source=(source or "")[:64],
        run_id=(run_id or "")[:128],
    )
    if Chats.update_chat_by_id(chat_id, chat_dict, update_title=False) is None:
        raise HermesNotifyError(500, "failed to persist the report")

    # Imported lazily: hermes_agent pulls in the socket and middleware stack.
    from open_webui.utils.hermes_agent import _schedule_completion_webhook
    from open_webui.utils.hermes_unread import mark_unread
    from open_webui.utils.html_visual_prompt import HTML_VISUAL_WEB_SURFACE

    metadata = {
        "user_id": user.id,
        "chat_id": chat_id,
        "message_id": assistant_message_id,
        "server_surface": HTML_VISUAL_WEB_SURFACE,
        "features": {
            "html_visual_artifacts": "force",
            "html_visual_surface": HTML_VISUAL_WEB_SURFACE,
        },
    }
    emitter = get_event_emitter(metadata, update_db=False)
    try:
        await emitter(
            {
                "type": RELOAD_EVENT_TYPE,
                "data": {
                    "reason": "hermes_notification",
                    "source": source or "",
                    "user_message_id": user_message_id,
                    "message_id": assistant_message_id,
                },
            }
        )
    except Exception as e:  # the report is saved; the chat shows it on next open
        log.warning(f"hermes report reload event failed for chat {chat_id}: {e}")
    if quiet:
        # The person caused it (a run they stopped) and is looking at the page:
        # no unread mark, no push, no design pass for a three-line notice.
        return {
            "status": True,
            "chat_id": chat_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
        }
    mark_unread(chat_id, user.id)
    if push:
        _schedule_completion_webhook(
            request,
            user,
            metadata,
            Chats.get_chat_title_by_id(chat_id),
            report_push_text(content),
        )

    if design:
        task = asyncio.create_task(_design_report(emitter, metadata, content))
        _REPORT_DESIGN_TASKS.add(task)
        task.add_done_callback(_REPORT_DESIGN_TASKS.discard)
    log.info(
        "hermes notification shown as a report chat=%s source=%s message=%s",
        chat_id,
        source or "",
        assistant_message_id,
    )
    return {
        "status": True,
        "chat_id": chat_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
    }


# A runner report's first line ("✅ agy 运行 <id> · 已完成") and, when present, its details
# line ("AGY conversation e87… · 1 轮" / "claude-opus · Claude 会话 … · $1.12 · 26 轮 · 4m08s").
_REPORT_HEADLINE_RE = re.compile(r"^\S+\s+\S+\s+运行\s+\S+\s+·\s+\S")
_REPORT_BODY_START_RE = re.compile(r"^(#|[-*>]|```|<)")


def split_report_header(content: str) -> tuple[str, str]:
    """(header, body) of a runner report; ("", content) when it has no runner header.

    The chat shows the header in the notice line above the report (HermesRunNotice), so the
    designed card leaves it out — the designer used to turn it into a chip row with the run
    id and "AGY conversation …" at the top of every card."""
    lines = (content or "").split("\n")
    if not lines or not _REPORT_HEADLINE_RE.match(lines[0].strip()):
        return "", content
    count = 1
    second = lines[1].strip() if len(lines) > 1 else ""
    if second and not _REPORT_BODY_START_RE.match(second):
        count = 2
    return "\n".join(lines[:count]), "\n".join(lines[count:]).lstrip("\n")


async def _design_report(emitter, metadata: dict[str, Any], content: str) -> None:
    """The HTML design pass for a shown report: same helpers as a hermes reply; the runner's
    header lines stay outside the card (see :func:`split_report_header`)."""
    from open_webui.utils.html_visual_prompt import (
        append_html_visual_fallback,
        design_html_visual_artifact_with_agy,
    )

    header, body = split_report_header(content)
    try:
        designed = await design_html_visual_artifact_with_agy(body, metadata)
        designed = append_html_visual_fallback(designed, metadata)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"hermes report design failed: {e}")
        return
    if designed == body:
        return
    if header:
        designed = f"{header}\n\n{designed}"
    try:
        Chats.upsert_message_to_chat_by_id_and_message_id(
            metadata["chat_id"],
            metadata["message_id"],
            {"content": designed},
            guard_stopped=True,
            set_current=False,
        )
        await emitter({"type": "chat:completion", "data": {"content": designed}})
    except Exception as e:
        log.warning(f"hermes report design update failed: {e}")

