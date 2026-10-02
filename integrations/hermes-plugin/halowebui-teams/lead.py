"""The lead stays with the team after the plan is approved.

* **对负责人说** (``request_change`` → ``apply_change`` / ``discard_change``): the user tells the
  lead something while the team works — or after it finished. The lead reads where the team
  stands (members, every task's state, results so far) and answers with a reply and, when the
  request calls for it, a *plan change*: new members, new tasks (which may build on finished
  ones), cancelling or rewriting tasks that have not started, rewriting a failed task (it is
  retried with the new description). Nothing on the board changes until the user applies it.
  A finished team that gets new work runs again; its conclusion is rewritten when it finishes.
* **Failure diagnosis** (``tick_board`` → ``apply_diagnosis``): when a task fails or is blocked,
  the lead reads the reason, the log tail and the task and suggests one action — retry, retry
  with a note for the member, another runner, skip the task, or a question for the user. One
  click applies it.
* **Acceptance** (``check_acceptance``, after the conclusion): the lead checks the result against
  the goal and lists the gaps; 「让团队补上」 turns them into a change request.

Model calls run in background threads (``HALO_TEAMS_LEAD_SYNC=1`` runs them inline, for tests)
on the lead's model (``plan.call_model``). State lives in the team record: ``change`` (the open
request / proposal), ``changes_log``, ``diagnoses`` {task id: entry}, ``conclusion.acceptance``.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from typing import Any, Callable, Optional

from .common import (
    EXECUTOR_ASSIGNEE,
    EXECUTORS,
    LEAD_NAME,
    TEAM_EVENT_TASK,
    append_event,
    board_conn,
    kb,
    kbc,
    logger,
    now,
    read_team,
    redact,
    task_executor,
    update_team,
)

LEAD_NOTE_AUTHOR = "user:" + LEAD_NAME   # a lead's note reaches the member like a user's note
MAX_TOTAL_TASKS = 20
MAX_TOTAL_MEMBERS = 8
MAX_NEW_MEMBERS = 2
CHANGE_STALE = 600            # a 'thinking' change this old lost its thread (gateway restart)
DIAGNOSIS_STALE = 600
CHANGES_LOG_KEEP = 12
REQUEST_MAX_CHARS = 2000
_jobs: dict[str, threading.Thread] = {}
_jobs_lock = threading.Lock()

NOT_STARTED = ("queued", "waiting_deps")
FAILED = ("failed", "blocked")
ACTIONS = ("retry", "retry_with_note", "switch_runner", "skip", "ask_user")
ACTION_LABEL = {"retry": "原样重试", "retry_with_note": "带说明重试", "switch_runner": "换执行器重试",
                "skip": "跳过这个任务", "ask_user": "需要你决定"}


def _spawn(key: str, fn: Callable[[], None]) -> bool:
    """Run *fn* in a background thread unless one for *key* is alive. False when already running."""
    with _jobs_lock:
        if key in _jobs and _jobs[key].is_alive():
            return False
        if os.environ.get("HALO_TEAMS_LEAD_SYNC") == "1":
            _jobs[key] = threading.current_thread()
        else:
            thread = threading.Thread(target=_guarded, args=(key, fn), name=f"halo-lead-{key}", daemon=True)
            _jobs[key] = thread
            thread.start()
            return True
    _guarded(key, fn)
    return True


def _guarded(key: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:
        logger.warning("halowebui-teams: lead job %s failed", key, exc_info=True)
    finally:
        with _jobs_lock:
            _jobs.pop(key, None)


def _alive(key: str) -> bool:
    with _jobs_lock:
        return key in _jobs and _jobs[key].is_alive()


def _lead_model(team: dict) -> Optional[str]:
    lead = team.get("lead_model") if isinstance(team.get("lead_model"), dict) else {}
    return lead.get("requested") or None


def _call(team: dict, messages: list, *, max_tokens: int = 3000, timeout: int = 150) -> tuple[Optional[dict], str, dict, str]:
    """One lead call expecting JSON, one retry when the reply is not JSON: (parsed, error, used, text)."""
    from . import plan

    text = ""
    for _attempt in range(2):
        text, reason, used = plan.call_model(messages, timeout=timeout, max_tokens=max_tokens, temperature=0.2,
                                             preferred=_lead_model(team))
        if text is None:
            return None, reason, used, ""
        parsed = plan.extract_json(text)
        if parsed is not None:
            return parsed, "", used, text
        messages = messages + [{"role": "assistant", "content": text[:4000]},
                               {"role": "user", "content": "只输出约定格式的 JSON 对象，不要其他文字。"}]
    return None, "负责人返回的不是 JSON", used, text or ""


# --- where the team stands (shared by the prompts) ------------------------------------------------

STATE_WORD = {"done": "已完成", "archived": "已移除", "running": "执行中", "review": "执行中", "quota_wait": "执行中（等额度）",
              "waiting_user": "等用户回答", "queued": "未开始（排队）", "waiting_deps": "未开始（等前置任务）",
              "failed": "失败", "blocked": "受阻", "stopped": "已停止"}


def _team_context(team: dict, snap: dict, *, results: int = 500) -> str:
    project = team.get("project") or {}
    where = (f"项目 {project.get('name')}（{project.get('path')}）的团队分支 {project.get('branch')}"
             if project.get("branch") else f"工作目录 {team.get('workspace')}")
    members = "\n".join(
        f"- {m.get('name')}（{m.get('role')}，类型 {m.get('kind') or '—'}，执行 {m.get('runner') or m.get('executor') or '—'}）"
        for m in team.get("members") or [])
    lines = []
    for t in snap.get("tasks") or []:
        deps = "、".join(_key_of(snap, p) for p in t.get("parents") or []) or "无"
        state = STATE_WORD.get(t.get("sub_status") or t.get("status"), t.get("status"))
        line = f"- {t.get('key')} {t.get('title')} · 成员 {t.get('member')} · {state} · 依赖：{deps}"
        if t.get("sub_status") in FAILED and t.get("block_reason"):
            line += f"\n  原因：{redact(t['block_reason'], 200)}"
        if t.get("status") == "done" and t.get("result") and results:
            line += f"\n  结果摘要：{redact(t['result'], results)}"
        lines.append(line)
    phase = (snap.get("team") or {}).get("phase")
    phase_word = {"completed": "全部完成", "paused": "已暂停派发", "attention": "有任务需要处理", "running": "执行中"}.get(phase, phase)
    return (f"协作目标：\n{team.get('goal') or ''}\n\n"
            f"团队：{team.get('title')}（{where}；现在{phase_word}）\n"
            f"当初的分工说明：{team.get('summary') or '（无）'}\n\n成员：\n{members}\n\n任务：\n" + "\n".join(lines))


def _key_of(snap: dict, task_id: str) -> str:
    for t in snap.get("tasks") or []:
        if t.get("id") == task_id:
            return t.get("key") or task_id
    return task_id


# --- 对负责人说: change requests -------------------------------------------------------------------

CHANGE_SYSTEM = """你是协作团队的负责人（team-lead）。团队正在按计划工作（或已经做完），用户对你说了一段话：可能是追加需求、调整分工、取消某项、改某个任务的做法，也可能只是问进展。你根据团队的当前状态给出回答，需要时再给出「计划变更」——用户确认后才会生效。

