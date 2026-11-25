"""Read-only local evidence collector for HaloWebUI 精答 / 讨论台 (POST /v1/halo-teams/inspect).

Runs a short, stateless, strictly read-only Hermes AIAgent turn with:
- no memory reads/writes and no session DB persistence (skip_memory=True, _persist_disabled=True);
- only read_file, search_files and a strictly allowlisted read-only terminal guard (write_file,
  patch, process_manage and all mutating/secret-reading commands are stripped and blocked);
- mandatory multi-layer secret redaction before anything leaves the host.
"""

from __future__ import annotations

import os
import re
import shlex
import threading
import time
import uuid
from typing import Any, Optional

from .common import logger

SESSION_PREFIX = "halo-inspect-"
ALLOWED_TOOLS = frozenset({"read_file", "search_files", "terminal"})
MAX_QUESTION_CHARS = 4000
MAX_CONTEXT_CHARS = 2000
MAX_SUMMARY_CHARS = 4500
MAX_SOURCES = 20
MAX_ITERATIONS = 8
BUDGET_SECONDS = 75
MAX_CONCURRENT = 2
SEMAPHORE_WAIT_SECONDS = 2.0

_semaphore = threading.Semaphore(MAX_CONCURRENT)
_sessions_lock = threading.Lock()
_active_sessions: set[str] = set()

# Safe read-only commands allowed in terminal during local inspection.
_SIMPLE_READONLY_CMDS = frozenset({
    "ls", "ll", "tree", "find", "stat", "file", "wc", "du", "df", "readlink", "realpath",
    "pwd", "which", "cat", "head", "tail", "nl", "awk", "grep", "egrep", "fgrep", "rg",
    "sort", "uniq", "cut", "tr", "jq", "yq", "diff", "echo", "uname", "uptime", "free",
    "ps", "ss", "netstat", "lsof", "mount", "lsblk", "id", "whoami", "hostname", "date",
    "timedatectl", "journalctl", "true", "false",
})

_GIT_READONLY_SUBS = frozenset({
    "status", "log", "diff", "show", "rev-parse", "ls-files", "describe", "shortlog", "blame",
    "branch", "tag", "remote",
})
_GIT_MUTATE_FLAGS = frozenset({
    "-d", "-D", "-m", "-M", "--delete", "--move", "--force", "-f",
    "add", "remove", "rm", "rename", "set-url", "prune", "set-head", "update",
})

_DOCKER_READONLY_SUBS = frozenset({
    "ps", "logs", "inspect", "images", "info", "version", "stats", "top", "port",
})
_DOCKER_COMPOSE_READONLY = frozenset({"ps", "ls", "logs", "images", "config", "version", "top"})
_DOCKER_OBJ_READONLY = frozenset({"ls", "inspect"})

_SYSTEMCTL_READONLY = frozenset({
    "status", "is-active", "is-enabled", "is-failed", "list-units", "list-unit-files",
    "list-timers", "cat", "show",
})

_IP_READONLY = frozenset({"a", "addr", "address", "r", "route", "l", "link", "neigh", "rule"})

# Sensitive paths that must never be read or leaked to external models.
_SENSITIVE_PATH_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.env(?:\.(?!example$|sample$|template$)[A-Za-z0-9._-]+)?|"
    r"id_(?:rsa|ed25519|ecdsa|dsa)(?:\.[A-Za-z0-9_-]+)?|"
    r"authorized_keys|known_hosts|"
    r"antigravity-oauth-token|credentials(?:\.[A-Za-z0-9_-]+)?|"
    r"auth\.json|secrets?\.(?:ya?ml|json|toml|env|txt|conf)|"
    r"settings-[A-Za-z0-9._-]+\.json|"
    r"shadow|gshadow|master\.key"
    r")$"
    r"|(?:^|/)\.ssh/"
    r"|(?:^|/)\.claude-thirdparty/"
    r"|(?:^|/)\.gnupg/"
    r"|\.(?:pem|key|p12|pfx|jks|keystore)$",
    re.I,
)

# Shell redirections and command substitutions (except harmless 2>/dev/null and 2>&1).
_HARMLESS_REDIR_RE = re.compile(r"\b2\s*>\s*(?:/dev/null|&1)\b")
_DANGEROUS_SHELL_RE = re.compile(r"`|\$\(|<\(|>\(|>>|(?<!2)>|\btee\b")

