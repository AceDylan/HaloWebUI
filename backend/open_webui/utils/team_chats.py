"""Every 协作台 team in the chat history, like a 精答 or a 讨论台 discussion.

A team is a conversation: what you asked, the team at work (a live card, ``team_dispatch`` on the
reply — TeamChatCard in the page), and the result once the lead has written it (posted by
agent_team_outputs.concluded into ``team.chat_id``). How a team gets its chat:

- 「交给协作台」 from a chat (agent_team_dispatch): that chat, the message and its card are there.
- Started on /teams for a chat (``chat_id``, from the chat's menu or a handoff): the goal and the
  card are added to that chat, so it shows the team at work too.
- Started on /teams or from Telegram on its own: a chat of its own, named after the team and
  sorted into a folder (对话分组) the way an ordinary chat is.
- Teams from before teams had chats get theirs the first time the list is read, in their place in
  the history (the team's own times), not at the top.

Never raises into the caller: a team without its chat still runs.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from open_webui.models.agent_teams import AgentTeamModel, AgentTeams
from open_webui.models.chats import ChatForm, ChatMessages, Chats

log = logging.getLogger(__name__)

# chat.meta of a chat written for a team: {"team_id": ...}
CHAT_META_KEY = "agent_team"
# What comes after the user's own words in a goal: the background a handoff carries
# (handoff.ts goalWithBackground), the conversation a chat dispatch carries (goal_from).
_GOAL_TAILS = ("\n\n背景（来自", "\n\n（这是在对话里交给协作台的")
ASK_MAX_CHARS = 4000
# Old teams given a chat per read of the list, and how many of them are sorted into folders
# (one small task-model call each, one after another, in the background).
BACKFILL_LIMIT = 100
BACKFILL_FOLDER_LIMIT = 20
_backfill_tried: set[str] = set()
_background: set = set()


def ask_of(goal: str) -> str:
    """The user's own words in a team's goal (without the background it was given)."""
    text = (goal or "").replace("\r\n", "\n")
    cut = min((i for i in (text.find(tail) for tail in _GOAL_TAILS) if i > 0), default=-1)
    ask = (text[:cut] if cut > 0 else text).strip()
    return ask[:ASK_MAX_CHARS] + ("…" if len(ask) > ASK_MAX_CHARS else "")


def card_text(team: AgentTeamModel, *, backfill: bool = False) -> str:
    """The card reply's words: what Hermes reads on a later turn, and what shows without the card."""
    title = (team.title or "协作任务").strip()
    if backfill:
        return f"🤝 已交给协作台「{title}」。进度、结果页和产出文件都在下面的卡片里。"
    inputs = len((team.meta or {}).get("inputs") or [])
    files = f"，附带的 {inputs} 个文件会放进团队的工作目录" if inputs else ""
    start = "计划好就直接开始" if (team.meta or {}).get("auto_start") else "计划好后等你批准再开始"
    return (f"🤝 已交给协作台「{title}」：负责人在制定计划，{start}{files}。"
            "进度在下面的卡片里实时更新，做完后完整结果会发回这个对话。")


def _model_info(model: Optional[dict]) -> dict:
    from open_webui.utils.model_identity import get_model_selection_id

    if not isinstance(model, dict):
        return {"model": "hermes-agent", "modelName": "Hermes", "modelIdx": 0}
    selection = get_model_selection_id(model) or "hermes-agent"
    info = {"model": selection, "modelName": model.get("name") or selection, "modelIdx": 0}
    if model.get("model_ref") is not None:
        info["model_ref"] = model["model_ref"]
    return info


async def hermes_model_info(request, user) -> dict:
    """The model a team's chat continues with: the user's Hermes model (it can read the team's
    workspace when asked about the result)."""
    from open_webui.utils.hermes_sessions import resolve_hermes_model

    try:
        return _model_info(await resolve_hermes_model(request, user))
    except Exception as exc:  # noqa: BLE001 — the chat is still worth having (HermesSessionsError too)
        log.info("teams: no Hermes model for the team chat of %s (%s)", user.id, exc)
        return _model_info(None)


def card_turn(team: AgentTeamModel, model_info: dict, *, parent_id: Optional[str] = None,
              at: Optional[int] = None, backfill: bool = False) -> tuple[dict, dict]:
    """(the user's message, the card reply) for a team: the goal as the user wrote it, the reply
    carrying ``team_dispatch`` for the live card."""
    stamp = int(at or time.time())
    user_id, reply_id = str(uuid.uuid4()), str(uuid.uuid4())
    user_message = {
        "id": user_id,
        "parentId": parent_id,
        "childrenIds": [reply_id],
        "role": "user",
        "content": ask_of(team.goal) or team.title or "协作任务",
        "timestamp": stamp,
        "models": [model_info["model"]],
    }
    reply: dict[str, Any] = {
        "id": reply_id,
        "parentId": user_id,
        "childrenIds": [],
        "role": "assistant",
        "content": card_text(team, backfill=backfill),
        "model": model_info["model"],
        "modelName": model_info.get("modelName") or model_info["model"],
        "modelIdx": model_info.get("modelIdx", 0),
        "timestamp": stamp,
        "done": True,
        "completedAt": stamp,
        "team_dispatch": {"team_id": team.id},
    }
    if model_info.get("model_ref") is not None:
        reply["model_ref"] = model_info["model_ref"]
    return user_message, reply