只输出一个 JSON 对象，不要输出任何其他文字：
{
  "reply": "对用户说的话：你理解的要求和打算怎么改；只是问进展就直接回答（1 到 4 句中文）",
  "add_members": [{"name": "qa-engineer", "role": "测试", "assistant": "模板编号或 null", "kind": "code", "focus": "负责什么"}],
  "add_tasks": [{"key": "N1", "title": "任务名", "description": "完整、可独立执行的说明：做什么、产出写到哪个文件、完成标准", "member": "成员 name", "depends_on": ["T2"]}],
  "cancel_tasks": ["T4"],
  "edit_tasks": [{"key": "T3", "title": "可选的新标题", "description": "新的完整说明"}]
}

规则：
- 不需要改计划时，四个数组都给空数组，只写 reply。不要为了显得积极而加任务。
- 已完成和正在执行的任务不能改、不能取消；要在它们的基础上继续，就追加新任务并依赖它们（结果会交给新任务）。
- 「未开始」的任务可以取消或改说明；「失败 / 受阻」的任务可以改说明（应用后带着新说明重试）或取消。
- 新任务优先交给已有成员；确实需要新角色才加成员（最多再加 {max_new} 个），name 用小写英文和连字符，不能和已有成员重名。
- 新任务的 key 写 N1、N2…（系统会接着现有编号重新编号）；depends_on 可以写已有任务的 key 或新任务的 key，不能有循环。
- 并行的任务不能写同一个文件；不要安排需要用户手动操作、需要密钥或改动生产服务的任务；在项目里工作时不要安排 push、合并到主分支、部署。
- kind 决定由哪种执行器来做：
{kinds}
- 助手模板（编号：名称（类型）— 说明）：
{catalog}"""


def _change_system() -> str:
    from . import assistants, runners

    kinds = "\n".join(f"  - \"{k}\"：{v['label']}（{v['hint']}）" for k, v in runners.KINDS.items())
    return (CHANGE_SYSTEM.replace("{max_new}", str(MAX_NEW_MEMBERS)).replace("{kinds}", kinds)
            .replace("{catalog}", assistants.catalog_text() or "（没有可用的助手模板，assistant 一律填 null）"))


def _public_change(entry: Optional[dict]) -> Optional[dict]:
    if not entry:
        return None
    keep = ("id", "status", "text", "by", "via", "source", "requested_at", "proposal", "model", "error",
            "decided_at", "decided_by", "applied")
    out = {k: entry[k] for k in keep if entry.get(k) not in (None, "")}
    if out.get("status") == "thinking" and now() - int(entry.get("requested_at") or 0) > CHANGE_STALE \
            and not _alive("change:" + str(entry.get("id"))):
        out["status"] = "failed"
        out["error"] = "负责人没有答完（网关重启或超时），再说一次就行"
    return out


def public_state(team: dict) -> dict:
    """What the snapshot carries for the lead: the open change and the latest decisions."""
    return {"change": _public_change(team.get("change")),
            "changes_log": [_public_change(c) for c in (team.get("changes_log") or [])[-5:]]}


def request_change(team_id: str, text: str, *, owner: Optional[str] = None, actor: str = "",
                   via: str = "web", source: str = "user", reply_to: Optional[dict] = None) -> dict:
    """Ask the lead for a change. Returns the change entry (status ``thinking``); the proposal is
    written in the background. A newer request replaces an open proposal."""
    from .teams import TeamError, _require_team

    slug, team = _require_team(team_id, owner)
    text = (text or "").strip()
    if not text:
        raise TeamError(400, "要对负责人说的话不能为空")
    if len(text) > REQUEST_MAX_CHARS:
        raise TeamError(400, f"最多 {REQUEST_MAX_CHARS} 字")
    _check_open(team)
    current = team.get("change") or {}
    if current.get("status") == "thinking" and _alive("change:" + str(current.get("id"))):
        raise TeamError(409, "负责人还在看上一条要求，等它答完再说")
    entry = {"id": uuid.uuid4().hex[:8], "status": "thinking", "text": redact(text, REQUEST_MAX_CHARS, one_line=False),
             "by": redact(actor, 40), "via": via if via in ("web", "telegram") else "web",
             "source": source if source in ("user", "acceptance") else "user", "requested_at": now()}
    if reply_to:
        entry["reply_to"] = {k: str(v)[:64] for k, v in reply_to.items() if k in ("chat_id", "thread_id") and v}

    def mutate(rec: dict) -> None:
        old = rec.get("change")
        if old and old.get("status") in ("ready", "answered", "failed"):
            _archive(rec, {**old, "status": "superseded" if old.get("status") == "ready" else old["status"]})
        rec["change"] = entry

    update_team(slug, mutate)
    with board_conn(slug) as conn:
        append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "change_requested", "change": entry["id"],
                                                          "by": entry["by"], "via": entry["via"],
                                                          "source": entry["source"], "text": redact(text, 300)})
    _spawn("change:" + entry["id"], lambda: _propose(slug, entry["id"]))
    return _public_change((read_team(slug) or {}).get("change")) or entry


def _check_open(team: dict) -> None:
    from .teams import TeamError

    if team.get("state") == "stopped":
        raise TeamError(409, "协作任务已停止，不能再调整")
    if (team.get("project") or {}).get("discarded_at"):
        raise TeamError(409, "团队分支已经放弃，不能再追加工作")


def _archive(rec: dict, entry: dict) -> None:
    rec["changes_log"] = ([*(rec.get("changes_log") or []), entry])[-CHANGES_LOG_KEEP:]


def _set_change(slug: str, change_id: str, **fields: Any) -> Optional[dict]:
    out: dict = {}

    def mutate(rec: dict) -> None:
        entry = rec.get("change") or {}
        if entry.get("id") != change_id:
            return
        entry.update(fields)
        rec["change"] = entry
        out.update(entry)

    update_team(slug, mutate)
    return out or None


def _propose(slug: str, change_id: str) -> None:
    from .teams import snapshot

    team = read_team(slug) or {}
    entry = team.get("change") or {}
    if entry.get("id") != change_id:
        return
    snap = snapshot(team["team_id"])
    messages = [{"role": "system", "content": _change_system()},
                {"role": "user", "content": _team_context(team, snap) + "\n\n用户对你说：\n" + entry["text"]}]
    parsed, error, used, _text = _call(team, messages, max_tokens=4000)
    errors: list[str] = []
    proposal = None
    if parsed is not None:
        proposal, errors = validate_change(team, snap, parsed)
        if proposal is None:
            from . import plan

            retry_messages = messages + [
                {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)[:6000]},
                {"role": "user", "content": "这个变更不能用：" + "；".join(errors) + "。请改正后只输出 JSON。"}]
            text, reason, used2 = plan.call_model(retry_messages, timeout=150, max_tokens=4000, temperature=0.2,
                                                  preferred=_lead_model(team))
            parsed2 = plan.extract_json(text) if text else None
            if parsed2 is not None:
                used = used2 or used
                proposal, errors = validate_change(team, snap, parsed2)
            elif text is None:
                errors.append(reason)
    if proposal is None:
        message = error or ("负责人给出的变更没通过检查：" + "；".join(errors[:6]))
        _set_change(slug, change_id, status="failed", error=redact(message, 600), model=used.get("model") or "",
                    decided_at=now())
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "change_failed", "change": change_id,
                                                              "error": redact(message, 200)})
        _notify_change(slug)
        return
    status = "ready" if _has_changes(proposal) else "answered"
    _set_change(slug, change_id, status=status, proposal=proposal, model=used.get("model") or "",
                **({"decided_at": now()} if status == "answered" else {}))
    with board_conn(slug) as conn:
        append_event(conn, TEAM_EVENT_TASK, "halo_team", {
            "action": "change_proposed" if status == "ready" else "change_answered", "change": change_id,
            "reply": redact(proposal.get("reply"), 300), "summary": change_summary(proposal)})
    _notify_change(slug)


def _has_changes(proposal: dict) -> bool:
    return any(proposal.get(k) for k in ("add_members", "add_tasks", "cancel_tasks", "edit_tasks"))


def change_summary(proposal: dict) -> str:
    parts = []
    if proposal.get("add_members"):
        parts.append("加成员 " + "、".join(m["name"] for m in proposal["add_members"]))
    if proposal.get("add_tasks"):
        parts.append("加任务 " + "、".join(t["key"] for t in proposal["add_tasks"]))
    if proposal.get("edit_tasks"):
        parts.append("改 " + "、".join(t["key"] for t in proposal["edit_tasks"]))
    if proposal.get("cancel_tasks"):
        parts.append("取消 " + "、".join(t["key"] for t in proposal["cancel_tasks"]))
    return "；".join(parts)


def _next_key_number(snap: dict) -> int:
    highest = 0
    for t in snap.get("tasks") or []:
        match = re.match(r"^T(\d+)$", str(t.get("key") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    return list(value) if isinstance(value, list) else []


def validate_change(team: dict, snap: dict, raw: Any) -> tuple[Optional[dict], list[str]]:
    """Normalize the lead's change against the team's current state: ``(proposal, [])`` or
    ``(None, errors)``. Existing tasks are referred to by key; new ones get the next T numbers."""
    from . import assistants, runners
    from .plan import _KEY_RE, _NAME_RE, _clean_text, _find_cycle, infer_kind

    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["变更不是一个 JSON 对象"]
    tasks = [t for t in snap.get("tasks") or [] if t.get("status") != "archived"]
    by_key = {t["key"]: t for t in tasks if t.get("key")}
    existing_members = {m.get("name") for m in team.get("members") or []}

    members: list[dict] = []
    for index, entry in enumerate(_as_list(raw.get("add_members")), 1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 个新成员格式不对")
            continue
        name = str(entry.get("name") or "").strip().lower().replace("_", "-").replace(" ", "-")
        if not _NAME_RE.match(name) or name == LEAD_NAME:
            errors.append(f"新成员名「{name or '(空)'}」不合法（小写英文、数字、连字符）")
            continue
        if name in existing_members or any(m["name"] == name for m in members):
            errors.append(f"成员「{name}」已经在团队里了，直接把任务交给它")
            continue
        template = assistants.resolve(entry.get("assistant"))
        role = _clean_text(entry.get("role"), 40) or (template["name"] if template else name)
        focus = _clean_text(entry.get("focus"), 300)
        executor = str(entry.get("executor") or "").strip().lower()
        members.append({"name": name, "role": role, "focus": focus,
                        "kind": runners.normalize_kind(entry.get("kind")) or (template["kind"] if template else "")
                        or infer_kind(role, focus),
                        "assistant": assistants.public(template),
                        "executor": executor if executor in EXECUTORS else "",
                        "executor_source": "goal" if executor in EXECUTORS else "auto"})
    if len(members) > MAX_NEW_MEMBERS:
        errors.append(f"一次最多加 {MAX_NEW_MEMBERS} 个成员")
    if len(existing_members) + len(members) > MAX_TOTAL_MEMBERS:
        errors.append(f"团队最多 {MAX_TOTAL_MEMBERS} 个成员")
    member_names = existing_members | {m["name"] for m in members}

    new_tasks: list[dict] = []
    lead_keys: dict[str, str] = {}
    number = _next_key_number(snap)
    raw_tasks = [e for e in _as_list(raw.get("add_tasks"))]
    for index, entry in enumerate(raw_tasks, 1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 个新任务格式不对")
            continue
        lead_key = str(entry.get("key") or f"N{index}").strip()
        if lead_key in lead_keys or (lead_key in by_key):
            lead_key = f"N{index}"
        key = f"T{number}"
        number += 1
        lead_keys[lead_key] = key
        title = _clean_text(entry.get("title"), 80)
        member = str(entry.get("member") or "").strip().lower().replace("_", "-")
        if not title:
            errors.append(f"新任务 {lead_key} 没有标题")
        if member not in member_names:
            errors.append(f"新任务 {lead_key} 分给了不存在的成员「{member or '(空)'}」")
        new_tasks.append({"key": key, "lead_key": lead_key, "title": title,
                          "description": _clean_text(entry.get("description"), 2000, one_line=False) or title,
                          "member": member, "depends_raw": _as_list(entry.get("depends_on"))})
    for t in new_tasks:
        deps: list[str] = []
        for dep in t.pop("depends_raw"):
            dep = str(dep).strip()
            target = lead_keys.get(dep) or (dep if dep in by_key else None)
            if target is None:
                errors.append(f"新任务 {t['lead_key']} 依赖了不存在的任务 {dep}")
                continue
            if target == t["key"]:
                errors.append(f"新任务 {t['lead_key']} 依赖了它自己")
                continue
            if target not in deps:
                deps.append(target)
        t["depends_on"] = deps
    if len(tasks) + len(new_tasks) > MAX_TOTAL_TASKS:
        errors.append(f"一个团队最多 {MAX_TOTAL_TASKS} 个任务（现在有 {len(tasks)} 个）")
    new_keys = {t["key"] for t in new_tasks}
    cycle = _find_cycle([{"key": t["key"], "depends_on": [d for d in t["depends_on"] if d in new_keys]}
                         for t in new_tasks]) if not errors else None
    if cycle:
        errors.append("新任务之间有循环依赖")

    cancels: list[dict] = []
    for value in _as_list(raw.get("cancel_tasks")):
        key = str(value.get("key") if isinstance(value, dict) else value).strip()
        task = by_key.get(key)
        if task is None:
            errors.append(f"要取消的任务 {key} 不存在")
            continue
        sub = task.get("sub_status")
        if sub not in NOT_STARTED + FAILED:
            errors.append(f"{key} {STATE_WORD.get(sub, sub)}，不能取消")
            continue
        if not any(c["key"] == key for c in cancels):
            cancels.append({"key": key, "task_id": task["id"], "title": task.get("title"), "state": sub})
    edits: list[dict] = []
    for index, entry in enumerate(_as_list(raw.get("edit_tasks")), 1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 个改动格式不对")
            continue
        key = str(entry.get("key") or "").strip()
        task = by_key.get(key)
        if task is None or not _KEY_RE.match(key):
            errors.append(f"要改的任务 {key or '(空)'} 不存在")
            continue
        sub = task.get("sub_status")
        if sub not in NOT_STARTED + FAILED:
            errors.append(f"{key} {STATE_WORD.get(sub, sub)}，不能改说明（可以追加一个后续任务）")
            continue
        if any(c["key"] == key for c in cancels):
            continue
        description = _clean_text(entry.get("description"), 2000, one_line=False)
        if not description:
            errors.append(f"改 {key} 时没写新的说明")
            continue
        edits.append({"key": key, "task_id": task["id"], "title": _clean_text(entry.get("title"), 80) or task.get("title"),
                      "description": description, "retry": sub in FAILED, "member": task.get("member")})
    cancelled = {c["key"] for c in cancels}
    for t in new_tasks:
        for dep in t["depends_on"]:
            if dep in cancelled:
                errors.append(f"新任务 {t['lead_key']} 依赖了要取消的 {dep}")
    used_members = {t["member"] for t in new_tasks}
    for m in members:
        if m["name"] not in used_members:
            errors.append(f"新成员 {m['name']} 没有分到任务")
    if errors:
        return None, errors
    notes = []
    for c in cancels:
        waiting = [t["key"] for t in tasks if c["task_id"] in (t.get("parents") or [])
                   and t["key"] not in cancelled and t.get("status") not in ("done", "archived")]
        if waiting:
            notes.append(f"{'、'.join(waiting)} 依赖 {c['key']}：取消后它们不再等它，直接开始")
    reply = _clean_text(raw.get("reply"), 1500, one_line=False)
    proposal = {"reply": reply or ("我按你的要求调整了计划。" if (members or new_tasks or cancels or edits) else "收到。"),
                "add_members": members, "add_tasks": new_tasks, "cancel_tasks": cancels, "edit_tasks": edits,
                "notes": notes}
    if members:
        from .plan import assign_runners

        assign_runners(members)  # shown in the card; worked out again when applied
    return proposal, []


def discard_change(team_id: str, change_id: str, *, owner: Optional[str] = None, actor: str = "") -> dict:
    from .teams import TeamError, _require_team

    slug, team = _require_team(team_id, owner)
    entry = team.get("change") or {}
    if entry.get("id") != change_id:
        raise TeamError(409, "这个提案已经不是最新的了")
    if entry.get("status") not in ("ready", "answered", "failed"):
        raise TeamError(409, "这个提案已经处理过了")

    def mutate(rec: dict) -> None:
        current = rec.get("change") or {}
        if current.get("id") != change_id:
            return
        _archive(rec, {**current, "status": "discarded" if current.get("status") == "ready" else current["status"],
                       "decided_at": now(), "decided_by": redact(actor, 40)})
        rec["change"] = None

    update_team(slug, mutate)
    if entry.get("status") == "ready":
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "change_discarded", "change": change_id,
                                                              "by": redact(actor, 40)})
    _close_cards(team_id, change_id, "discarded")
    return {"discarded": True}


def apply_change(team_id: str, change_id: str, *, owner: Optional[str] = None, actor: str = "") -> dict:
    """Put a proposal on the board: members, tasks, cancels, edits — checked again against the
    current state first (a task that started since is not touched; the user is told)."""
    from . import teams
    from .plan import assign_runners
    from .teams import TeamError, _require_team, _task_body, snapshot

    with teams._lock:
        slug, team = _require_team(team_id, owner)
        entry = team.get("change") or {}
        if entry.get("id") != change_id:
            raise TeamError(409, "这个提案已经不是最新的了")
        if entry.get("status") != "ready":
            raise TeamError(409, "这个提案已经处理过了" if entry.get("status") in ("applied", "discarded") else "还没有可应用的变更")
        _check_open(team)
        proposal = entry.get("proposal") or {}
        snap = snapshot(team_id)
        current = {t["id"]: t for t in snap.get("tasks") or []}
        skipped: list[str] = []
        for item in (proposal.get("cancel_tasks") or []) + (proposal.get("edit_tasks") or []):
            sub = (current.get(item["task_id"]) or {}).get("sub_status")
            if sub not in NOT_STARTED + FAILED:
                skipped.append(f"{item['key']} 已经{STATE_WORD.get(sub, sub or '变了')}")
        if skipped:
            raise TeamError(409, "计划在这期间变了：" + "；".join(skipped) + "。再对负责人说一次，让它按现在的状态重新提")
        new_members = [dict(m) for m in proposal.get("add_members") or []]
        if new_members:
            assign_runners(new_members)
        reopened = team.get("state") == "completed"
        stamp = now()

        def mutate_members(rec: dict) -> None:
            rec["members"] = [*(rec.get("members") or []), *new_members]
            if reopened:
                rec.update({"state": "running", "completed_at": None, "round": int(rec.get("round") or 0) + 1})
                if rec.get("conclusion"):
                    rec["conclusion"] = {**rec["conclusion"], "status": "outdated", "outdated_at": stamp,
                                         "acceptance": None}

        update_team(slug, mutate_members)
        team = read_team(slug) or team
        members = {m["name"]: m for m in team.get("members") or []}
        task_map = team.get("tasks") or {}
        keys = dict(team.get("keys") or {})
        seq = max([int(v.get("seq") or 0) for v in task_map.values()] or [0])
        added: dict[str, dict] = {}
        retry_ids: list[str] = []
        with board_conn(slug) as conn:
            for c in proposal.get("cancel_tasks") or []:
                if kb().archive_task(conn, c["task_id"]):
                    append_event(conn, c["task_id"], "halo_team", {"action": "task_cancelled", "by": redact(actor, 40),
                                                                    "change": change_id})
            for e in proposal.get("edit_tasks") or []:
                entry_map = task_map.get(e["task_id"]) or {}
                member = members.get(entry_map.get("member") or e.get("member") or "")
                if member is None:
                    continue
                body = _task_body(team, {"key": e["key"], "title": e["title"], "description": e["description"],
                                         "depends_on": entry_map.get("depends_on") or []}, member)
                with kbc().write_txn(conn, allow_nested=True):
                    cur = conn.execute(
                        "UPDATE tasks SET body = ?, title = ? WHERE id = ? AND status IN ('todo','ready','blocked','triage')",
                        (body, f"{e['key']} {e['title']}", e["task_id"]))
                if cur.rowcount:
                    append_event(conn, e["task_id"], "halo_team", {"action": "task_edited", "by": redact(actor, 40),
                                                                    "change": change_id})
                    if e.get("retry"):
                        retry_ids.append(e["task_id"])
            for t in proposal.get("add_tasks") or []:
                member = members[t["member"]]
                executor = member.get("runner") or member.get("executor") or "hermes"
                seq += 1
                task_id = kb().create_task(
                    conn, title=f"{t['key']} {t['title']}", body=_task_body(team, t, member),
                    assignee=EXECUTOR_ASSIGNEE[executor], created_by=f"halowebui:{team.get('owner')}",
                    workspace_kind="dir", workspace_path=team["workspace"], tenant=team_id,
                    parents=[keys[d] for d in t["depends_on"] if d in keys],
                    idempotency_key=f"{team_id}:{t['key']}",
                    max_runtime_seconds=teams.NATIVE_MAX_RUNTIME if executor == "hermes" else None, board=slug)
                keys[t["key"]] = task_id
                added[task_id] = {"key": t["key"], "member": member["name"], "seq": seq, "executor": executor,
                                  "chosen": member.get("executor") or executor,
                                  "chosen_by": member.get("executor_source") or "auto", "trail": [],
                                  "depends_on": t["depends_on"], "change": change_id}
            update_team(slug, lambda rec: rec.update({"tasks": {**(rec.get("tasks") or {}), **added}, "keys": keys}))
            summary = {"added": [t["key"] for t in proposal.get("add_tasks") or []],
                       "members": [m["name"] for m in new_members],
                       "cancelled": [c["key"] for c in proposal.get("cancel_tasks") or []],
                       "edited": [e["key"] for e in proposal.get("edit_tasks") or []]}
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "change_applied", "change": change_id,
                                                              "by": redact(actor, 40), "reopened": reopened, **summary})

        def finish(rec: dict) -> None:
            current_entry = rec.get("change") or {}
            if current_entry.get("id") == change_id:
                _archive(rec, {**current_entry, "status": "applied", "decided_at": now(),
                               "decided_by": redact(actor, 40), "applied": summary})
                rec["change"] = None

        update_team(slug, finish)
    for task_id in retry_ids:
        try:
            teams.retry(team_id, task_id, actor=actor or LEAD_NAME)
        except TeamError as exc:
            logger.info("halowebui-teams: retry after edit of %s: %s", task_id, exc.message)
    teams.nudge_dispatch(slug)
    _close_cards(team_id, change_id, "applied")
    return {"applied": True, "reopened": reopened, **summary}


def _close_cards(team_id: str, change_id: str, how: str) -> None:
    try:
        from .tg import close_change_cards

        close_change_cards(team_id, change_id, how)
    except Exception:  # noqa: BLE001
        logger.debug("halowebui-teams: could not close the change cards of %s", team_id, exc_info=True)


def _notify_change(slug: str) -> None:
    """A proposal asked for from Telegram goes back to that chat (the web page shows it by itself)."""
    team = read_team(slug) or {}
    entry = team.get("change") or {}
    target = entry.get("reply_to") or {}
    if entry.get("via") != "telegram" or not target.get("chat_id"):
        return
    try:
        from . import notify

        notify.change_notice(team, entry, target)
    except Exception:  # noqa: BLE001
        logger.warning("halowebui-teams: could not send the change card of %s", slug, exc_info=True)


# --- failure diagnosis -------------------------------------------------------------------------------

DIAGNOSIS_SYSTEM = """你是协作团队的负责人（team-lead）。团队里一个成员的任务失败了（或受阻），你要判断原因，给出一个处理建议。

