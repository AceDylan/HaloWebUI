"""The 协作台 in Telegram: ``/team``, buttons, and replies to team notices — no model turn.
(Named ``tg``, not ``telegram``: it must never shadow python-telegram-bot.)

* ``/team <目标>`` starts a team (HaloWebUI plans it; the plan card comes back here, see
  ``notify.plan_notice``); ``/team`` alone lists your recent teams.
* ``/work [runner …] <需求>`` starts the ``work`` workflow (AGY plans → Codex builds → Claude
  reviews and fixes → release), started at once; a runner named first is used for its family.
* Buttons on our messages (callback data ``ht:<action>:<team>[:<task>]``): approve / cancel /
  re-plan a plan, retry a failed task.
* A reply to one of our notices: to a plan → re-plan with it as feedback; to a question → the
  answer, delivered to the member; to a failure → a note for the member, then a retry; to the
  done notice or a change card → said to the lead (``lead.request_change``; its reply and plan
  change come back here). Plain 「批准」 right after a plan card approves it.
* Buttons also apply the lead's suggestion for a failed task (``dx``), turn the acceptance gaps
  into a change request (``fx``), and apply / discard a change proposal (``ca`` / ``cd``).

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
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import chat_progress, link, notify
from .common import logger, read_team
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


CHUNK_CHARS = 3800  # one Telegram message (4096 UTF-16 units) with room to spare
_ENTITY_OR_TAG_RE = re.compile(r"(&[#\w]*|<[^>]*)$")


def split_html(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """A notice too long for one message, in parts at line breaks (our tags never span lines); a
    line longer than a message is cut where no tag or entity is open."""
    parts: list[str] = []
    current = ""
    for line in str(text or "").split("\n"):
        while len(line) > limit:
            cut = limit
            open_ = _ENTITY_OR_TAG_RE.search(line[:cut])
            if open_ and open_.start() > 0:
                cut = open_.start()
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:cut])
            line = line[cut:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current.strip() or not parts:
        parts.append(current)
    return [p for p in parts if p.strip()] or [""]


# (chat, id of a long notice's last part) → the ids of its earlier parts: a reply to any part is a
# reply to the notice (remember_message).
_parts: dict[tuple[str, int], list[int]] = {}


async def asend(chat_id: Any, text: str, buttons: Optional[list] = None, *, thread_id: Any = None,
                reply_to: Any = None, silent: bool = False) -> Optional[int]:
    """Send on the gateway loop, in several messages when it is long (the buttons under the last);
    the last message's id, or None when it failed."""
    app = _state.get("app")
    if app is None:
        return None
    chunks = split_html(text)
    sent: list[int] = []
    for i, chunk in enumerate(chunks):
        last = i == len(chunks) - 1
        kwargs: dict = {"chat_id": _chat(chat_id), "text": chunk, "parse_mode": "HTML",
                        "disable_web_page_preview": True, "reply_markup": markup(buttons) if last else None}
        if silent:
            kwargs["disable_notification"] = True
        if thread_id:
            kwargs["message_thread_id"] = int(thread_id)
        if reply_to and not sent:
            from telegram import ReplyParameters

            kwargs["reply_parameters"] = ReplyParameters(message_id=int(reply_to), allow_sending_without_reply=True)
        try:
            message = await app.bot.send_message(**kwargs)
        except Exception as exc:  # noqa: BLE001 — a notice must never break the caller
            logger.warning("halowebui-teams: Telegram send failed: %s", type(exc).__name__)
            return None
        sent.append(int(message.message_id))
    if len(sent) > 1:
        _parts[(str(chat_id), sent[-1])] = sent[:-1]
        while len(_parts) > STORE_KEEP:
            _parts.pop(next(iter(_parts)))
    return sent[-1]


async def aedit(chat_id: Any, message_id: Any, text: str, buttons: Optional[list] = None) -> str:
    """Edit a progress card, distinguishing a deleted message from a transient failure."""
    app = _state.get("app")
    if app is None:
        return "failed"
    try:
        await app.bot.edit_message_text(chat_id=_chat(chat_id), message_id=int(message_id), text=text,
                                        parse_mode="HTML", disable_web_page_preview=True,
                                        reply_markup=markup(buttons))
    except Exception as exc:  # noqa: BLE001 — a notice must never break the caller
        message = str(exc).lower()
        if "message is not modified" in message:
            return "not_modified"
        if "message to edit not found" in message or "message can't be edited" in message:
            return "gone"
        logger.warning("halowebui-teams: Telegram edit failed: %s", type(exc).__name__)
        return "failed"
    return "ok"


