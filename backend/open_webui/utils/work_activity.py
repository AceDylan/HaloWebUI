"""运行中 beyond Hermes: what else is working for the user right now, one row per piece of work.

Hermes runs and background runners keep their own rows (``list_active_runs`` /
``list_runner_progress``); this adds an ordinary chat writing its reply (or drawing a picture),
精答, 讨论台, 协作台, 自动分流 choosing a mode, and the image studio making pictures, so the sidebar
answers "what is still going" for every mode. Everything here is read from memory or one bounded
query: it runs on the sidebar's 10 s poll.

Row: ``{kind, id, title, href, started_at, state}`` — ``state`` is ``running``, or ``waiting``
when the work waits for the user (a team's plan to approve, a member's question).
"""

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

TEAM_LIMIT = 10
# titles a chat has before it is named: the row shows the question instead
PLACEHOLDER_TITLES = {"New Chat", "新对话", "新聊天", "新精答", "新讨论"}
AUTO_STALE_SECONDS = 600  # the receipt's own interruption window (routers/auto.py)


def _titles(chat_ids: set[str]) -> dict[str, str]:
    """Chat titles in one query of the title column (never the chat JSON)."""
    if not chat_ids:
        return {}
    from open_webui.internal.db import get_db
    from open_webui.models.chats import Chat

    with get_db() as db:
        found = db.query(Chat.id, Chat.title).filter(Chat.id.in_(list(chat_ids))).all()
    return {id: title for id, title in found if title and title not in PLACEHOLDER_TITLES}


def _chat_replies(user_id: str, skip: set[str]) -> list[dict]:
    """Chats whose reply is being written now (a picture drawn in the chat counts too)."""
    from open_webui.tasks import task_metadata

    rows: dict[str, dict] = {}
    for meta in list(task_metadata.values()):
        chat_id = meta.get("chat_id")
        if meta.get("owner_id") != user_id or not chat_id or chat_id == "local" or chat_id in skip:
            continue
        # follow-up work after the reply (titles, tags) does not keep a chat "running"
        if not meta.get("blocks_completion", True) or meta.get("kind") not in (None, "image"):
            continue
        started = float(meta.get("started_at") or time.time())
        kind = "image" if meta.get("kind") == "image" else "chat"
        known = rows.get(chat_id)
        if known is None or started < known["started_at"]:
            rows[chat_id] = {"kind": kind, "id": chat_id, "chat_id": chat_id, "href": f"/c/{chat_id}",
                             "started_at": started, "state": "running"}
    return list(rows.values())


def _desks(user_id: str) -> list[dict]:
    from open_webui.utils import answer_desk, discussion_room

    rows = []
    for kind, live_map, path in (("answer", answer_desk.LIVE, "/answer/"),
                                 ("discuss", discussion_room.LIVE, "/discuss/")):
        for chat_id, live in list(live_map.items()):
            if getattr(live, "user_id", None) != user_id:
                continue
            run = (live.run if kind == "answer" else live.ask) or {}
            started = run.get("startedAt")
            rows.append({"kind": kind, "id": chat_id, "chat_id": chat_id, "href": path + chat_id,
                         "title": " ".join(str(run.get("question") or "").split())[:80] or None,
                         "started_at": started / 1000 if started else time.time(), "state": "running"})
    return rows


def _teams(user_id: str) -> list[dict]:
    from open_webui.models.agent_teams import AgentTeams

    rows = []
    for team in AgentTeams.list_working_for_user(user_id, TEAM_LIMIT):
        waiting = team.status == "plan_ready" or team.phase == "attention"
        rows.append({"kind": "team", "id": team.id, "chat_id": team.chat_id, "href": f"/teams/{team.id}",
                     "title": team.title or None,
                     "started_at": team.approved_at or team.created_at,
                     "state": "waiting" if waiting else "running",
                     "note": "等你批准" if team.status == "plan_ready" else ("需要处理" if waiting else None)})
    return rows


def _routes(user_id: str) -> list[dict]:
    from open_webui.models.auto_routes import AutoRoutes

    rows = []
    for route in AutoRoutes.active_for_user(user_id, since=int(time.time()) - AUTO_STALE_SECONDS):
        question = str(((route.get("data") or {}).get("input") or {}).get("question") or "")
        origin = (route.get("data") or {}).get("origin") or {}
        rows.append({"kind": "auto", "id": route["id"], "chat_id": origin.get("chatId"),
                     "href": f"/c/{origin['chatId']}" if origin.get("chatId") else f"/auto?request={route['id']}",
                     "title": " ".join(question.split())[:80] or None,
                     "started_at": route["created_at"], "state": "running"})
    return rows


def _studio(user_id: str) -> list[dict]:
    from open_webui.routers.images import active_image_runs

    return [{"kind": "image", "id": f"studio:{run['id']}", "chat_id": None,
             "href": "/workspace/images?tab=workbench", "title": run.get("prompt") or None,
             "started_at": run.get("started_at") or time.time(), "state": "running"}
            for run in active_image_runs(user_id)]


def list_work(user_id: str, hermes_chat_ids: set[str]) -> list[dict]:
    """Everything above, oldest first. ``hermes_chat_ids``: chats the Hermes rows already show."""
    rows: list[dict] = []
    for part in (_desks, _teams, _routes, _studio):
        try:
            rows.extend(part(user_id))
        except Exception:
            log.debug("运行中: %s unavailable", part.__name__, exc_info=True)
    # a chat that handed its message on shows the work it handed on, not itself
    skip = set(hermes_chat_ids) | {row["chat_id"] for row in rows if row.get("chat_id")}
    try:
        rows.extend(_chat_replies(user_id, skip))
    except Exception:
        log.debug("运行中: chat replies unavailable", exc_info=True)
    # chats are known by their title (精答 / 讨论 by their question until they have one)
    try:
        titles = _titles({row["id"] for row in rows if row["kind"] in ("chat", "image", "answer", "discuss")
                          and row.get("chat_id") == row["id"]})
    except Exception:
        titles = {}
    for row in rows:
        row["title"] = titles.get(row["id"]) or row.get("title")
    rows.sort(key=lambda row: row.get("started_at") or 0)
    return rows
