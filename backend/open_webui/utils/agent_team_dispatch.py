"""「交给协作台」 from a chat: the message — with what was said before it and its attachments —
becomes a 协作台 team's goal, the reply is a live team card, and the team's result comes back into
this chat when it is done (agent_team_outputs.concluded).

The chat's Hermes 派发方式 「协作台」 (``hermes_options.dispatch == "team"``) lands here instead of
a Hermes run: no model turn. The team starts planning at once with 直接开始 (it runs without an
approval step when every member has a runner; otherwise the card asks for the approval), and the
reply carries ``team_dispatch: {team_id}`` for the card.
"""

import logging
import time
from typing import Any, Optional

from open_webui.models.agent_teams import AgentTeams
from open_webui.models.chats import Chats
from open_webui.utils.agent_teams import (
    ENABLE_AGENT_TEAMS,
    GOAL_MAX_CHARS,
    TeamsError,
    default_title,
    hermes_target,
    start_planning,
)

log = logging.getLogger(__name__)

CONTEXT_MESSAGES = 6          # earlier turns the team sees
CONTEXT_MESSAGE_CHARS = 1200  # of each
CONTEXT_CHARS = 4000          # of all of them together
DEFAULT_TITLES = {"", "New Chat", "新对话", "新聊天"}


def _text(content: Any) -> str:
    """The text of a chat message's content (a string or a list of parts)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(p for p in parts if p).strip()
    return ""


def goal_from(messages: Any) -> tuple[str, str]:
    """(goal, the user's own words) from the request's messages: the last user message, then what
    was said before it (newest last), so the team knows the conversation it came from."""
    rows = [m for m in (messages or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    ask_index = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].get("role") == "user"), None)
    if ask_index is None:
        return "", ""
    ask = _text(rows[ask_index].get("content"))
    lines: list[str] = []
    used = 0
    for row in reversed(rows[max(0, ask_index - CONTEXT_MESSAGES):ask_index]):
        text = _text(row.get("content"))
        if not text:
            continue
        text = text[:CONTEXT_MESSAGE_CHARS] + ("…" if len(text) > CONTEXT_MESSAGE_CHARS else "")
        if used + len(text) > CONTEXT_CHARS:
            break
        used += len(text)
        lines.append(("用户：" if row.get("role") == "user" else "Hermes：") + text)
    goal = ask
    if lines:
        goal += "\n\n（这是在对话里交给协作台的；对话里之前说的，供参考）\n" + "\n\n".join(reversed(lines))
    return goal[:GOAL_MAX_CHARS], ask


def attachments(metadata: dict, user) -> list[dict]:
    """The files attached to this message (images too), as the Hermes host sees them."""
    from open_webui.utils.hermes_agent import _attachment_host_paths

    try:
        return [{"name": name, "path": path} for name, path in _attachment_host_paths(metadata, user, images=True)]
    except Exception:  # noqa: BLE001 — a team without its files is better than none
        log.warning("teams: could not resolve the attachments of a chat dispatch", exc_info=True)
        return []


def card_text(title: str, *, inputs: int = 0, error: Optional[str] = None) -> str:
    """The reply's words (what Hermes reads on the next turn, and what shows without the card)."""
    if error:
        return f"没能交给协作台：{error}"
    files = f"，附带的 {inputs} 个文件会放进团队的工作目录" if inputs else ""
    return (f"🤝 已交给协作台「{title}」：负责人在制定计划，计划好就直接开始{files}。"
            "进度在下面的卡片里实时更新，做完后完整结果会发回这个对话。")


async def run_team_dispatch(request, form_data: dict, user, metadata: dict, model_id: str) -> dict:
    """The chat's message → a team. Finishes the reply at once (no model turn)."""
    from open_webui.socket.main import get_event_emitter
    from open_webui.tasks import create_task

    chat_id, message_id = metadata["chat_id"], metadata["message_id"]
    emitter = get_event_emitter(metadata)
    goal, ask = goal_from(form_data.get("messages"))
    inputs = attachments(metadata, user)

    async def handler():
        team = None
        error = None
        if not ENABLE_AGENT_TEAMS:
            error = "协作台没有开启"
        elif not ask and not inputs:
            error = "消息是空的"
        else:
            try:
                target = await hermes_target(request, user)
                title = default_title(ask or "附件里的任务")
                meta: dict = {"auto_start": True, "from_chat": True}
                if inputs:
                    meta["inputs"] = inputs
                team = AgentTeams.insert(user.id, goal or "处理附带的文件", chat_id, title, meta=meta)
                start_planning(team, target)
            except TeamsError as exc:
                error = exc.detail
            except Exception as exc:  # noqa: BLE001
                log.exception("teams: chat dispatch failed")
                error = f"{type(exc).__name__}"
        content = card_text(team.title if team else "", inputs=len(inputs), error=error)
        fields: dict = {"content": content, "done": True, "completedAt": int(time.time()), "model": model_id}
        if team is not None:
            fields["team_dispatch"] = {"team_id": team.id}
        if error:
            fields["error"] = {"content": content}
        try:
            Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, fields)
        except Exception:  # noqa: BLE001
            log.warning("teams: could not save the dispatch reply", exc_info=True)
        data = dict(fields)
        title = None
        if team is not None:
            try:  # a new chat is named after its team
                if (Chats.get_chat_title_by_id(chat_id) or "").strip() in DEFAULT_TITLES:
                    Chats.update_chat_title_by_id(chat_id, team.title)
                title = Chats.get_chat_title_by_id(chat_id)
            except Exception:  # noqa: BLE001
                title = None
        if title:
            data["title"] = title
        try:
            await emitter({"type": "chat:completion", "data": data})
        except Exception:  # noqa: BLE001
            log.debug("teams: dispatch reply emit failed", exc_info=True)

    task_id, _ = create_task(handler(), id=chat_id, owner_id=user.id)
    return {"status": True, "task_id": task_id}