async def asend_photo(chat_id: Any, path: Path, caption: str = "", *, thread_id: Any = None,
                      reply_to: Any = None) -> Optional[int]:
    """A picture (a file on disk) on the gateway loop; the message id, or None when it failed."""
    app = _state.get("app")
    if app is None:
        return None
    kwargs: dict = {"chat_id": _chat(chat_id), "caption": caption or None, "parse_mode": "HTML"}
    if thread_id:
        kwargs["message_thread_id"] = int(thread_id)
    if reply_to:
        from telegram import ReplyParameters

        kwargs["reply_parameters"] = ReplyParameters(message_id=int(reply_to), allow_sending_without_reply=True)
    try:
        with open(path, "rb") as photo:
            message = await app.bot.send_photo(photo=photo, **kwargs)
    except Exception as exc:  # noqa: BLE001 — a notice must never break the caller
        logger.warning("halowebui-teams: Telegram photo failed: %s", type(exc).__name__)
        return None
    return int(message.message_id)


def _from_thread(make):
    """Run the coroutine ``make()`` returns on the gateway loop from a worker thread (bridge
    loop, API handlers run in threads) and wait for its result."""
    loop = _state.get("loop")
    if not ready():
        return None
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:  # pragma: no cover — misuse: waiting here would deadlock the loop
        raise RuntimeError("telegram.send called on the gateway loop; use asend")
    future = asyncio.run_coroutine_threadsafe(make(), loop)
    try:
        return future.result(timeout=SEND_TIMEOUT)
    except Exception:  # noqa: BLE001
        future.cancel()
        return None


def send(chat_id: Any, text: str, buttons: Optional[list] = None, *, thread_id: Any = None,
         silent: bool = False) -> Optional[int]:
    """``asend`` from a worker thread."""
    return _from_thread(lambda: asend(chat_id, text, buttons, thread_id=thread_id, silent=silent))


def edit(chat_id: Any, message_id: Any, text: str, buttons: Optional[list] = None) -> str:
    return _from_thread(lambda: aedit(chat_id, message_id, text, buttons)) or "failed"


def send_photo(chat_id: Any, path: Path, caption: str = "", *, thread_id: Any = None,
               reply_to: Any = None) -> Optional[int]:
    """``asend_photo`` from a worker thread."""
    return _from_thread(lambda: asend_photo(chat_id, path, caption, thread_id=thread_id, reply_to=reply_to))


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
    earlier = _parts.pop((str(chat_id), int(message_id)), []) if str(message_id).isdigit() else []
    with _store_lock:
        data = _load()
        for mid in [*earlier, message_id]:
            data[f"{chat_id}:{mid}"] = {**entry, "at": time.time()}
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


def close_change_cards(team_id: str, change_id: str, how: str) -> None:
    """A change proposal was applied / discarded somewhere: its Telegram card is answered."""
    with _store_lock:
        data = _load()
        changed = False
        for entry in data.values():
            if entry.get("team") == team_id and entry.get("kind") == "change" and entry.get("change") == change_id \
                    and not entry.get("acted"):
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
    if command == "work":
        _spawn(_work_command(source, owner, event.get_command_args().strip(), event))
        return {"action": "skip", "reason": "halo work command"}
    if not text or command:
        return None
    reply_to = getattr(event, "reply_to_message_id", None)
    if reply_to:
        entry = lookup(source.chat_id, reply_to)
        if entry and entry.get("kind") in ("plan", "plan_failed", "ask", "fail", "done", "change"):
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
         "/team 目标 —— 交给一个团队：负责人先做计划发给你，批准后成员分工执行，完成后把结论发回来。"
         "默认自由协作，要改仓库时自动转快速研发。\n"
         "/team 直接 目标 —— 计划好就直接开始，不用批准。\n"
         "/team 多模型 目标 —— 多模型研发：Claude 和 AGY 各出方案，合成后问你拍板（回复那条问题消息），再设计、写后端和前端。\n"
         "/team 快速研发 目标 —— 快速研发：摸底 → Codex 写后端 → Claude 写前端并测试。可以和「直接」叠着写。\n"
         "/team —— 最近的协作任务。\n"
         "/team 进度 [编号或 ID] —— 查看任务、验收与发布进度。\n"
         "/work 需求 —— 工作流：AGY 规划 → Codex 开发 → Claude 审阅修复 → 自动发布（/work help 看详情）。\n"
         "回复完成通知 —— 对负责人说还要补什么、改什么。")


