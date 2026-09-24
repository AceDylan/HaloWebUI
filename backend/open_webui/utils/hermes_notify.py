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
) -> tuple[str, str]:
    """Append the notice as a user message and the report as a finished reply.

    Same branch handling as :func:`append_follow_up_turn`; the assistant message is
    complete (``done``) instead of a placeholder for a model turn to fill.
    """
    timestamp = int(now if now is not None else time.time())
    user_id, assistant_id = append_follow_up_turn(chat_dict, notice, model_info, now=timestamp)
    assistant = _history(chat_dict)["messages"][assistant_id]
    assistant.update({"content": content, "done": True, "completedAt": timestamp})
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


async def show_notification_report(
    request, *, chat_id: str, content: str, notice: str = "", source: str = ""
) -> dict[str, Any]:
    """mode=display: show a finished background run's report as the reply, no model turn.

    The runner already wrote the report (its result.md plus a status line), so a hermes
    turn that only reads the file and retypes it (about two minutes) adds nothing. The
    chat gets the notice as a user message and the report as a finished assistant
    reply; open tabs reload, the chat is marked unread and the away webhook fires, as
    for a finished hermes run. The HTML design pass runs afterwards and swaps its
    artifact in, like a normal reply. Same errors as :func:`start_follow_up_turn`.
    """
    content = (content or "").strip()
    notice = (notice or "").strip() or DEFAULT_REPORT_NOTICE
    if not content:
        raise HermesNotifyError(422, "content is empty")
    if len(content) > NOTIFICATION_CONTENT_MAX_CHARS:
        raise HermesNotifyError(422, "content is too long")
    if len(notice) > NOTIFICATION_NOTICE_MAX_CHARS:
        notice = notice[:NOTIFICATION_NOTICE_MAX_CHARS]

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        raise HermesNotifyError(404, "chat not found")
    user = Users.get_user_by_id(chat.user_id)
    if user is None:
        raise HermesNotifyError(404, "chat owner not found")
    if list_task_ids_by_chat_id(chat_id, blocks_completion_only=True):
        raise HermesNotifyError(409, "chat is busy with another run; retry later")
    chat_dict = dict(chat.chat or {})
    model_info = find_chat_model(chat_dict)
    if not model_info:
        raise HermesNotifyError(422, "chat has no assistant model to continue with")

    user_message_id, assistant_message_id = append_report_turn(
        chat_dict, notice, content, model_info
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
    mark_unread(chat_id, user.id)
    _schedule_completion_webhook(
        request, user, metadata, Chats.get_chat_title_by_id(chat_id), content
    )

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


async def _design_report(emitter, metadata: dict[str, Any], content: str) -> None:
    """The HTML design pass for a shown report: same helpers as a hermes reply."""
    from open_webui.utils.html_visual_prompt import (
        append_html_visual_fallback,
        design_html_visual_artifact_with_agy,
    )

    try:
        designed = await design_html_visual_artifact_with_agy(content, metadata)
        designed = append_html_visual_fallback(designed, metadata)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"hermes report design failed: {e}")
        return
    if designed == content:
        return
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

