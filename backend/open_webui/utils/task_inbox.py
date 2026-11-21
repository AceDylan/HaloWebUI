"""Unified Task Inbox across HaloWebUI workbenches and Hermes channels.

Aggregates what is waiting for the user (``attention``), currently running
(``running``), and recently ended (``ended``, last N days) across:
- Hermes live runs & approvals
- Background runners (reclaude / cchclaude / anyclaude / officlaude / codex / agy / offiagy)
- 协作台 (Agent Teams), 精答 (Answer Desk), 讨论台 (Discussion Room), 视频工作台, 自动分流, 生图
- Unread finished Hermes chats
- Recent cross-channel Hermes sessions (Telegram / QQ) and (for admins) cross-channel
  runner runs so a task started yesterday on Telegram is immediately discoverable on web.

Called on demand when opening the Task Inbox (NOT on the 10 s sidebar poll),
and every sub-collector is isolated so a slow or unavailable upstream never
blocks local results.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_DAYS = 7
MAX_DAYS = 30
UPSTREAM_TIMEOUT_SECONDS = 4.0
MAX_ENDED_ITEMS = 40
STALE_RUNNER_SECONDS = 6 * 3600
DISMISSED_INFO_KEY = "task_inbox_dismissed"
DISMISSED_MAX_ITEMS = 200
DISMISSED_TTL_SECONDS = (MAX_DAYS + 1) * 86400
PLACEHOLDER_TITLES = {"New Chat", "新对话", "新聊天", "新精答", "新讨论"}
_GENERIC_CONTINUATION_TITLES = {
    "继续",
    "继续吧",
    "继续做",
    "继续执行",
    "好的",
    "好",
    "确认",
    "同意",
    "是",
    "ok",
    "yes",
    "continue",
    "go",
    "go on",
}
_CHAT_KEYED_PREFIXES = {"hermes", "chat", "video", "answer", "discuss", "image"}

_RUNNER_PLATFORM_TO_SOURCE = {
    "telegram": "telegram",
    "qqbot": "qqbot",
    "qq": "qqbot",
    "cli": "cli",
    "api_server": "web",
    "web": "web",
    "": "web",
}


def _epoch(value: Any, fallback: float = 0.0) -> float:
    if value is None or value == "":
        return fallback
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e12 else v
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return fallback
        try:
            v = float(s)
            return v / 1000.0 if v > 1e12 else v
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return fallback
    return fallback


def _clip(text: Any, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _normalize_source(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return _RUNNER_PLATFORM_TO_SOURCE.get(key, "web")


def _chat_summaries(chat_ids: set[str], user_id: str) -> dict[str, dict]:
    """Read id, title, updated_at, meta (never full chat JSON) for a bounded set of chats."""
    if not chat_ids:
        return {}
    from open_webui.internal.db import get_db
    from open_webui.models.chats import Chat

    with get_db() as db:
        rows = (
            db.query(Chat.id, Chat.title, Chat.updated_at, Chat.meta)
            .filter(Chat.user_id == user_id, Chat.id.in_(list(chat_ids)))
            .all()
        )
    out: dict[str, dict] = {}
    for cid, title, updated_at, meta in rows:
        meta_dict = meta if isinstance(meta, dict) else {}
        hermes_session = meta_dict.get("hermes_session")
        source = (
            _normalize_source(hermes_session.get("source"))
            if isinstance(hermes_session, dict)
            else "web"
        )
        out[cid] = {
            "title": title if title and title not in PLACEHOLDER_TITLES else None,
            "updated_at": _epoch(updated_at),
            "unread_at": _epoch(meta_dict.get("hermes_unread_at")),
            "source": source,
        }
    return out


def _collect_local(user_id: str, days: int, now: float) -> tuple[list[dict], list[dict], list[dict], set[str]]:
    """Collect attention, running, and ended items from local memory & SQLite DB."""
    from open_webui.utils.hermes_agent import list_active_runs
    from open_webui.utils.hermes_runner_progress import list_runner_progress
    from open_webui.utils.hermes_unread import list_unread_chat_ids
    from open_webui.utils.work_activity import list_work

    since = now - days * 86400
    attention: list[dict] = []
    running: list[dict] = []
    ended: list[dict] = []
    seen_chats: set[str] = set()
    seen_keys: set[str] = set()
    active_run_ids: set[str] = set()

    def claim(key: str, chat_id: Optional[str] = None) -> bool:
        if key in seen_keys:
            return False
        if chat_id and chat_id in seen_chats:
            return False
        seen_keys.add(key)
        if chat_id:
            seen_chats.add(chat_id)
        return True

    # 1. Active Hermes turns (approvals → attention; others → running)
    active_hermes = []
    try:
        active_hermes = list_active_runs(user_id)
    except Exception:
        log.debug("task_inbox: list_active_runs failed", exc_info=True)

    hermes_chat_ids = {r["chat_id"] for r in active_hermes if r.get("chat_id")}
    for run in active_hermes:
        cid = run.get("chat_id")
        if not cid or not claim(f"hermes:{cid}", cid):
            continue
        if run.get("awaiting_approval"):
            approval = run.get("approval") or {}
            attention.append({
                "id": f"hermes:{cid}",
                "bucket": "attention",
                "kind": "hermes",
                "source": "web",
                "title": run.get("title") or "Hermes 任务",
                "status": "waiting",
                "status_label": "等你批准",
                "summary": _clip(approval.get("command") or approval.get("description") or "等待命令审批"),
                "href": f"/c/{cid}",
                "chat_id": cid,
                "timestamp": _epoch(approval.get("since") or run.get("started_at"), now),
            })
        else:
            running.append({
                "id": f"hermes:{cid}",
                "bucket": "running",
                "kind": "hermes",
                "source": "web",
                "title": run.get("title") or "Hermes 任务",
                "status": "running",
                "status_label": "运行中",
                "summary": f"已引导 {run['steers']} 次" if run.get("steers") else "",
                "href": f"/c/{cid}",
                "chat_id": cid,
                "timestamp": _epoch(run.get("started_at"), now),
            })

    # 2. Live background runners
    try:
        for bg in list_runner_progress(user_id, now=now):
            rid = str(bg.get("run_id") or "")
            cid = bg.get("chat_id")
            if rid:
                active_run_ids.add(rid)
            if not claim(f"runner:{rid or cid}", cid):
                continue
            running.append({
                "id": f"runner:{rid or cid}",
                "bucket": "running",
                "kind": "runner",
                "source": "web",
                "title": bg.get("title") or f"{bg.get('agent') or '后台'}任务",
                "status": "running",
                "status_label": f"{bg.get('agent') or '后台'}运行中",
                "summary": _clip(bg.get("last_activity") or (f"第 {bg['step']} 步" if bg.get("step") else "")),
                "href": f"/c/{cid}" if cid else None,
                "chat_id": cid,
                "run_id": rid or None,
                "agent": bg.get("agent") or None,
                "timestamp": _epoch(bg.get("started_at") or bg.get("updated_at"), now),
            })
    except Exception:
        log.debug("task_inbox: list_runner_progress failed", exc_info=True)

    # 3. Other live work (精答, 讨论台, 协作台, 自动分流, 生图, 视频, chat)
    try:
        for row in list_work(user_id, hermes_chat_ids):
            kind = row.get("kind") or "chat"
            row_id = str(row.get("id") or "")
            cid = row.get("chat_id")
            if not claim(f"{kind}:{row_id}", cid):
                continue
            is_waiting = row.get("state") == "waiting"
            bucket = "attention" if is_waiting else "running"
            item = {
                "id": f"{kind}:{row_id}",
                "bucket": bucket,
                "kind": kind,
                "source": "web",
                "title": row.get("title") or "进行中的任务",
                "status": "waiting" if is_waiting else "running",
                "status_label": row.get("note") or ("等你处理" if is_waiting else "进行中"),
                "summary": "",
                "href": row.get("href"),
                "chat_id": cid,
                "timestamp": _epoch(row.get("started_at"), now),
            }
            (attention if is_waiting else running).append(item)
    except Exception:
        log.debug("task_inbox: list_work failed", exc_info=True)

    # 4. Unread finished Hermes chats (go to top of ended, with unread=True)
    try:
        unread_ids = list_unread_chat_ids(user_id, limit=30)
        unread_meta = _chat_summaries(set(unread_ids), user_id)
        for cid in unread_ids:
            if not claim(f"unread:{cid}", cid):
                continue
            info = unread_meta.get(cid, {})
            ts = info.get("unread_at") or info.get("updated_at") or now
            ended.append({
                "id": f"unread:{cid}",
                "bucket": "ended",
                "kind": "hermes",
                "source": info.get("source") or "web",
                "title": info.get("title") or "已完成的对话",
                "status": "unread",
                "status_label": "未读 · 已完成",
                "summary": "后台运行已完成，尚未打开查看",
                "href": f"/c/{cid}",
                "chat_id": cid,
                "timestamp": ts,
                "unread": True,
            })
    except Exception:
        log.debug("task_inbox: unread chats failed", exc_info=True)

    # 5. Recent 协作台 teams (ended / done within window)
    try:
        from open_webui.models.agent_teams import AgentTeams, bucket_of

        for team in AgentTeams.list_for_user(user_id, limit=25):
            ts = _epoch(team.finished_at or team.updated_at or team.created_at)
            if ts < since:
                continue
            b = bucket_of(team.status, team.phase)
            if b in ("active", "review"):
                continue  # already handled in live work
            if not claim(f"team:{team.id}"):
                continue
            state = (team.phase or "running") if team.status == "running" else (team.status or "")
            if b == "done":
                status, label, recovery = "done", "已完成", None
                summary = "完整结果已整理好"
            elif state == "stopped":
                status, label, recovery = "stopped", "已停止", "continue"
                summary = _clip(team.error or "可在协作台继续原任务或重新发起")
            elif state in ("plan_failed", "start_failed"):
                status, label, recovery = "failed", "启动失败" if state == "start_failed" else "计划失败", "restart"
                summary = _clip(team.error or "可重新发起计划")
            else:
                status, label, recovery = "stopped", "已取消", "restart"
                summary = _clip(team.error or "")
            ended.append({
                "id": f"team:{team.id}",
                "bucket": "ended",
                "kind": "team",
                "source": "web",
                "title": team.title or _clip(team.goal, 48) or "协作任务",
                "status": status,
                "status_label": label,
                "summary": summary,
                "href": f"/teams/{team.id}",
                "chat_id": team.chat_id,
                "timestamp": ts,
                "recovery": recovery,
            })
    except Exception:
        log.debug("task_inbox: agent_teams failed", exc_info=True)

    # 6. Recent 视频任务 (replied → attention; done / failed / stopped → ended)
    try:
        from open_webui.utils.video_tasks import list_tasks as list_video_tasks

        for task in list_video_tasks(user_id, limit=15, since=int(since)):
            cid = task.get("chatId")
            state = task.get("state")
            if state in ("running", "background"):
                continue
            if not claim(f"video:{cid}", cid):
                continue
            ts = _epoch(task.get("endedAt") or task.get("startedAt"), now)
            if state == "replied":
                attention.append({
                    "id": f"video:{cid}",
                    "bucket": "attention",
                    "kind": "video",
                    "source": "web",
                    "title": task.get("title") or "视频任务",
                    "status": "waiting",
                    "status_label": "已回复 · 待确认",
                    "summary": _clip(task.get("now") or "已回复但尚未出成片，可能需要确认"),
                    "href": f"/c/{cid}",
                    "chat_id": cid,
                    "timestamp": ts,
                    "recovery": "continue",
                })
            else:
                is_done = state == "done"
                status = "done" if is_done else ("stopped" if state == "stopped" else "failed")
                label = "成片已就绪" if is_done else ("已停止" if state == "stopped" else "制作失败")
                recovery = None if is_done else ("continue" if state == "stopped" else "restart")
                ended.append({
                    "id": f"video:{cid}",
                    "bucket": "ended",
                    "kind": "video",
                    "source": "web",
                    "title": task.get("title") or "视频任务",
                    "status": status,
                    "status_label": label,
                    "summary": _clip(task.get("now") or task.get("error") or ""),
                    "href": f"/workspace/videos?task={cid}" if is_done else f"/c/{cid}",
                    "chat_id": cid,
                    "timestamp": ts,
                    "recovery": recovery,
                })
    except Exception:
        log.debug("task_inbox: video_tasks failed", exc_info=True)

    # 7. Recent 精答 & 讨论台
    try:
        from open_webui.models.chats import Chats

        for meta_key, kind, path_prefix, default_title in (
            ("answer_desk", "answer", "/answer/", "精答"),
            ("discussion_room", "discuss", "/discuss/", "讨论"),
        ):
            rows, _ = Chats.page_chats_with_meta_key(user_id, meta_key, limit=12)
            for row in rows:
                cid = row["id"]
                ts = _epoch(row.get("updated_at") or row.get("created_at"))
                if ts < since:
                    continue
                if not claim(f"{kind}:{cid}", cid):
                    continue
                meta_val = (row.get("meta") or {}).get(meta_key) or {}
                raw_status = str(meta_val.get("status") or "done").lower()
                if raw_status in ("routing", "researching", "answering", "running", "concluding"):
                    # Not in live map → interrupted by restart
                    status, label, recovery = "failed", "已中断", "continue"
                elif raw_status == "done":
                    status, label, recovery = "done", "已完成", None
                elif raw_status == "stopped":
                    status, label, recovery = "stopped", "已停止", "continue"
                else:
                    status, label, recovery = "failed", "未完成", "continue"
                title = row.get("title")
                if not title or title in PLACEHOLDER_TITLES:
                    title = _clip(meta_val.get("question"), 48) or default_title
                assistant = meta_val.get("assistant")
                if isinstance(assistant, dict):
                    assistant_text = " ".join(
                        p
                        for p in (
                            str(assistant.get("emoji") or "").strip(),
                            str(assistant.get("name") or "").strip(),
                        )
                        if p
                    )
                else:
                    assistant_text = str(assistant or "").strip()
                ended.append({
                    "id": f"{kind}:{cid}",
                    "bucket": "ended",
                    "kind": kind,
                    "source": "web",
                    "title": title,
                    "status": status,
                    "status_label": label,
                    "summary": _clip(assistant_text or meta_val.get("preview") or ""),
                    "href": f"{path_prefix}{cid}",
                    "chat_id": cid,
                    "timestamp": ts,
                    "recovery": recovery,
                })
    except Exception:
        log.debug("task_inbox: answer/discuss failed", exc_info=True)

    # 8. Recent failed/interrupted 自动分流
    try:
        from open_webui.models.auto_routes import AutoRoutes

        for route in AutoRoutes.page(user_id, limit=10):
            ts = _epoch(route.get("updated_at") or route.get("created_at"))
            if ts < since:
                continue
            rstatus = str(route.get("status") or "")
            if rstatus not in ("error", "interrupted", "cancelled"):
                continue
            rid = route["id"]
            if not claim(f"auto:{rid}"):
                continue
            data = route.get("data") or {}
            question = _clip((data.get("input") or {}).get("question"), 60)
            origin = data.get("origin") or {}
            origin_cid = origin.get("chatId")
            ended.append({
                "id": f"auto:{rid}",
                "bucket": "ended",
                "kind": "auto",
                "source": "web",
                "title": question or "自动分流",
                "status": "failed" if rstatus != "cancelled" else "stopped",
                "status_label": "已取消" if rstatus == "cancelled" else "分流失败",
                "summary": _clip(data.get("error") or ""),
                "href": f"/c/{origin_cid}" if origin_cid else f"/auto?request={rid}",
                "chat_id": origin_cid,
                "timestamp": ts,
                "recovery": "restart",
            })
    except Exception:
        log.debug("task_inbox: auto_routes failed", exc_info=True)

    return attention, running, ended, active_run_ids


def _resolve_runner_title(run: dict, runs_by_id: dict[str, dict]) -> str:
    """Walk parent_run upwards when a resumed run's prompt is a bare continuation like '继续'."""
    cur: Optional[dict] = run
    visited: set[str] = set()
    first_raw = str(run.get("title") or "").strip()
    for _ in range(16):
        if cur is None:
            break
        rid = str(cur.get("run_id") or "").strip()
        if rid in visited:
            break
        if rid:
            visited.add(rid)
        raw = str(cur.get("title") or "").strip()
        normalized = raw.lower().strip("。.!！,， ")
        if raw and normalized not in _GENERIC_CONTINUATION_TITLES:
            return _clip(raw, 64)
        parent_id = str(cur.get("parent_run") or "").strip()
        cur = runs_by_id.get(parent_id) if parent_id else None
    agent = str(run.get("agent") or "runner")
    return _clip(first_raw or run.get("project") or f"{agent} 任务", 64)