async def _team_command(source: Any, owner: str, args: str, event: Any) -> None:
    if args in ("", "列表", "list", "ls"):
        await _list(source, owner, event)
        return
    selector = chat_progress.parse_progress_query(args)
    if selector is not None:
        await _progress_command(source, owner, selector, event)
        return
    if args in ("help", "帮助", "?", "？"):
        await _say(source, USAGE, None, event)
        return
    goal, auto_start, workflow = split_team_args(args)
    if not goal:
        await _say(source, USAGE, None, event)
        return
    try:
        team = await asyncio.to_thread(link.create, owner, goal, _origin(source), auto_start, workflow)
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能发起协作：{esc(exc.message)}", None, event)
        return
    after = ("计划好就直接开始（不用批准），计划发到这里给你过目。" if auto_start
             else "计划好了发到这里（一般 1 分钟内），你批准后才会开始。")
    await _say(source, f"🧭 已交给负责人做计划{workflow_note(workflow)}：<b>{esc(clip(team.get('title'), 60))}</b>\n{after}",
               _started_buttons(team["id"]), event)


WORK_USAGE = ("<b>工作流 /work</b>\n"
              "/work 需求 —— AGY 出规划 → Codex 开发 → Claude 审阅并修复问题 → 提交、推送、部署、清理，全程自动。"
              "需求里写上项目名或路径（例如「/work HaloWebUI 给设置页加个开关」）。\n"
              "默认 offiagy 规划（不行换 agy），officlaude 审阅（不行依次换 cchclaude、anyclaude、reclaude）。\n"
              "/work cchclaude 需求 —— 指定审阅的 Claude（cchclaude / anyclaude / reclaude / officlaude），"
              "指定了就只用它，不可用时暂停等你换；agy / offiagy 同理指定规划的。\n"
              "/work 进度 —— 查看工作流进度。")
_WORK_RUNNER_RE = re.compile(r"([A-Za-z]+)(?=$|[\s：:，,])")


def split_work_args(args: str) -> tuple[str, dict[str, str]]:
    """``/work [runner …] <需求>`` → (goal, runner_prefs). Runners named first pick their family's
    runner (``{"claude": "cchclaude"}``); one per family, Hermes is not one."""
    from . import runners

    text, prefs = (args or "").strip(), {}
    while True:
        found = _WORK_RUNNER_RE.match(text)
        spec = runners.BY_NAME.get(found.group(1).lower()) if found else None
        if spec is None or spec.native or spec.family in prefs:
            return text, prefs
        prefs[spec.family] = spec.name
        text = text[found.end():].strip(AUTO_START_SEPARATORS)


def work_flow(prefs: Optional[dict] = None) -> str:
    """The /work steps with the runners that will do them."""
    prefs = prefs or {}
    planner = prefs.get("agy") or "offiagy（不行换 agy）"
    developer = prefs.get("codex") or "Codex"
    reviewer = prefs.get("claude") or "officlaude（不行依次换 cchclaude、anyclaude、reclaude）"
    return f"{planner} 出规划 → {developer} 开发 → {reviewer} 审阅修复 → 提交推送部署清理"


def work_started(team: dict, prefs: dict) -> str:
    """The reply to /work (Telegram HTML; QQ strips the tags)."""
    return (f"🛠️ 已交给工作流：<b>{esc(clip(team.get('title'), 60))}</b>\n{esc(work_flow(prefs))}。\n"
            "规划好就直接开始，全程自动；需要你处理或做完发布了会发到这里。")