只输出一个 JSON 对象：
{"cause": "一两句话说清楚为什么失败（写给不看代码的人）", "action": "retry | retry_with_note | switch_runner | skip | ask_user", "note": "见下", "runner": "见下"}

action 选一个：
- retry：偶发问题（网络抖动、超时、限流、进程意外退出），原样重试就行。note 留空。
- retry_with_note：任务说明不清、方法不对、缺了能补上的信息。note 写给成员的补充说明：具体、可执行，直接说该怎么做。
- switch_runner：执行器本身的问题（额度、登录、地区限制、同一种崩溃反复出现、这类任务它做不好）。runner 写换成哪个，只能从这些可用的里选：{runners}。
- skip：这个任务对目标不是必需的，或前面的成果已经覆盖了；跳过后依赖它的任务照常开始。
- ask_user：需要用户决定或提供的东西（密钥、账号、取舍、外部操作）。note 写要问用户的问题（一句话）。
不要编造日志里没有的原因；看不出来就说看不出来并选 retry。"""


def _diagnosis_entry(team: dict, task_id: str) -> dict:
    return ((team.get("diagnoses") or {}).get(task_id)) or {}


def public_diagnosis(team: dict, task: dict) -> Optional[dict]:
    """The lead's diagnosis of a failed task's current attempt (None when there is none)."""
    entry = _diagnosis_entry(team, task["id"])
    if not entry or int(entry.get("attempt") or -1) != int(task.get("attempts") or 0):
        return None
    out = {k: entry[k] for k in ("status", "cause", "action", "note", "runner", "at", "model", "error", "applied_at")
           if entry.get(k) not in (None, "")}
    if out.get("action"):
        out["action_label"] = ACTION_LABEL.get(out["action"], out["action"])
    if out.get("status") == "thinking" and now() - int(entry.get("started_at") or 0) > DIAGNOSIS_STALE \
            and not _alive("diag:" + task["id"]):
        out["status"] = "failed"
        out["error"] = "诊断被中断"
    return out


def tick_board(slug: str, team: dict) -> None:
    """From the bridge: diagnose every failed / blocked task whose current attempt has none yet."""
    if team.get("state") not in ("running", "paused") or not team.get("tasks"):
        return
    ids = list(team["tasks"])
    with board_conn(slug) as conn:
        blocked = conn.execute(
            f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join('?' * len(ids))}) AND status IN ('blocked','triage')",
            ids).fetchone()[0]
    if not blocked:
        return
    from .teams import snapshot

    snap = snapshot(team["team_id"])
    for task in snap.get("tasks") or []:
        if task.get("sub_status") not in FAILED:
            continue
        entry = _diagnosis_entry(team, task["id"])
        if entry and int(entry.get("attempt") or -1) == int(task.get("attempts") or 0):
            continue
        start_diagnosis(slug, task["id"], attempt=int(task.get("attempts") or 0))


def start_diagnosis(slug: str, task_id: str, *, attempt: int) -> None:
    stamp = now()

    def mutate(rec: dict) -> None:
        rec.setdefault("diagnoses", {})[task_id] = {"attempt": attempt, "status": "thinking", "started_at": stamp}

    update_team(slug, mutate)
    _spawn("diag:" + task_id, lambda: _diagnose(slug, task_id, attempt))


def _available_runners() -> list[str]:
    from . import runners

    try:
        availability = runners.check()
    except Exception:  # noqa: BLE001
        return []
    return [name for name in EXECUTORS if (availability.get(name) or {}).get("available")]


def _diagnose(slug: str, task_id: str, attempt: int) -> None:
    from .teams import snapshot, worker_log

    team = read_team(slug) or {}
    snap = snapshot(team["team_id"])
    task = next((t for t in snap.get("tasks") or [] if t["id"] == task_id), None)
    if task is None:
        return
    with board_conn(slug) as conn:
        row = kb().get_task(conn, task_id)
        runs = kb().list_runs(conn, task_id)
        comments = conn.execute("SELECT author, body FROM task_comments WHERE task_id = ? ORDER BY id DESC LIMIT 5",
                                (task_id,)).fetchall()
    body = redact(row.body if row else "", 3000, one_line=False)
    last = runs[-1] if runs else None
    log = worker_log(slug, team, task_id, runs, row.assignee if row else None).get("text") or ""
    executor = task_executor(team, task_id, row.assignee if row else None)
    available = [r for r in _available_runners() if r != executor]
    trail = "；".join(f"{s.get('from')}→{s.get('to') or '无'}（{s.get('reason') or ''}）"
                     for s in ((team.get("tasks") or {}).get(task_id) or {}).get("trail") or [])
    user = "\n\n".join(filter(None, [
        f"团队目标：\n{redact(team.get('goal'), 1500, one_line=False)}",
        f"失败的任务 {task.get('key')} {task.get('title')}（成员 {task.get('member')}，执行器 {executor}，第 {attempt} 次执行，"
        f"连续失败 {task.get('consecutive_failures') or 0} 次）",
        f"任务说明：\n{body}",
        f"失败 / 受阻原因：{task.get('block_reason') or (last.error if last else '') or '（没写）'}",
        f"最后一次执行的结果：{redact((last.summary or last.error or '') if last else '', 800, one_line=False)}" if last else "",
        f"执行器切换记录：{trail}" if trail else "",
        "任务上的留言（新的在前）：\n" + "\n".join(f"- {a}: {redact(b, 300)}" for a, b in comments) if comments else "",
        f"日志末尾：\n```\n{log[-6000:]}\n```" if log else "（没有日志）",
    ]))
    messages = [{"role": "system", "content": DIAGNOSIS_SYSTEM.replace("{runners}", "、".join(available) or "（没有其他可用的）")},
                {"role": "user", "content": user}]
    parsed, error, used, _text = _call(team, messages, max_tokens=1200, timeout=120)
    result: dict = {"attempt": attempt, "at": now(), "model": used.get("model") or ""}
    if parsed is None:
        result.update(status="failed", error=redact(error, 300))
    else:
        action = str(parsed.get("action") or "").strip()
        if action not in ACTIONS:
            action = "retry"
        runner = str(parsed.get("runner") or "").strip().lower()
        if action == "switch_runner" and runner not in available:
            action, runner = ("retry", "") if not available else ("switch_runner", available[0])
        if action != "switch_runner":
            runner = ""
        note = redact(parsed.get("note"), 1200, one_line=False)
        if action in ("retry_with_note", "ask_user") and not note:
            action = "retry"
        result.update(status="ready", cause=redact(parsed.get("cause"), 400, one_line=False) or "看不出具体原因",
                      action=action, note=note if action in ("retry_with_note", "ask_user") else "", runner=runner)

    def mutate(rec: dict) -> None:
        current = (rec.get("diagnoses") or {}).get(task_id) or {}
        if int(current.get("attempt") or -1) != attempt:
            return
        rec.setdefault("diagnoses", {})[task_id] = {**current, **result}

    update_team(slug, mutate)
    if result["status"] == "ready":
        with board_conn(slug) as conn:
            append_event(conn, task_id, "halo_team", {"action": "diagnosed", "cause": redact(result["cause"], 200),
                                                      "suggestion": result["action"], "runner": result.get("runner") or ""})


def request_diagnosis(team_id: str, task_id: str, *, owner: Optional[str] = None) -> dict:
    """Diagnose again now (the user asked)."""
    from .teams import TeamError, _require_team, snapshot

    slug, team = _require_team(team_id, owner)
    snap = snapshot(team_id, owner)
    task = next((t for t in snap.get("tasks") or [] if t["id"] == task_id), None)
    if task is None:
        raise TeamError(404, "task not found")
    if task.get("sub_status") not in FAILED:
        raise TeamError(409, "只有失败或受阻的任务需要诊断")
    if _alive("diag:" + task_id):
        raise TeamError(409, "负责人正在诊断")
    start_diagnosis(slug, task_id, attempt=int(task.get("attempts") or 0))
    return public_diagnosis(read_team(slug) or team, task) or {"status": "thinking"}


def apply_diagnosis(team_id: str, task_id: str, *, owner: Optional[str] = None, actor: str = "") -> dict:
    """Do what the lead suggested for a failed task."""
    from . import fallback
    from .teams import TeamError, _require_team, retry, snapshot

    slug, team = _require_team(team_id, owner)
    snap = snapshot(team_id, owner)
    task = next((t for t in snap.get("tasks") or [] if t["id"] == task_id), None)
    if task is None:
        raise TeamError(404, "task not found")
    if team.get("state") == "stopped":
        raise TeamError(409, "协作任务已停止")
    diagnosis = public_diagnosis(team, task)
    if not diagnosis or diagnosis.get("status") != "ready":
        raise TeamError(409, "负责人还没有给出建议")
    if task.get("sub_status") not in FAILED:
        raise TeamError(409, "这个任务已经不在失败状态了")
    action = diagnosis["action"]
    if action == "ask_user":
        raise TeamError(409, "这一步需要你来决定：回答负责人的问题后再重试")
    with board_conn(slug) as conn:
        if action == "retry_with_note" and diagnosis.get("note"):
            kb().add_comment(conn, task_id, LEAD_NOTE_AUTHOR, diagnosis["note"])
        if action == "switch_runner" and diagnosis.get("runner") in EXECUTORS:
            row = kb().get_task(conn, task_id)
            current = task_executor(team, task_id, row.assignee if row else None)
            runner = diagnosis["runner"]

            def choose(rec: dict) -> None:
                entry = rec.setdefault("tasks", {}).setdefault(task_id, {})
                entry["chosen"] = runner
                entry["chosen_by"] = "lead"

            update_team(slug, choose)
            fallback._record(slug, task_id, {"from": current, "to": runner, "reason": "负责人建议：" + redact(diagnosis.get("cause"), 200),
                                             "at": now(), "phase": "lead"}, runner)
            fallback._assign(conn, task_id, runner)
            append_event(conn, task_id, "halo_runner", {
                "phase": "fallback", "runner": current, "to": runner, "reason": "负责人建议",
                "text": f"负责人建议换执行器：{current} → {runner}"})
        if action == "skip":
            kb().archive_task(conn, task_id)
        append_event(conn, task_id, "halo_team", {"action": "diagnosis_applied", "suggestion": action,
                                                  "by": redact(actor, 40)})

    def mark(rec: dict) -> None:
        entry = (rec.get("diagnoses") or {}).get(task_id)
        if entry:
            entry["applied_at"] = now()

    update_team(slug, mark)
    if action != "skip":
        retry(team_id, task_id, owner=owner, actor=actor or LEAD_NAME)
    else:
        from .teams import nudge_dispatch

        nudge_dispatch(slug)
    return {"applied": action}


# --- acceptance --------------------------------------------------------------------------------------

ACCEPTANCE_SYSTEM = """你是协作团队的负责人（team-lead）。团队做完了，你也写好了结论。现在对照用户的目标做验收：目标要求的每一项是否真的做到了——以任务结果和结论里的事实为准，不以计划为准。