def _load_dismissed(user_id: str, now: float) -> dict[str, float]:
    """Read this user's dismissed inbox item timestamps from ``user.info``."""
    try:
        from open_webui.models.users import Users

        user = Users.get_user_by_id(user_id)
        info = user.info if user and isinstance(user.info, dict) else {}
        raw = info.get(DISMISSED_INFO_KEY)
        if not isinstance(raw, dict):
            return {}
        cutoff = now - DISMISSED_TTL_SECONDS
        out: dict[str, float] = {}
        for k, v in raw.items():
            ts = _epoch(v, 0.0)
            if isinstance(k, str) and k and ts >= cutoff:
                out[k] = ts
        return out
    except Exception:
        log.debug("task_inbox: _load_dismissed failed", exc_info=True)
        return {}


def _save_dismissed(user_id: str, keys: list[str], now: float) -> None:
    """Persist dismissed item IDs into ``user.info`` (pruned & bounded)."""
    clean_keys = [str(k).strip() for k in keys if str(k or "").strip()]
    if not clean_keys:
        return
    try:
        from open_webui.models.users import Users

        current = _load_dismissed(user_id, now)
        for k in clean_keys:
            current[k] = now
        if len(current) > DISMISSED_MAX_ITEMS:
            newest = sorted(current.items(), key=lambda kv: kv[1], reverse=True)[:DISMISSED_MAX_ITEMS]
            current = dict(newest)
        Users.patch_user_info_by_id(user_id, {DISMISSED_INFO_KEY: current})
    except Exception:
        log.debug("task_inbox: _save_dismissed failed", exc_info=True)


