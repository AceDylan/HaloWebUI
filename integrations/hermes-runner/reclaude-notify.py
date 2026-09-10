#!/usr/bin/env python3
"""reclaude-notify.py — tell HaloWebUI that a background agent run finished.

Shared by both runners: reclaude-run.sh (defaults) and codex-run.sh (which passes
--agent/--runner-name/--tool-marker/--answer-command/--config-file).

Hermes's API server cannot push a background completion back to a HaloWebUI
chat, so the runner does it itself: it finds the hermes session that launched
this run (read-only lookup in state.db), and if that session came from the API
server (HaloWebUI) it POSTs a completion notice to HaloWebUI's
/api/v1/hermes/notifications endpoint. HaloWebUI then appends a follow-up user
turn to the chat and starts a normal hermes run, which reads result.md and
reports. Telegram/QQ sessions are left alone: the gateway delivers those.

Config file (KEY=VALUE lines): /root/.hermes/reclaude-runner.env, or the first
existing path given with --config-file:
  HALOWEBUI_NOTIFY_URL=http://127.0.0.1:3000/api/v1/hermes/notifications
  HALOWEBUI_NOTIFY_TOKEN=<same value as HERMES_AGENT_NOTIFY_TOKEN in the container>

Always exits 0; never affects the runner's own exit code. Stdlib only.
"""
import argparse
import datetime
import json
import os
import re
import shlex
import sqlite3
import sys
import time
import urllib.error
import urllib.request

CONFIG_FILE = "/root/.hermes/reclaude-runner.env"
STATE_DB = "/root/.hermes/state.db"
LOOKBACK_SECONDS = 48 * 3600
RETRY_ATTEMPTS = 10
RETRY_INTERVAL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 30


def log(message):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    sys.stdout.write(f"{stamp} {message}\n")
    sys.stdout.flush()


def load_config(paths=None):
    """Load the first existing KEY=VALUE config file out of *paths*."""
    candidates = [p for p in (paths or []) if p] or [CONFIG_FILE]
    path = next((p for p in candidates if os.path.exists(p)), "")
    config = {}
    if not path:
        return config
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip().strip('"').strip("'")
    return config


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
            r"(?:^|\n)==== (?:codex|reclaude) run "
            + re.escape(run_id)
            + r" (?:started|finished)(?::|\s)"
        )
        results = db.execute(
            """select m.session_id, s.source, m.tool_name, m.tool_call_id, m.content
               from messages m join sessions s on s.id=m.session_id
               where m.role='tool' and m.timestamp >= ? and m.content like ?
                 and m.tool_name in ('terminal', 'process')""",
            (since, f"%{run_id}%"),
        )
        for session_id, source, tool_name, call_id, raw in results:
            result = _json_object(raw)
            output = result.get("output_preview") or result.get("output") or ""
            if not isinstance(output, str) or not banner.search(output):
                continue
            terminal_call_ids = {call_id} if tool_name == "terminal" else set()
            process_id = result.get("session_id")
            if tool_name == "process" and isinstance(process_id, str):
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
    session_label = "Claude 会话" if agent == "reclaude" else "codex thread"
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
        help="agent label used in the notice text (reclaude, codex)",
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
        help="KEY=VALUE config path; repeatable, first existing wins",
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

    config = {} if args.dry_run else load_config(args.config_file)
    url = config.get("HALOWEBUI_NOTIFY_URL", "").strip()
    token = config.get("HALOWEBUI_NOTIFY_TOKEN", "").strip()
    if not args.dry_run and (not url or not token):
        record["skipped"] = "notify not configured"
        log("notify skipped: HALOWEBUI_NOTIFY_URL / HALOWEBUI_NOTIFY_TOKEN not set")
        save()
        return 0

    origin = find_origin(
        args.run_id,
        args.launch_task_file,
        args.parent_run,
        tool_marker=args.tool_marker,
        db_path=args.state_db,
    )
    if not origin:
        record["skipped"] = "origin session not found"
        log("notify skipped: launching hermes session not found in state.db")
        save()
        return 0
    session_id, source = origin
    record["origin_session"] = session_id
    record["origin_source"] = source
    if args.dry_run:
        record["chat_id"] = session_id if source == "api_server" else None
        save()
        return 0
    if source != "api_server":
        record["skipped"] = f"origin is {source}; gateway delivers"
        log(
            f"notify skipped: origin session {session_id} came from {source}; the gateway delivers there"
        )
        save()
        return 0

    agent_session = ""
    try:
        with open(os.path.join(args.run_dir, "meta.json"), encoding="utf-8") as handle:
            agent_session = json.load(handle).get("session_id", "")
    except (OSError, ValueError):
        pass

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
    record["attempted"] = True
    record["chat_id"] = session_id
    for attempt in range(1, RETRY_ATTEMPTS + 1):
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
            retryable = exc.code in (409, 429) or exc.code >= 500
            log(
                f"attempt {attempt}: HTTP {exc.code} {body[:160]}{' (will retry)' if retryable else ''}"
            )
            if not retryable:
                break
        except (urllib.error.URLError, OSError) as exc:
            log(f"attempt {attempt}: {exc} (will retry)")
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_INTERVAL_SECONDS)
    record["failed"] = True
    log("giving up; the user can ask Hermes for the run result by run id")
    save()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the runner
        log(f"notify crashed: {exc}")
        sys.exit(0)
