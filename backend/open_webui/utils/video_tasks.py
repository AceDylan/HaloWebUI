"""The video studio's tasks: a video is made from the workbench itself.

开始制作 used to hand the brief to the chat page, which opened a new Hermes chat and sent it
there: the workbench was left behind. Now the server writes that chat (the brief as the user's
message, the files with it, an empty reply carrying ``video_task``) and starts the Hermes turn
for it the way a runner's notification starts one (hermes_notify.start_follow_up_turn): the
workbench stays where it is and lists the task, the chat is an ordinary chat that shows the
same task as a card on its reply, and either leads to the other.

A task is its chat (``chat.meta.video_task``): no table of its own. Its state is read from the
chat as it is — the reply's statusHistory while Hermes works (the 提示词增强 that the brief may
still be waiting for, then the tools it runs), the runner it handed the work to and that
runner's progress reports, the report coming back, and the videos the library filed for the
chat (utils/video_library.py). Deleting the chat deletes the task.
"""

import asyncio
import html
import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from open_webui.models.chats import ChatForm, Chats

log = logging.getLogger(__name__)

TASK_META_KEY = "video_task"
BRIEF_MAX_CHARS = 8000  # the workbench's own limit (handoff.ts HANDOFF_TEXT_MAX)
FILES_MAX = 9  # 8 attachments + the background music
LIST_LIMIT = 8
VIDEO_SCAN_LIMIT = 300
TITLE_MAX_CHARS = 40
NOW_MAX_CHARS = 140
# 开始制作 once per click: a phone that loses the response (nginx 499) has the browser send the
# same POST again while the first goes on — both used to become tasks. A click's key (the
# workbench sends one) maps to its chat for this long; the server runs one worker process.
CLIENT_KEY_TTL = 30 * 60
_STARTED: dict[tuple[str, str], tuple[float, "asyncio.Future[Optional[str]]"]] = {}

# what a reply's status says while nothing specific is going on (i18n keys, model requests)
_QUIET_STATUS = {"model_request", "web_search", "hermes_start_retry"}
_TOOL_RE = re.compile(r'<details type="tool_calls" done="(true|false)"[^>]*?\sname="([^"]*)"[^>]*?\sarguments="([^"]*)"')


class VideoTaskError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _title_of(idea: str) -> str:
    text = " ".join(str(idea or "").split()) or "视频任务"
    return text[:TITLE_MAX_CHARS] + ("…" if len(text) > TITLE_MAX_CHARS else "")


def _checked_files(files: list[dict], user) -> list[dict]:
    """The attachments as the chat page sends them: the user's own uploads only."""
    from open_webui.models.files import Files
    from open_webui.utils.chat_image_refs import build_chat_image_content_url

    out, seen = [], set()
    for item in files[:FILES_MAX]:
        file_id = str((item or {}).get("id") or "").strip()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        record = Files.get_file_by_id(file_id)
        if record is None or (record.user_id != user.id and getattr(user, "role", "") != "admin"):
            raise VideoTaskError(404, "附件不存在，重新上传后再试")
        meta = record.meta if isinstance(record.meta, dict) else {}
        name = str(item.get("name") or meta.get("name") or record.filename)[:200]
        if item.get("type") == "image":
            out.append({"type": "image", "id": file_id, "url": build_chat_image_content_url(file_id),
                        "name": name, "status": "uploaded"})
        else:
            out.append({"type": "file", "id": file_id, "url": f"/api/v1/files/{file_id}",
                        "name": name, "status": "uploaded"})
    return out


def _html_mode(user) -> str:
    """The user's 「HTML 卡片」 setting, as the chat page would send it (default: force)."""
    settings = getattr(user, "settings", None)
    ui = settings.get("ui") if isinstance(settings, dict) else getattr(settings, "ui", None)
    value = ui.get("htmlVisualArtifacts") if isinstance(ui, dict) else None
    if value is None or value is True:
        return "force"
    if value is False:
        return "off"
    value = str(value).strip().lower()
    return value if value in ("off", "auto", "force") else "off"


async def start_task(request, user, *, brief: str, idea: str = "", files: Optional[list[dict]] = None,
                     maker: str = "", client_key: str = "") -> dict:
    """A new chat with the brief and its files, its Hermes turn started. Returns the task.

    The same *client_key* again (a resent request) waits for the first and returns its task."""
    if not client_key:
        return await _start_task(request, user, brief=brief, idea=idea, files=files, maker=maker)
    now = time.time()
    for key in [k for k, (at, _) in _STARTED.items() if now - at > CLIENT_KEY_TTL]:
        _STARTED.pop(key, None)
    key = (user.id, client_key)
    held = _STARTED.get(key)
    if held is not None:
        chat_id = await asyncio.shield(held[1])
        chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id) if chat_id else None
        task = task_of(chat, user.id) if chat else None
        if task is not None:
            return task
        # the first did not get as far as its chat: this one is a fresh start
    started: "asyncio.Future[Optional[str]]" = asyncio.get_running_loop().create_future()
    _STARTED[key] = (now, started)
    try:
        return await _start_task(request, user, brief=brief, idea=idea, files=files, maker=maker,
                                 created=lambda chat_id: started.done() or started.set_result(chat_id))
    finally:
        if not started.done():
            started.set_result(None)
            _STARTED.pop(key, None)