def _is_dismissed(item: dict, dismissed: dict[str, float]) -> bool:
    if not dismissed:
        return False
    item_id = str(item.get("id") or "")
    candidates = [item_id]
    run_id = str(item.get("run_id") or "").strip()
    if run_id:
        candidates.extend([f"runner:{run_id}", f"runner-stat:{run_id}"])
    dismissed_at = 0.0
    matched_key = ""
    for key in candidates:
        if key in dismissed and dismissed[key] > dismissed_at:
            dismissed_at = dismissed[key]
            matched_key = key
    if not matched_key:
        return False
    prefix = matched_key.partition(":")[0]
    if prefix in _CHAT_KEYED_PREFIXES:
        item_ts = _epoch(item.get("timestamp"), 0.0)
        return item_ts <= dismissed_at + 2.0
    return True


async def _collect_upstream_hermes(
    request, user, days: int, since: float, now: float, active_run_ids: set[str], seen_chat_ids: set[str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch cross-channel Telegram/QQ sessions and (for admins) runner runs from Hermes.

    Non-fatal: returns empty lists if the user has no Hermes model or Hermes times out.
    """
    from open_webui.utils import hermes_jobs
    from open_webui.utils.hermes_sessions import list_sessions

    attention: list[dict] = []
    running: list[dict] = []
    ended: list[dict] = []

    async def safe_sessions(src: str) -> list[dict]:
        try:
            page = await list_sessions(request, user, source=src, limit=12, offset=0)
            return page.get("sessions") or []
        except Exception:
            return []

    async def safe_runner_stats() -> list[dict]:
        if getattr(user, "role", None) != "admin":
            return []
        try:
            res = await hermes_jobs.runner_stats(request, user, days=days)
            return res.get("runs") or []
        except Exception:
            return []

    try:
        tg_sessions, qq_sessions, runner_runs = await asyncio.wait_for(
            asyncio.gather(
                safe_sessions("telegram"),
                safe_sessions("qqbot"),
                safe_runner_stats(),
            ),
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )
    except Exception:
        log.debug("task_inbox: upstream hermes timed out or failed", exc_info=True)
        return [], [], []

    # Build parent_run chain index across ALL returned runner_runs before filtering:
    # if a run (e.g. status="question") already has a child run with parent_run == rid,
    # the user already answered / continued it and only the latest run in the chain represents it.
    runs_by_id: dict[str, dict] = {}
    superseded_ids: set[str] = set()
    for r in runner_runs:
        rid = str(r.get("run_id") or "").strip()
        if rid:
            runs_by_id[rid] = r
        parent = str(r.get("parent_run") or "").strip()
        if parent:
            superseded_ids.add(parent)

    # Cross-channel runner runs (Telegram / QQ / CLI / web questions)
    for r in runner_runs:
        rid = str(r.get("run_id") or "").strip()
        if not rid or rid in active_run_ids or rid in superseded_ids:
            continue
        source = _normalize_source(r.get("origin"))
        status = str(r.get("status") or "").lower()
        started = _epoch(r.get("started_at"))
        has_ended = r.get("ended_at") not in (None, "")
        ended_at = _epoch(r.get("ended_at"), started)
        if max(started, ended_at) < since:
            continue
        agent = str(r.get("agent") or "runner")
        title = _resolve_runner_title(r, runs_by_id)
        project = str(r.get("project") or "").strip()

        if status == "question":
            attention.append({
                "id": f"runner-stat:{rid}",
                "bucket": "attention",
                "kind": "runner",
                "source": source,
                "title": title,
                "status": "question",
                "status_label": "等你回答",
                "summary": " · ".join(p for p in (agent, project, "任务在等你决定") if p),
                "href": None,
                "run_id": rid,
                "agent": agent,
                "timestamp": ended_at or started,
                "recovery": "continue",
            })
        elif status == "running" and not has_ended and (not started or now - started <= STALE_RUNNER_SECONDS):
            running.append({
                "id": f"runner-stat:{rid}",
                "bucket": "running",
                "kind": "runner",
                "source": source,
                "title": title,
                "status": "running",
                "status_label": f"{agent}运行中",
                "summary": " · ".join(p for p in (project, f"{r['turns']} 轮" if r.get("turns") else "") if p),
                "href": None,
                "run_id": rid,
                "agent": agent,
                "timestamp": started,
            })
        elif source != "web":
            # Show recent non-web runner results (e.g. Telegram/QQ/CLI runs) so user can find them on web
            ok = status in ("ok", "success", "completed", "done")
            stopped = status in ("stopped", "cancelled")
            stale_running = status == "running"
            ended.append({
                "id": f"runner-stat:{rid}",
                "bucket": "ended",
                "kind": "runner",
                "source": source,
                "title": title,
                "status": "done" if ok else ("stopped" if stopped else "failed"),
                "status_label": (
                    "已完成"
                    if ok
                    else ("已停止" if stopped else ("已中断" if stale_running else "执行失败"))
                ),
                "summary": " · ".join(
                    p
                    for p in (
                        agent,
                        project,
                        str(r.get("failure_kind") or "").strip() if not ok and not stopped else "",
                    )
                    if p
                ),
                "href": None,
                "run_id": rid,
                "agent": agent,
                "timestamp": ended_at or started,
                "recovery": None if ok else ("continue" if (stopped or stale_running) else "restart"),
            })

    # Recent Telegram / QQ sessions (clickable to import & open directly in web!)
    for session in (*tg_sessions, *qq_sessions):
        sid = str(session.get("id") or "")
        if not sid or sid in seen_chat_ids:
            continue
        ts = _epoch(session.get("last_active") or session.get("started_at"))
        if ts < since:
            continue
        src = _normalize_source(session.get("source"))
        imported = bool(session.get("imported"))
        title = _clip(session.get("title") or session.get("preview") or sid, 64)
        preview = _clip(session.get("preview"), 90) if session.get("title") else ""
        msg_count = int(session.get("message_count") or 0)
        summary_parts = [f"{msg_count} 条消息" if msg_count else "", preview]
        ended.append({
            "id": f"session:{sid}",
            "bucket": "ended",
            "kind": "session",
            "source": src,
            "title": title,
            "status": "done",
            "status_label": "已导入" if imported else "点开导入",
            "summary": " · ".join(p for p in summary_parts if p),
            "href": f"/c/{sid}" if imported else None,
            "chat_id": sid if imported else None,
            "session_id": sid,
            "imported": imported,
            "timestamp": ts,
        })

    return attention, running, ended


async def remove_inbox_item(
    request,
    user,
    *,
    item_id: str,
    kind: Optional[str] = None,
    chat_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    """Stop (when owned & live) and dismiss a task inbox item so unwanted running / pending tasks
    can be cleaned up directly from the page without deleting chat history."""
    item_id = str(item_id or "").strip()
    prefix, sep, target = item_id.partition(":")
    if not sep or not prefix or not target:
        raise ValueError("invalid task inbox item id")

    stopped = False
    dismiss_keys: list[str] = [item_id]

    if prefix in ("runner", "runner-stat"):
        rid = str(run_id or target).strip()
        if rid:
            dismiss_keys.extend([f"runner:{rid}", f"runner-stat:{rid}"])
            try:
                from open_webui.utils.hermes_runner_progress import (
                    clear_runner_progress,
                    get_runner_progress,
                )
                from open_webui.utils.hermes_sessions import stop_background_runner

                entry = get_runner_progress(rid)
                if entry and entry.get("user_id") == user.id:
                    try:
                        await stop_background_runner(request, user, rid)
                        stopped = True
                    except Exception:
                        log.debug("task_inbox: stop_background_runner failed for %s", rid, exc_info=True)
                    clear_runner_progress(rid)
                    stopped = True
            except Exception:
                log.debug("task_inbox: runner cleanup failed for %s", rid, exc_info=True)

    elif prefix == "hermes":
        cid = str(chat_id or target).strip()
        if cid:
            dismiss_keys.extend([f"hermes:{cid}", f"chat:{cid}"])
            try:
                from open_webui.models.chats import Chats
                from open_webui.tasks import list_task_ids_by_chat_id, stop_task
                from open_webui.utils.hermes_agent import list_active_runs

                owns = bool(Chats.get_chat_by_id_and_user_id(cid, user.id)) or any(
                    r.get("chat_id") == cid for r in list_active_runs(user.id)
                )
                if owns:
                    for tid in list_task_ids_by_chat_id(cid):
                        try:
                            await stop_task(tid)
                            stopped = True
                        except Exception:
                            pass
            except Exception:
                log.debug("task_inbox: hermes stop failed for %s", cid, exc_info=True)

    elif prefix == "video":
        cid = str(chat_id or target).strip()
        if cid:
            try:
                from open_webui.utils import video_tasks

                task = video_tasks.get_task(user.id, cid)
                if task and task.get("state") in ("running", "background"):
                    await video_tasks.stop(request, user, cid)
                    stopped = True
            except Exception:
                log.debug("task_inbox: video stop failed for %s", cid, exc_info=True)

    elif prefix == "team":
        try:
            from open_webui.models.agent_teams import AgentTeams

            team = AgentTeams.get(target)
            if team and team.user_id == user.id:
                if team.status in ("planning", "plan_ready", "plan_failed", "start_failed"):
                    updated = AgentTeams.update(
                        team.id,
                        user.id,
                        expect_status=("planning", "plan_ready", "plan_failed", "start_failed"),
                        status="cancelled",
                    )
                    stopped = updated is not None
                elif team.status in ("running", "starting") and team.phase not in ("completed", "stopped"):
                    try:
                        from open_webui.utils.agent_teams import hermes_call, hermes_target

                        cfg = await hermes_target(request, user)
                        await hermes_call(
                            cfg,
                            "POST",
                            f"/{team.id}/control",
                            json_body={"action": "stop", "actor": getattr(user, "name", "") or ""},
                        )
                    except Exception:
                        log.debug("task_inbox: team hermes stop failed for %s", team.id, exc_info=True)
                    AgentTeams.update(
                        team.id,
                        user.id,
                        phase="stopped",
                        finished_at=team.finished_at or int(time.time()),
                    )
                    stopped = True
        except Exception:
            log.debug("task_inbox: team stop failed for %s", target, exc_info=True)

    elif prefix in ("answer", "discuss"):
        cid = str(chat_id or target).strip()
        if cid:
            try:
                from open_webui.models.chats import Chats
                from open_webui.utils import answer_desk, discussion_room
                from open_webui.utils.mode_illustrate import DRAWING

                if Chats.get_chat_by_id_and_user_id(cid, user.id):
                    mod = answer_desk if prefix == "answer" else discussion_room
                    stopped = bool(await mod.stop_live(cid))
                    drawing = DRAWING.get(cid)
                    if drawing and drawing.get("user_id") == user.id and drawing.get("kind") == prefix:
                        DRAWING.pop(cid, None)
                        stopped = True
            except Exception:
                log.debug("task_inbox: %s stop failed for %s", prefix, cid, exc_info=True)

    elif prefix == "auto":
        try:
            from open_webui.models.auto_routes import AutoRoutes

            row = AutoRoutes.update(target, user.id, expect=("routing",), status="cancelled")
            stopped = row is not None
        except Exception:
            log.debug("task_inbox: auto cancel failed for %s", target, exc_info=True)

    elif prefix in ("chat", "image"):
        cid = str(chat_id or (target if prefix == "chat" else "")).strip()
        if cid:
            try:
                from open_webui.models.chats import Chats
                from open_webui.tasks import list_task_ids_by_chat_id, stop_task

                if Chats.get_chat_by_id_and_user_id(cid, user.id):
                    for tid in list_task_ids_by_chat_id(cid):
                        try:
                            await stop_task(tid)
                            stopped = True
                        except Exception:
                            pass
            except Exception:
                log.debug("task_inbox: %s stop failed for %s", prefix, cid, exc_info=True)

    # Save dismissal timestamp AFTER stop actions so any newly recorded finished_at / stoppedAt
    # is <= dismissed_at.
    _save_dismissed(user.id, list(dict.fromkeys(dismiss_keys)), time.time())
    return {
        "status": True,
        "id": item_id,
        "stopped": stopped,
        "dismissed": True,
        "cross_channel": prefix == "runner-stat" and not stopped,
    }


async def get_task_inbox(request, user, days: int = DEFAULT_DAYS) -> dict:
    """Return the user's unified Task Inbox grouped into attention / running / ended."""
    days = max(1, min(int(days), MAX_DAYS))
    now = time.time()
    since = now - days * 86400

    attention, running, ended, active_run_ids = _collect_local(user.id, days, now)
    seen_chat_ids = {
        item["chat_id"]
        for item in (*attention, *running, *ended)
        if item.get("chat_id")
    }

    up_att, up_run, up_end = await _collect_upstream_hermes(
        request, user, days, since, now, active_run_ids, seen_chat_ids
    )
    attention.extend(up_att)
    running.extend(up_run)
    ended.extend(up_end)

    dismissed = _load_dismissed(user.id, now)
    if dismissed:
        attention = [item for item in attention if not _is_dismissed(item, dismissed)]
        running = [item for item in running if not _is_dismissed(item, dismissed)]
        ended = [item for item in ended if not _is_dismissed(item, dismissed)]

    # Sort: attention & running newest first; ended has unread first, then newest first
    attention.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    running.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    ended.sort(
        key=lambda item: (1 if item.get("unread") else 0, item.get("timestamp") or 0),
        reverse=True,
    )
    ended = ended[:MAX_ENDED_ITEMS]

    return {
        "days": days,
        "attention": attention,
        "running": running,
        "ended": ended,
        "counts": {
            "attention": len(attention),
            "running": len(running),
            "ended": len(ended),
        },
    }
