#!/usr/bin/env python3
"""reclaude-notify.py — deliver a finished background agent run to the chat that launched it.

Shared by the runners: reclaude-run.sh (defaults), codex-run.sh and agy_runner.py (which
pass --agent/--runner-name/--tool-marker/--answer-command/--config-file).

It finds the hermes session that launched this run, then:
  * HaloWebUI (api_server): POSTs to HaloWebUI's /api/v1/hermes/notifications. The
    payload carries the report itself (mode=display: HaloWebUI shows it as the reply,
    no model turn) and, for an older HaloWebUI, the prompt of a follow-up turn in which
    hermes reads result.md and reports.
  * Telegram, for a run started with --detach (RUNNER_DETACHED_LOG is set): sends the
    report straight to the chat through runner-deliver.py and records it in the chat's
    session. Nothing else would: a detached run has no gateway watcher.
  * Telegram without --detach, QQ, CLI: left alone; the gateway's background-process
    notice delivers those.
RUNNER_DIRECT_DELIVERY=0 turns both report paths off (HaloWebUI gets only the prompt,
Telegram is left to the gateway).

Two ways to learn the origin, in order:
  1. What the runner recorded at launch (--origin-session / meta.json's
     origin_session_id), taken from the HERMES_SESSION_* variables hermes
     bridges into every tool subprocess. This is exact and tool-name agnostic.
  2. Legacy fallback: reverse-engineer it from tool-call provenance in state.db
     (read-only) for runs launched before the runner recorded it.
Path 2 is inherently fragile — it broke once when hermes renamed the `process`
tool to `process_manage`, and it never worked for a plain background launch
(`terminal(background=true)` returns "Background process started" with no run
id, so nothing links the launch to the run until somebody polls).

Config (KEY=VALUE lines):
  HALOWEBUI_NOTIFY_URL=http://127.0.0.1:3000/api/v1/hermes/notifications
  HALOWEBUI_NOTIFY_TOKEN=<same value as HERMES_AGENT_NOTIFY_TOKEN in the container>
Every --config-file is consulted in order and the results are layered, earlier files
winning per key; a file that defines nothing usable is logged and skipped over instead
of shadowing the next one. $RECLAUDE_NOTIFY_CONFIG replaces the whole list (so a test
never falls through to the production credentials); with no --config-file the default is
/root/.hermes/reclaude-runner.env.

Always exits 0; never affects the runner's own exit code. Stdlib only.
"""
import argparse
import datetime
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCRIPT_VERSION = "2026-10-08.1"
CONFIG_FILE = "/root/.hermes/reclaude-runner.env"
REQUIRED_CONFIG_KEYS = ("HALOWEBUI_NOTIFY_URL", "HALOWEBUI_NOTIFY_TOKEN")
STATE_DB = "/root/.hermes/state.db"
LOOKBACK_SECONDS = 48 * 3600
# Poll/wait tool for background processes.  Hermes 0.21 renamed `process` to
# `process_manage`; both names appear in state.db, so the provenance fallback
# accepts either.  Add new spellings here rather than at the call sites.
PROCESS_TOOL_NAMES = ("process", "process_manage")
PROVENANCE_TOOL_NAMES = ("terminal",) + PROCESS_TOOL_NAMES
RETRY_ATTEMPTS = 10
RETRY_INTERVAL_SECONDS = 30
# HTTP 409 from HaloWebUI means only "that chat is mid-turn", and a turn always ends —
# unlike a 5xx, which may be a server that stays broken. Outlasting someone else's turn
# is exactly what this notice has to do, and ten attempts is not enough to: on
# 2026-09-15 codex run 20260915-193235-32b394d1 finished 56 seconds after it started,
# spent all ten attempts against a busy chat between 19:33:31 and 19:38:01, and its
# result was then lost for good — nothing anywhere redelivers a notice the notifier gave
# up on (reclaude-notify-backfill.py only records what happened, it never re-sends).
# So "busy" gets its own, longer budget; every other retryable error keeps the original.
BUSY_HTTP_STATUS = 409
BUSY_RETRY_ATTEMPTS = 40  # 40 x 30s = 20 minutes of someone else's turn
HTTP_TIMEOUT_SECONDS = 30
# Report sent to the chat: result.md, capped (the quota footer, the last line, always kept).
DIGEST_MAX_CHARS = 6000
# HaloWebUI shows the whole report on one page and accepts 20000 characters
# (NOTIFICATION_CONTENT_MAX_CHARS); a prompt the user asked for was cut at 6000 there.
HALOWEBUI_DIGEST_MAX_CHARS = 18000
DIRECT_PLATFORMS = ("telegram",)
HERMES_PYTHON = "/usr/local/lib/hermes-agent/venv/bin/python"
DELIVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner-deliver.py")
DELIVER_TIMEOUT_SECONDS = 180
# A detached run can end before the turn that launched it has replied; hold its report
# until that reply is in (RUNNER_LAUNCH_REPLY_WAIT seconds at most, 0 = never wait).
LAUNCH_REPLY_WAIT_SECONDS = 60
LAUNCH_REPLY_POLL_SECONDS = 2
# A cron job's own reply reaches the chat only after its turn ends and the worker delivers
# it; the job's execution stays claimed/running in cron/executions.db until then.
CRON_SESSION_RE = re.compile(r"^cron_(.+)_\d{8}_\d{6}$")
CRON_DELIVERY_WAIT_SECONDS = 180
STATUS_LABELS = {
    "success": ("✅", "已完成"),
    "question": ("❓", "等你决定"),
    "max_turns": ("⏸", "达到轮数上限"),
    "quota_blocked": ("⛔", "没有启动"),
    "timeout": ("⏱", "超时"),
}
SESSION_LABELS = {"reclaude": "Claude 会话", "cchclaude": "Claude 会话", "anyclaude": "Claude 会话", "officlaude": "Claude 会话",
                  "codex": "codex thread", "agy": "AGY conversation"}


