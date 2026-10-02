"""External runners as team members: the executor bridge for tasks assigned to a runner
(``reclaude``, ``cchclaude``, ``anyclaude``, ``codex``, ``agy``).

The Kanban dispatcher leaves such tasks alone (a runner name is not a Hermes profile), so this
bridge claims them like any external worker would and drives the existing runner script
(``reclaude-run.sh``, ``cchclaude-run.sh``, ``anyclaude-run.sh``, ``codex-run.sh``,
``agy-run.sh``) — no Hermes agent sits in between waiting for it. All of them share the run
directory protocol (meta.json / progress.log / result.json + result.md, QUESTION: and
``answer`` in the same session); only reclaude-run.sh and its two siblings park a run for a
quota reset and continue it by themselves (``auto_resume``).

Per task attempt (one Kanban ``task_runs`` row = one claim):
* launch: claim → write the task file (the same context a Hermes worker reads:
  ``build_worker_context`` = task body, parent handoffs, earlier attempts, comments) →
  ``systemd-run --user`` the runner with a run id chosen here, so it is recorded before it
  starts. No HERMES_SESSION_* in its environment: the runner's own completion notice finds no
  chat and stays quiet, and autopilot-supervisor skips runs whose origin cannot get a report,
  so only this bridge ever resumes these runs.
* follow (every bridge tick): read the runner's meta.json, following its own continuations
  (``auto_resume_run`` = ``<id>-aN``) and our answers (also ``<id>-aN``); extend the claim while
  anything is alive or waiting; copy new progress.log tool lines as ``halo_tool`` events.
* finish: success → ``complete_task`` with the agent's final answer as the handoff;
  QUESTION → the task stays claimed, ``waiting_user`` until the user answers in the 协作台
  (their note is sent with ``answer``, same session); quota wait (``auto_resume=scheduled``)
  → ``quota_wait`` until the runner resumes by itself; stopped / failed → task blocked.
* notes written by the user while reclaude runs cannot reach it mid-run (print mode): they are
  sent with ``answer`` (same Claude session) when the current run ends, before the task is
  marked done.

The run ids of every runner run of an attempt are kept in the attempt's metadata
(``runner_runs``), so the board shows which runner runs belong to which attempt of which task.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

from .common import (
    append_event,
    board_conn,
    executor_of,
    kb,
    kbc,
    logger,
    member_of,
    now,
    read_team,
    RUNNER_EXECUTORS,
    redact,
    task_key,
    team_boards,
)

TASK_DIR = Path(os.environ.get("HALO_TEAMS_TASK_DIR", "/root/.hermes/halo-teams/tasks"))
CLAIMER = "halowebui-teams-reclaude"  # the claim name of every runner member (kept from reclaude-only days)
CLAIM_TTL = 1800
# Runner members of the same kind that run at once (host-wide cap kanban.max_in_progress on top).
MAX_CONCURRENT = int(os.environ.get("HALO_TEAMS_RUNNER_MAX") or os.environ.get("HALO_TEAMS_RECLAUDE_MAX") or 1)
MAX_TURNS = int(os.environ.get("HALO_TEAMS_RECLAUDE_MAX_TURNS", "150") or 150)
MAX_PROGRESS_EVENTS = 400
LAUNCH_GRACE = 90          # seconds for the run dir to appear after systemd-run
INTERRUPT_RESUMES = 1      # a runner that died mid-run is resumed this many times per attempt
QUOTA_BLOCKED_RETRY = 600
_HOME = os.environ.get("HALO_TEAMS_RUNS_HOME", "/root/.hermes")
_SCRIPTS = os.environ.get("HALO_TEAMS_RUNNER_SCRIPTS", "/root/.hermes/scripts")


class Runner(NamedTuple):
    name: str
    runs_root: Path
    script: str
    extra_args: tuple       # added to run and answer (what this runner accepts)
    answer_sets_id: bool    # answer is told the new run id (--run-id) instead of picking <id>-aN itself

    @property
    def fail_prefix(self) -> str:
        return f"{self.name} 运行失败"


def _runner(name: str, script: str, extra_args: tuple = (), answer_sets_id: bool = False) -> Runner:
    env = name.upper()
    root = os.environ.get(f"HALO_TEAMS_{env}_RUNS_ROOT") or os.path.join(_HOME, f"{name}-runs")
    path = os.environ.get(f"HALO_TEAMS_{env}_RUNNER") or os.path.join(_SCRIPTS, script)
    return Runner(name, Path(root), path, tuple(extra_args), answer_sets_id)


_TURNS = ("--max-turns", str(MAX_TURNS))
RUNNERS = {
    "reclaude": _runner("reclaude", "reclaude-run.sh", _TURNS),
    "cchclaude": _runner("cchclaude", "cchclaude-run.sh", _TURNS),
    "anyclaude": _runner("anyclaude", "anyclaude-run.sh", _TURNS),
    "codex": _runner("codex", "codex-run.sh"),            # codex exec has no turn cap
    "agy": _runner("agy", "agy-run.sh", answer_sets_id=True),  # agy's answer takes --run-id, no --max-turns
}
assert tuple(RUNNERS) == RUNNER_EXECUTORS
_ASSIGNEES_SQL = "(" + ",".join("'%s'" % name for name in RUNNERS) + ")"
_RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}(-a[0-9]+)*$")
_PROGRESS_TOOL_RE = re.compile(r"^(\d\d:\d\d:\d\d) \[tool#(\d+)\] ([^:]{1,60}):\s?(.*)$")
_launcher = {"fn": None}  # tests replace the systemd launch


def runner_of(name: Any) -> Optional[Runner]:
    return RUNNERS.get(str(name or ""))


def _read_meta(rn: Runner, run_id: str) -> dict:
    if not run_id or not _RUN_ID_RE.match(run_id):
        return {}
    try:
        data = json.loads((rn.runs_root / run_id / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            return handle.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def _next_answer_id(rn: Runner, run_id: str) -> str:
    n = 1
    while (rn.runs_root / f"{run_id}-a{n}").exists():
        n += 1
    return f"{run_id}-a{n}"


def _launch(unit: str, argv: list[str]) -> tuple[bool, str]:
    if _launcher["fn"] is not None:
        return _launcher["fn"](unit, argv)
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    # The unit gets the user manager's bare PATH, not ours: agy-run.sh calls `agy` by name and it
    # lives in /root/.local/bin, so hand down the gateway's PATH (what /agy from a chat runs with).
    cmd = ["systemd-run", "--user", "--quiet", "--collect", "--unit", unit,
           "--setenv=HERMES_HOME=/root/.hermes", "--setenv=HALO_TEAMS_MEMBER_RUN=1",
           f"--setenv=PATH={env.get('PATH') or '/usr/local/bin:/usr/bin:/bin'}", "--", *argv]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}"
    if proc.returncode != 0:
        return False, redact(proc.stderr or proc.stdout, 300)
    return True, ""


def _set_run_meta(conn: Any, run_row_id: int, updates: dict) -> dict:
    with kbc().write_txn(conn, allow_nested=True):
        row = conn.execute("SELECT metadata FROM task_runs WHERE id = ?", (run_row_id,)).fetchone()
        current = {}
        if row and row[0]:
            try:
                current = json.loads(row[0]) or {}
            except ValueError:
                current = {}
        current.update(updates)
        conn.execute("UPDATE task_runs SET metadata = ? WHERE id = ?", (json.dumps(current, ensure_ascii=False), run_row_id))
    return current


def close_preserving(conn: Any, run_row: Optional[int], action):
    """Run a Kanban call that closes the attempt (block / complete / reclaim): Kanban rewrites the
    attempt's metadata column when it closes it, which would drop which runner runs belong to it."""
    keep = _run_meta(conn, run_row) if run_row else {}
    result = action()
    if run_row and keep:
        _set_run_meta(conn, run_row, {**keep, **_run_meta(conn, run_row)})
    return result


