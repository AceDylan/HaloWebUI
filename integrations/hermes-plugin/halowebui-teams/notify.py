"""Telegram notices for teams: what the user should hear about without having the page open.

* plan ready / plan failed — teams started from Telegram (HaloWebUI hands the plan over through
  ``POST /v1/halo-teams/notify``), with buttons to approve or cancel; a reply re-plans with it.
* a member asks something (runner QUESTION, a Hermes member blocked for input) — a reply answers.
* a task failed or is blocked — retry button; a reply is a note for the member, then a retry.
* the team finished — with the start of the lead's conclusion (waits for it a few minutes).

Where: the chat a team was started from, else (``notify_web_teams``) the owner's linked private
chat. Nothing is sent while the team's page is open in front of the user (HaloWebUI polls its
events with ``visible=1`` every few seconds): the page shows it, and the notice counts as given.
What was announced is kept in the team record (``notified``), so a gateway restart neither
repeats old notices nor loses the next ones; the first look at a team only records where it
stands (no flood of old news when this starts).
"""

from __future__ import annotations

import html
import re
import threading
import time
from typing import Any, Optional

from . import link
from .common import logger, now, read_team, update_team

SEEN_WINDOW = 25            # seconds a visible poll of the team's page counts as "watching"
DONE_WAIT = 6 * 60          # how long the done notice waits for the conclusion
RECENT = 6 * 3600           # finished teams older than this are not looked at
NOTIFIED_KEEP = 200
TG_LIMIT = 3800
DIAGNOSIS_WAIT = 120        # a failure notice waits this long for the lead's diagnosis
ACCEPTANCE_WAIT = 180       # the done notice waits this long for the lead's acceptance check

_seen: dict[str, float] = {}
_seen_lock = threading.Lock()


def mark_seen(team_id: str) -> None:
    with _seen_lock:
        _seen[team_id] = time.time()


def watching(team_id: str) -> bool:
    with _seen_lock:
        return time.time() - _seen.get(team_id, 0) < SEEN_WINDOW


def _own_telegram_origin(origin: Any, owner: Any) -> bool:
    """A Telegram chat started by the Telegram user linked to this owner (nobody else's chat)."""
    return (isinstance(origin, dict) and origin.get("platform") == "telegram" and bool(origin.get("chat_id"))
            and bool(owner) and link.owner_for_telegram(origin.get("user_id")) == str(owner))


def target_for(team: dict) -> Optional[dict]:
    """Where this team's notices go: {"chat_id", "thread_id"?} or None."""
    origin = team.get("origin") if isinstance(team.get("origin"), dict) else {}
    if _own_telegram_origin(origin, team.get("owner")):
        out = {"chat_id": str(origin["chat_id"])}
        if origin.get("thread_id"):
            out["thread_id"] = str(origin["thread_id"])
        return out
    if link.notify_web_teams():
        chat = link.telegram_chat_for(team.get("owner"))
        if chat:
            return {"chat_id": chat}
    return None


# --- formatting ----------------------------------------------------------------------------------

def esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def clip(text: Any, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_MD_RULES = (
    (re.compile(r"```[^\n]*\n?"), ""),
    (re.compile(r"^#{1,6}\s*", re.M), ""),
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"(?<!\w)[*_](\S.*?\S|\S)[*_](?!\w)"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"[图：\1]"),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^\s*[-*+]\s+", re.M), "• "),
    (re.compile(r"^\s*>\s?", re.M), ""),
    (re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.M), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
)


def plain(markdown: str) -> str:
    """Markdown → readable plain text for a chat message (tables keep their cells)."""
    text = str(markdown or "")
    for pattern, repl in _MD_RULES:
        text = pattern.sub(repl, text)
    text = re.sub(r"^\|(.*)\|\s*$", lambda m: " · ".join(c.strip() for c in m.group(1).split("|") if c.strip()),
                  text, flags=re.M)
    return text.strip()


