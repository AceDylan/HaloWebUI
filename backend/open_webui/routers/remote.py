"""精答, 讨论台 and 自动分流 from Telegram / QQ: Hermes asks on the user's behalf.

The halowebui-teams Hermes plugin (its ``remote.py``) turns ``/answer``, ``/discuss`` and ``/auto``
in a linked Telegram or QQ chat into a run here, then reads it back until it is finished and sends
the result to that chat. A run started this way is an ordinary 精答 / discussion / 分流 of the user
(listed on its page, named and filed like one started in the browser); only the start and the
read-back live here. It authenticates as the 协作台's Hermes routes do (``X-Hermes-Key`` = the key of
the user's Hermes connection, ``X-Halo-Owner`` = the user).
"""

import asyncio
import hashlib
import logging
import re
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from open_webui.models.chats import Chats
from open_webui.routers.teams import _authenticated_hermes_caller

router = APIRouter()
log = logging.getLogger(__name__)

Kind = Literal["answer", "discuss", "auto"]
PAGES = {"answer": "/answer/", "discuss": "/discuss/"}
# what the chat messages carry of the result (all of it, short of a very long one)
TEXT_MAX_CHARS = 30000
# 「done」 a moment after the text: the run takes its picture's slot right after it ends
SETTLE_SECONDS = 10
# a resent command (same key) within this window is the run it already started
KEY_WINDOW = 30 * 60
_keys: dict[tuple[str, str], tuple[float, dict]] = {}
_key_lock = asyncio.Lock()
_FILE_URL_RE = re.compile(r"^/api/v1/files/([A-Za-z0-9-]{8,64})/content$")


class StartForm(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    # one per chat message (platform:chat:message), so a redelivered command starts nothing new;
    # QQ's openids and message ids alone come to ~120 characters
    key: str = Field(min_length=1, max_length=512)


def _auto_key(key: str) -> str:
    """The 分流's client_key (≤128): the message key itself, or its digest when that is too long."""
    out = f"remote:{key}"
    return out if len(out) <= 128 else "remote:sha256:" + hashlib.sha256(key.encode()).hexdigest()


def _remember(user_id: str, key: str, value: dict) -> None:
    now = time.time()
    for stale in [k for k, (at, _v) in _keys.items() if now - at > KEY_WINDOW]:
        _keys.pop(stale, None)
    _keys[(user_id, key)] = (now, value)


@router.post("/{kind}")
async def start(request: Request, kind: Kind, form: StartForm, caller=Depends(_authenticated_hermes_caller)):
    user, _target = caller
    question = form.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="先写下问题")
    async with _key_lock:
        known = _keys.get((user.id, form.key))
        if known and time.time() - known[0] <= KEY_WINDOW:
            return {**known[1], "deduplicated": True}
        if kind == "answer":
            from open_webui.routers import answers

            run_id = await answers.open_for_chat(request, user, question=question, context=None, origin=None)
        elif kind == "discuss":
            from open_webui.routers import discussions

            run_id = await discussions.open_for_chat(request, user, question=question, context=None, origin=None)
        else:
            from open_webui.routers import auto

            row = await auto.start(request, user, auto.CreateForm(question=question, client_key=_auto_key(form.key)))
            run_id = row["id"]
        out = {"kind": kind, "id": run_id}
        _remember(user.id, form.key, out)
    return out


def _chat_run(kind: str, chat_id: str, user) -> tuple[Optional[object], Optional[dict]]:
    """(chat, its latest run) of a 精答 / discussion of this user."""
    if kind == "answer":
        from open_webui.routers import answers

        chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
        if chat is None or not isinstance((chat.chat or {}).get(answers.CHAT_KEY), dict):
            return None, None
        return chat, answers._run_of(chat)
    from open_webui.routers import discussions

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None or not isinstance((chat.chat or {}).get(discussions.CHAT_KEY), dict):
        return None, None
    asks = discussions._asks_of(chat)
    return chat, (asks[-1] if asks else None)