def _dual_write(chat_id: str, user_id: str, messages: list[dict]) -> None:
    for message in messages:
        try:
            ChatMessages.upsert_message(chat_id=chat_id, user_id=user_id, message_id=message["id"], message=message)
        except Exception:  # noqa: BLE001 — the chat row is what the page reads
            log.debug("teams: chat_message dual-write failed", exc_info=True)


def new_team_chat(team: AgentTeamModel, model_info: dict, *,
                  backfill: bool = False) -> Optional[tuple[str, str]]:
    """A chat of the team's own (the goal, the card) linked to the team: (chat id, the card's
    message id), or None when it was not written."""
    at = int(team.created_at) if backfill else None
    user_message, reply = card_turn(team, model_info, at=at, backfill=backfill)
    payload = {
        "id": "",
        "title": (team.title or "协作任务")[:80],
        "models": [model_info["model"]],
        "params": {},
        "files": [],
        "history": {"messages": {user_message["id"]: user_message, reply["id"]: reply}, "currentId": reply["id"]},
        "messages": [user_message, reply],
        "tags": [],
        "timestamp": int((at or time.time()) * 1000),
    }
    chat = Chats.insert_new_chat(
        team.user_id,
        ChatForm(chat=payload, title_auto_generated=False),
        meta={CHAT_META_KEY: {"team_id": team.id}},
        created_at=at,
        updated_at=int(team.finished_at or team.updated_at or 0) if backfill else None,
    )
    if chat is None:
        return None
    fresh = AgentTeams.get(team.id, team.user_id)
    if fresh is None or fresh.chat_id:  # gone, or linked meanwhile (a follow-up opened one)
        Chats.delete_chat_by_id(chat.id)
        return None
    _dual_write(chat.id, team.user_id, [user_message, reply])
    AgentTeams.update(team.id, team.user_id, chat_id=chat.id)
    return chat.id, reply["id"]


def add_card_to_chat(team: AgentTeamModel, chat_id: str, model_info: Optional[dict] = None) -> bool:
    """The goal and the team's card at the end of the chat the team was started for (from the
    chat's menu or a handoff): the chat shows its team at work. ``model_info``: for a chat with
    no reply yet (the card is signed by the chat's model otherwise). Not while the chat is
    answering (that reply would be cut off); the result still comes back there when written."""
    from open_webui.tasks import list_task_ids_by_chat_id
    from open_webui.utils.hermes_notify import find_chat_model

    if list_task_ids_by_chat_id(chat_id, blocks_completion_only=True):
        return False
    chat = Chats.get_chat_by_id_and_user_id(chat_id, team.user_id)
    if chat is None:
        return False
    chat_dict = dict(chat.chat or {})
    history = chat_dict.get("history") if isinstance(chat_dict.get("history"), dict) else {}
    messages = history.get("messages") if isinstance(history.get("messages"), dict) else {}
    if any(isinstance(m, dict) and (m.get("team_dispatch") or {}).get("team_id") == team.id
           for m in messages.values()):
        return True
    info = find_chat_model(chat_dict) or model_info
    if not info:
        return False
    leaf_id = history.get("currentId") if history.get("currentId") in messages else None
    user_message, reply = card_turn(team, info, parent_id=leaf_id)
    if leaf_id:
        leaf = messages[leaf_id]
        leaf["childrenIds"] = [*(leaf.get("childrenIds") or []), user_message["id"]]
    messages[user_message["id"]] = user_message
    messages[reply["id"]] = reply
    history["messages"] = messages
    history["currentId"] = reply["id"]
    chat_dict["history"] = history
    if Chats.update_chat_by_id(chat_id, chat_dict, update_title=False) is None:
        return False
    _dual_write(chat_id, team.user_id, [user_message, reply])
    return True


async def emit_chat_event(user_id: str, chat_id: str, kind: str, data: Any = None) -> None:
    """``chat:title`` (the sidebar reloads its list) or ``chat:reload`` (an open chat re-reads)."""
    from open_webui.socket.main import get_event_emitter

    try:
        emitter = get_event_emitter({"user_id": user_id, "chat_id": chat_id, "message_id": None,
                                     "session_id": None}, update_db=False)
        await emitter({"type": kind, "data": data if data is not None else {}})
    except Exception:  # noqa: BLE001
        log.debug("teams: %s event for chat %s failed", kind, chat_id, exc_info=True)


async def sort_into_folder(request, user, chat_id: str, *, model_id: str, messages: list[dict],
                           message_id: str, user_message_count: int = 1) -> Optional[str]:
    """The team's chat into a folder (对话分组) on the ordinary chat's rules; the sidebar is told
    when it moved. Returns the folder id afterwards."""
    from open_webui.utils.mode_chats import auto_folder

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        return None
    folder_id = await auto_folder(request, user, chat, messages=messages, model_id=model_id, message_id=message_id,
                                  user_message_count=user_message_count, title=chat.title, label="team")
    if folder_id != chat.folder_id:
        await emit_chat_event(user.id, chat_id, "chat:title", chat.title)
    return folder_id


