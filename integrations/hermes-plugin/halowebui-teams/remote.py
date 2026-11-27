"""精答、讨论台、自动分流 — and the 协作台 on QQ — from Telegram and QQ: commands, no model turn.

* ``/answer <问题>`` → 精答, ``/discuss <问题>`` → 讨论台 (at the user's usual table), ``/auto <问题>``
  → 自动分流 (HaloWebUI picks 精答 / 讨论 / 协作台). The run is the user's own HaloWebUI run, on its
  page there (``/api/v1/remote``); its result — text, picture, link — comes back to the chat when it
  is done (``tick``, from the bridge loop). The command alone: what it does and what is still going.
* QQ also gets ``/team`` (Telegram's is tg.py, with buttons): the plan comes back as text,
  「批准」/「取消」 are plain words, the result comes back when the lead has written it. A member's
  question (a 多模型研发's 拍板 too) and a failed task come in full, numbered; 「答 …」 answers the
  question, 「重试 [说明]」 / 「按建议」 settle the failure (``_tick_prompts`` / ``_answer_prompt``). A
  team started from QQ tells QQ only (notify.target_for).

Only users linked in ``halo-teams.json`` (``telegram.owners`` / ``qqbot.owners``) are handled; every
other message goes on to Hermes untouched. Messages go out through the gateway's own adapters
(captured when they connect), so formatting, chunking and QQ's passive-reply rules are theirs.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import chat_progress, link
from .common import logger, valid_team_id
from .notify import clip, plain

PLATFORMS = ("telegram", "qqbot")
KINDS = ("answer", "discuss", "auto")
LABEL = {"answer": "精答", "discuss": "讨论", "auto": "自动分流", "team": "协作台"}
PAGE = {"answer": "/answer", "discuss": "/discuss", "auto": "/auto", "team": "/teams"}
# The whole result goes to the chat (the adapters split it into several messages); only beyond
# this — a few thousand words — is the rest left to the page.
TEXT_MAX_CHARS = 30000
JOB_MAX_AGE = {"answer": 3 * 3600, "discuss": 3 * 3600, "auto": 3600, "team": 2 * 86400}
# a team's result: the lead writes it (and checks it, draws its picture) after the last task
CONCLUSION_WAIT = 15 * 60
APPROVE_WINDOW = 30 * 60
APPROVE_WORDS = {"批准", "批准并开始", "开始吧", "批准开始", "同意", "approve"}
CANCEL_WORDS = {"取消", "不做了", "cancel"}
SEND_TIMEOUT = 60
QQ_MILESTONE_COOLDOWN = 20
QQ_PROGRESS_MAX = 10
AUTO_DEPLOY_GRACE = chat_progress.AUTO_DEPLOY_GRACE

_state: dict = {"adapters": {}, "loop": None}
_tasks: set = set()
_store_lock = threading.Lock()


# --- transport -----------------------------------------------------------------------------------

def install(native: Any, adapter: Any) -> None:
    """Platform handler factory for Telegram and QQ (called in the adapter's ``connect()``)."""
    platform = str(getattr(getattr(adapter, "platform", None), "value", "") or "")
    if platform not in PLATFORMS:
        return
    _state["adapters"][platform] = adapter
    try:
        _state["loop"] = asyncio.get_running_loop()
    except RuntimeError:
        pass


def ready(platform: str) -> bool:
    loop = _state.get("loop")
    return platform in _state["adapters"] and loop is not None and loop.is_running()


def _metadata(thread_id: Any) -> Optional[dict]:
    return {"thread_id": str(thread_id)} if thread_id else None


async def asend(platform: str, chat_id: Any, text: str, *, thread_id: Any = None, reply_to: Any = None) -> bool:
    adapter = _state["adapters"].get(platform)
    if adapter is None or not text.strip():
        return False
    if platform == "qqbot":  # QQ shows Markdown as it is typed
        text = plain(text)
    try:
        result = await adapter.send(str(chat_id), text, reply_to=str(reply_to) if reply_to else None,
                                    metadata=_metadata(thread_id))
    except Exception as exc:  # noqa: BLE001 — a notice must never break the caller
        logger.warning("halowebui-teams: %s send failed: %s", platform, type(exc).__name__)
        return False
    return bool(getattr(result, "success", False))


async def asend_picture(platform: str, chat_id: Any, path: Path, caption: str = "", *, thread_id: Any = None) -> bool:
    adapter = _state["adapters"].get(platform)
    if adapter is None:
        return False
    try:
        result = await adapter.send_image_file(str(chat_id), str(path), caption=caption or None,
                                               metadata=_metadata(thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("halowebui-teams: %s picture failed: %s", platform, type(exc).__name__)
        return False
    return bool(getattr(result, "success", False))


def _from_thread(make) -> bool:
    """Run ``make()``'s coroutine on the gateway loop from the bridge thread and wait for it."""
    loop = _state.get("loop")
    if loop is None or not loop.is_running():
        return False
    future = asyncio.run_coroutine_threadsafe(make(), loop)
    try:
        return bool(future.result(timeout=SEND_TIMEOUT))
    except Exception:  # noqa: BLE001
        future.cancel()
        return False


def send(job: dict, text: str) -> bool:
    return _from_thread(lambda: asend(job["platform"], job["chat_id"], text, thread_id=job.get("thread_id"),
                                      reply_to=job.get("reply_to")))


def send_picture(job: dict, path: Path, caption: str) -> bool:
    return _from_thread(lambda: asend_picture(job["platform"], job["chat_id"], path, caption,
                                              thread_id=job.get("thread_id")))


# --- the runs we are waiting for -------------------------------------------------------------------

def _store_path() -> Path:
    override = os.environ.get("HALO_REMOTE_JOBS")
    if override:
        return Path(override)
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "halo-teams" / "remote-jobs.json"


def _load() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def jobs() -> dict:
    with _store_lock:
        return _load()


def put_job(job: dict) -> None:
    with _store_lock:
        data = _load()
        data[f"{job['kind']}:{job['id']}"] = job
        _save(data)


def drop_job(key: str) -> None:
    with _store_lock:
        data = _load()
        if data.pop(key, None) is not None:
            _save(data)


def update_job(key: str, **fields: Any) -> None:
    with _store_lock:
        data = _load()
        if key in data:
            data[key].update(fields)
            _save(data)


def chat_jobs(platform: str, chat_id: Any) -> list[dict]:
    return sorted((j for j in jobs().values() if j.get("platform") == platform and j.get("chat_id") == str(chat_id)),
                  key=lambda j: j.get("at") or 0)


def _refresh_chat_reply_to(platform: str, chat_id: Any, message_id: Any) -> None:
    if platform != "qqbot" or not message_id:
        return
    with _store_lock:
        data = _load()
        changed = False
        for job in data.values():
            if (isinstance(job, dict) and job.get("kind") == "team" and job.get("platform") == platform
                    and job.get("chat_id") == str(chat_id) and job.get("reply_to") != str(message_id)):
                job["reply_to"] = str(message_id)
                changed = True
        if changed:
            _save(data)


def open_plan(platform: str, chat_id: Any) -> Optional[dict]:
    """The newest QQ team plan in this chat sent and not answered yet, if recent."""
    plans = [j for j in chat_jobs(platform, chat_id) if j["kind"] == "team" and j.get("plan_at")
             and not j.get("approved") and time.time() - j["plan_at"] <= APPROVE_WINDOW]
    return plans[-1] if plans else None


# --- incoming ------------------------------------------------------------------------------------

def _platform(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "")


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def on_pre_gateway_dispatch(event: Any = None, gateway: Any = None, session_store: Any = None, **_: Any):
    """``pre_gateway_dispatch`` hook: take what is ours, leave the rest to Hermes."""
    try:
        return _dispatch(event)
    except Exception:  # noqa: BLE001 — never break the gateway's own handling
        logger.warning("halowebui-teams: remote dispatch failed", exc_info=True)
        return None


def _dispatch(event: Any) -> Optional[dict]:
    source = getattr(event, "source", None)
    if event is None or source is None or getattr(event, "internal", False):
        return None
    platform = _platform(source)
    if platform not in PLATFORMS or not ready(platform):
        return None
    owner = link.owner_for(platform, getattr(source, "user_id", None) or getattr(event, "user_id", None))
    if not owner:
        return None
    command = event.get_command() if hasattr(event, "is_command") and event.is_command() else None
    if command in KINDS:
        _spawn(_start(source, owner, command, event.get_command_args().strip(), event))
        return {"action": "skip", "reason": f"halo {command} command"}
    if platform != "qqbot":
        return None  # Telegram's /team and its plan replies: tg.py
    if command in ("team", "teams"):
        _spawn(_team_command(source, owner, event.get_command_args().strip(), event))
        return {"action": "skip", "reason": "halo team command (QQ)"}
    if command == "work":
        _spawn(_work_command(source, owner, event.get_command_args().strip(), event))
        return {"action": "skip", "reason": "halo work command (QQ)"}
    if not command:
        said = prompt_reply(getattr(event, "text", "") or "")
        if said and pick_prompt(platform, source.chat_id, said[0], said[1]):
            _spawn(_answer_prompt(source, owner, *said, event))
            return {"action": "skip", "reason": "answer a team notice (QQ)"}
    word = (getattr(event, "text", "") or "").strip().rstrip("。.!！ ").lower()
    if not command and word in chat_progress.QQ_SHORTCUT_WORDS:
        _refresh_chat_reply_to(platform, source.chat_id, getattr(event, "message_id", None))
        _spawn(_progress_command(source, owner, "", event,
                                 workflow_first="work" if word == "工作流进度" else None))
        return {"action": "skip", "reason": "halo team progress (QQ)"}
    if not command and (word in APPROVE_WORDS or word in CANCEL_WORDS) and open_plan(platform, source.chat_id):
        _spawn(_team_command(source, owner, "批准" if word in APPROVE_WORDS else "取消", event))
        return {"action": "skip", "reason": "answer the team plan (QQ)"}
    return None


def command_fallback(raw_args: str = "") -> str:
    """``/answer`` etc. when the hook did not take it: not a linked user (or not Telegram / QQ)."""
    if not link.configured():
        return "HaloWebUI 还没有和这里接通（~/.hermes/halo-teams.json 缺 halowebui.url，或网关没有 API_SERVER_KEY）。"
    return ("这个账号没有绑定 HaloWebUI 用户（~/.hermes/halo-teams.json → telegram.owners / qqbot.owners），"
            "请在 HaloWebUI 网页里用。")


def _origin(source: Any) -> dict:
    """The chat a command came from, as a team started from it records it (``notify.target_for``)."""
    out = {"platform": _platform(source), "chat_id": str(source.chat_id), "user_id": str(source.user_id or "")}
    if getattr(source, "thread_id", None):
        out["thread_id"] = str(source.thread_id)
    return out


def _job_base(source: Any, event: Any) -> dict:
    job = {"platform": _platform(source), "chat_id": str(source.chat_id), "at": time.time()}
    if getattr(source, "thread_id", None):
        job["thread_id"] = str(source.thread_id)
    if getattr(event, "message_id", None):
        job["reply_to"] = str(event.message_id)
    return job


async def _say(source: Any, text: str, event: Any = None) -> bool:
    return await asend(_platform(source), source.chat_id, text, thread_id=getattr(source, "thread_id", None),
                       reply_to=getattr(event, "message_id", None))


def _url(path: str) -> str:
    return link.public_url(path) if path else ""


USAGE = {
    "answer": "精答：/answer 问题 —— HaloWebUI 先挑（或现写）最合适的助手，需要时上网查资料，再回答；答好了发回这里。",
    "discuss": "讨论：/discuss 问题 —— 几个模型按你平时的讨论台设置讨论，主持人整理结论后发回这里。",
    "auto": "自动分流：/auto 问题或任务 —— HaloWebUI 判断交给精答、讨论还是协作台，结果发回这里。",
}


def usage_text(platform: str, chat_id: Any) -> str:
    lines = ["**HaloWebUI 命令**", *USAGE.values()]
    if platform == "qqbot":
        lines.append("协作台：/team 目标 —— 负责人做计划发到这里，回「批准」开始、「取消」作罢；/team 直接 目标 —— 计划好就开始；"
                     "/team 多模型 目标、/team 快速研发 目标 —— 选研发流程（可以和「直接」叠着写）。"
                     "成员提问回「答 内容」，任务失败回「重试」或「重试 说明」。发 /team 进度 或「协作进度」查详情。")
        lines.append("工作流：/work 需求 —— AGY 出规划 → Codex 开发 → Claude 审阅修复 → 提交推送部署清理，全程自动；"
                     "/work cchclaude 需求 —— 指定审阅用的 Claude。发 /work 进度 查进度。")
    going = chat_jobs(platform, chat_id)
    if going:
        lines.append("")
        lines.append("**还在进行的**")
        for job in going[-6:]:
            minutes = max(0, int((time.time() - (job.get("at") or time.time())) / 60))
            lines.append(f"• {LABEL[job['kind']]}：{clip(job.get('question') or job.get('title'), 40)}（{minutes} 分钟前）")
    return "\n".join(lines)


async def _start(source: Any, owner: str, kind: str, question: str, event: Any) -> None:
    platform = _platform(source)
    if not question or question in ("help", "帮助", "?", "？", "列表", "状态"):
        await _say(source, usage_text(platform, source.chat_id), event)
        return
    key = f"{platform}:{source.chat_id}:{getattr(event, 'message_id', '') or int(time.time())}"
    try:
        started = await asyncio.to_thread(link.remote_start, owner, kind, question, key, _origin(source))
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能交给{LABEL[kind]}：{exc.message}", event)
        return
    put_job({**_job_base(source, event), "kind": kind, "id": started["id"], "owner": owner, "question": question[:200]})
    if started.get("deduplicated"):
        return  # the command came twice: the first one is under way and was answered
    url = _url(f"{PAGE[kind]}/{started['id']}" if kind != "auto" else "")
    after = {"answer": "答好了发回这里（一般一两分钟）。", "discuss": "结论写好了发回这里（一般几分钟）。",
             "auto": "选好了会告诉你交给了谁，结果发回这里。"}[kind]
    icon = {"answer": "🎯", "discuss": "🗣", "auto": "🔀"}[kind]
    await _say(source, f"{icon} 已交给{LABEL[kind]}：{clip(question, 60)}\n{after}" + (f"\n🌐 {url}" if url else ""), event)


# --- QQ: the 协作台 -----------------------------------------------------------------------------------

async def _team_command(source: Any, owner: str, args: str, event: Any) -> None:
    from .tg import list_message, split_team_args, workflow_note

    platform = _platform(source)
    _refresh_chat_reply_to(platform, source.chat_id, getattr(event, "message_id", None))
    if args in ("", "列表", "list", "ls"):
        try:
            teams = await asyncio.to_thread(link.recent, owner)
        except link.HaloError as exc:
            await _say(source, f"⚠️ 读不到协作任务：{exc.message}", event)
            return
        text, _buttons = list_message(teams)
        await _say(source, html_text(text) + "\n\n发 /team 进度 查详情。回「批准」开始最近一个等批准的计划。", event)
        return
    selector = chat_progress.parse_progress_query(args)
    if selector is not None:
        await _progress_command(source, owner, selector, event)
        return
    if args in ("help", "帮助", "?", "？"):
        await _say(source, usage_text(platform, source.chat_id), event)
        return
    if args in ("批准", "取消") or args.startswith("重做"):
        job = open_plan(platform, source.chat_id)
        if job is None:
            await _say(source, "这里没有等你批准的计划。发 /team 看最近的协作任务。", event)
            return
        key = f"team:{job['id']}"
        try:
            if args == "批准":
                team = await asyncio.to_thread(link.approve, owner, job["id"])
                update_job(key, approved=True)
                await _say(source, f"✅ 已批准「{clip(team.get('title'), 40)}」，成员开始干活了，完成后把结论发到这里。", event)
            elif args == "取消":
                await asyncio.to_thread(link.cancel, owner, job["id"])
                drop_job(key)
                await _say(source, "✖ 已取消。", event)
            else:
                feedback = args[2:].strip(" ：:，,")
                await asyncio.to_thread(link.replan, owner, job["id"], feedback)
                update_job(key, plan_at=None, plan_sent=False)
                await _say(source, "🔄 已把你的意见交给负责人，新计划好了发到这里。", event)
        except link.HaloError as exc:
            await _say(source, f"⚠️ {exc.message}", event)
        return
    goal, auto_start, workflow = split_team_args(args)
    if not goal:
        await _say(source, usage_text(platform, source.chat_id), event)
        return
    try:
        team = await asyncio.to_thread(link.create, owner, goal, _origin(source), auto_start, workflow)
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能发起协作：{exc.message}", event)
        return
    put_job({**_job_base(source, event), "kind": "team", "id": team["id"], "owner": owner, "question": goal[:200],
             "auto_start": auto_start})
    url = link.team_url(team["id"])
    after = ("计划好就直接开始，完成后把结论发到这里。" if auto_start
             else "计划好了发到这里（一般 1 分钟内），回「批准」才开始。")
    await _say(source, f"🧭 已交给负责人做计划{workflow_note(workflow)}：{clip(team.get('title'), 60)}\n{after}" + (f"\n🌐 {url}" if url else ""), event)


async def _work_command(source: Any, owner: str, args: str, event: Any) -> None:
    """QQ's ``/work``: the same workflow as Telegram's (tg.py), its notices and questions come here."""
    from .tg import WORK_USAGE, split_work_args, work_started

    _refresh_chat_reply_to(_platform(source), source.chat_id, getattr(event, "message_id", None))
    if chat_progress.is_work_progress_query(args):
        selector = chat_progress.parse_progress_query(args)
        if selector is None:
            await _say(source, "发 /work 进度 [编号或 ID] 查看工作流进度。要发起新需求，换个说法别用「进度 / 状态 / 详情」开头。",
                       event)
        else:
            await _progress_command(source, owner, selector, event, workflow_first="work")
        return
    goal, prefs = split_work_args(args)
    if not goal or goal in ("help", "帮助", "?", "？"):
        await _say(source, html_text(WORK_USAGE), event)
        return
    try:
        team = await asyncio.to_thread(link.create, owner, goal, _origin(source), True, "work", prefs)
    except link.HaloError as exc:
        await _say(source, f"⚠️ 没能发起工作流：{exc.message}", event)
        return
    put_job({**_job_base(source, event), "kind": "team", "id": team["id"], "owner": owner, "question": goal[:200],
             "auto_start": True})
    url = link.team_url(team["id"])
    await _say(source, html_text(work_started(team, prefs)) + (f"\n🌐 {url}" if url else ""), event)


async def _progress_command(source: Any, owner: str, selector: str, event: Any, *,
                            workflow_first: Optional[str] = None) -> None:
    from .teams import TeamError
    from .tg import list_message

    try:
        views, recent = await asyncio.to_thread(chat_progress.resolve_query_views, owner, selector,
                                                workflow_first=workflow_first)
    except (link.HaloError, TeamError) as exc:
        await _say(source, f"⚠️ 读不到协作进度：{exc.message}", event)
        return
    if not views:
        text, _buttons = list_message(recent)
        hint = "没有找到唯一匹配的协作任务。" if selector else "当前没有进行中的协作。"
        await _say(source, hint + "\n\n" + html_text(text), event)
        return
    for view in views:
        await _say(source, chat_progress.render_qq(view), event)


_TAG_RE = re.compile(r"<[^>]+>")


def html_text(text: str) -> str:
    """A Telegram HTML notice as plain text (QQ): tags out, entities back, its Telegram hint lines out."""
    lines = [line for line in str(text or "").split("\n") if "回复这条消息" not in line]
    return html.unescape(_TAG_RE.sub("", "\n".join(lines))).strip()


# --- the read-back (bridge loop) ---------------------------------------------------------------------

def tick() -> None:
    """Look at every run we are waiting for; tell its chat what came of it."""
    for key, job in list(jobs().items()):
        if not isinstance(job, dict) or job.get("platform") not in PLATFORMS or job.get("kind") not in LABEL:
            drop_job(key)
            continue
        if not ready(job["platform"]):
            continue
        if time.time() - (job.get("at") or 0) > JOB_MAX_AGE[job["kind"]]:
            url = _job_url(job)
            send(job, f"⏳ {LABEL[job['kind']]}「{clip(job.get('question'), 40)}」很久还没好，不再等了，结果请到网页看。"
                      + (f"\n🌐 {url}" if url else ""))
            drop_job(key)
            continue
        try:
            if job["kind"] == "team":
                _tick_team(key, job)
            else:
                _tick_run(key, job)
        except link.HaloError as exc:
            if exc.status in (401, 403, 404):
                logger.info("halowebui-teams: %s %s is gone for us (%s)", job["kind"], job["id"], exc.message)
                drop_job(key)
            else:
                logger.info("halowebui-teams: %s %s not read (%s); trying again", job["kind"], job["id"], exc.message)
        except Exception:  # noqa: BLE001
            logger.warning("halowebui-teams: remote tick failed for %s", key, exc_info=True)


def _job_url(job: dict) -> str:
    if job["kind"] == "team":
        return link.team_url(job["id"])
    return _url(f"{PAGE[job['kind']]}/{job['id']}") if job["kind"] != "auto" else ""


def _tick_run(key: str, job: dict) -> None:
    state = link.remote_state(job["owner"], job["kind"], job["id"])
    status = state.get("status")
    if status == "running":
        return
    if status == "gone":
        drop_job(key)
        return
    if job["kind"] == "auto":
        _after_routing(key, job, state)
        return
    label = LABEL[job["kind"]]
    url = _url(state.get("url") or "")
    if status != "done":
        why = f"：{state['error']}" if state.get("error") else ""
        verb = "停下了" if status == "stopped" else "没完成"
        if send(job, f"⚠️ {label}「{clip(state.get('title') or job.get('question'), 40)}」{verb}{why}"
                     + (f"\n🌐 {url}" if url else "")):
            drop_job(key)
        return
    if not send(job, result_message(job, state)):
        return  # not sent: tried again on the next tick
    drop_job(key)
    if state.get("picture"):
        _send_run_picture(job, state)


def whole(body: str) -> str:
    """The result as it is, cut only past TEXT_MAX_CHARS."""
    if len(body) <= TEXT_MAX_CHARS:
        return body
    return body[:TEXT_MAX_CHARS].rstrip() + "\n\n…（太长了，后面的在网页看）"


def result_message(job: dict, state: dict) -> str:
    label = LABEL[job["kind"]]
    title = clip(state.get("title") or job.get("question"), 60)
    by = f"（{state['by']}）" if state.get("by") else ""
    head = f"✅ {label}好了：**{title}**{by}"
    url = _url(state.get("url") or "")
    tail = f"\n\n🌐 网页：{url}" if url else ""
    body = whole(str(state.get("text") or "").strip())
    return f"{head}\n\n{body}{tail}"


def _send_run_picture(job: dict, state: dict) -> None:
    try:
        data = link.remote_picture(job["owner"], job["kind"], job["id"])
    except link.HaloError as exc:
        logger.info("halowebui-teams: no picture for %s %s (%s)", job["kind"], job["id"], exc.message)
        return
    with tempfile.TemporaryDirectory(prefix="halo-remote-") as folder:
        path = Path(folder) / "picture.png"
        path.write_bytes(data)
        send_picture(job, path, f"🖼 结论配图 · {clip(state.get('title') or job.get('question'), 60)}")


def _after_routing(key: str, job: dict, state: dict) -> None:
    status = state.get("status")
    if status != "dispatched":
        why = state.get("error") or "原因未知"
        if send(job, f"⚠️ 自动分流没有派发「{clip(job.get('question'), 40)}」：{why}"):
            drop_job(key)
        return
    mode, target = state.get("mode"), state.get("target_id")
    reason = f"（{clip(state['reason'], 120)}）" if state.get("reason") else ""
    notes = []
    if state.get("read_only"):
        notes.append("只读，不改文件")
    if state.get("degraded"):
        notes.append("临时改用了别的方式")
    note = f"\n{'；'.join(notes)}" if notes else ""
    if mode not in ("answer", "discuss", "team") or not target:
        drop_job(key)
        return
    if mode == "team" and job["platform"] == "telegram":
        # the team carries this chat as its origin: the 协作台 sends its plan here, with buttons
        tail = "计划好了发到这里，点「✅ 批准并开始」才开始；回复计划消息可以写修改意见。"
    elif mode == "team":
        tail = "计划好了发到这里，回「批准」开始。"
    else:
        tail = "结果好了发到这里。"
    url = link.team_url(target) if mode == "team" else _url(f"{PAGE[mode]}/{target}")
    if not send(job, f"🔀 自动分流：交给{LABEL[mode]}{reason}{note}\n{tail}" + (f"\n🌐 {url}" if url else "")):
        return
    drop_job(key)
    if mode == "team" and job["platform"] == "telegram":
        return  # the 协作台's own Telegram notices take it from here (notify.py)
    put_job({**job, "kind": mode, "id": target, "at": time.time()})


def _live_snapshot(job: dict) -> Optional[dict]:
    from .teams import TeamError, snapshot

    if valid_team_id(job["id"]):
        try:
            return snapshot(job["id"], job["owner"])
        except TeamError as exc:
            if exc.status != 404:
                raise
    return None


def _tick_qq_progress(key: str, job: dict, snap: dict) -> None:
    if job["platform"] != "qqbot" or not link.qq_progress_enabled():
        return
    count = int(job.get("progress_count") or 0)
    if count >= QQ_PROGRESS_MAX:
        return
    view = chat_progress.view_from_snapshot(snap)
    prev = job.get("progress_state")
    current = chat_progress.qq_milestone_state(view)
    message = chat_progress.qq_milestone_message(prev, view)
    if not message:
        if prev != current:
            update_job(key, progress_state=current)
        return
    stamp = time.time()
    last = max(job.get("progress_at") or 0, job.get("progress_attempt_at") or 0)
    if stamp - last < QQ_MILESTONE_COOLDOWN:
        return
    if send(job, message):
        update_job(key, progress_state=current, progress_at=stamp, progress_count=count + 1)
    else:
        update_job(key, progress_attempt_at=stamp)


def _tick_team(key: str, job: dict) -> None:
    """A team started from QQ: its plan, its finish (QQ has no buttons and no plan hand-over)."""
    from .notify import plan_failed_message, plan_message

    snap = _live_snapshot(job) if job.get("approved") else None
    team = ({**(snap.get("team") or {}), "status": "running"} if snap
            else link.get(job["owner"], job["id"]))
    status = team.get("status")
    if status in ("planning", "starting"):
        return
    if status in ("plan_ready", "start_failed") and not job.get("plan_sent") and not job.get("approved"):
        text, _buttons = plan_message(team)
        if send(job, html_text(text) + "\n\n回「批准」开始，「取消」作罢；/team 重做 意见 —— 按意见重新规划。"):
            update_job(key, plan_sent=True, plan_at=time.time())
        return
    if status == "plan_failed":
        text, _buttons = plan_failed_message(team)
        if send(job, html_text(text) + "\n\n发 /team 重做 补充要求 —— 按它重新规划。"):
            update_job(key, plan_sent=True, plan_at=time.time())
        return
    if status == "cancelled":
        drop_job(key)
        return
    if status != "running":
        return
    if not job.get("approved"):
        if job.get("auto_start"):
            text, _buttons = plan_message(team, started=True)
            send(job, html_text(text))
        update_job(key, approved=True)
        return
    phase = team.get("phase")
    if snap and phase in ("running", "paused", "completed"):
        _tick_qq_progress(key, job, snap)
    url = link.team_url(job["id"])
    if phase == "attention":
        if _tick_prompts(key, job, snap) or job.get("attention_sent"):
            return
        # nothing we can put to the user here (a task in triage): the page
        if send(job, f"🟣 协作「{clip(team.get('title'), 40)}」需要你处理，请到网页看。" + (f"\n🌐 {url}" if url else "")):
            update_job(key, attention_sent=True)
        return
    if job.get("attention_sent") or job.get("prompts"):
        update_job(key, attention_sent=False, prompts={})
    if phase == "running":
        return
    if phase == "stopped":
        if send(job, f"⏹ 协作「{clip(team.get('title'), 40)}」已停止。" + (f"\n🌐 {url}" if url else "")):
            drop_job(key)
        return
    if phase == "completed":
        _team_done(key, job, team)


def _team_done(key: str, job: dict, team: dict) -> None:
    from .common import board_slug, read_team
    from .notify import _conclusion_markdown, picture_of

    board = read_team(board_slug(job["id"])) or {}
    deploy = ((board.get("project") or {}).get("deploy") or team.get("deploy") or {})
    deploy_status = deploy.get("status")
    if job.get("done_sent"):
        if deploy_status in chat_progress.DEPLOY_TERMINAL or (
            deploy_status != "running" and time.time() - float(job.get("done_at") or 0) >= AUTO_DEPLOY_GRACE
        ):
            drop_job(key)
        return
    conclusion = board.get("conclusion") or {}
    waited = time.time() - float(job.get("completed_seen") or time.time())
    if not job.get("completed_seen"):
        update_job(key, completed_seen=time.time())
    from . import illustrate

    writing = conclusion.get("status") not in ("ready", "failed") or illustrate.drawing(conclusion) \
        or (conclusion.get("acceptance") or {}).get("status") == "checking"
    if writing and waited < CONCLUSION_WAIT:
        return
    markdown = _conclusion_markdown(board) if board else ""
    url = link.team_url(job["id"], "/conclusion" if markdown else "")
    head = f"✅ 协作好了：**{clip(team.get('title'), 60)}**"
    tail = f"\n\n🌐 {'阅读结论' if markdown else '工作台'}：{url}" if url else ""
    body = markdown.strip() or "结论没有写出来，各任务的结果请到工作台看。"
    body = whole(body)
    if not send(job, f"{head}\n\n{body}{tail}"):
        return
    if deploy_status == "running" or (deploy_status not in chat_progress.DEPLOY_TERMINAL
                                      and chat_progress.expects_auto_deploy(board)):
        update_job(key, done_sent=True, done_at=time.time())
    else:
        drop_job(key)
    picture = picture_of(board) if board else None
    if picture is not None:
        send_picture(job, picture, f"🖼 结果配图 · {clip(team.get('title'), 60)}")


# --- QQ: a member's question, a failed task ----------------------------------------------------------

ANSWER_WORDS = ("回答", "答")
RETRY_WORDS = ("重试",)
ADVICE_WORDS = {"按建议", "按建议处理", "照建议"}
_PROMPT_RE = re.compile(r"^(回答|答|重试)\s*(?:[#＃](\d{1,3}))?(?:$|[\s：:，,]+)(.*)$", re.S)


def prompt_reply(text: str) -> Optional[tuple[str, Optional[int], str]]:
    """「答 …」 / 「答#2 …」 / 「重试 [说明]」 / 「按建议」 → (verb, number, text); None: not one of ours.
    A word counts only with a separator (or a number) after it: 「答案是…」 is a message."""
    text = (text or "").strip()
    if text.rstrip("。.!！ ") in ADVICE_WORDS:
        return "advice", None, ""
    m = _PROMPT_RE.match(text)
    if not m:
        return None
    verb = "answer" if m.group(1) in ANSWER_WORDS else "retry"
    body = m.group(3).strip()
    if verb == "answer" and not body:
        return None
    return verb, int(m.group(2)) if m.group(2) else None, body


VERB_KIND = {"answer": "ask", "retry": "fail", "advice": "fail"}


def pick_prompt(platform: str, chat_id: Any, verb: str, number: Optional[int]) -> Optional[tuple[str, str, dict]]:
    """The open notice a reply is for: (job key, prompt key, prompt) — the numbered one, else the newest
    of its kind (a question for 「答」, a failure for 「重试」 / 「按建议」)."""
    kind = VERB_KIND[verb]
    found = []
    for job in chat_jobs(platform, chat_id):
        if job.get("kind") != "team":
            continue
        for pkey, prompt in (job.get("prompts") or {}).items():
            if prompt.get("acted") or prompt.get("kind") != kind:
                continue
            if verb == "advice" and not prompt.get("advice"):
                continue
            if number is None or prompt.get("n") == number:
                found.append((f"team:{job['id']}", pkey, prompt))
    return max(found, key=lambda f: f[2].get("at") or 0) if found else None


def _chat_numbers(platform: str, chat_id: Any) -> list[int]:
    return [int(p.get("n") or 0) for j in chat_jobs(platform, chat_id) for p in (j.get("prompts") or {}).values()]


def _tick_prompts(key: str, job: dict, snap: Optional[dict] = None) -> bool:
    """A QQ team's members asking or failing: each notice once, in full, numbered. True when some
    notice is open (sent now or before) or will be (the lead is still diagnosing)."""
    from .common import board_slug, read_team
    from .notify import ask_message, fail_message, pending

    snap = snap or _live_snapshot(job)
    if not snap:
        return False
    board = read_team(board_slug(job["id"]))
    if not board:
        return False
    found = [(k, kind, task) for k, kind, task in pending(board, snap) if kind in ("ask", "fail")]
    prompts = {k: p for k, p in (job.get("prompts") or {}).items() if k in {f[0] for f in found}}
    changed = prompts != (job.get("prompts") or {})
    for pkey, kind, task in found:
        if pkey in prompts:
            continue
        number = max(_chat_numbers(job["platform"], job["chat_id"]) + [int(p.get("n") or 0) for p in prompts.values()],
                     default=0) + 1
        diagnosis = task.get("diagnosis") or {}
        advice = diagnosis.get("status") == "ready" and diagnosis.get("action") not in (None, "", "ask_user")
        if kind == "ask":
            text, _buttons = ask_message(board, task)
            hint = f"回「答 你的回答」转给它；同时有几个问题在等时写「答#{number} 内容」。"
        else:
            text, _buttons = fail_message(board, task)
            hint = (f"回「重试」原样重试，「重试 说明」带着说明重试{'，「按建议」按负责人的建议处理' if advice else ''}；"
                    f"同时有几个在等时写「重试#{number}」。")
        if not send(job, f"【#{number}】" + html_text(text) + f"\n\n{hint}"):
            break
        prompts[pkey] = {"kind": kind, "task": task["id"], "member": task.get("member") or "", "n": number,
                         "at": time.time(), **({"advice": True} if advice else {})}
        changed = True
    if changed:
        update_job(key, prompts=prompts)
    # a failure the lead is still looking at comes once it has: no 「请到网页看」 meanwhile
    held = any(t.get("sub_status") in ("waiting_user", "failed", "blocked") for t in snap.get("tasks") or [])
    return bool(prompts) or held


async def _answer_prompt(source: Any, owner: str, verb: str, number: Optional[int], text: str, event: Any) -> None:
    from .teams import TeamError, post_message, retry

    picked = pick_prompt(_platform(source), source.chat_id, verb, number)
    if picked is None:
        return
    _refresh_chat_reply_to(_platform(source), source.chat_id, getattr(event, "message_id", None))
    job_key, pkey, prompt = picked
    team_id = job_key.split(":", 1)[1]
    author = str(getattr(source, "user_name", None) or "你")[:40]
    try:
        if verb == "answer":
            await asyncio.to_thread(post_message, team_id, prompt["task"], text, author_name=author, owner=owner)
            reply = f"✅ 已转给 {prompt.get('member') or '成员'}，它会接着做。"
        elif verb == "advice":
            from .lead import apply_diagnosis

            await asyncio.to_thread(apply_diagnosis, team_id, prompt["task"], owner=owner, actor=author)
            reply = "✅ 已按负责人的建议处理。"
        else:
            if text:
                await asyncio.to_thread(post_message, team_id, prompt["task"], text, author_name=author, owner=owner)
            await asyncio.to_thread(retry, team_id, prompt["task"], owner=owner, actor=author)
            reply = "🔁 已带着你的说明重试。" if text else "🔁 已重试。"
    except (link.HaloError, TeamError) as exc:
        await _say(source, f"⚠️ {exc.message}", event)
        return
    with _store_lock:
        data = _load()
        entry = ((data.get(job_key) or {}).get("prompts") or {}).get(pkey)
        if entry is not None:
            entry["acted"] = verb
            _save(data)
    await _say(source, reply, event)