async def _work_command(source: Any, owner: str, args: str, event: Any) -> None:
    if chat_progress.is_work_progress_query(args):
        selector = chat_progress.parse_progress_query(args)
        if selector is None:
            await _say(source, "发 <code>/work 进度 [编号或 ID]</code> 查看工作流进度。"
                               "要发起新需求，换个说法别用「进度 / 状态 / 详情」开头。", None, event)
        else:
            await _progress_command(source, owner, selector, event, workflow_first="work")
        return
    goal, prefs = split_work_args(args)
    if not goal or goal in ("help", "帮助", "?", "？"):
        await _say(source, WORK_USAGE, None, event)
        return
    try:
        team = await asyncio.to_thread(link.create, owner, goal, _origin(source), True, "work", prefs)
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能发起工作流：{esc(exc.message)}", None, event)
        return
    await _say(source, work_started(team, prefs), _started_buttons(team["id"]), event)


def _started_buttons(team_id: str) -> list:
    url = link.team_url(team_id)
    row = [("📊 看进度", f"cb:pg:{team_id}")]
    if url:
        row.append(("🌐 在网页看", "url:" + url))
    return [row]


AUTO_START_WORDS = ("直接开始", "直接", "自动开始", "自动")
# 「快速」 alone is not one: 「/team 快速 看下日志」 is a goal, not a request for the dev template.
WORKFLOW_WORDS = (("多模型研发", "dev_pipeline"), ("多模型", "dev_pipeline"), ("快速研发", "dev_lite"),
                  ("自由协作", "auto"))
WORKFLOW_LABEL = {"dev_pipeline": "多模型研发", "dev_lite": "快速研发", "work": "工作流"}
AUTO_START_SEPARATORS = " ：:，,\u3000"


def workflow_note(workflow: str) -> str:
    label = WORKFLOW_LABEL.get(workflow)
    return f"（{label}）" if label else ""


def _leading_word(text: str, words) -> Optional[tuple[str, str]]:
    """The word *text* starts with, followed by a separator: (word, rest)."""
    for word in words:
        if text.startswith(word) and text[len(word):len(word) + 1] in tuple(AUTO_START_SEPARATORS):
            return word, text[len(word):].strip(AUTO_START_SEPARATORS)
    return None


def split_team_args(args: str) -> tuple[str, bool, str]:
    """``/team [直接] [多模型|快速研发|自由协作] <目标>`` in either order → (goal, auto_start, workflow).
    「直接」 (also ``自动 …`` or ``! …``): start as soon as the plan is ready. A word counts only with a
    separator after it, so a goal that merely begins with 「直接」 is a goal."""
    text = (args or "").strip()
    auto_start, workflow, picked = False, "auto", False
    modes = dict(WORKFLOW_WORDS)
    for _ in range(2):
        if not auto_start and text[:1] in ("!", "！"):
            text, auto_start = text[1:].strip(), True
            continue
        found = None if auto_start else _leading_word(text, AUTO_START_WORDS)
        if found:
            text, auto_start = found[1], True
            continue
        found = None if picked else _leading_word(text, modes)
        if found:
            text, workflow, picked = found[1], modes[found[0]], True
            continue
        break
    return text, auto_start, workflow


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
    progress_buttons = []
    for number, team in enumerate(teams[:8], 1):
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
        lines.append(f"{icon} {number}. {title} · {word}")
        stage = team.get("stage") if isinstance(team.get("stage"), dict) else {}
        if stage.get("key") in chat_progress.ACTIVE_STAGES:
            from .progress import eta_text

            when = ""
            if stage.get("key") == "approval" and stage.get("after_approval"):
                when = f"批准后{eta_text(stage['after_approval'], stage.get('after_approval_high'))}出结果"
            elif stage.get("eta") is not None:  # counted from when HaloWebUI read it
                gone = max(0, int(time.time()) - int(stage.get("at") or time.time()))
                left = max(0, int(stage["eta"]) - gone)
                high = max(left, int(stage.get("eta_high") or 0) - gone)
                when = f"还要{eta_text(left, high)}" if high > 0 else "比平时久，快好了"
            now_text = esc(clip(stage.get("now") or "", 60))
            detail = " · ".join(x for x in (now_text, when) if x)
            if detail:
                lines.append(f"   └ {detail}")
        if team.get("status") == "plan_ready" and len(buttons) < 3:
            buttons.append([(f"✅ 批准「{clip(team.get('title'), 16)}」", f"cb:ap:{team['id']}")])
        active = stage.get("key") in chat_progress.ACTIVE_STAGES or (
            not stage and (team.get("status") in ("planning", "plan_ready", "starting") or
                           (team.get("status") == "running" and team.get("phase") not in ("completed", "stopped"))))
        if active and len(progress_buttons) < 3:
            progress_buttons.append([(f"📊 进度「{clip(team.get('title'), 16)}」", f"cb:pg:{team['id']}")])
    buttons.extend(progress_buttons)
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