def _keep(task) -> None:
    _background.add(task)
    task.add_done_callback(_background.discard)


def _sort_later(request, user, chats: list[tuple[str, str, str, str]]) -> None:
    """[(chat id, model id, ask, message id)] into folders, one after another, after the response."""
    config = getattr(getattr(getattr(request, "app", None), "state", None), "config", None)
    if not chats or not getattr(config, "ENABLE_FOLDER_AUTO_ASSIGNMENT", False):
        return

    async def run():
        for chat_id, model_id, ask, message_id in chats:
            try:
                await sort_into_folder(request, user, chat_id, model_id=model_id,
                                       messages=[{"role": "user", "content": ask}], message_id=message_id)
            except Exception:  # noqa: BLE001
                log.warning("teams: sorting the chat %s into a folder failed", chat_id, exc_info=True)

    _keep(asyncio.create_task(run()))


async def attach(request, user, team: AgentTeamModel) -> AgentTeamModel:
    """A team that was just created gets its place in a chat (see the module doc). Returns the
    team as it is afterwards."""
    from open_webui.utils.hermes_notify import find_chat_model

    try:
        if team.chat_id:
            chat = Chats.get_chat_by_id_and_user_id(team.chat_id, user.id)
            fallback = None
            if chat is not None and not find_chat_model(dict(chat.chat or {})):
                fallback = await hermes_model_info(request, user)
            if chat is not None and add_card_to_chat(team, team.chat_id, fallback):
                await emit_chat_event(user.id, team.chat_id, "chat:reload", {"reason": "team"})
            return team
        info = await hermes_model_info(request, user)
        made = new_team_chat(team, info)
        if not made:
            return AgentTeams.get(team.id, user.id) or team
        chat_id, message_id = made
        await emit_chat_event(user.id, chat_id, "chat:title", team.title)
        _sort_later(request, user, [(chat_id, info["model"], ask_of(team.goal), message_id)])
        return AgentTeams.get(team.id, user.id) or team
    except Exception:  # noqa: BLE001 — the team runs without its chat rather than not at all
        log.exception("teams: could not give team %s its chat", team.id)
        return AgentTeams.get(team.id, user.id) or team


async def backfill(request, user, teams: list[AgentTeamModel]) -> list[AgentTeamModel]:
    """Teams from before teams had chats get one, in their place in the history. Returns the list
    with their chat ids filled in."""
    missing = [t for t in teams if not t.chat_id and t.id not in _backfill_tried][:BACKFILL_LIMIT]
    if not missing:
        return teams
    # taken before the await below: a list read at the same time (the sidebar badge and the
    # 协作台 page) does not write a second chat for the same team
    _backfill_tried.update(t.id for t in missing)
    info = await hermes_model_info(request, user)
    made: dict[str, str] = {}
    to_sort: list[tuple[str, str, str, str]] = []
    for team in missing:
        try:
            written = new_team_chat(team, info, backfill=True)
        except Exception:  # noqa: BLE001
            log.warning("teams: could not write the chat of team %s", team.id, exc_info=True)
            continue
        if written:
            made[team.id] = written[0]
            if len(to_sort) < BACKFILL_FOLDER_LIMIT:
                to_sort.append((written[0], info["model"], ask_of(team.goal), written[1]))
    if not made:
        return teams
    log.info("teams: wrote chats for %d earlier teams of %s", len(made), user.id)
    first = next(t for t in missing if t.id in made)
    await emit_chat_event(user.id, made[first.id], "chat:title", first.title)
    _sort_later(request, user, to_sort)
    return [t.model_copy(update={"chat_id": made[t.id]}) if t.id in made else t for t in teams]


async def backfill_missing(request, user) -> None:
    """backfill for the user's teams that still have no chat, whichever page of the list is read
    (one small indexed read when there are none)."""
    missing = AgentTeams.list_without_chat(user.id, BACKFILL_LIMIT, exclude=_backfill_tried)
    if missing:
        await backfill(request, user, missing)


async def follow_title(team_before: AgentTeamModel, team_after: Optional[AgentTeamModel]) -> None:
    """The lead named the team in its plan: the team's chat takes the name, unless the chat was
    renamed meanwhile (it still carries the old name) or is a chat of its own (another title)."""
    if team_after is None or not team_after.chat_id or team_after.title == team_before.title:
        return
    try:
        current = (Chats.get_chat_title_by_id(team_after.chat_id) or "").strip()
        if current != (team_before.title or "").strip():
            return
        if Chats.update_chat_title_by_id(team_after.chat_id, team_after.title):
            await emit_chat_event(team_after.user_id, team_after.chat_id, "chat:title", team_after.title)
    except Exception:  # noqa: BLE001
        log.debug("teams: chat title of %s not followed", team_after.id, exc_info=True)