async def _start_task(request, user, *, brief: str, idea: str, files: Optional[list[dict]], maker: str,
                      created=None) -> dict:
    from open_webui.main import chat_completion
    from open_webui.utils.hermes_notify import append_follow_up_turn
    from open_webui.utils.hermes_sessions import HermesSessionsError, resolve_hermes_model
    from open_webui.utils.mode_chats import schedule_chat_metadata
    from open_webui.utils.team_chats import _dual_write, _model_info, emit_chat_event
    from open_webui.utils.video_library import CHAT_META_KEY, is_video_brief

    brief = str(brief or "").strip()
    if not brief or not is_video_brief(brief):
        raise VideoTaskError(422, "不是视频工作台的需求")
    if len(brief) > BRIEF_MAX_CHARS:
        raise VideoTaskError(422, "需求较长，请精简后再制作")
    try:
        model = await resolve_hermes_model(request, user)
    except HermesSessionsError as exc:
        raise VideoTaskError(exc.status_code, "没有可用的 Hermes 模型：视频由 Hermes 或 runner 制作")
    info = _model_info(model)
    attached = _checked_files(list(files or []), user)

    chat_dict: dict[str, Any] = {"history": {"messages": {}, "currentId": None}}
    user_id, reply_id = append_follow_up_turn(chat_dict, brief, info)
    messages = chat_dict["history"]["messages"]
    messages[user_id].update({"files": attached, "models": [info["model"]]})
    messages[reply_id]["video_task"] = True
    started = int(time.time())
    title = _title_of(idea)
    payload = {
        "id": "",
        "title": title,
        "models": [info["model"]],
        "params": {},
        "files": [],
        "history": chat_dict["history"],
        "messages": [messages[user_id], messages[reply_id]],
        "tags": [],
        "timestamp": started * 1000,
    }
    task_meta = {"messageId": reply_id, "startedAt": started, "maker": str(maker or "")[:32]}
    chat = Chats.insert_new_chat(
        user.id,
        ChatForm(chat=payload, title_auto_generated=True),
        meta={TASK_META_KEY: task_meta, CHAT_META_KEY: True},
    )
    if chat is None:
        raise VideoTaskError(500, "对话没能建立，请稍后再试")
    _dual_write(chat.id, user.id, [messages[user_id], messages[reply_id]])
    if created is not None:
        created(chat.id)  # a resent request returns this chat from now on

    images = [f for f in attached if f["type"] == "image"]
    content: Any = brief
    if images:
        content = [{"type": "text", "text": brief},
                   *({"type": "image_url", "image_url": {"url": f["url"]}} for f in images)]
    form_data = {
        "stream": True,
        "model": info["model"],
        "messages": [{"role": "user", "content": content}],
        "params": {},
        "files": attached,
        "features": {"html_visual_artifacts": _html_mode(user), "html_visual_surface": "halowebui-web"},
        "chat_id": chat.id,
        "id": reply_id,
        # the Hermes path needs a session id; its events go to every tab of the user anyway
        "session_id": f"video-studio:{uuid.uuid4()}",
        "background_tasks": {"title_generation": False, "tags_generation": False,
                             "follow_up_generation": False},
    }
    try:
        await chat_completion(request, form_data, user)
    except Exception as exc:  # noqa: BLE001 — the chat stays, with what went wrong on its reply
        detail = getattr(exc, "detail", None) or "Hermes 没能开始，请稍后再试"
        log.warning("video studio: the Hermes turn of chat %s did not start: %s", chat.id, exc)
        Chats.upsert_message_to_chat_by_id_and_message_id(
            chat.id, reply_id, {"done": True, "completedAt": int(time.time()), "error": {"content": str(detail)}},
            set_current=False,
        )
    await emit_chat_event(user.id, chat.id, "chat:title", title)
    schedule_chat_metadata(request, user, chat.id, model_id=info["model"],
                           messages=[{"role": "user", "content": idea or title}], message_id=reply_id)
    return task_of(Chats.get_chat_by_id_and_user_id(chat.id, user.id) or chat, user.id)


# ---- reading a task -----------------------------------------------------------------------------