# Aggressive defense-in-depth secret redaction patterns.
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.I,
)
_URL_CREDS_RE = re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@", re.I)
_KV_SECRET_RE = re.compile(
    r"""(?ix)
    (
        (?:["']?[A-Za-z0-9_.-]*(?:
            api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret|
            auth[_-]?token|access[_-]?token|refresh[_-]?token|bearer[_-]?token|
            bot[_-]?token|notify[_-]?token|session[_-]?secret|jwt[_-]?secret|
            webhook[_-]?secret|private[_-]?key|password|passwd|secret|token
        )[A-Za-z0-9_.-]*["']?)
        \s*[:=]\s*
    )
    (["']?)(\$\{[^}\n]+\}|[^\s,"'}\]\n]{4,})(\2)
    """
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{12,}")
_VENDOR_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|AIza[0-9A-Za-z_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
_SAFE_PLACEHOLDER_RE = re.compile(
    r"^(?:\$\{[^}]+\}|\$[A-Z0-9_]+|\[REDACTED\]|<[^>]+>|true|false|null|none|off|on|\d+)$",
    re.I,
)

INSPECT_SYSTEM_PROMPT = """你是 HaloWebUI 的只读本机取证员。你的唯一职责是在本机只读查看与用户问题直接相关的文件、配置、仓库代码或运行状态，整理出一份简明、准确、已脱敏的「本机现状事实摘要」，供后续的精答助手或讨论台多模型使用。

严格规则：
1. 只读：绝不修改、创建、删除任何文件，绝不重启服务或执行会改变系统状态的命令。
2. 严禁泄露凭据：不要读取 `.env`、私钥、OAuth token、凭据文件；若配置文件中出现密钥、token、密码、鉴权头，一律只保留键名并用 `[REDACTED]` 替代值，绝不原样输出任何凭据。
3. 快速克制：最多做几次精准查询即可收手（预算有限），拿到能回答问题的关键配置、文件路径、代码片段和运行状态就立即整理输出。
4. 只整理事实，不要替用户做冗长辩论或完整作答：用简体中文输出结构化要点（总计不超过 2500 字），每条写明核查到的文件路径、关键配置项或运行状态，未查到的项如实说明「未查到」，绝不编造。"""


def is_sensitive_path(path: Any) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    norm = text.replace("\\", "/")
    return bool(_SENSITIVE_PATH_RE.search(norm))


def _split_shell_segments(command: str) -> Optional[list[str]]:
    """Split a shell command on unquoted pipes / logical chains; None on unclosed quotes."""
    segments: list[str] = []
    buf: list[str] = []
    quote: Optional[str] = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(ch)
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            buf.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if command[i : i + 2] in ("&&", "||"):
            segments.append("".join(buf).strip())
            buf = []
            i += 2
            continue
        if ch in ("|", ";", "\n"):
            segments.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote is not None:
        return None
    segments.append("".join(buf).strip())
    return [s for s in segments if s]


def _check_segment(segment: str) -> tuple[bool, str]:
    cleaned = _HARMLESS_REDIR_RE.sub("", segment).strip()
    if not cleaned:
        return False, "empty command segment"
    if _DANGEROUS_SHELL_RE.search(cleaned):
        return False, "shell redirection, command substitution, or tee is not allowed in read-only inspect"
    try:
        tokens = shlex.split(cleaned)
    except ValueError as exc:
        return False, f"invalid shell syntax: {exc}"
    if not tokens:
        return False, "empty command"

    # Strip leading simple env assignments only if none (disallow mutating/printing env)
    cmd = os.path.basename(tokens[0])
    args = tokens[1:]

    for arg in args:
        if is_sensitive_path(arg):
            return False, f"reading sensitive path '{arg}' is blocked"

    if cmd == "cd":
        return True, ""

    if cmd in _SIMPLE_READONLY_CMDS:
        if cmd == "find":
            for flag in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprintf"):
                if flag in args:
                    return False, f"find {flag} is not allowed in read-only inspect"
        return True, ""

    if cmd == "sed":
        if any(a == "-i" or a.startswith("-i") or a.startswith("--in-place") for a in args):
            return False, "sed in-place edit is not allowed"
        return True, ""

    if cmd == "git":
        # Skip leading -C <dir> / --no-pager flags
        idx = 0
        while idx < len(args):
            a = args[idx]
            if a in ("-C", "--git-dir", "--work-tree"):
                idx += 2
                continue
            if a.startswith("-"):
                idx += 1
                continue
            break
        if idx >= len(args):
            return False, "git subcommand required"
        sub = args[idx]
        rest = args[idx + 1 :]
        if sub not in _GIT_READONLY_SUBS:
            return False, f"git {sub} is not allowed in read-only inspect"
        if sub in ("branch", "tag", "remote") and any(tok in _GIT_MUTATE_FLAGS for tok in rest):
            return False, f"mutating git {sub} is not allowed"
        return True, ""

    if cmd == "docker":
        if not args:
            return False, "docker subcommand required"
        sub = args[0]
        if sub in _DOCKER_READONLY_SUBS:
            if sub == "stats" and "--no-stream" not in args:
                return False, "docker stats requires --no-stream"
            return True, ""
        if sub == "compose":
            # skip -f <file> / -p <project>
            idx = 1
            while idx < len(args):
                if args[idx] in ("-f", "--file", "-p", "--project-name", "--project-directory"):
                    idx += 2
                    continue
                if args[idx].startswith("-"):
                    idx += 1
                    continue
                break
            if idx < len(args) and args[idx] in _DOCKER_COMPOSE_READONLY:
                return True, ""
            return False, "only read-only docker compose subcommands (ps/logs/ls/config/images) are allowed"
        if sub in ("network", "volume", "container", "image") and len(args) >= 2 and args[1] in _DOCKER_OBJ_READONLY:
            return True, ""
        return False, f"docker {sub} is not allowed in read-only inspect"

    if cmd == "systemctl":
        non_flags = [a for a in args if not a.startswith("-")]
        if non_flags and non_flags[0] in _SYSTEMCTL_READONLY:
            return True, ""
        return False, "only read-only systemctl queries (status/is-active/list-units/cat/show) are allowed"

    if cmd == "nginx":
        if args and all(a in ("-t", "-v", "-V") for a in args):
            return True, ""
        return False, "only nginx -t / -v / -V is allowed"

    if cmd == "ip":
        non_flags = [a for a in args if not a.startswith("-")]
        if non_flags and non_flags[0] in _IP_READONLY and not any(a in ("add", "del", "delete", "set", "flush", "replace") for a in non_flags[1:]):
            return True, ""
        return False, "only read-only ip queries are allowed"

    if cmd == "ufw":
        if args and args[0] == "status":
            return True, ""
        return False, "only ufw status is allowed"

    return False, f"command '{cmd}' is not in the read-only inspect allowlist"


def is_readonly_command(command: Any) -> tuple[bool, str]:
    text = str(command or "").strip()
    if not text:
        return False, "empty command"
    if len(text) > 1200:
        return False, "command too long for read-only inspect"
    segments = _split_shell_segments(text)
    if not segments:
        return False, "invalid or unclosed shell command"
    for seg in segments:
        ok, reason = _check_segment(seg)
        if not ok:
            return False, reason
    return True, ""


def redact_evidence(text: Any) -> str:
    """Multi-layer secret redaction before evidence leaves the host."""
    value = "" if text is None else str(text)
    if not value:
        return ""
    try:
        from agent.redact import redact_sensitive_text

        value = redact_sensitive_text(value, force=True)
    except Exception:
        pass
    value = _PEM_BLOCK_RE.sub("[REDACTED PRIVATE KEY]", value)
    value = _URL_CREDS_RE.sub(r"\1[REDACTED]@", value)
    value = _BEARER_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", value)
    value = _VENDOR_TOKEN_RE.sub("[REDACTED]", value)

    def _mask_kv(match: re.Match) -> str:
        val = match.group(3)
        if _SAFE_PLACEHOLDER_RE.match(val):
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(4)}"

    value = _KV_SECRET_RE.sub(_mask_kv, value)
    return value


def on_pre_tool_call(tool_name: Any = None, args: Any = None, **kwargs: Any) -> Optional[dict[str, Any]]:
    """Hermes pre_tool_call hook: strictly enforce read-only & no-secret access during inspect runs."""
    session_id = str(kwargs.get("session_id") or kwargs.get("task_id") or "")
    if not session_id or not session_id.startswith(SESSION_PREFIX):
        return None
    with _sessions_lock:
        if session_id not in _active_sessions:
            return None

    name = str(tool_name or "")
    if name not in ALLOWED_TOOLS:
        return {
            "action": "block",
            "message": f"Read-only local inspection blocked tool '{name}'. Only read_file, search_files and read-only terminal commands are allowed.",
        }
    parsed_args = args if isinstance(args, dict) else {}
    if name in ("read_file", "search_files"):
        for key in ("path", "file_path", "directory"):
            target = parsed_args.get(key)
            if target and is_sensitive_path(target):
                return {
                    "action": "block",
                    "message": f"Read-only local inspection blocked reading sensitive path '{target}'. Skip credentials/secrets and continue with non-sensitive config/code.",
                }
        return None

    if name == "terminal":
        command = parsed_args.get("command") or parsed_args.get("cmd") or ""
        ok, reason = is_readonly_command(command)
        if not ok:
            return {
                "action": "block",
                "message": f"Read-only local inspection blocked command ({reason}). Use read_file/search_files or a strictly read-only command instead.",
            }
    return None


def _build_agent(session_id: str, on_tool_start: Any):
    """Build a stateless, read-only AIAgent using Hermes' configured runtime."""
    from gateway.run import GatewayRunner, _resolve_gateway_model, _resolve_runtime_agent_kwargs
    from run_agent import AIAgent

    runtime_kwargs = _resolve_runtime_agent_kwargs()
    model = runtime_kwargs.pop("model", None) or _resolve_gateway_model()
    agent = AIAgent(
        model=model,
        **runtime_kwargs,
        max_iterations=MAX_ITERATIONS,
        run_budget_seconds=BUDGET_SECONDS,
        enabled_toolsets=["file", "terminal"],
        ephemeral_system_prompt=INSPECT_SYSTEM_PROMPT,
        session_id=session_id,
        platform="api_server",
        quiet_mode=True,
        verbose_logging=False,
        save_trajectories=False,
        skip_context_files=True,
        load_soul_identity=False,
        skip_memory=True,
        skip_background_review=True,
        session_db=None,
        fallback_model=GatewayRunner._load_fallback_model(),
        tool_start_callback=on_tool_start,
    )
    # Prevent any lazy open/write of canonical SessionDB.
    agent._persist_disabled = True
    # Physically remove write/process tools so the model never sees them.
    if isinstance(getattr(agent, "tools", None), list):
        agent.tools = [
            t for t in agent.tools
            if isinstance(t, dict) and (t.get("function") or {}).get("name") in ALLOWED_TOOLS
        ]
    if hasattr(agent, "valid_tool_names"):
        agent.valid_tool_names = set(ALLOWED_TOOLS) & set(agent.valid_tool_names or ALLOWED_TOOLS)
    return agent


def collect(question: str, *, context: str = "", mode: str = "answer") -> dict[str, Any]:
    """Run a bounded, read-only local evidence inspection and return redacted summary + sources."""
    from .teams import TeamError

    q = str(question or "").strip()[:MAX_QUESTION_CHARS]
    if not q:
        raise ValueError("question is required")
    ctx = str(context or "").strip()[:MAX_CONTEXT_CHARS]
    mode_label = "讨论台多模型讨论" if mode == "discuss" else "精答"

    if not _semaphore.acquire(timeout=SEMAPHORE_WAIT_SECONDS):
        raise TeamError(429, "本机只读取证并发已满，请稍后再试")

    session_id = f"{SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
    started = time.time()
    sources: list[dict[str, str]] = []
    seen_sources: set[tuple[str, str]] = set()

    def record_tool(call_id: Any = None, tool_name: Any = None, args: Any = None, *_a: Any, **_kw: Any) -> None:
        name = str(tool_name or "")
        parsed = args if isinstance(args, dict) else {}
        kind = ""
        target = ""
        if name == "read_file":
            kind = "file"
            target = str(parsed.get("path") or parsed.get("file_path") or "").strip()
        elif name == "search_files":
            kind = "search"
            path = str(parsed.get("path") or "").strip()
            pattern = str(parsed.get("pattern") or "").strip()
            target = f"{path}: {pattern}" if path and pattern else (path or pattern)
        elif name == "terminal":
            kind = "command"
            target = str(parsed.get("command") or parsed.get("cmd") or "").strip()
        if not kind or not target or is_sensitive_path(target):
            return
        safe_target = redact_evidence(target).replace("\n", " ").strip()[:180]
        key = (kind, safe_target)
        if key not in seen_sources and len(sources) < MAX_SOURCES:
            seen_sources.add(key)
            sources.append({"kind": kind, "path": safe_target})

    with _sessions_lock:
        _active_sessions.add(session_id)
    try:
        agent = _build_agent(session_id, record_tool)
        user_prompt = (
            f"目标场景：为 HaloWebUI 的「{mode_label}」收集本机真实文件/配置/运行状态事实（只读、必须脱敏）。\n\n"
            f"用户问题：\n{q}"
        )
        if ctx:
            user_prompt += f"\n\n对话背景（供定位相关项目/配置）：\n{ctx}"
        result = agent.run_conversation(user_message=user_prompt, task_id=session_id)
        raw_text = ""
        if isinstance(result, dict):
            raw_text = str(result.get("final_response") or result.get("response") or "")
        elif isinstance(result, str):
            raw_text = result
        summary = redact_evidence(raw_text).strip()
        truncated = len(summary) > MAX_SUMMARY_CHARS
        if truncated:
            summary = summary[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
        model_used = str(getattr(agent, "model", "") or "")
        duration_ms = int((time.time() - started) * 1000)
        logger.info(
            "halowebui-teams: local_inspect session=%s mode=%s sources=%d chars=%d ms=%d",
            session_id, mode, len(sources), len(summary), duration_ms,
        )
        return {
            "ok": True,
            "summary": summary,
            "sources": sources,
            "model": model_used,
            "truncated": truncated,
            "duration_ms": duration_ms,
        }
    finally:
        with _sessions_lock:
            _active_sessions.discard(session_id)
        _semaphore.release()