def _run_meta(conn: Any, run_row_id: Optional[int]) -> dict:
    if not run_row_id:
        return {}
    row = conn.execute("SELECT metadata FROM task_runs WHERE id = ?", (run_row_id,)).fetchone()
    if not row or not row[0]:
        return {}
    try:
        value = json.loads(row[0])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _running_count(name: str) -> int:
    count = 0
    for slug in team_boards():
        try:
            with board_conn(slug) as conn:
                count += conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = 'running' AND assignee = ?", (name,)
                ).fetchone()[0]
        except Exception:
            continue
    return count


def _host_running_count() -> int:
    """Running tasks on every board (Hermes members included): the host-wide budget."""
    total = 0
    try:
        slugs = [s for s in [None] + [b["slug"] for b in kb().list_boards(include_archived=True)]]
    except Exception:
        slugs = team_boards()
    seen = set()
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        try:
            with board_conn(slug or "default") as conn:
                total += conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'running'").fetchone()[0]
        except Exception:
            continue
    return total


def _host_cap() -> Optional[int]:
    try:
        from .teams import _dispatch_kwargs

        cap = _dispatch_kwargs().get("max_in_progress")
        return int(cap) if cap else None
    except Exception:
        return None


# --- launch -------------------------------------------------------------------------------------

def _task_text(conn: Any, team: dict, task_id: str) -> str:
    try:
        context = kb().build_worker_context(conn, task_id)
    except Exception:
        task = kb().get_task(conn, task_id)
        context = (task.body or task.title) if task else ""
    return (
        "你是 HaloWebUI 协作台里一个协作团队的成员，下面是你在共享任务板上的任务（含前置任务交接和用户留言）。\n"
        "直接完成它，不要再派发给别的代理或 runner。\n"
        "完成时，最终回答写清楚：做了什么、产出物在哪个文件、给后续成员的交接要点——这段会原样交给依赖你的成员。\n"
        "如果必须由用户决定才能继续，按 QUESTION: 协议停下（用户会在协作台里回答）。\n"
        "你没有 kanban_complete / kanban_comment / kanban_block 这些任务板工具，也不需要它们：下面说明里让你调用"
        "这些工具的地方，一律改为写进最终回答，协作台会据此更新任务板。\n\n"
        + context
    )