def _live(kind: str) -> dict:
    if kind == "answer":
        from open_webui.routers.answers import LIVE
    else:
        from open_webui.routers.discussions import LIVE
    return LIVE


def chat_state(kind: str, chat_id: str, user) -> dict:
    """Where a 精答 / discussion stands, as Telegram / QQ is told it."""
    from open_webui.utils import mode_dispatch
    from open_webui.utils.mode_illustrate import DRAWING

    chat, run = _chat_run(kind, chat_id, user)
    out: dict = {"kind": kind, "id": chat_id, "url": PAGES[kind] + chat_id}
    if chat is None:
        return {**out, "status": "gone"}
    question = str((run or {}).get("question") or "")
    title = chat.title if chat.title and chat.title not in mode_dispatch.DEFAULT_TITLES else question[:60]
    out["title"] = title
    status = str((run or {}).get("status") or "")
    ended = ((run or {}).get("endedAt") or 0) / 1000
    if (not run or chat_id in _live(kind) or chat_id in DRAWING
            or status not in ("done", "stopped", "error", "interrupted")
            or (status == "done" and time.time() - ended < SETTLE_SECONDS)):
        return {**out, "status": "running", "stage": status}
    if status != "done":
        return {**out, "status": "failed" if status in ("error", "interrupted") else "stopped",
                "error": str(run.get("error") or "")[:300]}
    text = mode_dispatch.result_content(kind, run, picture=False)
    if len(text) > TEXT_MAX_CHARS:
        text = text[:TEXT_MAX_CHARS].rstrip() + "\n\n…（太长了，完整内容在网页）"
    if kind == "answer":
        assistant = run.get("assistant") or {}
        by = f"{assistant.get('emoji') or ''}{assistant.get('name') or ''}".strip()
    else:
        seats = [s.get("label") or s.get("name") or "" for s in run.get("seats") or []]
        by = "、".join(s for s in seats if s)
    picture = run.get("illustration") or {}
    return {**out, "status": "done", "text": text, "by": by,
            "picture": picture.get("status") == "ready" and bool(_FILE_URL_RE.match(str(picture.get("url") or "")))}


def auto_state(route_id: str, user) -> dict:
    from open_webui.routers import auto

    try:
        row = auto.public(auto._own(route_id, user), user)
    except HTTPException:
        return {"kind": "auto", "id": route_id, "status": "gone"}
    out = {"kind": "auto", "id": route_id, "title": row.get("title"), "reason": row.get("reason") or "",
           "mode": row.get("mode"), "target_id": row.get("target_id"), "read_only": row.get("read_only"),
           "degraded": row.get("degraded")}
    if row["status"] == "dispatched" and row.get("target_id"):
        return {**out, "status": "dispatched", "url": row.get("href")}
    if row["status"] in ("error", "interrupted", "cancelled"):
        return {**out, "status": "failed", "error": row.get("error") or ""}
    return {**out, "status": "running"}


@router.get("/{kind}/{run_id}")
async def state(kind: Kind, run_id: str, caller=Depends(_authenticated_hermes_caller)):
    user, _target = caller
    if kind == "auto":
        return await asyncio.to_thread(auto_state, run_id, user)
    return await asyncio.to_thread(chat_state, kind, run_id, user)


@router.get("/{kind}/{run_id}/picture")
def picture(kind: Literal["answer", "discuss"], run_id: str, caller=Depends(_authenticated_hermes_caller)):
    """The result's picture (结论配图), for the chat message that brings the result."""
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage

    user, _target = caller
    _chat, run = _chat_run(kind, run_id, user)
    entry = (run or {}).get("illustration") or {}
    match = _FILE_URL_RE.match(str(entry.get("url") or "")) if entry.get("status") == "ready" else None
    file = Files.get_file_by_id(match.group(1)) if match else None
    if file is None or file.user_id != user.id or not file.path:
        raise HTTPException(status_code=404, detail="没有配图")
    meta = file.meta or {}
    return FileResponse(Storage.get_file(file.path), media_type=meta.get("content_type") or "image/png")