def duration(seconds: Any) -> str:
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60} 分钟" if minutes % 60 else f"{minutes // 60} 小时"


RUNNER_LABEL = {"hermes": "Hermes", "reclaude": "reclaude", "cchclaude": "cchclaude", "anyclaude": "anyclaude",
                "codex": "codex", "agy": "agy"}


def _open_row(team_id: str, label: str = "🌐 在网页看", suffix: str = "") -> list:
    url = link.team_url(team_id, suffix)
    return [(label, "url:" + url)] if url else []


def plan_message(team: dict, *, started: bool = False) -> tuple[str, list]:
    """The plan card: who does what, in which order; approve / cancel. ``started``: the plan was
    approved on its own (「直接开始」) — the same card as a notice, without the buttons."""
    plan = team.get("plan") or {}
    team_id = team["id"]
    members = [m for m in plan.get("members") or [] if isinstance(m, dict)]
    tasks = [t for t in plan.get("tasks") or [] if isinstance(t, dict)]
    head = "已直接开始" if started else "计划好了"
    lines = [f"{'🚀' if started else '🧭'} <b>{esc(clip(team.get('title') or plan.get('title'), 60))}</b> · {head}"]
    if team.get("status") == "start_failed" and team.get("error"):
        lines.append(f"⚠️ 没能直接开始：{esc(clip(team['error'], 300))}。看过计划后可以手动批准。")
    if plan.get("summary"):
        lines.append(esc(clip(plan["summary"], 300)))
    project = plan.get("project") if isinstance(plan.get("project"), dict) else None
    if project and project.get("path"):
        lines.append("")
        lines.append(f"📁 在项目 <b>{esc(project.get('name'))}</b> 里做：团队开自己的分支，不碰你的工作区；"
                     "合并、推送由你在协作台决定" + ("（目标里点名了它）" if project.get("auto") else ""))
    lines.append("")
    lines.append(f"<b>成员 {len(members)} 位</b>")
    for m in members[:8]:
        runner = m.get("runner") or m.get("executor") or "hermes"
        note = f"（{esc(clip(m.get('runner_note'), 60))}）" if m.get("runner_note") else ""
        model = f" · {esc(m['model'])}" if runner == "hermes" and m.get("model") else ""
        lines.append(f"• {esc(m.get('name'))} · {esc(clip(m.get('role'), 24))} · {esc(RUNNER_LABEL.get(runner, runner))}{model}{note}")
    lines.append("")
    lines.append(f"<b>任务 {len(tasks)} 个</b>（最多同时 {plan.get('max_parallel') or 2} 个）")
    keys = {t.get("key"): i for i, t in enumerate(tasks, 1)}
    for i, t in enumerate(tasks[:12], 1):
        deps = [str(keys[d]) for d in t.get("depends_on") or [] if d in keys]
        wait = f"（等 {'、'.join(deps)}）" if deps else ""
        lines.append(f"{i}. {esc(clip(t.get('title'), 40))} — {esc(t.get('member'))}{wait}")
    if len(tasks) > 12:
        lines.append(f"… 还有 {len(tasks) - 12} 个")
    lead = (plan.get("lead_model") or {}).get("model") if isinstance(plan.get("lead_model"), dict) else ""
    if lead:
        lines.append("")
        lines.append(f"负责人模型：{esc(lead)}")
    lines.append("")
    if started:
        lines.append("<i>成员已经开始干活，完成或需要你时我会告诉你；回复完成通知可以对负责人说要改什么。</i>")
        row = _open_row(team_id, "🌐 看工作台")
        return clip("\n".join(lines), TG_LIMIT), [row] if row else []
    lines.append("<i>回复这条消息写修改意见，负责人会按意见重新规划。</i>")
    buttons = [[("✅ 批准并开始", f"cb:ap:{team_id}"), ("✖ 取消", f"cb:cx:{team_id}")]]
    row = _open_row(team_id)
    if row:
        buttons.append(row)
    return clip("\n".join(lines), TG_LIMIT), buttons


def plan_failed_message(team: dict) -> tuple[str, list]:
    team_id = team["id"]
    text = (f"⚠️ <b>{esc(clip(team.get('title'), 60))}</b> · 负责人没做出计划\n"
            f"{esc(clip(team.get('error') or '原因未知', 600))}\n\n"
            "<i>回复这条消息补充要求，会按它重新规划。</i>")
    buttons = [[("🔄 重新规划", f"cb:rp:{team_id}"), ("✖ 取消", f"cb:cx:{team_id}")]]
    row = _open_row(team_id)
    if row:
        buttons.append(row)
    return text, buttons


def _member_role(team: dict, name: str) -> str:
    for m in team.get("members") or []:
        if m.get("name") == name:
            return m.get("role") or ""
    return ""


def ask_message(team: dict, task: dict) -> tuple[str, list]:
    run = task.get("current_run") or {}
    question = run.get("question") or task.get("block_reason") or "（没有写问题内容，去网页看日志）"
    role = _member_role(team, task.get("member"))
    who = f"{esc(task.get('member'))}{f'（{esc(role)}）' if role else ''}"
    text = (f"❓ <b>{esc(clip(team.get('title'), 60))}</b>\n"
            f"{who} 在任务「{esc(clip(task.get('title'), 40))}」里问你：\n\n"
            f"{esc(clip(plain(question), 2500))}")
    lead_line, lead_buttons = _diagnosis_lines(team, task)
    text += lead_line + "\n\n<i>直接回复这条消息就是回答它。</i>"
    buttons = [lead_buttons] if lead_buttons else []
    row = _open_row(team["team_id"])
    if row:
        buttons.append(row)
    return text, buttons


def _diagnosis_lines(team: dict, task: dict) -> tuple[str, list]:
    """The lead's take on a stopped task, for a notice: text and the 「按建议处理」 button."""
    diagnosis = task.get("diagnosis") or {}
    if diagnosis.get("status") != "ready":
        return "", []
    text = f"\n\n🩺 <b>负责人判断</b>：{esc(clip(diagnosis.get('cause'), 400))}"
    action = diagnosis.get("action")
    if action == "ask_user":
        return text + f"\n❓ 需要你决定：{esc(clip(diagnosis.get('note'), 600))}", []
    detail = {"retry_with_note": f"带说明重试——「{esc(clip(diagnosis.get('note'), 400))}」",
              "switch_runner": f"换成 {esc(diagnosis.get('runner'))} 重试",
              "skip": "跳过这个任务，后面的任务照常开始", "retry": "原样重试"}.get(action, "")
    return text + f"\n💡 建议：{detail}", [("✅ 按建议处理", f"cb:dx:{team['team_id']}:{task['id']}")]


def fail_message(team: dict, task: dict) -> tuple[str, list]:
    word = "受阻" if task.get("sub_status") == "blocked" else "失败"
    text = (f"⚠️ <b>{esc(clip(team.get('title'), 60))}</b>\n"
            f"{esc(task.get('member'))} 的任务「{esc(clip(task.get('title'), 40))}」{word}：\n"
            f"{esc(clip(plain(task.get('block_reason') or '原因未知'), 800))}")
    lead_line, first = _diagnosis_lines(team, task)
    text += lead_line + "\n\n<i>回复这条消息写补充说明，会带着说明重试。</i>"
    buttons = [[*first, ("🔁 重试", f"cb:rt:{team['team_id']}:{task['id']}")]]
    row = _open_row(team["team_id"])
    if row:
        buttons.append(row)
    return text, buttons


def done_message(team: dict, snap: dict, markdown: str) -> tuple[str, list]:
    tasks = snap.get("tasks") or []
    done = sum(1 for t in tasks if t.get("status") in ("done", "archived"))
    started = team.get("approved_at") or team.get("created_at") or 0
    took = duration((team.get("completed_at") or now()) - started) if started else ""
    head = (f"✅ <b>{esc(clip(team.get('title'), 60))}</b> · 完成\n"
            f"{done}/{len(tasks)} 个任务{' · 用时 ' + took if took else ''}")
    project = team.get("project") or {}
    if project.get("branch"):
        from . import projects

        try:
            change = projects.changes(team)
        except Exception:  # noqa: BLE001 — the notice goes out without the change line
            change = {}
        if change.get("available"):
            head += (f"\n📁 {esc(project.get('name'))} · 分支 <code>{esc(project['branch'])}</code>："
                     f"{len(change.get('files') or [])} 个文件 +{change.get('added', 0)} −{change.get('removed', 0)}，"
                     "还没合并——在工作台「变更」里看差异、合并或推送")
    acceptance = (team.get("conclusion") or {}).get("acceptance") or {}
    check = ""
    if acceptance.get("status") == "ready":
        if acceptance.get("verdict") == "met":
            check = "\n🎯 负责人验收：目标已达成"
        else:
            gaps = acceptance.get("gaps") or []
            check = (f"\n🎯 负责人验收：{esc(clip(acceptance.get('summary'), 200)) or '没有完全达成'}\n"
                     + "\n".join(f"  · {esc(clip(g.get('title'), 40))}：{esc(clip(g.get('detail'), 160))}" for g in gaps[:5]))
    head += check
    body = plain(markdown) if markdown else ""
    if not body:
        body = "\n".join(f"• {t.get('title')}：{plain(t.get('result') or '')[:200]}" for t in tasks[:8])
    tail = "\n\n<i>回复这条消息对负责人说要追加或修改什么。</i>"
    room = TG_LIMIT - len(head) - len(tail) - 80
    text = head + "\n\n" + esc(clip(body, max(400, room))) + tail
    actions = []
    if acceptance.get("status") == "ready" and acceptance.get("gaps"):
        actions.append(("🛠 让团队补上", f"cb:fx:{team['team_id']}"))
    if markdown:
        actions.append(("📚 存入知识库", f"cb:kb:{team['team_id']}"))
    buttons = [actions] if actions else []
    buttons.append([*_open_row(team["team_id"], "📄 阅读结论", "/conclusion"), *_open_row(team["team_id"], "🌐 工作台")])
    return text, [b for b in buttons if b]


def change_message(team: dict, entry: dict) -> tuple[str, list]:
    """The lead's answer to something said from Telegram: its reply and, when there is one, the
    plan change to apply or discard."""
    team_id = team["team_id"]
    title = esc(clip(team.get("title"), 60))
    if entry.get("status") == "failed":
        return (f"⚠️ <b>{title}</b> · 负责人没能给出调整\n{esc(clip(entry.get('error'), 600))}\n\n"
                "<i>回复这条消息再说一次。</i>"), [r for r in [_open_row(team_id)] if r]
    proposal = entry.get("proposal") or {}
    lines = [f"🧭 <b>{title}</b> · 负责人回复", esc(clip(proposal.get("reply"), 1200))]
    if entry.get("status") == "ready":
        lines += ["", "<b>计划变更</b>（应用后才生效）"]
        for m in proposal.get("add_members") or []:
            runner = m.get("runner") or m.get("executor") or "hermes"
            lines.append(f"＋ 成员 {esc(m.get('name'))} · {esc(clip(m.get('role'), 24))} · {esc(RUNNER_LABEL.get(runner, runner))}")
        for t in proposal.get("add_tasks") or []:
            wait = f"（等 {'、'.join(t.get('depends_on') or [])}）" if t.get("depends_on") else ""
            lines.append(f"＋ {esc(t.get('key'))} {esc(clip(t.get('title'), 40))} — {esc(t.get('member'))}{esc(wait)}")
        for t in proposal.get("edit_tasks") or []:
            lines.append(f"✎ {esc(t.get('key'))} {esc(clip(t.get('title'), 40))}：改写说明{'并重试' if t.get('retry') else ''}")
        for t in proposal.get("cancel_tasks") or []:
            lines.append(f"✕ 取消 {esc(t.get('key'))} {esc(clip(t.get('title'), 40))}")
        for note in proposal.get("notes") or []:
            lines.append(f"<i>注意：{esc(clip(note, 200))}</i>")
        if team.get("state") == "completed":
            lines.append("<i>团队已经做完：应用后重新开工，做完会重写结论。</i>")
        lines += ["", "<i>回复这条消息可以让负责人再改。</i>"]
        buttons = [[("✅ 应用变更", f"cb:ca:{team_id}:{entry['id']}"), ("✖ 放弃", f"cb:cd:{team_id}:{entry['id']}")]]
    else:
        lines += ["", "<i>不需要改计划。回复这条消息可以接着说。</i>"]
        buttons = []
    row = _open_row(team_id)
    if row:
        buttons.append(row)
    return clip("\n".join(lines), TG_LIMIT), buttons


def change_notice(team: dict, entry: dict, target: dict) -> Optional[int]:
    from . import tg as telegram

    if not telegram.ready():
        return None
    text, buttons = change_message(team, entry)
    message_id = telegram.send(target["chat_id"], text, buttons, thread_id=target.get("thread_id"))
    if message_id is not None:
        telegram.remember_message(target["chat_id"], message_id, {
            "team": team["team_id"], "kind": "change", "change": entry.get("id"), "owner": team.get("owner"),
            "text": clip(entry.get("text"), 600)})
    return message_id


# --- what is new ---------------------------------------------------------------------------------

def pending(team: dict, snap: dict) -> list[tuple[str, str, Optional[dict]]]:
    """Every notice this team's state calls for now: (key, kind, task). Keys are stable, so a notice
    goes out once per attempt (a retried task that asks again is a new notice)."""
    out = []
    for task in snap.get("tasks") or []:
        sub = task.get("sub_status")
        attempt = task.get("attempts") or 0
        if sub not in ("waiting_user", "failed", "blocked"):
            continue
        # Held back while the lead is still working out what went wrong (a bounded wait).
        diagnosis = ((team.get("diagnoses") or {}).get(task["id"])) or {}
        thinking = (diagnosis.get("status") == "thinking" and int(diagnosis.get("attempt") or -1) == attempt
                    and now() - int(diagnosis.get("started_at") or 0) < DIAGNOSIS_WAIT)
        if thinking:
            continue
        if sub == "waiting_user":
            out.append((f"ask:{task['id']}:{attempt}", "ask", task))
        else:
            out.append((f"fail:{task['id']}:{attempt}", "fail", task))
    if (snap.get("team") or {}).get("phase") == "completed":
        entry = team.get("conclusion") or {}
        waited = now() - int(team.get("completed_at") or now())
        checking = ((entry.get("acceptance") or {}).get("status") == "checking"
                    and now() - int((entry.get("acceptance") or {}).get("started_at") or 0) < ACCEPTANCE_WAIT)
        if (entry.get("status") in ("ready", "failed") and not checking) or waited >= DONE_WAIT:
            rounds = int(team.get("round") or 0)
            out.append(("done" if not rounds else f"done:{rounds}", "done", None))
    return out


def _conclusion_markdown(team: dict) -> str:
    from . import conclusion

    if (team.get("conclusion") or {}).get("status") != "ready":
        return ""
    path = conclusion.conclusion_path(team)
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path is not None and path.exists() else ""
    except OSError:
        return ""


def _remember(slug: str, keys: list[str]) -> None:
    def apply(rec: dict) -> None:
        known = [k for k in rec.get("notified") or [] if k not in keys]
        rec["notified"] = (known + keys)[-NOTIFIED_KEEP:]

    update_team(slug, apply)


def tick_board(slug: str, team: dict) -> None:
    """One look at one team board (from the bridge loop in the gateway)."""
    from . import tg as telegram

    if not telegram.ready():
        return
    state = team.get("state")
    if state not in ("running", "paused", "completed"):
        return
    if state == "completed" and now() - int(team.get("completed_at") or 0) > RECENT:
        return
    target = target_for(team)
    if target is None:
        return
    from .teams import snapshot

    snap = snapshot(team["team_id"])
    team = read_team(slug) or team  # the snapshot may just have marked it completed
    found = pending(team, snap)
    if "notified" not in team:
        _remember(slug, [key for key, _kind, _task in found])
        return
    known = set(team.get("notified") or [])
    new = [(key, kind, task) for key, kind, task in found if key not in known]
    if not new:
        return
    if watching(team["team_id"]):
        _remember(slug, [key for key, _kind, _task in new])
        return
    sent = []
    for key, kind, task in new:
        if kind == "ask":
            text, buttons = ask_message(team, task)
        elif kind == "fail":
            text, buttons = fail_message(team, task)
        else:
            text, buttons = done_message(team, snap, _conclusion_markdown(team))
        message_id = telegram.send(target["chat_id"], text, buttons, thread_id=target.get("thread_id"))
        if message_id is None:
            logger.warning("halowebui-teams: Telegram notice %s for %s not sent; will retry", key, slug)
            break
        telegram.remember_message(target["chat_id"], message_id, {
            "team": team["team_id"], "kind": kind, "task": (task or {}).get("id"), "owner": team.get("owner"),
            "member": (task or {}).get("member")})
        sent.append(key)
    if sent:
        _remember(slug, sent)


def plan_notice(owner: str, event: str, team: dict, origin: dict) -> dict:
    """HaloWebUI's hand-over of a plan for a team started from Telegram (POST /notify)."""
    from . import tg as telegram

    if not _own_telegram_origin(origin, owner):
        return {"sent": False, "reason": "not a Telegram team of this owner"}
    if not telegram.ready():
        return {"sent": False, "reason": "Telegram is not connected"}
    if not isinstance(team, dict) or not team.get("id"):
        return {"sent": False, "reason": "no team"}
    if event in ("plan_ready", "start_failed"):
        text, buttons = plan_message(team)
        kind = "plan"
    elif event == "running":  # 「直接开始」: approved on its own
        text, buttons = plan_message(team, started=True)
        kind = "started"
    elif event == "plan_failed":
        text, buttons = plan_failed_message(team)
        kind = "plan_failed"
    else:
        return {"sent": False, "reason": f"unknown event {event}"}
    chat = str(origin["chat_id"])
    message_id = telegram.send(chat, text, buttons, thread_id=origin.get("thread_id"))
    if message_id is None:
        return {"sent": False, "reason": "send failed"}
    telegram.remember_message(chat, message_id, {"team": team["id"], "kind": kind, "owner": owner})
    return {"sent": True, "message_id": message_id}