def _anchor_progress_card(view: dict, chat_id: Any, thread_id: Any, message_id: Any, *, refresh: bool = False) -> None:
    slug = view.get("board")
    board = read_team(slug) if slug else None
    target = notify.target_for(board) if board else None
    if not target or (str(chat_id), str(thread_id or "")) != (target["chat_id"], str(target.get("thread_id") or "")):
        return
    current = board.get("tg_progress") or {}
    if refresh and str(current.get("message_id")) != str(message_id):
        return
    notify.anchor_tg_progress(slug, chat_id, thread_id, message_id, *chat_progress.fingerprints(view),
                              finalized=not chat_progress.is_active(view), expected=current if refresh else None)


async def _progress_command(source: Any, owner: str, selector: str, event: Any, *,
                            workflow_first: Optional[str] = None) -> None:
    from .teams import TeamError

    try:
        views, recent = await asyncio.to_thread(chat_progress.resolve_query_views, owner, selector,
                                                workflow_first=workflow_first)
    except (link.HaloError, TeamError) as exc:
        await _say(source, f"⚠️ 读不到协作进度：{esc(exc.message)}", None, event)
        return
    if not views:
        text, buttons = list_message(recent)
        hint = "没有找到唯一匹配的协作任务。" if selector else "当前没有进行中的协作。"
        await _say(source, hint + "\n\n" + text, buttons, event)
        return
    for view in views:
        text, buttons = chat_progress.render_telegram(view)
        message_id = await _say(source, text, buttons, event)
        if message_id is not None and len(views) == 1:
            _anchor_progress_card(view, source.chat_id, getattr(source, "thread_id", None), message_id)


async def _progress_callback(query: Any, owner: str, team_id: str, *, refresh: bool) -> None:
    view = await asyncio.to_thread(chat_progress.resolve_team_view, owner, team_id)
    message = query.message
    if not view or message is None:
        await query.answer("找不到这个协作任务", show_alert=True)
        return
    chat_id = message.chat_id
    thread_id = getattr(message, "message_thread_id", None)
    text, buttons = chat_progress.render_telegram(view)
    if refresh:
        result = await aedit(chat_id, message.message_id, text, buttons)
        if result in ("ok", "not_modified"):
            _anchor_progress_card(view, chat_id, thread_id, message.message_id, refresh=True)
            await query.answer("已是最新进度" if result == "not_modified" else "已刷新进度")
        else:
            await query.answer("暂时无法刷新，发 /team 进度 查看", show_alert=True)
        return
    message_id = await asend(chat_id, text, buttons, thread_id=thread_id)
    if message_id is None:
        await query.answer("暂时无法发送进度", show_alert=True)
        return
    _anchor_progress_card(view, chat_id, thread_id, message_id)
    await query.answer("已打开进度")


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
        elif kind in ("done", "change"):
            from .lead import request_change

            said = text
            if kind == "change" and entry.get("text"):
                said = f"（接着上一条）上一条要求：{entry['text']}\n用户补充：{text}"
            await asyncio.to_thread(request_change, team_id, said, owner=owner, actor=_author(event, source),
                                    via="telegram", reply_to=_reply_target(source))
            await _say(source, "🧭 已交给负责人，它看完团队现在的状态会把回复和要改的计划发到这里。", None, event)
    except link.HaloError as exc:
        await _say(source, f"⚠️ {esc(exc.message)}", None, event)
    except TeamError as exc:
        await _say(source, f"⚠️ {esc(exc.message)}", None, event)


def _reply_target(source: Any) -> dict:
    target = {"chat_id": str(source.chat_id)}
    if getattr(source, "thread_id", None):
        target["thread_id"] = str(source.thread_id)
    return target