def _videos_by_chat(user_id: str) -> dict[str, list[dict]]:
    from open_webui.models.image_studio import ImageStudioItems
    from open_webui.utils.video_library import VIDEO_KIND

    found: dict[str, list[dict]] = {}
    for row in ImageStudioItems.get_items_by_user_id(user_id, kind=VIDEO_KIND, limit=VIDEO_SCAN_LIMIT):
        data = row.data or {}
        chat_id = data.get("chatId")
        if chat_id:
            video = {key: data[key] for key in ("fileId", "url", "name", "title", "size", "contentType",
                                                "createdAt", "runner") if data.get(key) is not None}
            found.setdefault(chat_id, []).append({**video, "id": row.id})
    for videos in found.values():
        videos.sort(key=lambda v: v.get("createdAt") or 0)
    return found


def _clip(text: str, limit: int = NOW_MAX_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _last_tool(content: str) -> tuple[int, Optional[dict]]:
    """(how many tool calls the reply made, the newest one: name, its input, still running)."""
    calls = _TOOL_RE.findall(str(content or ""))
    if not calls:
        return 0, None
    done, name, arguments = calls[-1]
    try:
        preview = json.loads(html.unescape(arguments)).get("input") or ""
    except (ValueError, AttributeError):
        preview = ""
    return len(calls), {"name": html.unescape(name), "input": _clip(preview, 100), "running": done == "false"}


def _status_line(reply: dict) -> tuple[str, Optional[str]]:
    """(the newest status worth showing, the 提示词增强's state: running / done / None)."""
    history = [s for s in (reply.get("statusHistory") or []) if isinstance(s, dict)]
    prep = [s for s in history if s.get("action") == "studio_prep"]
    prep_state = None
    if prep:
        prep_state = "done" if any(s.get("done") for s in prep) else "running"
    for item in reversed(history):
        text = str(item.get("description") or "")
        if text and "{{" not in text and item.get("action") not in _QUIET_STATUS:
            return _clip(text), prep_state
    return "", prep_state


def _report_after(messages: dict, reply: dict, run_id: str) -> Optional[dict]:
    """The runner's report that came back into the chat after the reply that launched it."""
    since = int(reply.get("timestamp") or 0)
    for message in messages.values():
        notice = message.get("hermes_notice") if isinstance(message, dict) else None
        if not isinstance(notice, dict) or message.get("role") != "user":
            continue
        if run_id and notice.get("run_id") != run_id:
            continue
        if int(message.get("timestamp") or 0) < since:
            continue
        child = next((messages.get(c) for c in message.get("childrenIds") or [] if messages.get(c)), None)
        return {"messageId": (child or message).get("id"), "at": int(message.get("timestamp") or 0),
                "content": str((child or {}).get("content") or "")}
    return None


def task_of(chat, user_id: str, videos: Optional[dict[str, list[dict]]] = None) -> Optional[dict]:
    """The task a chat stands for, as the workbench and the chat's card show it; None when the
    chat is not one."""
    from open_webui.tasks import list_task_ids_by_chat_id
    from open_webui.utils.hermes_runner_progress import get_runner_progress
    from open_webui.utils.studio_prep import prep_job_in

    meta = (chat.meta or {}).get(TASK_META_KEY) if chat is not None else None
    if not isinstance(meta, dict):
        return None
    history = (chat.chat or {}).get("history") or {}
    messages = history.get("messages") if isinstance(history.get("messages"), dict) else {}
    reply = messages.get(meta.get("messageId")) or {}
    asked = messages.get(reply.get("parentId") or "") or {}
    run = reply.get("hermes_run") if isinstance(reply.get("hermes_run"), dict) else {}
    runner = str(run.get("dispatch") or meta.get("maker") or "").strip()
    runner_run_id = str(run.get("runner_run_id") or "").strip()
    if videos is None:
        videos = _videos_by_chat(user_id)
    made = videos.get(chat.id, [])
    working = bool(list_task_ids_by_chat_id(chat.id, blocks_completion_only=True))
    replied = reply.get("done") is True
    now_line, prep = _status_line(reply)
    steps, last_tool = _last_tool(reply.get("content"))
    launched = replied and bool(runner_run_id or run.get("fast_dispatch")
                                or (runner and runner != "hermes" and not made))
    report = _report_after(messages, reply, runner_run_id) if launched else None
    progress = get_runner_progress(runner_run_id) if launched and not report else None
    error = reply.get("error")
    error = str(error.get("content") or "") if isinstance(error, dict) else ("出错了" if error else "")

    task: dict[str, Any] = {
        "id": chat.id,
        "chatId": chat.id,
        "messageId": reply.get("id") or meta.get("messageId"),
        "title": chat.title or "视频任务",
        "maker": runner if runner and runner != "hermes" else "Hermes",
        "startedAt": int(meta.get("startedAt") or chat.created_at or 0),
        "endedAt": None,
        # before the turn's first status the brief still carries the enhancement's number
        "prep": prep or ("running" if not replied and prep_job_in(asked.get("content")) else None),
        "steps": steps,
        "videos": made,
        "runner": None,
        "now": "",
        "error": "",
        # where a stopped or failed task ended: prep (增强需求), make (Hermes' turn), runner
        "endedIn": None,
    }
    where = "prep" if task["prep"] == "running" else "make"
    if not replied and (working or run.get("active")):
        task["state"] = "running"
        if task["prep"] == "running":
            task["now"] = now_line or "正在增强需求"
        elif last_tool and last_tool["running"]:
            task["now"] = _clip(f"在执行 {last_tool['name']}：{last_tool['input']}" if last_tool["input"]
                                else f"在执行 {last_tool['name']}")
        else:
            task["now"] = now_line or "Hermes 在制作"
        return task
    if meta.get("stoppedAt") and not made and not report:
        task.update(state="stopped", now="已停止", endedAt=int(meta["stoppedAt"]),
                    endedIn="runner" if launched else where)
        return task
    if error:
        task.update(state="failed", now=_clip(error), error=_clip(error, 400),
                    endedAt=int(reply.get("completedAt") or 0) or None, endedIn=where)
        return task
    if not replied:
        task.update(state="failed", now="制作中断了，打开对话看看停在哪里", error="制作中断了", endedIn=where)
        return task
    if launched and not report:
        task["state"] = "background"
        if progress:
            task["runner"] = {"runId": runner_run_id, "agent": progress.get("agent") or runner,
                              "step": progress.get("step"), "startedAt": progress.get("started_at"),
                              "activity": _clip(progress.get("last_activity") or "")}
            task["now"] = task["runner"]["activity"] or f"{task['maker']} 在后台制作"
        else:
            task["runner"] = {"runId": runner_run_id, "agent": runner}
            task["now"] = f"{task['maker']} 在后台制作，做好后报告会发回对话"
        return task
    task["endedAt"] = (report or {}).get("at") or int(reply.get("completedAt") or 0) or None
    if made:
        task.update(state="done", now=f"成片 {len(made)} 个，已进视频库")
    else:
        task.update(state="replied", now="已回复，但还没有成片：打开对话看看（可能在等你确认）")
    return task


def get_task(user_id: str, chat_id: str) -> Optional[dict]:
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    return task_of(chat, user_id) if chat is not None else None


def list_tasks(user_id: str, limit: int = LIST_LIMIT, since: Optional[int] = None) -> list[dict]:
    """The user's newest tasks (started at or after ``since``), newest first."""
    from sqlalchemy import String, cast

    from open_webui.internal.db import get_db
    from open_webui.models.chats import Chat, ChatModel

    with get_db() as db:
        query = db.query(Chat).filter(Chat.user_id == user_id,
                                      cast(Chat.meta, String).like(f'%"{TASK_META_KEY}"%'))
        if since is not None:
            query = query.filter(Chat.created_at >= since)
        rows = query.order_by(Chat.created_at.desc()).limit(max(1, min(int(limit), 30))).all()
        chats = [ChatModel.model_validate(row) for row in rows]
    if not chats:
        return []
    videos = _videos_by_chat(user_id)
    return [task for task in (task_of(chat, user_id, videos) for chat in chats) if task]


async def stop(request, user, chat_id: str) -> dict:
    """Stops the task: the Hermes turn still working, or the runner it handed the work to."""
    from open_webui.tasks import list_task_ids_by_chat_id, stop_task
    from open_webui.utils.hermes_sessions import HermesSessionsError, stop_background_runner

    task = get_task(user.id, chat_id)
    if task is None:
        raise VideoTaskError(404, "这个视频任务不存在")
    if task["state"] == "running":
        for task_id in list_task_ids_by_chat_id(chat_id, blocks_completion_only=True):
            try:
                await stop_task(task_id)
            except ValueError:
                pass
        await asyncio.sleep(0)  # the stopped turn's cleanup (tasks.cleanup_task) runs first
    elif task["state"] == "background" and (task.get("runner") or {}).get("runId"):
        try:
            await stop_background_runner(request, user, task["runner"]["runId"])
        except HermesSessionsError as exc:
            raise VideoTaskError(exc.status_code, exc.detail)
    else:
        return task
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    meta = dict(((chat.meta or {}) if chat else {}).get(TASK_META_KEY) or {})
    if meta:
        Chats.set_chat_meta_value_by_id(chat_id, TASK_META_KEY, {**meta, "stoppedAt": int(time.time())})
    return get_task(user.id, chat_id) or task