def log(message):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    sys.stdout.write(f"{stamp} {message}\n")
    sys.stdout.flush()


def read_config_file(path):
    """The KEY=VALUE lines of *path* as a dict; {} when it cannot be read."""
    config = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        log(f"config {path} unreadable: {exc}")
    return config


def config_candidates(paths=None):
    """The config files to consult, most specific first.

    ``RECLAUDE_NOTIFY_CONFIG`` *replaces* the list instead of heading it: a test or a
    diagnostic run pointed at a throwaway config must never fall through to the
    production credentials when its own file is incomplete.
    """
    override = os.environ.get("RECLAUDE_NOTIFY_CONFIG", "").strip()
    if override:
        return [override]
    ordered, seen = [], set()
    for path in [p for p in (paths or []) if p] or [CONFIG_FILE]:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def load_config(paths=None, required=REQUIRED_CONFIG_KEYS):
    """Layer the candidate config files, the earliest file winning per key.

    Layering rather than "the first file that exists wins" is the point: codex-run.sh
    passes ``--config-file codex-runner.env --config-file reclaude-runner.env``, so an
    empty or half-written codex-runner.env used to shadow the working one and codex
    notifications were skipped silently while reclaude kept working.  A candidate now
    only supplies the keys it actually defines with a non-empty value, and one that
    supplies none of *required* is logged instead of ending the search.

    Returns ``(config, sources)``; *sources* lists every candidate with the key names it
    contributed — paths and key names only, never values.
    """
    config, sources = {}, []
    candidates = config_candidates(paths)
    for index, path in enumerate(candidates):
        if not os.path.exists(path):
            sources.append({"path": path, "exists": False, "provided": []})
            continue
        provided = []
        for key, value in read_config_file(path).items():
            if key in config or not value.strip():
                continue
            config[key] = value
            provided.append(key)
        sources.append({"path": path, "exists": True, "provided": sorted(provided)})
        if required and not any(key in provided for key in required):
            remaining = len(candidates) - index - 1
            log(
                f"config {path} exists but defines no usable {' / '.join(required)}; "
                + (f"reading the next candidate ({remaining} left)" if remaining
                   else "no further candidate to fall back on")
            )
    return config, sources


def missing_config_keys(config, required=REQUIRED_CONFIG_KEYS):
    """Which *required* keys the merged config still lacks."""
    return [key for key in required if not (config.get(key) or "").strip()]