async def _approve_by_text(source: Any, owner: str, message_id: str, entry: dict, event: Any) -> None:
    try:
        team = await asyncio.to_thread(link.approve, owner, entry["team"])
    except link.HaloError as exc:
        mark_acted(source.chat_id, message_id, "approve-failed")
        await _say(source, f"⚠️ 没能批准：{esc(exc.message)}", None, event)
        return
    mark_acted(source.chat_id, message_id, "approve")
    await _say(source, f"✅ 已批准「{esc(clip(team.get('title'), 40))}」，成员开始干活了。完成或需要你时我会告诉你。",
               _started_buttons(team["id"]), event)


async def _on_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    try:
        await _handle_callback(update.callback_query)
    except Exception:  # noqa: BLE001
        logger.warning("halowebui-teams: Telegram button failed", exc_info=True)
    raise ApplicationHandlerStop


CALLBACK_DONE = {"ap": "✅ 已批准，成员开始干活了", "cx": "✖ 已取消", "rp": "🔄 负责人在重新规划", "rt": "🔁 已重试",
                 "dx": "✅ 已按负责人的建议处理", "fx": "🛠 已交给负责人：补缺口的计划好了发到这里",
                 "ca": "✅ 变更已应用", "cd": "✖ 已放弃这个变更", "kb": "📚 已存入「协作结论」知识库",
                 "dp": "🚀 已启动合并、推送、部署与清理，完成后会通知你"}


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
        if action in ("pg", "pr"):
            await _progress_callback(query, owner, team_id, refresh=action == "pr")
            return
        if action == "ap":
            await asyncio.to_thread(link.approve, owner, team_id)
        elif action == "cx":
            await asyncio.to_thread(link.cancel, owner, team_id)
        elif action == "rp":
            await asyncio.to_thread(link.replan, owner, team_id, "")
        elif action == "rt" and task_id:
            await asyncio.to_thread(retry, team_id, task_id, owner=owner, actor=str(query.from_user.first_name or ""))
        elif action == "dx" and task_id:
            from .lead import apply_diagnosis

            await asyncio.to_thread(apply_diagnosis, team_id, task_id, owner=owner, actor=str(query.from_user.first_name or ""))
        elif action == "fx":
            from .lead import fill_gaps

            chat = getattr(query.message, "chat_id", None) or getattr(getattr(query.message, "chat", None), "id", None)
            thread = getattr(query.message, "message_thread_id", None)
            await asyncio.to_thread(fill_gaps, team_id, owner=owner, actor=str(query.from_user.first_name or ""),
                                    via="telegram", reply_to={"chat_id": chat, "thread_id": thread})
        elif action == "kb":
            await asyncio.to_thread(link.save_knowledge, owner, team_id)
        elif action == "dp":
            from . import deploy, projects
            from .teams import _require_team

            def _start_dp() -> None:
                slug, _team = _require_team(team_id, owner)
                try:
                    deploy.start(slug, by="telegram")
                except projects.ProjectError as exc:
                    raise TeamError(exc.status, exc.message) from None

            await asyncio.to_thread(_start_dp)
        elif action in ("ca", "cd") and task_id:
            from .lead import apply_change, discard_change

            fn = apply_change if action == "ca" else discard_change
            result = await asyncio.to_thread(fn, team_id, task_id, owner=owner, actor=str(query.from_user.first_name or ""))
            if isinstance(result, dict) and result.get("reopened"):
                try:  # HaloWebUI's list shows the team at work again
                    await asyncio.to_thread(link.sync, owner, team_id)
                except link.HaloError as exc:
                    logger.info("halowebui-teams: HaloWebUI sync after reopening %s: %s", team_id, exc.message)
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
        # Links stay; so do the other buttons of a notice that 存入知识库 does not settle.
        urls = [(b.text, "url:" + b.url if getattr(b, "url", None) else "cb:" + b.callback_data[3:]) for b in row
                if getattr(b, "url", None) or (action in ("kb", "dp") and str(b.callback_data or "").startswith("ht:")
                                               and b.callback_data != query.data)]
        if urls:
            keep.append(urls)
    try:
        await query.edit_message_text(text=(message.text_html or "") + f"\n\n<b>{esc(note)}</b>", parse_mode="HTML",
                                      reply_markup=markup(keep), disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001 — an old or unchanged message: the answer above is enough
        logger.debug("halowebui-teams: could not edit the Telegram message: %s", exc)
