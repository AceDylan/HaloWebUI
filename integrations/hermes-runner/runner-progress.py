#!/usr/bin/env python3
"""runner-progress.py — report a detached runner's progress to the HaloWebUI chat that launched it.

A runner started from HaloWebUI with `--detach` (reclaude, codex, agy) works for many
minutes after the hermes turn that launched it has ended; until its report arrives the
chat knows nothing, and asking hermes "查看进度" cost a two-minute model turn. This
reporter is started next to the runner by runner-detach.py (HaloWebUI launches only). It
reads the run directory — meta.json (status, started_at) and progress.log (the
`[tool#N] Tool: detail` lines) — and POSTs `mode=progress` to the notification endpoint
the completion report uses:

  * once as soon as the run directory exists ("started"),
  * once more about FIRST_UPDATE_SECONDS in, so a two-minute run shows what it is
    doing instead of only "已运行 N 分钟",
  * then whenever the step count has moved, at most once per MIN_GAP_SECONDS,
  * at least every --interval seconds (default 180, RUNNER_PROGRESS_INTERVAL) while
    nothing moves,
  * and once when meta.json says the run is over (the report itself follows from
    reclaude-notify.py and replaces the progress line in the chat).

The chat shows "reclaude · 已运行 12 分钟 · 第 198 步 · 最近：Bash: npm test".

Config: HALOWEBUI_NOTIFY_URL / HALOWEBUI_NOTIFY_TOKEN from the same KEY=VALUE files the
notifier reads (RECLAUDE_NOTIFY_CONFIG, then each --config-file, earlier file winning per
key; default /root/.hermes/reclaude-runner.env). Missing config or an unreachable
HaloWebUI never affects the runner: this process only reads the run directory.

Stdlib only.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SCRIPT_VERSION = "2026-09-26.2"
DEFAULT_CONFIG = "/root/.hermes/reclaude-runner.env"
REQUIRED_KEYS = ("HALOWEBUI_NOTIFY_URL", "HALOWEBUI_NOTIFY_TOKEN")
RUNNING_STATUSES = {"", "running", "queued", "starting", "waiting", "retrying"}
CHECK_SECONDS = 15
DEFAULT_INTERVAL = 180
FIRST_UPDATE_SECONDS = 40
MIN_GAP_SECONDS = 60
MAX_LIFETIME_SECONDS = 12 * 3600
MISSING_RUN_DIR_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 10
TAIL_BYTES = 64 * 1024
ACTIVITY_MAX_CHARS = 240

_TOOL_STEP_RE = re.compile(r"\[tool#(\d+)\]")
_LINE_PREFIX_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\s+\[[^\]]+\]\s*")
# Progress lines echo commands; a token in one must not end up on screen.
_SECRET_RES = (
    re.compile(r"(?i)\b(authorization:\s*bearer)\s+\S+"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|ACCESS_KEY)[A-Z0-9_]*)=\S+"
    ),
    re.compile(r"\b(sk|ghp|gho|github_pat|xox[bap])[-_][A-Za-z0-9_-]{10,}"),
)


def redact(text):
    for pattern in _SECRET_RES:
        text = pattern.sub(lambda m: f"{m.group(1)} [redacted]" if m.lastindex else "[redacted]", text)
    return text


def read_config(paths):
    config = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value and key not in config:
                        config[key] = value
        except OSError:
            continue
    return config


def config_paths(extra):
    paths = []
    override = os.environ.get("RECLAUDE_NOTIFY_CONFIG", "").strip()
    if override:
        paths.append(override)
    paths.extend(extra or [DEFAULT_CONFIG])
    return paths


def read_meta(run_dir):
    try:
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def parse_started_at(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(text)
    except ValueError:
        return None


def read_progress(run_dir):
    """(step, last activity) from the tail of progress.log."""
    path = os.path.join(run_dir, "progress.log")
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return None, ""
    steps = [int(value) for value in _TOOL_STEP_RE.findall(tail)]
    step = max(steps) if steps else None
    last = ""
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line or "[tool-result]" in line:
            continue
        last = _LINE_PREFIX_RE.sub("", line)
        break
    last = redact(" ".join(last.split()))
    if len(last) > ACTIVITY_MAX_CHARS:
        last = last[: ACTIVITY_MAX_CHARS - 1] + "…"
    return step, last


def build_payload(chat_id, run_id, agent, meta, run_dir, *, final=False):
    status = str((meta or {}).get("status") or "running").strip().lower()
    step, last = read_progress(run_dir)
    payload = {
        "chat_id": chat_id,
        "run_id": run_id,
        "mode": "progress",
        "agent": agent,
        "source": agent,
        "status": "finished" if final else "running",
        "started_at": parse_started_at((meta or {}).get("started_at")),
        "last_activity": last,
    }
    if step is not None:
        payload["step"] = step
    if final:
        payload["runner_status"] = status
    return payload


def post(url, token, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"runner-progress/{SCRIPT_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def run(args, *, sleep=time.sleep, clock=time.monotonic, send=post):
    config = read_config(config_paths(args.config_file))
    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        print(f"runner-progress: {' / '.join(missing)} not configured; not reporting", file=sys.stderr)
        return 0
    url, token = config["HALOWEBUI_NOTIFY_URL"], config["HALOWEBUI_NOTIFY_TOKEN"]
    run_dir = os.path.join(args.runs_root, args.run_id)
    started = clock()
    last_post = None
    last_step = None
    posts = 0
    while True:
        elapsed = clock() - started
        meta = read_meta(run_dir)
        if meta is None:
            if elapsed > MISSING_RUN_DIR_SECONDS:
                return 0
        else:
            status = str(meta.get("status") or "").strip().lower()
            if status not in RUNNING_STATUSES:
                send(url, token, build_payload(args.chat_id, args.run_id, args.agent, meta, run_dir, final=True))
                return 0
            payload = build_payload(args.chat_id, args.run_id, args.agent, meta, run_dir)
            since = None if last_post is None else clock() - last_post
            due = (
                since is None
                or since >= args.interval
                or (posts == 1 and elapsed >= FIRST_UPDATE_SECONDS)
                or (payload.get("step") != last_step and since >= MIN_GAP_SECONDS)
            )
            if due:
                send(url, token, payload)
                last_post, last_step, posts = clock(), payload.get("step"), posts + 1
        if elapsed > MAX_LIFETIME_SECONDS:
            return 0
        sleep(CHECK_SECONDS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--chat-id", required=True, help="the HaloWebUI chat (= hermes session id)")
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("RUNNER_PROGRESS_INTERVAL", DEFAULT_INTERVAL) or DEFAULT_INTERVAL),
    )
    parser.add_argument("--config-file", action="append", default=[])
    args = parser.parse_args(argv)
    args.interval = max(30.0, args.interval)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