def _json_object(value):
    try:
        value = json.loads(value or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _launch_args(command, tool_marker):
    """Recognize an actual runner invocation, never a mention inside --task."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        segments = [[]]
        for token in lexer:
            if token in {";", "&&", "||", "|", "&"}:
                segments.append([])
            else:
                segments[-1].append(token)
        for words in segments:
            if words and words[0] in {"bash", "sh"}:
                words = words[1:]
            if (
                len(words) >= 2
                and os.path.basename(words[0]) == os.path.basename(tool_marker)
                and words[1] in {"run", "answer"}
            ):
                return words[1:]
    except (TypeError, ValueError):
        pass
    return []


def _terminal_calls(raw_calls):
    try:
        calls = json.loads(raw_calls or "[]")
    except (TypeError, ValueError):
        return
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        if not isinstance(function, dict):
            continue
        if function.get("name") != "terminal":
            continue
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            arguments = _json_object(arguments)
        if isinstance(arguments, dict) and isinstance(arguments.get("command"), str):
            yield call.get("id") or call.get("call_id"), arguments["command"]


def find_origin(
    run_id,
    launch_task_file,
    parent_run,
    tool_marker="reclaude-run.sh",
    db_path=STATE_DB,
):
    """Resolve a unique launching session from tool-call/result provenance.

    Inline --task runs get their ID after launch, so the launch command cannot
    contain it. A process poll result contains the ID and process session_id;
    follow that ID to its terminal result, then the terminal call_id. Never
    choose the latest chat merely mentioning someone else's run.
    """
    since = time.time() - LOOKBACK_SECONDS
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        log(f"origin lookup skipped: cannot open state.db ({exc})")
        return None
    try:
        origins = set()
        banner = re.compile(
            r"(?:^|\n)==== (?:codex|reclaude|cchclaude|anyclaude|officlaude) run "
            + re.escape(run_id)
            + r" (?:started|finished)(?::|\s)"
        )
        placeholders = ", ".join("?" * len(PROVENANCE_TOOL_NAMES))
        results = db.execute(
            f"""select m.session_id, s.source, m.tool_name, m.tool_call_id, m.content
               from messages m join sessions s on s.id=m.session_id
               where m.role='tool' and m.timestamp >= ? and m.content like ?
                 and m.tool_name in ({placeholders})""",
            (since, f"%{run_id}%", *PROVENANCE_TOOL_NAMES),
        )
        for session_id, source, tool_name, call_id, raw in results:
            result = _json_object(raw)
            output = result.get("output_preview") or result.get("output") or ""
            if not isinstance(output, str) or not banner.search(output):
                continue
            terminal_call_ids = {call_id} if tool_name == "terminal" else set()
            process_id = result.get("session_id")
            if tool_name in PROCESS_TOOL_NAMES and isinstance(process_id, str):
                for terminal_call_id, content in db.execute(
                    """select tool_call_id, content from messages where session_id=?
                       and role='tool' and tool_name='terminal' and timestamp>=?
                       and content like ?""",
                    (session_id, since, f"%{process_id}%"),
                ):
                    if _json_object(content).get("session_id") == process_id:
                        terminal_call_ids.add(terminal_call_id)
            for (raw_calls,) in db.execute(
                "select tool_calls from messages where session_id=? and role='assistant' and timestamp>=?",
                (session_id, since),
            ):
                for launch_call_id, command in _terminal_calls(raw_calls):
                    if launch_call_id in terminal_call_ids and _launch_args(
                        command, tool_marker
                    ):
                        origins.add((session_id, source or ""))
        if origins:
            return next(iter(origins)) if len(origins) == 1 else None

        # Compatibility for launches with an explicit ID/task file or answer
        # command. Parse the arguments; SQL LIKE on the entire command also
        # matches diagnostic prompts quoting another run's ID.
        candidates = set()
        for session_id, source, raw_calls in db.execute(
            """
                select m.session_id, s.source, m.tool_calls
                from messages m join sessions s on s.id = m.session_id
                where m.role = 'assistant' and m.timestamp >= ?
                  and m.tool_calls like ?
                """,
            (since, f"%{tool_marker}%"),
        ):
            for _, command in _terminal_calls(raw_calls):
                args = _launch_args(command, tool_marker)
                if not args:
                    continue
                options = {}
                index = 2 if args[0] == "answer" else 1
                while index + 1 < len(args):
                    if args[index] == "--":
                        break
                    options[args[index]] = args[index + 1]
                    index += 2
                if (
                    options.get("--run-id") == run_id
                    or (
                        launch_task_file
                        and options.get("--task-file") == launch_task_file
                    )
                    or (parent_run and args[:2] == ["answer", parent_run])
                ):
                    candidates.add((session_id, source or ""))
        if len(candidates) == 1:
            return next(iter(candidates))
    except sqlite3.Error as exc:
        log(f"origin lookup failed: {exc}")
    finally:
        db.close()
    return None


def read_meta(run_dir):
    """meta.json of *run_dir* as a dict; {} when missing or unreadable."""
    try:
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def session_source(session_id, db_path=STATE_DB):
    """sessions.source for *session_id*; None when the row (or the DB) is missing."""
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        log(f"origin source lookup skipped: cannot open state.db ({exc})")
        return None
    try:
        row = db.execute("select source from sessions where id=?", (session_id,)).fetchone()
    except sqlite3.Error as exc:
        log(f"origin source lookup failed: {exc}")
        return None
    finally:
        db.close()
    return row[0] if row else None


def recorded_origin(meta, session_id="", platform="", db_path=STATE_DB):
    """The launching session as the runner recorded it, or None if it recorded none.

    The runner copies hermes's HERMES_SESSION_ID / HERMES_SESSION_PLATFORM into
    meta.json at launch, so the origin is known before the run even starts.
    state.db only supplies the authoritative `source`; when the row is missing
    (pruned history, unreadable DB) the recorded platform stands in for it, so a
    HaloWebUI run is still delivered.
    """
    session_id = (session_id or meta.get("origin_session_id") or "").strip()
    if not session_id:
        return None
    platform = (
        platform
        or meta.get("origin_platform")
        or meta.get("origin_source")
        or ""
    ).strip()
    source = session_source(session_id, db_path)
    if source == "cron" and platform in DIRECT_PLATFORMS:
        # A cron job's turn has no chat; runner-detach.py recorded the job's Telegram
        # delivery target as the platform, and that chat is where the report goes.
        return session_id, platform
    return session_id, (platform if source is None else source)


QUOTA_FOOTER_MARKER = "reclaude 额度"


def has_quota_footer(result_path, marker=QUOTA_FOOTER_MARKER):
    """result.md 末尾是否带着 runner 写入的实时额度页脚。"""
    try:
        with open(result_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 2000))
            return marker in handle.read().decode("utf-8", "replace")
    except OSError:
        return False


def build_prompt(
    run_id,
    status,
    run_dir,
    session_id,
    agent="reclaude",
    answer_command="reclaude-run.sh answer",
):
    result_path = os.path.join(run_dir, "result.md")
    session_label = SESSION_LABELS.get(agent, "agent session")
    lines = [
        f"[后台任务完成通知] {agent} 运行 {run_id} 已结束，状态：{status}，{session_label}：{session_id}。",
        f"请用 read_file 读取 {result_path}，把其中内容如实转述给我（保留文件、提交、验证结果和风险，不要缩写成一句话）。",
    ]
    if status == "question":
        lines.append(
            f"这次结束是因为它需要我做决定：请把 QUESTION 块原样转给我并等待我的回答；我回答后用 {answer_command} 续跑。"
        )
    elif status == "max_turns":
        lines.append(
            f"这次结束是因为达到了轮数上限：请说明进展，并问我是否用 {answer_command} 继续。"
        )
    elif status != "success":
        lines.append(
            f"这次没有正常完成：请一并读取 {os.path.join(run_dir, 'progress.log')} 的最后 40 行和 stderr.log，说明失败原因。"
        )
    if has_quota_footer(result_path):
        lines.append(
            "result.md 末尾有一行 reclaude 实时额度（剩余额度 / 下次重置时间），"
            "请把它一字不改地放在你回复的最后一行；如果那行写的是无法获取，也照实说，不要用旧数值代替。"
        )
    lines.append(f"不要重新执行原任务，不要启动新的 {agent} 运行。")
    return "\n".join(lines)


def direct_delivery_enabled():
    return os.environ.get("RUNNER_DIRECT_DELIVERY", "1").strip() != "0"


def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _tail_lines(path, count):
    lines = [line for line in _read_text(path).splitlines() if line.strip()]
    return lines[-count:]


def _strip_result_header(body, agent, run_id):
    """result.md without the runner's own header: "# <agent> run <id>", the status /
    session / model / turns / cost list, then a "---" line. The digest's first two lines
    already say all of it; repeated, it came right under them and used up the excerpt a
    later fast dispatch quotes. A result.md not starting with that header is kept whole
    (agy writes none, and a "---" in its text is part of the answer)."""
    lines = body.splitlines()
    if not lines or not re.match(rf"#\s+{re.escape(agent)}\s+run\s+{re.escape(run_id)}\s*$", lines[0].strip()):
        return body
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
        if line.strip() and not line.lstrip().startswith("- "):
            break  # not the header list: leave the text alone
    return body


def _cost_label(value):
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return ""
    return f"${cost:.2f}" if cost > 0 else ""


def _short_session(session_id):
    """A session UUID as its first 8 characters: the report line is read on a phone, the
    full id stays in the notice line and meta.json for resuming."""
    session_id = str(session_id or "")
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", session_id):
        return session_id[:8]
    return session_id


RUNNER_NOTE_HEADING = "**runner 提示**"


def _scheduled_resume_label(run_dir):
    """"04:31" (or "09-29 04:31" on another day) when the runner parked this run and will
    resume it by itself (meta.json auto_resume=scheduled); "" otherwise."""
    meta = read_meta(run_dir)
    if meta.get("auto_resume") != "scheduled":
        return ""
    match = re.match(r"(\d{4})-(\d{2}-\d{2}) (\d{2}:\d{2})", str(meta.get("auto_resume_at") or ""))
    if not match:
        return ""
    beijing_today = (datetime.datetime.now(datetime.timezone.utc)
                     + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    day = f"{match.group(1)}-{match.group(2)}"
    return match.group(3) if day == beijing_today else f"{match.group(2)} {match.group(3)}"


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _meta_epoch(value):
    """A meta.json time ("2026-10-02 22:56:14 +0800", or agy's ISO form) as epoch seconds."""
    text = str(value or "").strip()
    for parse in (lambda t: datetime.datetime.strptime(t, "%Y-%m-%d %H:%M:%S %z"),
                  lambda t: datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))):
        try:
            moment = parse(text)
        except ValueError:
            continue
        if moment.tzinfo is not None:
            return moment.timestamp()
    return None