def launch(rn: Runner, slug: str, conn: Any, team: dict, task_id: str, *, previous_run: str = "") -> Optional[str]:
    claimed = kb().claim_task(conn, task_id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
    if claimed is None:
        return None
    run_row = conn.execute("SELECT current_run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
    run_id = new_run_id()
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    task_file = TASK_DIR / f"{slug}-{task_id}-{run_id}.md"
    task_file.write_text(_task_text(conn, team, task_id), encoding="utf-8")
    cwd = team.get("workspace") or "/root"
    Path(cwd).mkdir(parents=True, exist_ok=True)
    argv = [rn.script, "run", "--cwd", cwd, "--task-file", str(task_file), "--run-id", run_id,
            *rn.extra_args, "--no-vault-archive"]
    _set_run_meta(conn, run_row, {
        "runner": rn.name, "runner_run_id": run_id, "runner_runs": [{"run_id": run_id, "kind": "launch"}],
        "runner_phase": "starting", "launched_at": now(), "progress_seen": 0, "tool_events": 0,
        "interrupt_resumes": 0, **({"parent_runner_run_id": previous_run} if previous_run else {}),
    })
    ok, why = _launch(f"halo-team-{run_id}", argv)
    if not ok:
        _fail(rn, conn, task_id, run_row, f"{rn.fail_prefix}：启动失败（{why or '未知原因'}）")
        return None
    append_event(conn, task_id, "halo_runner", {"phase": "launched", "runner": rn.name, "runner_run_id": run_id,
                                                 "text": f"{rn.name} 已启动（run {run_id}）"}, run_id=run_row)
    return run_id


def _fail(rn: Runner, conn: Any, task_id: str, run_row: Optional[int], reason: str) -> None:
    if run_row:
        _set_run_meta(conn, run_row, {"runner_phase": "failed"})
    append_event(conn, task_id, "halo_runner", {"phase": "failed", "runner": rn.name, "text": redact(reason, 600)},
                 run_id=run_row)
    try:
        close_preserving(conn, run_row, lambda: kb().block_task(conn, task_id, reason=redact(reason, 400)))
    except Exception:
        logger.warning("halowebui-teams: could not block %s", task_id, exc_info=True)


# --- follow -------------------------------------------------------------------------------------

def _effective_run(rn: Runner, run_id: str) -> tuple[str, dict]:
    """Follow the runner's own continuations (<id>-aN started by auto_resume) to the live run."""
    seen = set()
    meta = _read_meta(rn, run_id)
    while meta and run_id not in seen:
        seen.add(run_id)
        nxt = str(meta.get("auto_resume_run") or "")
        if meta.get("auto_resume") in ("started",) and nxt and (rn.runs_root / nxt / "meta.json").exists():
            run_id, meta = nxt, _read_meta(rn, nxt)
            continue
        break
    return run_id, meta


def _copy_progress(rn: Runner, conn: Any, task_id: str, run_row: int, rmeta: dict, runner_run: str) -> dict:
    path = rn.runs_root / runner_run / "progress.log"
    key = f"progress_seen:{runner_run}"
    seen = int(rmeta.get(key) or 0)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    fresh = lines[seen:]
    if not fresh:
        return {}
    written = int(rmeta.get("tool_events") or 0)
    for line in fresh:
        match = _PROGRESS_TOOL_RE.match(line)
        if not match or written >= MAX_PROGRESS_EVENTS:
            continue
        written += 1
        append_event(conn, task_id, "halo_tool", {"name": match.group(3).strip()[:60],
                                                  "preview": redact(match.group(4), 160), "runner_run_id": runner_run},
                     run_id=run_row)
    return {key: len(lines), "tool_events": written}


def _final_answer(rn: Runner, runner_run: str) -> str:
    try:
        data = json.loads((rn.runs_root / runner_run / "result.json").read_text(encoding="utf-8"))
        text = data.get("result") or data.get("answer") or data.get("response") or ""
        if text:
            return str(text)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return (rn.runs_root / runner_run / "result.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _question_text(answer: str) -> str:
    idx = answer.rfind("QUESTION:")
    return answer[idx:].strip() if idx >= 0 else answer.strip()[-1200:]


def _undelivered_notes(conn: Any, task_id: str, since_ts: int, delivered: list) -> list:
    rows = conn.execute(
        "SELECT id, author, body, created_at FROM task_comments WHERE task_id = ? AND created_at >= ? ORDER BY id",
        (task_id, since_ts),
    ).fetchall()
    return [r for r in rows if str(r[1] or "").startswith("user:") and int(r[0]) not in set(delivered)]


def _answer(rn: Runner, conn: Any, task_id: str, run_row: int, rmeta: dict, runner_run: str, text: str,
            kind: str) -> Optional[str]:
    next_id = _next_answer_id(rn, runner_run)
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    task_file = TASK_DIR / f"answer-{next_id}.md"
    task_file.write_text(text, encoding="utf-8")
    argv = [rn.script, "answer", runner_run, "--task-file", str(task_file), *rn.extra_args]
    if rn.answer_sets_id:
        argv += ["--run-id", next_id]
    ok, why = _launch(f"halo-team-{next_id}", argv)
    if not ok:
        logger.warning("halowebui-teams: answer launch failed for %s: %s", runner_run, why)
        return None
    runs = list(rmeta.get("runner_runs") or []) + [{"run_id": next_id, "kind": kind, "parent": runner_run}]
    _set_run_meta(conn, run_row, {"runner_run_id": next_id, "runner_runs": runs, "runner_phase": "starting",
                                  "launched_at": now(), "question": None})
    append_event(conn, task_id, "halo_runner", {
        "phase": "answered" if kind == "answer" else "continued", "runner": rn.name, "runner_run_id": next_id,
        "text": {"answer": f"已把你的说明交给 {rn.name}，同一会话续跑（run {next_id}）",
                 "notes": f"{rn.name} 这一轮结束，带着你的补充说明续跑同一会话（run {next_id}）",
                 "resume": f"runner 被打断，已在同一会话里接着跑（run {next_id}）"}.get(kind, f"续跑 run {next_id}")},
        run_id=run_row)
    return next_id


def follow(rn: Runner, slug: str, conn: Any, team: dict, task: Any) -> None:
    run_row = task.current_run_id
    rmeta = _run_meta(conn, run_row)
    runner_run = str(rmeta.get("runner_run_id") or "")
    if not runner_run:
        # Claimed by us but nothing recorded (crash between claim and launch): retry the launch.
        if task.claim_lock == CLAIMER and now() - int(task.started_at or now()) > LAUNCH_GRACE:
            _fail(rn, conn, task.id, run_row, f"{rn.fail_prefix}：认领后没有启动记录")
        return
    live_id, meta = _effective_run(rn, runner_run)
    if live_id != runner_run:
        runs = list(rmeta.get("runner_runs") or [])
        if not any(r.get("run_id") == live_id for r in runs):
            runs.append({"run_id": live_id, "kind": "auto_continue", "parent": runner_run})
        rmeta = _set_run_meta(conn, run_row, {"runner_run_id": live_id, "runner_runs": runs, "runner_phase": "running",
                                              "resume_at": None})
        append_event(conn, task.id, "halo_runner", {"phase": "continued", "runner": rn.name, "runner_run_id": live_id,
                                                     "text": f"runner 自动续跑同一会话（run {live_id}）"}, run_id=run_row)
        runner_run = live_id
    if not meta:
        if now() - int(rmeta.get("launched_at") or now()) > LAUNCH_GRACE:
            _fail(rn, conn, task.id, run_row, f"{rn.fail_prefix}：run {runner_run} 没有生成运行目录")
        else:
            kb().heartbeat_claim(conn, task.id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
        return
    updates = _copy_progress(rn, conn, task.id, run_row, rmeta, runner_run)
    if updates:
        rmeta = _set_run_meta(conn, run_row, updates)
    status = str(meta.get("status") or "")
    auto = str(meta.get("auto_resume") or "")
    if team.get("state") == "stopped":
        return
    if status == "running":
        alive = _pid_alive(meta.get("runner_pid"))
        if alive:
            kb().heartbeat_claim(conn, task.id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
            if rmeta.get("runner_phase") != "running":
                _set_run_meta(conn, run_row, {"runner_phase": "running", "question": None})
            return
        status = "interrupted"
    if auto == "scheduled":
        kb().heartbeat_claim(conn, task.id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
        if _pid_alive(meta.get("auto_resume_pid")):
            if rmeta.get("runner_phase") != "quota_wait":
                resume_at = str(meta.get("auto_resume_at") or "")
                _set_run_meta(conn, run_row, {"runner_phase": "quota_wait", "resume_at": resume_at})
                kind = str(meta.get("failure_kind") or "")
                why = "额度用完" if "quota" in kind else ("达到轮数上限" if "turn" in kind else "暂时中断")
                append_event(conn, task.id, "halo_runner", {
                    "phase": "quota_wait", "runner": rn.name, "runner_run_id": runner_run, "resume_at": resume_at,
                    "status": status, "text": f"{rn.name} {why}，runner 会在 {resume_at or '重置后'} 自动续跑同一会话（不是失败）"},
                    run_id=run_row)
            return
        status = "interrupted"  # the waiting runner died (reboot): resume it ourselves below
    if status == "quota_blocked":
        kb().heartbeat_claim(conn, task.id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
        if rmeta.get("runner_phase") != "quota_wait":
            _set_run_meta(conn, run_row, {"runner_phase": "quota_wait", "quota_blocked_at": now()})
            append_event(conn, task.id, "halo_runner", {
                "phase": "quota_wait", "runner": rn.name, "runner_run_id": runner_run, "status": status,
                "text": f"额度不足，{rn.name} 还没开始；额度恢复后会重新启动这个任务（不是失败）"}, run_id=run_row)
        elif now() - int(rmeta.get("quota_blocked_at") or now()) > QUOTA_BLOCKED_RETRY:
            try:
                close_preserving(conn, run_row, lambda: kb().reclaim_task(conn, task.id, reason=f"{rn.name} 额度不足，稍后重新启动"))
            except Exception:
                pass
        return
    delivered = list(rmeta.get("delivered_comment_ids") or [])
    if status == "success":
        notes = _undelivered_notes(conn, task.id, int(rmeta.get("launched_at") or 0), delivered)
        if notes:
            text = "用户在协作台给你补充了说明，请按说明继续，完成后同样在最终回答里写交接摘要：\n" + "\n".join(
                f"- {redact(r[2], 2000, one_line=False)}" for r in notes)
            next_id = _answer(rn, conn, task.id, run_row, rmeta, runner_run, text, "notes")
            if next_id:
                ids = [int(r[0]) for r in notes]
                _set_run_meta(conn, run_row, {"delivered_comment_ids": delivered + ids})
                append_event(conn, task.id, "halo_comment_delivered", {"comment_ids": ids, "via": "runner_answer"},
                             run_id=run_row)
                return
        answer = _final_answer(rn, runner_run)
        summary = redact(answer, 1500, one_line=False)
        final = _set_run_meta(conn, run_row, {"runner_phase": "done"})
        kb().complete_task(conn, task.id, result=redact(answer, 6000, one_line=False), summary=summary,
                           metadata=final)
        return
    if status == "question":
        kb().heartbeat_claim(conn, task.id, ttl_seconds=CLAIM_TTL, claimer=CLAIMER)
        if rmeta.get("runner_phase") != "question":
            question = _question_text(_final_answer(rn, runner_run))
            _set_run_meta(conn, run_row, {"runner_phase": "question", "question": redact(question, 1500, one_line=False),
                                          "question_at": now()})
            append_event(conn, task.id, "halo_runner", {"phase": "question", "runner": rn.name,
                                                         "runner_run_id": runner_run,
                                                         "text": redact(question, 1500, one_line=False)}, run_id=run_row)
            return
        notes = _undelivered_notes(conn, task.id, int(rmeta.get("question_at") or 0), delivered)
        if notes:
            text = "\n\n".join(redact(r[2], 4000, one_line=False) for r in notes)
            if _answer(rn, conn, task.id, run_row, rmeta, runner_run, text, "answer"):
                ids = [int(r[0]) for r in notes]
                _set_run_meta(conn, run_row, {"delivered_comment_ids": delivered + ids})
                append_event(conn, task.id, "halo_comment_delivered", {"comment_ids": ids, "via": "runner_answer"},
                             run_id=run_row)
        return
    if status == "stopped":
        _fail(rn, conn, task.id, run_row, f"{rn.fail_prefix}：{rn.name} 运行 {runner_run} 被停止")
        return
    if status == "interrupted" and int(rmeta.get("interrupt_resumes") or 0) < INTERRUPT_RESUMES and meta.get("session_id"):
        if _answer(rn, conn, task.id, run_row, rmeta, runner_run,
                   "你上一轮被打断了（runner 进程意外退出或本机重启）。请检查已完成的部分，接着把任务做完。", "resume"):
            _set_run_meta(conn, run_row, {"interrupt_resumes": int(rmeta.get("interrupt_resumes") or 0) + 1})
            return
    _fail(rn, conn, task.id, run_row, f"{rn.fail_prefix}：run {runner_run} 状态 {status or '未知'}")


# --- board tick / stop --------------------------------------------------------------------------

def tick_board(slug: str, team: dict) -> None:
    with board_conn(slug) as conn:
        running = conn.execute(
            "SELECT id, assignee FROM tasks WHERE status = 'running' AND assignee IN " + _ASSIGNEES_SQL
        ).fetchall()
        for task_id, assignee in running:
            task = kb().get_task(conn, task_id)
            if task is not None and task.claim_lock == CLAIMER:
                follow(RUNNERS[assignee], slug, conn, team, task)
        if team.get("archived") or team.get("state") != "running":
            return
        ready = conn.execute(
            "SELECT id, assignee FROM tasks WHERE status = 'ready' AND assignee IN " + _ASSIGNEES_SQL
            + " AND claim_lock IS NULL ORDER BY priority DESC, created_at"
        ).fetchall()
    if not ready:
        return
    for task_id, assignee in ready:
        if _running_count(assignee) >= MAX_CONCURRENT:
            continue
        cap = _host_cap()
        if cap is not None and _host_running_count() >= cap:
            return
        with board_conn(slug) as conn:
            previous = ""
            runs = kb().list_runs(conn, task_id)
            if runs:
                previous = str(_run_meta(conn, runs[-1].id).get("runner_run_id") or "")
            launch(RUNNERS[assignee], slug, conn, team, task_id, previous_run=previous)


def stop_task(slug: str, conn: Any, task_id: str) -> bool:
    """Stop the runner run(s) of *task_id* (team stop). The caller blocks the task."""
    task = kb().get_task(conn, task_id)
    if task is None:
        return False
    rn = runner_of(task.assignee)
    if rn is None:
        return False
    rmeta = _run_meta(conn, task.current_run_id)
    runner_run = str(rmeta.get("runner_run_id") or "")
    if not runner_run:
        return False
    live_id, meta = _effective_run(rn, runner_run)
    if not meta:
        return False
    stoppable = meta.get("status") == "running" or meta.get("auto_resume") == "scheduled"
    if stoppable:
        try:
            from gateway.runner_dispatch import stop_run

            why = asyncio.run(stop_run({**meta, "run_id": live_id, "_agent": rn.name,
                                        "_dir": str(rn.runs_root / live_id)}, stopped_by="HaloWebUI 协作台"))
            if why:
                logger.warning("halowebui-teams: stop %s: %s", live_id, why)
        except Exception:
            logger.warning("halowebui-teams: stop %s failed", live_id, exc_info=True)
    if task.current_run_id:
        _set_run_meta(conn, task.current_run_id, {"runner_phase": "stopped"})
    append_event(conn, task_id, "halo_runner", {"phase": "stopped", "runner": rn.name, "runner_run_id": live_id,
                                                 "text": f"{rn.name} 运行 {live_id} 已停止"}, run_id=task.current_run_id)
    return True


def member_label(team: dict, task_id: str) -> str:
    member = member_of(team, task_id)
    return f"{task_key(team, task_id)} {member}（{executor_of(team, member)}）"