只输出一个 JSON 对象：
{"verdict": "met | partial | unmet", "summary": "一句话验收结论", "gaps": [{"title": "缺口（10 个字左右）", "detail": "缺了什么、该怎么补（1 到 2 句）"}]}

- verdict 为 met 时 gaps 为空数组。gaps 最多 5 条，只列目标真正要求、团队没做到或做错的；锦上添花的建议不算缺口。
- 有任务失败或被停止、导致目标没达成的，也是缺口。"""


def check_acceptance(slug: str) -> None:
    """After the conclusion is written: the lead's acceptance against the goal (in the entry)."""
    from .conclusion import _set, conclusion_path

    team = read_team(slug) or {}
    path = conclusion_path(team)
    try:
        markdown = path.read_text(encoding="utf-8", errors="replace") if path is not None and path.exists() else ""
    except OSError:
        markdown = ""
    if not markdown:
        return
    from .teams import snapshot

    snap = snapshot(team["team_id"])
    statuses = "\n".join(f"- {t.get('key')} {t.get('title')}：{STATE_WORD.get(t.get('sub_status') or t.get('status'), t.get('status'))}"
                         for t in snap.get("tasks") or [])
    messages = [{"role": "system", "content": ACCEPTANCE_SYSTEM},
                {"role": "user", "content": f"协作目标：\n{redact(team.get('goal'), 3000, one_line=False)}\n\n任务：\n{statuses}\n\n"
                                            f"结论：\n{markdown[:20000]}"}]
    parsed, error, used, _text = _call(team, messages, max_tokens=1500, timeout=120)
    if parsed is None:
        _set(slug, acceptance={"status": "failed", "error": redact(error, 300), "at": now()})
        return
    verdict = str(parsed.get("verdict") or "").strip()
    if verdict not in ("met", "partial", "unmet"):
        verdict = "partial"
    gaps = []
    for gap in _as_list(parsed.get("gaps"))[:5]:
        if isinstance(gap, dict) and (gap.get("title") or gap.get("detail")):
            gaps.append({"title": redact(gap.get("title") or gap.get("detail"), 40),
                         "detail": redact(gap.get("detail") or "", 300, one_line=False)})
        elif isinstance(gap, str) and gap.strip():
            gaps.append({"title": redact(gap, 40), "detail": redact(gap, 300)})
    if verdict == "met":
        gaps = []
    elif not gaps:
        verdict = "met"
    entry = {"status": "ready", "verdict": verdict, "summary": redact(parsed.get("summary"), 300, one_line=False),
             "gaps": gaps, "model": used.get("model") or "", "at": now()}
    _set(slug, acceptance=entry)
    with board_conn(slug) as conn:
        append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": "accepted", "verdict": verdict, "gaps": len(gaps)})


def gaps_request(acceptance: dict) -> str:
    """The change request 「让团队补上」 sends for the acceptance gaps."""
    lines = ["按验收发现的缺口补上（只补这些，已完成的不要重做）："]
    for gap in acceptance.get("gaps") or []:
        lines.append(f"- {gap.get('title')}：{gap.get('detail') or ''}".rstrip("："))
    return "\n".join(lines)


def fill_gaps(team_id: str, *, owner: Optional[str] = None, actor: str = "", via: str = "web",
              reply_to: Optional[dict] = None) -> dict:
    from .teams import TeamError, _require_team

    _slug, team = _require_team(team_id, owner)
    acceptance = (team.get("conclusion") or {}).get("acceptance") or {}
    if acceptance.get("status") != "ready" or not acceptance.get("gaps"):
        raise TeamError(409, "验收没有发现缺口")
    return request_change(team_id, gaps_request(acceptance), owner=owner, actor=actor, via=via, source="acceptance",
                          reply_to=reply_to)
