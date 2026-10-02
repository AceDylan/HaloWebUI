"""The 协作台 in Telegram: ``/team``, buttons, and replies to team notices — no model turn.
(Named ``tg``, not ``telegram``: it must never shadow python-telegram-bot.)

* ``/team <目标>`` starts a team (HaloWebUI plans it; the plan card comes back here, see
  ``notify.plan_notice``); ``/team`` alone lists your recent teams.
* Buttons on our messages (callback data ``ht:<action>:<team>[:<task>]``): approve / cancel /
  re-plan a plan, retry a failed task.
* A reply to one of our notices: to a plan → re-plan with it as feedback; to a question → the
  answer, delivered to the member; to a failure → a note for the member, then a retry. Plain
  「批准」 right after a plan card approves it.

Only Telegram users listed in ``halo-teams.json`` → ``telegram.owners`` are handled here (the
hook runs before the gateway's own auth); every other message goes on to Hermes untouched.

Sending uses the gateway's own python-telegram-bot ``Application`` (captured when the adapter
connects, same proxy and settings), scheduled on the gateway loop.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import link
from .common import logger
from .notify import clip, esc

_state: dict = {"app": None, "loop": None}
_tasks: set = set()
_store_lock = threading.Lock()
STORE_KEEP = 400
STORE_DAYS = 14
APPROVE_WINDOW = 30 * 60
APPROVE_WORDS = {"批准", "批准并开始", "开始吧", "批准开始", "同意", "approve"}
SEND_TIMEOUT = 30


# --- transport -----------------------------------------------------------------------------------

def install(native: Any, adapter: Any) -> None:
    """Telegram platform handler factory (called in the adapter's ``connect()``)."""
    if native is None:
        return
    from telegram.ext import CallbackQueryHandler

    _state["app"] = native
    try:
        _state["loop"] = asyncio.get_running_loop()
    except RuntimeError:
        _state["loop"] = None
    # Group -1 runs before the core's catch-all callback handler (group 0); ours stops the update.
    native.add_handler(CallbackQueryHandler(_on_callback, pattern=r"^ht:"), group=-1)


def ready() -> bool:
    loop = _state.get("loop")
    return _state.get("app") is not None and loop is not None and loop.is_running()


def _chat(chat_id: Any) -> Any:
    text = str(chat_id)
    return int(text) if text.lstrip("-").isdigit() else text


def markup(buttons: Optional[list]):
    """Rows of (label, "cb:<data>" | "url:<url>") → InlineKeyboardMarkup (None when empty)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for row in buttons or []:
        out = []
        for label, spec in row:
            if spec.startswith("cb:"):
                out.append(InlineKeyboardButton(label, callback_data="ht:" + spec[3:]))
            elif spec.startswith("url:") and spec[4:].startswith(("https://", "http://")):
                out.append(InlineKeyboardButton(label, url=spec[4:]))
        if out:
            rows.append(out)
    return InlineKeyboardMarkup(rows) if rows else None


async def asend(chat_id: Any, text: str, buttons: Optional[list] = None, *, thread_id: Any = None,
                reply_to: Any = None) -> Optional[int]:
    """Send on the gateway loop; the message id, or None when it failed."""
    app = _state.get("app")
    if app is None:
        return None
    kwargs: dict = {"chat_id": _chat(chat_id), "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": True, "reply_markup": markup(buttons)}
    if thread_id:
        kwargs["message_thread_id"] = int(thread_id)
    if reply_to:
        from telegram import ReplyParameters

        kwargs["reply_parameters"] = ReplyParameters(message_id=int(reply_to), allow_sending_without_reply=True)
    try:
        message = await app.bot.send_message(**kwargs)
    except Exception as exc:  # noqa: BLE001 — a notice must never break the caller
        logger.warning("halowebui-teams: Telegram send failed: %s", type(exc).__name__)
        return None
    return int(message.message_id)


def send(chat_id: Any, text: str, buttons: Optional[list] = None, *, thread_id: Any = None) -> Optional[int]:
    """``asend`` from a worker thread (bridge loop, API handlers run in threads)."""
    loop = _state.get("loop")
    if not ready():
        return None
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:  # pragma: no cover — misuse: waiting here would deadlock the loop
        raise RuntimeError("telegram.send called on the gateway loop; use asend")
    future = asyncio.run_coroutine_threadsafe(asend(chat_id, text, buttons, thread_id=thread_id), loop)
    try:
        return future.result(timeout=SEND_TIMEOUT)
    except Exception:  # noqa: BLE001
        future.cancel()
        return None


# --- which message is which ----------------------------------------------------------------------

def _store_path() -> Path:
    override = os.environ.get("HALO_TEAMS_TG_STORE")
    if override:
        return Path(override)
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "halo-teams" / "telegram-messages.json"


def _load() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STORE_DAYS * 86400
    items = sorted(((k, v) for k, v in data.items() if (v.get("at") or 0) >= cutoff), key=lambda kv: kv[1].get("at") or 0)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(items[-STORE_KEEP:]), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def remember_message(chat_id: Any, message_id: Any, entry: dict) -> None:
    with _store_lock:
        data = _load()
        data[f"{chat_id}:{message_id}"] = {**entry, "at": time.time()}
        _save(data)


def lookup(chat_id: Any, message_id: Any) -> Optional[dict]:
    with _store_lock:
        return _load().get(f"{chat_id}:{message_id}")


def mark_acted(chat_id: Any, message_id: Any, how: str) -> None:
    with _store_lock:
        data = _load()
        entry = data.get(f"{chat_id}:{message_id}")
        if entry is not None:
            entry["acted"] = how
            _save(data)


def close_plan_cards(team_id: str, how: str) -> None:
    """The team's plan was approved somewhere (button, text, browser): its cards are answered."""
    with _store_lock:
        data = _load()
        changed = False
        for entry in data.values():
            if entry.get("team") == team_id and entry.get("kind") in ("plan", "plan_failed") and not entry.get("acted"):
                entry["acted"] = how
                changed = True
        if changed:
            _save(data)


def latest_open_plan(chat_id: Any) -> Optional[tuple[str, dict]]:
    """The newest plan card in this chat nobody acted on yet, if it is recent."""
    prefix = f"{chat_id}:"
    with _store_lock:
        rows = [(k, v) for k, v in _load().items() if k.startswith(prefix) and v.get("kind") == "plan"]
    if not rows:
        return None
    key, entry = max(rows, key=lambda kv: kv[1].get("at") or 0)
    if entry.get("acted") or time.time() - (entry.get("at") or 0) > APPROVE_WINDOW:
        return None
    return key.split(":", 1)[1], entry


# --- incoming ------------------------------------------------------------------------------------

def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def on_pre_gateway_dispatch(event: Any = None, gateway: Any = None, session_store: Any = None, **_: Any):
    """``pre_gateway_dispatch`` hook: take what is ours, leave the rest to Hermes."""
    try:
        return _dispatch(event)
    except Exception:  # noqa: BLE001 — never break the gateway's own handling
        logger.warning("halowebui-teams: Telegram dispatch failed", exc_info=True)
        return None


def _platform(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "")


def _dispatch(event: Any) -> Optional[dict]:
    source = getattr(event, "source", None)
    if event is None or source is None or getattr(event, "internal", False) or _platform(source) != "telegram":
        return None
    owner = link.owner_for_telegram(getattr(source, "user_id", None) or getattr(event, "user_id", None))
    if not owner or not ready():
        return None
    text = (getattr(event, "text", "") or "").strip()
    command = event.get_command() if hasattr(event, "is_command") and event.is_command() else None
    if command in ("team", "teams"):
        _spawn(_team_command(source, owner, event.get_command_args().strip(), event))
        return {"action": "skip", "reason": "halo team command"}
    if not text or command:
        return None
    reply_to = getattr(event, "reply_to_message_id", None)
    if reply_to:
        entry = lookup(source.chat_id, reply_to)
        if entry and entry.get("kind") in ("plan", "plan_failed", "ask", "fail"):
            _spawn(_reply(source, owner, entry, str(reply_to), text, event))
            return {"action": "skip", "reason": "reply to a team notice"}
    if text.rstrip("。.!！ ").lower() in APPROVE_WORDS:
        found = latest_open_plan(source.chat_id)
        if found:
            message_id, entry = found
            _spawn(_approve_by_text(source, owner, message_id, entry, event))
            return {"action": "skip", "reason": "approve the plan card"}
    return None


def command_fallback(raw_args: str = "") -> str:
    """``/team`` when the hook did not take it: not a linked Telegram user (or not Telegram)."""
    if not link.config():
        return "协作台还没有和 Telegram 接通（缺 ~/.hermes/halo-teams.json）。"
    return "这个账号没有绑定协作台用户（~/.hermes/halo-teams.json → telegram.owners），请在网页的协作台发起。"


def _origin(source: Any) -> dict:
    origin = {"platform": "telegram", "chat_id": str(source.chat_id), "user_id": str(source.user_id or "")}
    if getattr(source, "thread_id", None):
        origin["thread_id"] = str(source.thread_id)
    return origin


async def _say(source: Any, text: str, buttons: Optional[list] = None, event: Any = None) -> Optional[int]:
    return await asend(source.chat_id, text, buttons, thread_id=getattr(source, "thread_id", None),
                       reply_to=getattr(event, "message_id", None))


USAGE = ("<b>协作台</b>\n"
         "/team 目标 —— 交给一个团队：负责人先做计划发给你，批准后成员分工执行，完成后把结论发回来。\n"
         "/team —— 最近的协作任务。")


async def _team_command(source: Any, owner: str, args: str, event: Any) -> None:
    if args in ("", "列表", "list", "ls", "状态"):
        await _list(source, owner, event)
        return
    if args in ("help", "帮助", "?", "？"):
        await _say(source, USAGE, None, event)
        return
    try:
        team = await asyncio.to_thread(link.create, owner, args, _origin(source))
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能发起协作：{esc(exc.message)}", None, event)
        return
    url = link.team_url(team["id"])
    await _say(source, (f"🧭 已交给负责人做计划：<b>{esc(clip(team.get('title'), 60))}</b>\n"
                        "计划好了发到这里（一般 1 分钟内），你批准后才会开始。"),
               [[("🌐 在网页看", "url:" + url)]] if url else None, event)


STATUS_LINE = {
    "planning": ("🧭", "负责人在做计划"), "plan_ready": ("🟣", "等你批准"), "plan_failed": ("⚠️", "计划没做出来"),
    "starting": ("🔵", "正在启动"), "start_failed": ("⚠️", "启动失败"), "cancelled": ("⚪", "已取消"),
}
PHASE_LINE = {"running": ("🔵", "执行中"), "attention": ("🟣", "需要你处理"), "paused": ("⏸", "已暂停派发"),
              "completed": ("✅", "完成"), "stopped": ("⏹", "已停止")}


def list_message(teams: list) -> tuple[str, list]:
    if not teams:
        return "还没有协作任务。发 <code>/team 目标</code> 开一个。", []
    lines = ["<b>协作任务</b>（最近的）"]
    buttons = []
    for team in teams[:8]:
        if team.get("status") == "running":
            icon, word = PHASE_LINE.get(team.get("phase") or "running", PHASE_LINE["running"])
            progress = team.get("progress") or {}
            if progress.get("total") and team.get("phase") not in ("completed",):
                word += f" {progress.get('done', 0)}/{progress['total']}"
        else:
            icon, word = STATUS_LINE.get(team.get("status"), ("•", team.get("status") or ""))
        url = link.team_url(team["id"])
        title = esc(clip(team.get("title"), 40))
        if url:
            title = f'<a href="{html.escape(url)}">{title}</a>'
        lines.append(f"{icon} {title} · {word}")
        if team.get("status") == "plan_ready" and len(buttons) < 3:
            buttons.append([(f"✅ 批准「{clip(team.get('title'), 16)}」", f"cb:ap:{team['id']}")])
    home = link.public_url("/teams")
    if home:
        buttons.append([("🌐 打开协作台", "url:" + home)])
    return "\n".join(lines), buttons


async def _list(source: Any, owner: str, event: Any) -> None:
    try:
        teams = await asyncio.to_thread(link.recent, owner)
    except link.HaloError as exc:
        await _say(source, f"⚠️ 读不到协作任务：{esc(exc.message)}", None, event)
        return
    text, buttons = list_message(teams)
    await _say(source, text, buttons, event)


def _author(event: Any, source: Any) -> str:
    return str(getattr(source, "user_name", None) or getattr(event, "user_name", None) or "你")[:40]


async def _reply(source: Any, owner: str, entry: dict, message_id: str, text: str, event: Any) -> None:
    from .teams import TeamError, post_message, retry

    kind = entry.get("kind")
    team_id = entry.get("team")
    try:
        if kind in ("plan", "plan_failed"):
            await asyncio.to_thread(link.replan, owner, team_id, text)
            mark_acted(source.chat_id, message_id, "replan")
            await _say(source, "🔄 已把你的意见交给负责人，新计划好了发到这里。", None, event)
        elif kind == "ask":
            await asyncio.to_thread(post_message, team_id, entry["task"], text, author_name=_author(event, source),
                                    owner=owner)
            await _say(source, f"✅ 已转给 {esc(entry.get('member') or '成员')}，它会接着做。", None, event)
        elif kind == "fail":
            await asyncio.to_thread(post_message, team_id, entry["task"], text, author_name=_author(event, source),
                                    owner=owner)
            await asyncio.to_thread(retry, team_id, entry["task"], owner=owner, actor=_author(event, source))
            mark_acted(source.chat_id, message_id, "retry")
            await _say(source, "🔁 已带着你的说明重试。", None, event)
    except link.HaloError as exc:
        await _say(source, f"⚠️ {esc(exc.message)}", None, event)
    except TeamError as exc:
        await _say(source, f"⚠️ {esc(exc.message)}", None, event)


async def _approve_by_text(source: Any, owner: str, message_id: str, entry: dict, event: Any) -> None:
    try:
        team = await asyncio.to_thread(link.approve, owner, entry["team"])
    except link.HaloError as exc:
        mark_acted(source.chat_id, message_id, "approve-failed")
        await _say(source, f"⚠️ 没能批准：{esc(exc.message)}", None, event)
        return
    mark_acted(source.chat_id, message_id, "approve")
    url = link.team_url(team["id"])
    await _say(source, f"✅ 已批准「{esc(clip(team.get('title'), 40))}」，成员开始干活了。完成或需要你时我会告诉你。",
               [[("🌐 看工作台", "url:" + url)]] if url else None, event)


async def _on_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    try:
        await _handle_callback(update.callback_query)
    except Exception:  # noqa: BLE001
        logger.warning("halowebui-teams: Telegram button failed", exc_info=True)
    raise ApplicationHandlerStop


CALLBACK_DONE = {"ap": "✅ 已批准，成员开始干活了", "cx": "✖ 已取消", "rp": "🔄 负责人在重新规划", "rt": "🔁 已重试"}


async def _handle_callback(query: Any) -> None:
    from .teams import TeamError, retry

    owner = link.owner_for_telegram(getattr(query.from_user, "id", None))
    if not owner:
        await query.answer("只有协作任务的主人能用这个按钮")
        return
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        await query.answer("按钮已失效")
        return
    action, team_id = parts[1], parts[2]
    task_id = parts[3] if len(parts) > 3 else ""
    try:
        if action == "ap":
            await asyncio.to_thread(link.approve, owner, team_id)
        elif action == "cx":
            await asyncio.to_thread(link.cancel, owner, team_id)
        elif action == "rp":
            await asyncio.to_thread(link.replan, owner, team_id, "")
        elif action == "rt" and task_id:
            await asyncio.to_thread(retry, team_id, task_id, owner=owner, actor=str(query.from_user.first_name or ""))
        else:
            await query.answer("按钮已失效")
            return
    except (link.HaloError, TeamError) as exc:
        await query.answer(clip(exc.message, 190), show_alert=True)
        return
    note = CALLBACK_DONE[action]
    await query.answer(note)
    message = query.message
    if message is None:
        return
    mark_acted(message.chat_id, message.message_id, action)
    keep = []
    for row in (message.reply_markup.inline_keyboard if message.reply_markup else ()):
        urls = [(b.text, "url:" + b.url) for b in row if getattr(b, "url", None)]
        if urls:
            keep.append(urls)
    try:
        await query.edit_message_text(text=(message.text_html or "") + f"\n\n<b>{esc(note)}</b>", parse_mode="HTML",
                                      reply_markup=markup(keep), disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001 — an old or unchanged message: the answer above is enough
        logger.debug("halowebui-teams: could not edit the Telegram message: %s", exc)