def _chat_duration(ms):
    """'2 小时 3 分', '4 分 8 秒', '45 秒': the Telegram report's time, read on a phone."""
    seconds = int(ms) // 1000
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"
    return f"{minutes} 分 {sec} 秒" if minutes else f"{sec} 秒"


def _human_duration(ms):
    seconds = int(ms) // 1000
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{sec:02d}s" if hours else f"{minutes}m{sec:02d}s"


def _result_events(run_dir):
    """(count, summed num_turns, last total_cost_usd) of Claude Code's result events."""
    count, turns, cost = 0, 0, None
    try:
        handle = open(os.path.join(run_dir, "events.jsonl"), encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0, None
    with handle:
        for line in handle:
            if '"result"' not in line:
                continue
            event = _json_object(line)
            if event.get("type") != "result":
                continue
            count += 1
            turns += int(_number(event.get("num_turns")) or 0)
            cost = _number(event.get("total_cost_usd"))
    return count, turns, cost


def _session_cost(run_dir):
    """The session's running cost at the end of *run_dir* (Claude Code keeps counting on --resume)."""
    summary = _json_object(_read_text(os.path.join(run_dir, "result.json")))
    if "session_cost_usd" in summary:
        return _number(summary.get("session_cost_usd"))
    return _number(summary.get("total_cost_usd"))  # before 2026-10-03 it was the running total


def _cost_before(run_dir, session):
    """What the session had cost when *run_dir* started: the run it resumed, or 0.0."""
    meta = read_meta(run_dir)
    if not meta.get("resume_from"):
        return 0.0
    root, parent = os.path.dirname(os.path.abspath(run_dir)), meta.get("parent_run")
    for _ in range(50):
        if not parent or "/" in str(parent):
            break
        parent_dir = os.path.join(root, str(parent))
        summary = _json_object(_read_text(os.path.join(parent_dir, "result.json")))
        if session and summary.get("session_id") and summary["session_id"] != session:
            break
        value = _session_cost(parent_dir)
        if value is not None:
            return value
        parent = read_meta(parent_dir).get("parent_run")
    return 0.0


def run_figures(run_dir):
    """This run's own cost, turns and duration: {"cost", "turns", "duration_ms"} (None = unknown).

    reclaude-stream.py writes them into result.json since 2026-10-03 (session_cost_usd marks
    that).  An older result.json had the last result event's turns and duration (a run whose
    background agents reported back answers several prompts: 080100 said 21 turns · 9m12s for
    291 turns in 107 minutes) and the session's running cost (each continuation of
    20261001-173907 showed everything spent since its first run); those are worked out again
    from events.jsonl and meta.json."""
    summary = _json_object(_read_text(os.path.join(run_dir, "result.json")))
    if "session_cost_usd" in summary:
        return {"cost": _number(summary.get("total_cost_usd")), "turns": _number(summary.get("num_turns")),
                "duration_ms": _number(summary.get("duration_ms"))}
    figures = {"cost": _number(summary.get("total_cost_usd")), "turns": _number(summary.get("num_turns")),
               "duration_ms": _number(summary.get("duration_ms"))}
    count, turns, session_cost = _result_events(run_dir)
    if count > 1:
        meta = read_meta(run_dir)
        started, ended = _meta_epoch(meta.get("started_at")), _meta_epoch(meta.get("ended_at"))
        figures["turns"] = float(turns)
        if started is not None and ended is not None and ended >= started:
            figures["duration_ms"] = (ended - started) * 1000
    if session_cost is not None:
        figures["cost"] = session_cost
    if figures["cost"] is not None:
        before = _cost_before(run_dir, summary.get("session_id"))
        if before and figures["cost"] >= before:
            figures["cost"] = figures["cost"] - before
    return figures


def report_figures(run_dir):
    """The figures for the report: this run's, plus the runs the runner itself continued into it
    (max_turns, a quota wait: meta auto_resume=started) — one task, one report, its whole cost.
    {"cost", "turns", "duration_ms", "segments"}."""
    dirs, current = [run_dir], run_dir
    root = os.path.dirname(os.path.abspath(run_dir))
    for _ in range(50):
        parent = read_meta(current).get("parent_run")
        if not parent or "/" in str(parent):
            break
        parent_dir = os.path.join(root, str(parent))
        if read_meta(parent_dir).get("auto_resume") != "started":
            break
        dirs.insert(0, parent_dir)
        current = parent_dir
    total = {"cost": None, "turns": None, "duration_ms": None}
    for directory in dirs:
        figures = run_figures(directory)
        for key, value in figures.items():
            if value is not None:
                total[key] = (total[key] or 0.0) + value
    total["segments"] = len(dirs)
    return total


def build_digest(run_id, status, run_dir, session_id, agent="reclaude", chat=False,
                 max_chars=DIGEST_MAX_CHARS):
    """The report as the user reads it: a status line, result.md, and what to do next.

    *chat* (a Telegram report): the next step is spelled as the command that goes straight
    back to the run's session; a plain reply there takes a model turn (about a minute).

    The second line says who answered and what it took (model, turns, duration, cost,
    session); result.md's own header, which repeats that, is left out. Capped at
    *max_chars* (DIGEST_MAX_CHARS for a chat, more for HaloWebUI); a longer result keeps its
    head and the quota footer and points at result.md for the rest.
    """
    result_path = os.path.join(run_dir, "result.md")
    icon, label = STATUS_LABELS.get(status, ("❌", f"没有正常完成（{status}）"))
    resume_at = _scheduled_resume_label(run_dir) if status != "success" else ""
    if resume_at:
        # Parked until the quota resets, not failed: a ❌ here had the user wake up to
        # "没有正常完成（error）" for a run that went on by itself an hour later.
        icon, label = "⏳", f"额度用完，暂停中，约 {resume_at} 自动接着跑（不用管）"
    summary = _json_object(_read_text(os.path.join(run_dir, "result.json")))
    figures = report_figures(run_dir)
    details = []
    if summary.get("model"):
        # "claude-opus-5-5[1m]": the context-window tag is not something to read.
        details.append(re.sub(r"\[[^\]]*\]$", "", str(summary["model"])))
    if session_id and not chat:
        # Telegram: the session id helps nobody reading on a phone (the run id in the first
        # line is what "继续" and a quoted reply go by); HaloWebUI keeps it in 详情.
        details.append(f"{SESSION_LABELS.get(agent, 'session')} {_short_session(session_id)}")
    amounts = []
    if _cost_label(figures["cost"]):
        amounts.append(_cost_label(figures["cost"]))
    if figures["turns"]:
        amounts.append(f"{int(figures['turns'])} 轮")
    if figures["duration_ms"]:
        amounts.append(_chat_duration(figures["duration_ms"]) if chat else _human_duration(figures["duration_ms"]))
    elif summary.get("duration_human"):
        amounts.append(str(summary["duration_human"]))
    if figures["segments"] > 1 and amounts:
        # The amounts cover the whole task, not just the last stretch of it.
        details.append(f"自动续跑 {figures['segments'] - 1} 次")
        amounts[0] = "共 " + amounts[0]
    details += amounts
    lines = [f"{icon} {'官方 Claude' if agent == 'officlaude' else agent} 运行 {run_id} · {label}"]
    if details:
        lines.append(" · ".join(details))

    body = _strip_result_header(_read_text(result_path).strip(), agent, run_id)
    if resume_at and body.startswith("API Error") and RUNNER_NOTE_HEADING in body:
        # The raw upstream error ("… (not your usage limit) · 拼车 5 小时额度已用完 …") only
        # contradicts itself; the runner note below says the same thing plainly.
        body = body[body.index(RUNNER_NOTE_HEADING):]
    footer = ""
    if body:
        head, _, last = body.rpartition("\n")
        if QUOTA_FOOTER_MARKER in last:
            body, footer = head.rstrip(), last.strip()
            # reclaude-quota.py puts a rule above its line; without the line it dangles.
            body = re.sub(r"\n+-{3,}\s*$", "", body).rstrip()
    if len(body) > max_chars:
        rest = len(body) - max_chars
        body = (body[:max_chars].rstrip()
                + f"\n\n…（后面还有约 {rest} 字，完整结果在 {result_path}，需要时让 Hermes 读取）")
    lines += ["", body or f"（没有 result.md：{result_path}）"]

    # Telegram: the gateway hands a plain reply to this report straight back to the run
    # (runner_dispatch.awaited_report, up to an hour; the command works after that too).
    if status == "question" and chat:
        lines += ["", f"↩️ 直接回复你的决定，原样交回同一个会话续跑（不经过模型）；"
                      f"隔了一小时以上再回，发「/{agent} 你的决定」。"]
    elif status == "question":
        lines += ["", "↩️ 直接回复你的决定，Hermes 会在同一个会话里续跑。"]
    elif status == "max_turns" and chat:
        lines += ["", f"↩️ 回复「继续」（后面可以接着写要求），在同一个会话里接着跑（不经过模型）；"
                      f"隔了一小时以上再回，发 /{agent} 继续。"]
    elif status == "max_turns":
        lines += ["", "↩️ 回复「继续」，可以在同一个会话里接着跑。"]
    elif status == "success" and chat:
        # The gateway sends a reply that quotes this report back to the run (runner_dispatch
        # replied_report); a fresh message goes to Hermes' model, which may start something new.
        lines += ["", "↩️ 要接着做：引用回复这条报告写新要求，回到同一个会话（不经过模型）。"]
    elif status != "success" and "runner 提示" not in body:
        progress = _tail_lines(os.path.join(run_dir, "progress.log"), 8)
        if progress:
            lines += ["", "最后几步：", "```", *progress, "```"]
    if footer:
        lines += ["", footer]
    return "\n".join(lines)


def build_session_notice(run_id, status, run_dir, session_id, digest, agent="reclaude",
                         answer_command="reclaude-run.sh answer"):
    """What the chat's session records next to the delivered report (a user-role line)."""
    result_path = os.path.join(run_dir, "result.md")
    session_label = SESSION_LABELS.get(agent, "agent session")
    hint = ""
    if status in ("question", "max_turns"):
        hint = f"用户回复后用 {answer_command} {run_id} --task \"<用户的话>\" --detach 续跑同一个会话。"
    return (
        f"[后台任务完成通知] {agent} 运行 {run_id} 已结束，状态：{status}，{session_label}：{session_id}。\n"
        f"（下面的报告已由 runner 直接发给用户，不要再转述；用户接着问时以它为准，完整结果见 {result_path}。{hint}）\n\n"
        + digest
    )


def wait_for_launch_reply(session_id, since, db_path=STATE_DB, timeout=None):
    """Hold a fast run's report until the turn that launched it has replied.

    On 2026-09-24 an agy run finished 12 s after it started, so its report reached the
    Telegram chat before the launching turn's own "已启动" reply. That reply is the first
    assistant message without tool calls in the launching session after the run started.
    Returns the seconds waited, or None when it gave up (then the report goes anyway).
    """
    if timeout is None:
        try:
            timeout = float(os.environ.get("RUNNER_LAUNCH_REPLY_WAIT", LAUNCH_REPLY_WAIT_SECONDS))
        except ValueError:
            timeout = LAUNCH_REPLY_WAIT_SECONDS
    if timeout <= 0 or not session_id:
        return None
    started = time.monotonic()
    while True:
        try:
            db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                row = db.execute(
                    """select 1 from messages where session_id=? and role='assistant' and timestamp>=?
                       and (tool_calls is null or tool_calls in ('', '[]')) limit 1""",
                    (session_id, since),
                ).fetchone()
            finally:
                db.close()
        except sqlite3.Error:
            return None
        if row:
            return round(time.monotonic() - started, 1)
        if time.monotonic() - started >= timeout:
            return None
        time.sleep(LAUNCH_REPLY_POLL_SECONDS)


def wait_for_cron_delivery(job_id, db_path, timeout=None):
    """Hold a cron-launched run's report until the cron job has delivered its own reply.

    That reply ("已启动") is sent only after the cron turn ends and the worker cleans up,
    20-40 s after it is written: on 2026-10-01 run 20261001-090605-f4a96bf9 finished in
    10 s and its report reached Telegram before the job's reply. Waits while an execution
    of *job_id* is still claimed/running. Returns the seconds waited, or None when it gave
    up or cannot tell (then the report goes anyway).
    """
    if timeout is None:
        try:
            timeout = float(os.environ.get("RUNNER_LAUNCH_REPLY_WAIT", CRON_DELIVERY_WAIT_SECONDS))
        except ValueError:
            timeout = CRON_DELIVERY_WAIT_SECONDS
    if timeout <= 0 or not job_id:
        return None
    started = time.monotonic()
    while True:
        try:
            db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                row = db.execute(
                    "select 1 from executions where job_id=? and status in ('claimed','running') limit 1",
                    (job_id,),
                ).fetchone()
            finally:
                db.close()
        except sqlite3.Error:
            return None
        if not row:
            return round(time.monotonic() - started, 1)
        if time.monotonic() - started >= timeout:
            return None
        time.sleep(LAUNCH_REPLY_POLL_SECONDS)


def deliver_to_chat(platform, chat_id, session_id, run_dir, digest, notice):
    """Send *digest* to the chat through runner-deliver.py; record *notice* in its session.

    Returns the helper's JSON result (``success`` True/False). A send is never repeated
    once the helper exited 0, even if its output cannot be parsed.
    """
    message_file = os.path.join(run_dir, "delivery.md")
    notice_file = os.path.join(run_dir, "delivery-notice.md")
    for path, text in ((message_file, digest), (notice_file, notice)):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o600)
    command = [
        os.environ.get("HERMES_PYTHON", HERMES_PYTHON), DELIVER_SCRIPT,
        "--platform", platform, "--chat-id", chat_id, "--session-id", session_id or "",
        "--user-id", os.environ.get("HERMES_SESSION_USER_ID", ""),
        "--thread-id", os.environ.get("HERMES_SESSION_THREAD_ID", ""),
        "--message-file", message_file, "--mirror-file", notice_file,
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=DELIVER_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    result = {}
    for line in reversed((proc.stdout or "").splitlines()):
        result = _json_object(line)
        if result:
            break
    if proc.returncode == 0:
        result["success"] = True
    else:
        result["success"] = False
        result.setdefault("error", (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[-300:])
    return result


def post_notification(url, token, payload, user_agent="reclaude-runner/1.0"):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.status, response.read().decode("utf-8", "replace")[:500]


def deliver_direct(args, record, save, platform, chat_id, session_id, agent_session):
    """Report a detached run to its gateway chat, retrying like the HaloWebUI path."""
    digest = build_digest(args.run_id, args.status, args.run_dir, agent_session, agent=args.agent, chat=True)
    notice = build_session_notice(
        args.run_id, args.status, args.run_dir, agent_session, digest, agent=args.agent,
        answer_command=args.answer_command,
    )
    record["attempted"] = True
    record["delivery"] = f"{platform}-direct"
    record["chat_id"] = chat_id
    # An automatic continuation (reclaude's auto_chain) has no launching turn to wait for.
    if not read_meta(args.run_dir).get("auto_chain"):
        try:
            since = os.path.getmtime(os.path.join(args.run_dir, "task.md"))
        except OSError:
            since = time.time()
        cron = CRON_SESSION_RE.match(session_id or "")
        if cron:
            executions_db = os.path.join(os.path.dirname(args.state_db), "cron", "executions.db")
            waited = wait_for_cron_delivery(cron.group(1), executions_db)
            record["waited_for"] = "cron delivery"
        else:
            waited = wait_for_launch_reply(session_id, since, db_path=args.state_db)
            if waited is None and os.environ.get("RUNNER_LAUNCH_REPLY_WAIT", "").strip() in ("0", "0.0"):
                # A chain's next round or a resume by autopilot-supervisor: no turn launched
                # it, so nothing will reply first (waiting held each such report back 60 s).
                waited = "off"
        record["waited_for_launch_reply"] = waited if waited is not None else "gave up"
    attempt = 0
    while True:
        attempt += 1
        result = deliver_to_chat(platform, chat_id, session_id, args.run_dir, digest, notice)
        if result.get("success"):
            record["delivered_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            for key in ("message_id", "mirrored", "mirror_target"):
                if key in result:
                    record[key] = result[key]
            log(f"sent the report to {platform} chat {chat_id} (session record: "
                f"{result.get('mirror_target', '?')} mirrored={result.get('mirrored')})")
            save()
            return 0
        record["error"] = result.get("error", "")
        if result.get("uncertain"):
            # The request reached the platform and only its reply timed out: the message is
            # most likely in the chat already, and a resend would post it a second time.
            record["uncertain"] = True
            record["attempts"] = attempt
            log(f"attempt {attempt}: {platform} reply timed out after the request went out "
                f"({record['error'][:200]}); not resending, it most likely arrived "
                f"(session record: {result.get('mirror_target', '?')} mirrored={result.get('mirrored')})")
            save()
            return 0
        log(f"attempt {attempt}: {platform} delivery failed: {record['error'][:200]}"
            f"{' (will retry)' if attempt < RETRY_ATTEMPTS else ''}")
        if attempt >= RETRY_ATTEMPTS:
            break
        time.sleep(RETRY_INTERVAL_SECONDS)
    record["failed"] = True
    record["attempts"] = attempt
    log(f"giving up after {attempt} attempts; the report stays in {args.run_dir}/result.md")
    save()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--launch-task-file", default="")
    parser.add_argument("--parent-run", default="")
    parser.add_argument(
        "--agent",
        default="reclaude",
        help="agent label used in the notice text (reclaude, cchclaude, anyclaude, officlaude, codex, agy)",
    )
    parser.add_argument(
        "--runner-name",
        default="reclaude-runner",
        help="payload `source` and User-Agent of the notification",
    )
    parser.add_argument(
        "--tool-marker",
        default="reclaude-run.sh",
        help="substring identifying the launching tool call in state.db",
    )
    parser.add_argument(
        "--answer-command",
        default="reclaude-run.sh answer",
        help="command the follow-up turn should use to resume the session",
    )
    parser.add_argument(
        "--config-file",
        action="append",
        default=[],
        help="KEY=VALUE config path; repeatable, layered in order (earlier file wins "
        "per key, a file that defines nothing usable is skipped over)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=SCRIPT_VERSION,
        help="print the script version (install guards compare it before overwriting)",
    )
    parser.add_argument(
        "--origin-session",
        default="",
        help="hermes session that launched this run (HERMES_SESSION_ID at launch); "
        "defaults to meta.json's origin_session_id",
    )
    parser.add_argument(
        "--origin-platform",
        default="",
        help="platform of that session (HERMES_SESSION_PLATFORM at launch), used only "
        "when state.db has no row for it",
    )
    parser.add_argument(
        "--state-db", default=STATE_DB, help="Hermes state DB (always opened read-only)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve origin only; no HTTP request or run-file changes",
    )
    args = parser.parse_args()

    record = {
        "run_id": args.run_id,
        "status": args.status,
        "agent": args.agent,
        "attempted": False,
    }
    record_path = os.path.join(args.run_dir, "notify.json")

    def save():
        if args.dry_run:
            print(json.dumps({**record, "dry_run": True}, ensure_ascii=False))
            return
        try:
            with open(record_path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # What the runner recorded at launch beats anything reconstructed afterwards.
    meta = read_meta(args.run_dir)
    origin = recorded_origin(
        meta,
        args.origin_session,
        args.origin_platform,
        db_path=args.state_db,
    )
    resolved_by = "runner"
    if not origin:
        resolved_by = "state.db"
        origin = find_origin(
            args.run_id,
            args.launch_task_file,
            args.parent_run,
            tool_marker=args.tool_marker,
            db_path=args.state_db,
        )
    if not origin:
        record["skipped"] = "origin session not found"
        log(
            "notify skipped: the runner recorded no launching session and none could be "
            "found in state.db"
        )
        save()
        return 0
    session_id, source = origin
    record["origin_session"] = session_id
    record["origin_source"] = source
    record["origin_resolved_by"] = resolved_by
    log(f"origin session {session_id} (source={source or '?'}) resolved from {resolved_by}")
    # --detach (runner-detach.py) leaves this in the runner's environment, and nothing but
    # this notifier reports a detached run: there is no gateway watcher behind it.
    detached = bool(os.environ.get("RUNNER_DETACHED_LOG", "").strip())
    record["launch"] = "detached" if detached else "background"
    direct = (
        source in DIRECT_PLATFORMS and detached and direct_delivery_enabled()
    )
    chat_id = (meta.get("origin_chat_id") or os.environ.get("HERMES_SESSION_CHAT_ID") or "").strip()
    agent_session = meta.get("session_id", "") or meta.get("thread_id", "")
    if args.dry_run:
        record["chat_id"] = session_id if source == "api_server" else (chat_id if direct else None)
        if direct:
            record["would_deliver"] = f"{source}:{chat_id or '?'}"
        save()
        return 0
    if source != "api_server":
        if direct:
            if not chat_id:
                record["skipped"] = f"origin is {source} but the runner recorded no chat id"
                log(f"notify skipped: {record['skipped']}")
                save()
                return 0
            return deliver_direct(args, record, save, source, chat_id, session_id, agent_session)
        record["skipped"] = f"origin is {source}; gateway delivers"
        log(
            f"notify skipped: origin session {session_id} came from {source}; the gateway delivers there"
        )
        save()
        return 0

    config, config_sources = load_config(args.config_file)
    url = config.get("HALOWEBUI_NOTIFY_URL", "").strip()
    token = config.get("HALOWEBUI_NOTIFY_TOKEN", "").strip()
    record["config_files"] = config_sources
    missing = missing_config_keys(config)
    if missing:
        record["skipped"] = "notify not configured"
        record["config_missing"] = missing
        looked_at = ", ".join(entry["path"] for entry in config_sources) or "(none)"
        log(f"notify skipped: {' / '.join(missing)} not set in any config file ({looked_at})")
        save()
        return 0

    payload = {
        "chat_id": session_id,
        "source": args.runner_name,
        "run_id": args.run_id,
        "prompt": build_prompt(
            args.run_id,
            args.status,
            args.run_dir,
            agent_session,
            agent=args.agent,
            answer_command=args.answer_command,
        ),
    }
    if direct_delivery_enabled():
        # A HaloWebUI that knows mode=display shows the report as the reply, with no model
        # turn; an older one ignores these keys and runs the prompt above.
        digest = build_digest(args.run_id, args.status, args.run_dir, agent_session, agent=args.agent,
                              max_chars=HALOWEBUI_DIGEST_MAX_CHARS)
        payload["mode"] = "display"
        payload["content"] = digest
        # The user turn HaloWebUI shows above the report: the notice's first line.
        payload["notice"] = build_session_notice(
            args.run_id, args.status, args.run_dir, agent_session, "", agent=args.agent,
            answer_command=args.answer_command,
        ).splitlines()[0]
    record["attempted"] = True
    record["chat_id"] = session_id
    attempt = 0
    busy_attempts = 0
    other_attempts = 0
    while True:
        attempt += 1
        try:
            status, body = post_notification(
                url, token, payload, user_agent=f"{args.runner_name}/1.0"
            )
            record["http_status"] = status
            record["response"] = body
            record["delivered_at"] = datetime.datetime.now().isoformat(
                timespec="seconds"
            )
            log(f"notified HaloWebUI chat {session_id}: HTTP {status} {body[:160]}")
            save()
            return 0
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300] if exc.fp else ""
            record["http_status"] = exc.code
            record["response"] = body
            busy = exc.code == BUSY_HTTP_STATUS
            retryable = busy or exc.code == 429 or exc.code >= 500
            log(
                f"attempt {attempt}: HTTP {exc.code} {body[:160]}{' (will retry)' if retryable else ''}"
            )
            if not retryable:
                break
            if busy:
                busy_attempts += 1
            else:
                other_attempts += 1
        except (urllib.error.URLError, OSError) as exc:
            log(f"attempt {attempt}: {exc} (will retry)")
            other_attempts += 1
        # Each failure class spends its own budget, so a chat that stays busy cannot be
        # cut short by the budget meant for broken servers, and vice versa. Whichever
        # budget runs out first ends the loop, which keeps the total bounded.
        if busy_attempts >= BUSY_RETRY_ATTEMPTS or other_attempts >= RETRY_ATTEMPTS:
            break
        time.sleep(RETRY_INTERVAL_SECONDS)
    record["failed"] = True
    record["attempts"] = attempt
    record["busy_attempts"] = busy_attempts
    log(
        f"giving up after {attempt} attempts ({busy_attempts} of them a busy chat); "
        "the user can ask Hermes for the run result by run id"
    )
    save()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the runner
        log(f"notify crashed: {exc}")
        sys.exit(0)
