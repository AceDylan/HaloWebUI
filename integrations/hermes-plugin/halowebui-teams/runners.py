"""Who can run a team member, as data: the runner registry, which runner a kind of task starts
with, the fallback order, and whether each runner can take work right now.

A member's *role* (assistant template, see ``assistants.py``) and the *runner* that executes its
tasks are independent: the same 后端开发 can run on cchclaude, codex or Hermes. This module only
knows runners.

Selection
  task kind → default runner (``KIND_DEFAULT``) → the first runner from there along
  ``FALLBACK_ORDER`` that is available. A user's explicit choice replaces the default but walks
  the same order when it is not available. Both are recorded, with the reason, wherever a
  different runner ends up doing the work.

Availability, layer by layer (the first failing layer is the reason shown):
  configured   in the registry and not switched off in the override file
  installed    its runner script and command exist (with the gateway's PATH)
  executable   ``<command> --version`` runs
  account      account / login / quota answer (reclaude carpool quota, the relay of
               cchclaude / anyclaude, ``codex login status``, agy's OAuth token)
  reachable    the same request got through (network)
  recent       its last run did not just fail for quota / login / network / a missing command
Results are cached for ``CACHE_SECONDS``; ``check(force=True)`` re-runs them.

``~/.hermes/halo-teams-runners.json`` (optional) overrides the defaults without code changes:
  {"order": [...], "kinds": {"code": "codex"}, "disabled": ["anyclaude"],
   "unavailable": {"cchclaude": "中转维护中"}}
"unavailable" marks a runner down by hand (maintenance) — it then falls back like any other
unavailable runner, with that reason.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .common import RUNNER_EXECUTORS, logger, redact

_HOME = os.environ.get("HALO_TEAMS_RUNS_HOME", "/root/.hermes")
_SCRIPTS = os.environ.get("HALO_TEAMS_RUNNER_SCRIPTS", "/root/.hermes/scripts")
OVERRIDE_FILE = Path(os.environ.get("HALO_TEAMS_RUNNERS_FILE", "/root/.hermes/halo-teams-runners.json"))
CACHE_SECONDS = int(os.environ.get("HALO_TEAMS_RUNNER_CHECK_TTL", "120") or 120)
PROBE_TIMEOUT = 10
RECENT_WINDOW = 1800        # a quota / login / network failure this recent marks the runner down
RECENT_RUNS_SCANNED = 6


@dataclass(frozen=True)
class RunnerSpec:
    name: str
    label: str              # short, for pickers and chips
    engine: str             # what actually runs: Claude Code / Codex / Antigravity / Hermes
    note: str               # one line: what it is good at / how it behaves
    native: bool = False    # Hermes: the gateway's Kanban dispatcher runs it
    script: str = ""        # <name>-run.sh in ~/.hermes/scripts
    command: str = ""       # the CLI it drives
    probe: str = ""         # account / reachability check, see _probe_account
    settings: str = ""      # Claude Code settings file of a relay (claude_settings probe)
    max_turns: bool = False  # the script takes --max-turns
    answer_sets_id: bool = False  # `answer` is told the new run id
    quota_wait: bool = False      # parks itself for a quota reset and continues the same session

    @property
    def runs_root(self) -> Path:
        env = self.name.upper()
        return Path(os.environ.get(f"HALO_TEAMS_{env}_RUNS_ROOT") or os.path.join(_HOME, f"{self.name}-runs"))

    @property
    def script_path(self) -> str:
        env = self.name.upper()
        return os.environ.get(f"HALO_TEAMS_{env}_RUNNER") or os.path.join(_SCRIPTS, self.script)


SPECS: tuple[RunnerSpec, ...] = (
    RunnerSpec("reclaude", "reclaude", "Claude Code", "Claude Code（拼车账号）：自主性最强，额度用完会自己等重置续跑",
               script="reclaude-run.sh", command="reclaude", probe="reclaude_quota", max_turns=True, quota_wait=True),
    RunnerSpec("cchclaude", "cchclaude", "Claude Code", "Claude Code（自己的 cch 中转）：后端 / 通用代码的首选",
               script="cchclaude-run.sh", command="cchclaude", probe="claude_settings",
               settings="/root/.claude/settings-cch.json", max_turns=True, quota_wait=True),
    RunnerSpec("anyclaude", "anyclaude", "Claude Code", "Claude Code（anyrouter 免费服务）：慢，适合不急的代码任务",
               script="anyclaude-run.sh", command="anyclaude", probe="claude_settings",
               settings="/root/.claude/settings-any.json", max_turns=True, quota_wait=True),
    RunnerSpec("codex", "codex", "Codex", "OpenAI Codex CLI：代码任务的另一条线，额度用完即失败",
               script="codex-run.sh", command="codex", probe="codex_login"),
    RunnerSpec("agy", "agy", "Antigravity", "Antigravity CLI：前端 / UI / UX / 视觉设计的首选；没有工具记录",
               script="agy-run.sh", command="agy", probe="agy_token", answer_sets_id=True),
    RunnerSpec("hermes", "Hermes", "Hermes", "Hermes 代理：联网搜索、调研、写作、汇总；永远是最后的兜底",
               native=True, probe="hermes"),
)
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = tuple(BY_NAME)
EXTERNAL = tuple(spec.name for spec in SPECS if not spec.native)
assert EXTERNAL == RUNNER_EXECUTORS, "common.RUNNER_EXECUTORS and runners.SPECS must list the same runners"
DEFAULT_ORDER = ("reclaude", "cchclaude", "anyclaude", "codex", "agy", "hermes")

# Task kinds the lead labels every member with, and the runner each starts from.
KINDS: dict[str, dict] = {
    "code": {"label": "后端 / 通用代码", "default": "cchclaude",
             "hint": "后端、服务端、脚本、接口、数据库、测试、代码评审、修 bug 等通用代码任务"},
    "ui": {"label": "前端 / UI / UX / 视觉", "default": "agy",
           "hint": "前端页面、组件、交互、样式、视觉设计、UX 走查"},
    "complex": {"label": "复杂任务", "default": "reclaude",
                "hint": "深度重构、跨多个项目修改、大规模架构调整、需要很强自主执行能力的长任务"},
    "research": {"label": "调研 / 分析", "default": "hermes",
                 "hint": "联网调研、资料搜集、数据分析、对比评估（不改代码）"},
    "writing": {"label": "写作 / 文档", "default": "hermes",
                "hint": "写文档、报告、方案、说明，汇总前面成员的产出"},
}
DEFAULT_KIND = "code"

FAIL_KINDS = {
    "missing": "命令或脚本不存在",
    "auth": "登录 / 密钥失效",
    "account": "账号或所在地区不可用",
    "quota": "额度或限流",
    "network": "网络或上游服务不可用",
}
# Failures that say "this runner cannot work now", not "the task went wrong" — they move the
# task to the next runner. Checked on the head of the error text only (a long final answer
# quoting these words must not count).
_FAIL_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("missing", re.compile(r"No such file or directory|command not found|could not start|not found in PATH|"
                           r"Exec format error|Permission denied \(.*exec", re.I)),
    ("account", re.compile(r"location is not supported|not (available|supported) in your (country|region|location)|"
                           r"unsupported[_ ](country|region|location)|FAILED_PRECONDITION|PERMISSION_DENIED|"
                           r"account.{0,20}(disabled|suspended|banned|deactivated)", re.I)),
    ("auth", re.compile(r"\b401\b|\b403\b|unauthori[sz]ed|invalid[ _-]?api[ _-]?key|authentication|"
                        r"not logged in|please (run )?.{0,12}login|token (has )?expired|API 密钥无效|"
                        r"设备.{0,6}解绑|账号.{0,8}(停用|不可用)", re.I)),
    ("quota", re.compile(r"quota|rate[ _-]?limit|\b429\b|usage limit|insufficient|余额|额度|credit|"
                         r"limit (reached|exceeded)|too many requests|resource[ _]exhausted", re.I)),
    ("network", re.compile(r"ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|Could not resolve|Connection (refused|reset)|"
                           r"network (error|is unreachable)|\b50[234]\b|\b529\b|overloaded|upstream|"
                           r"timed out connecting|SSL", re.I)),
)
# reclaude-run.sh classifies its own failures (reclaude-guard.py classify).
_RECLAUDE_FAIL_KIND = {
    "quota_window": "quota", "quota_reset": "quota", "model_limit": "quota",
    "device_unbound": "auth", "account_unavailable": "auth", "session_rebound": "auth",
    "upstream_transient": "network", "upstream_failed": "network",
}


# --- override file / order ------------------------------------------------------------------

_override_cache: dict[str, Any] = {"mtime": None, "data": {}}


def overrides() -> dict:
    try:
        mtime = OVERRIDE_FILE.stat().st_mtime
    except OSError:
        _override_cache.update(mtime=None, data={})
        return {}
    if _override_cache["mtime"] != mtime:
        try:
            data = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("halowebui-teams: %s is not valid JSON, ignored", OVERRIDE_FILE)
            data = {}
        _override_cache.update(mtime=mtime, data=data if isinstance(data, dict) else {})
    return _override_cache["data"]


def fallback_order() -> tuple[str, ...]:
    order = overrides().get("order")
    if isinstance(order, list):
        names = [n for n in order if n in BY_NAME]
        if names:
            # Hermes always ends the chain: it is the executor that never needs another account.
            return tuple(n for n in names if n != "hermes") + ("hermes",)
    return DEFAULT_ORDER


def kind_default(kind: str) -> str:
    custom = overrides().get("kinds")
    if isinstance(custom, dict) and custom.get(kind) in BY_NAME:
        return custom[kind]
    return KINDS.get(kind, KINDS[DEFAULT_KIND])["default"]


def normalize_kind(kind: Any) -> str:
    value = str(kind or "").strip().lower()
    aliases = {"backend": "code", "server": "code", "general": "code", "coding": "code", "review": "code",
               "test": "code", "qa": "code", "frontend": "ui", "design": "ui", "ux": "ui", "visual": "ui",
               "docs": "writing", "doc": "writing", "report": "writing", "analysis": "research",
               "data": "research"}
    value = aliases.get(value, value)
    return value if value in KINDS else ""


def chain_from(start: str) -> list[str]:
    """``start`` and every runner after it in the fallback order (Hermes last)."""
    order = list(fallback_order())
    if start not in order:
        return ["hermes"] if start != "hermes" else ["hermes"]
    return order[order.index(start):]


# --- probes -------------------------------------------------------------------------------------

def _gateway_path() -> str:
    return os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"


def _which(command: str) -> Optional[str]:
    extra = "/root/.local/bin"
    path = _gateway_path()
    if extra not in path.split(":"):
        path = path + ":" + extra
    return shutil.which(command, path=path)


def _run(argv: list[str], timeout: int = PROBE_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "PATH": _gateway_path() + ":/root/.local/bin"})
    except subprocess.TimeoutExpired:
        return 124, "超时"
    except OSError as exc:
        return 127, type(exc).__name__
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _layer(name: str, ok: bool, detail: str = "") -> dict:
    return {"layer": name, "ok": bool(ok), "detail": detail}


def _http_probe(url: str, headers: dict) -> tuple[str, str]:
    """('ok' | 'account' | 'quota' | 'unreachable', detail)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            return "ok", f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "account", f"中转拒绝了密钥（HTTP {exc.code}）"
        if exc.code == 429:
            return "quota", "中转返回 429（限流或额度用完）"
        if exc.code == 404:
            return "ok", "中转没有模型列表接口（HTTP 404），网络可达"
        if exc.code >= 500:
            return "unreachable", f"中转返回 HTTP {exc.code}"
        return "ok", f"HTTP {exc.code}"
    except Exception as exc:  # URLError, timeouts, SSL
        return "unreachable", f"连不上中转（{type(exc).__name__}）"


def _probe_account(spec: RunnerSpec) -> tuple[str, str, Optional[str]]:
    """(state, detail, resume_at): state ∈ ok | account | quota | unreachable."""
    if spec.probe == "hermes":
        return "ok", "Hermes 网关在运行", None
    if spec.probe == "reclaude_quota":
        guard = os.path.join(_SCRIPTS, "reclaude-guard.py")
        if not os.path.exists(guard):
            return "ok", "没有额度预检脚本，按可用处理", None
        rc, out = _run(["python3", guard, "preflight"], timeout=PROBE_TIMEOUT + 4)
        try:
            verdict = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return "ok", "额度预检没有结果，按可用处理", None
        if verdict.get("ok"):
            return "ok", redact(verdict.get("headline") or "额度充足", 160), None
        reason = verdict.get("reason")
        state = "account" if reason == "account_inactive" else "quota"
        return state, redact(verdict.get("headline") or "额度不足", 200), verdict.get("resume_at") or None
    if spec.probe == "claude_settings":
        try:
            env = (json.loads(Path(spec.settings).read_text(encoding="utf-8")).get("env") or {})
        except (OSError, ValueError):
            return "account", f"读不到设置文件 {spec.settings}", None
        base = str(env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
        key = str(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or "")
        if not base or not key:
            return "account", "设置文件里没有中转地址或密钥", None
        state, detail = _http_probe(base + "/v1/models", {
            "x-api-key": key, "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01",
            "User-Agent": "halowebui-teams/runner-check"})
        host = re.sub(r"^https?://", "", base).split("/")[0]
        return state, f"{host}：{detail}", None
    if spec.probe == "codex_login":
        rc, out = _run([_which("codex") or "codex", "login", "status"])
        if rc == 0:
            return "ok", "已登录", None
        return "account", "codex 没有登录（codex login status 失败）", None
    if spec.probe == "agy_token":
        token = Path(os.environ.get("HALO_TEAMS_AGY_TOKEN", "/root/.gemini/antigravity-cli/antigravity-oauth-token"))
        try:
            if token.stat().st_size > 0:
                return "ok", "已登录（有 OAuth 令牌）", None
        except OSError:
            pass
        return "account", "agy 没有登录（找不到 OAuth 令牌）", None
    return "ok", "", None


def _iso_or_text_ts(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            from datetime import datetime

            return datetime.strptime(text.replace("+00:00", "+0000"), fmt).timestamp()
        except ValueError:
            continue
    return None


def classify_failure(text: Any, failure_kind: Any = None, status: Any = None) -> Optional[str]:
    """'missing' | 'auth' | 'quota' | 'network' when a runner failed because it cannot work now;
    None for an ordinary failure of the task itself."""
    if status == "quota_blocked":
        return "quota"
    mapped = _RECLAUDE_FAIL_KIND.get(str(failure_kind or ""))
    if mapped:
        return mapped
    head = str(text or "")[:600]
    for kind, pattern in _FAIL_PATTERNS:
        if pattern.search(head):
            return kind
    return None


def run_failure_text(spec: RunnerSpec, run_dir: Path) -> str:
    """The error part of a finished run: result.json error/result head, else stderr tail."""
    parts = []
    try:
        data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("error", "result", "message"):
                if data.get(key):
                    parts.append(str(data[key])[:600])
                    break
    except (OSError, ValueError):
        pass
    if not parts:
        try:
            parts.append((run_dir / "stderr.log").read_bytes()[-1500:].decode("utf-8", "replace"))
        except OSError:
            pass
    return "\n".join(parts)


def _recent_failure(spec: RunnerSpec, now: float) -> Optional[tuple[str, str]]:
    """The newest finished run of *spec*: (kind, detail) if it failed in the last RECENT_WINDOW
    for a reason that says the runner itself is down."""
    root = spec.runs_root
    try:
        names = sorted((n for n in os.listdir(root) if re.match(r"^\d{8}-\d{6}-[0-9a-f]{8}", n)), reverse=True)
    except OSError:
        return None
    for name in names[:RECENT_RUNS_SCANNED]:
        try:
            meta = json.loads((root / name / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = meta.get("status")
        if status in ("running", "question") or (status == "stopped"):
            continue
        if status == "success":
            return None
        ended = _iso_or_text_ts(meta.get("ended_at")) or _iso_or_text_ts(meta.get("started_at"))
        if ended is None or now - ended > RECENT_WINDOW:
            return None
        kind = classify_failure(run_failure_text(spec, root / name), meta.get("failure_kind"), status)
        if not kind:
            return None
        clock = time.strftime("%H:%M", time.localtime(ended))
        return kind, f"最近一次运行（{clock}，{name}）因{FAIL_KINDS[kind]}失败"
    return None


def _check_one(spec: RunnerSpec, now: float) -> dict:
    layers: list[dict] = []
    out = {"name": spec.name, "label": spec.label, "engine": spec.engine, "note": spec.note,
           "native": spec.native, "quota_wait": spec.quota_wait, "available": False, "state": "ok",
           "reason": "", "resume_at": None, "checked_at": int(now), "layers": layers}

    def down(state: str, reason: str, resume_at: Optional[str] = None) -> dict:
        out.update(available=False, state=state, reason=reason, resume_at=resume_at)
        return out

    over = overrides()
    disabled = over.get("disabled") if isinstance(over.get("disabled"), list) else []
    if spec.name in disabled:
        layers.append(_layer("configured", False, "在 halo-teams-runners.json 里停用"))
        return down("not_configured", f"{spec.label} 已在 runner 设置里停用")
    layers.append(_layer("configured", True))
    manual = over.get("unavailable") if isinstance(over.get("unavailable"), dict) else {}
    if spec.name in manual:
        reason = redact(manual.get(spec.name) or "手动标记为不可用", 120)
        layers.append(_layer("manual", False, reason))
        return down("manual", f"{spec.label} 手动标记为不可用：{reason}")
    if not spec.native:
        script = spec.script_path
        if not os.access(script, os.X_OK):
            layers.append(_layer("installed", False, f"找不到 runner 脚本 {script}"))
            return down("not_installed", f"{spec.label} 没有安装（找不到 {os.path.basename(script)}）")
        command = _which(spec.command)
        if not command:
            layers.append(_layer("installed", False, f"PATH 里找不到 {spec.command}"))
            return down("not_installed", f"{spec.label} 没有安装（找不到命令 {spec.command}）")
        layers.append(_layer("installed", True, command))
        if spec.name != "reclaude":  # reclaude --version syncs its config; the quota check covers it
            rc, text = _run([command, "--version"])
            if rc != 0:
                layers.append(_layer("executable", False, redact(text, 120) or f"退出码 {rc}"))
                return down("not_executable", f"{spec.label} 无法运行（{spec.command} --version 退出码 {rc}）")
            layers.append(_layer("executable", True, redact(text.strip().splitlines()[0] if text.strip() else "", 60)))
    state, detail, resume_at = _probe_account(spec)
    if state == "unreachable":
        layers.append(_layer("account", True, "未知（网络不通）"))
        layers.append(_layer("reachable", False, detail))
        return down("unreachable", f"{spec.label} 连不上：{detail}")
    if state in ("account", "quota"):
        layers.append(_layer("account", False, detail))
        return down(state, f"{spec.label} {'额度不足' if state == 'quota' else '账号不可用'}：{detail}", resume_at)
    layers.append(_layer("account", True, detail))
    layers.append(_layer("reachable", True))
    if not spec.native:
        recent = _recent_failure(spec, now)
        if recent:
            kind, text = recent
            layers.append(_layer("recent", False, text))
            return down("recent_failure", f"{spec.label} {text}")
        layers.append(_layer("recent", True))
    out.update(available=True, state="ok", reason=detail or "可用")
    return out


_cache: dict[str, dict] = {}
_cache_overrides: dict[str, Any] = {}  # override-file mtime each cached result was computed with
_cache_lock = threading.Lock()


def _override_mtime() -> Optional[float]:
    try:
        return OVERRIDE_FILE.stat().st_mtime
    except OSError:
        return None


def check_live(names: Optional[list[str]] = None, *, force: bool = False) -> dict[str, dict]:
    """Availability of *names* (all runners by default), cached for CACHE_SECONDS — and
    recomputed at once when the override file changed (marking a runner down takes effect now)."""
    wanted = [n for n in (names or NAMES) if n in BY_NAME]
    now = time.time()
    ov = _override_mtime()
    with _cache_lock:
        stale = [n for n in wanted if force or n not in _cache or now - _cache[n]["checked_at"] > CACHE_SECONDS
                 or _cache_overrides.get(n, "unset") != ov]
    if stale:
        def one(name: str) -> dict:
            try:
                return _check_one(BY_NAME[name], now)
            except Exception as exc:  # a probe bug must not take the bridge down
                logger.warning("halowebui-teams: runner check %s failed", name, exc_info=True)
                return {"name": name, "label": BY_NAME[name].label, "available": BY_NAME[name].native,
                        "state": "ok" if BY_NAME[name].native else "check_failed",
                        "reason": f"检测出错（{type(exc).__name__}）", "checked_at": int(now), "layers": []}

        with ThreadPoolExecutor(max_workers=min(6, len(stale))) as pool:
            results = list(pool.map(one, stale))
        with _cache_lock:
            for result in results:
                _cache[result["name"]] = result
                _cache_overrides[result["name"]] = ov
    with _cache_lock:
        return {n: dict(_cache[n]) for n in wanted}


check = check_live  # the name everything calls (tests replace it with a fake)


def mark_down(name: str, state: str, reason: str) -> None:
    """Record a runtime failure in the cache so the next selection skips *name* right away."""
    if name not in BY_NAME or BY_NAME[name].native:
        return
    with _cache_lock:
        _cache_overrides[name] = _override_mtime()
        _cache[name] = {"name": name, "label": BY_NAME[name].label, "engine": BY_NAME[name].engine,
                        "note": BY_NAME[name].note, "native": False, "available": False, "state": state,
                        "reason": reason, "resume_at": None, "checked_at": int(time.time()), "layers": []}


def forget(name: Optional[str] = None) -> None:
    with _cache_lock:
        if name:
            _cache.pop(name, None)
        else:
            _cache.clear()


# --- selection ----------------------------------------------------------------------------------

def select(start: str, availability: Optional[dict] = None, *, skip: tuple = ()) -> dict:
    """Walk the fallback chain from *start*: {executor, start, chain, skipped:[{name, reason}]}.
    ``executor`` is None when nothing in the chain can run."""
    chain = chain_from(start if start in BY_NAME else "hermes")
    avail = availability if availability is not None else check(chain)
    skipped = []
    for name in chain:
        info = avail.get(name) or {}
        if name in skip:
            skipped.append({"name": name, "reason": f"{BY_NAME[name].label} 这次已失败"})
            continue
        if info.get("available") or (not info and BY_NAME[name].native):
            return {"executor": name, "start": start, "chain": chain, "skipped": skipped}
        skipped.append({"name": name, "reason": info.get("reason") or f"{BY_NAME[name].label} 不可用",
                        "state": info.get("state")})
    return {"executor": None, "start": start, "chain": chain, "skipped": skipped}


def select_after(start: str, current: str, availability: Optional[dict] = None) -> dict:
    """The next available runner *after* ``current`` on the chain that starts at ``start`` (a
    fallback only moves forward). Same shape as ``select``."""
    chain = chain_from(start if start in BY_NAME else current)
    rest = chain[chain.index(current) + 1:] if current in chain else chain_from(current)[1:]
    if not rest:
        return {"executor": None, "start": start, "chain": chain, "skipped": []}
    avail = availability if availability is not None else check(rest)
    skipped = []
    for name in rest:
        info = avail.get(name) or {}
        if info.get("available") or (not info and BY_NAME[name].native):
            return {"executor": name, "start": start, "chain": chain, "skipped": skipped}
        skipped.append({"name": name, "reason": info.get("reason") or f"{BY_NAME[name].label} 不可用",
                        "state": info.get("state")})
    return {"executor": None, "start": start, "chain": chain, "skipped": skipped}


def quota_wait_max() -> int:
    """How long a runner parked for a quota reset may wait before its task moves on (seconds)."""
    try:
        return max(0, int(overrides().get("quota_wait_max_seconds", 1200)))
    except (TypeError, ValueError):
        return 1200


def recommend(kind: str, availability: Optional[dict] = None) -> dict:
    """Default runner for a task kind and what will actually run it now."""
    kind = normalize_kind(kind) or DEFAULT_KIND
    default = kind_default(kind)
    picked = select(default, availability)
    return {"kind": kind, "default": default, **picked}


def fallback_reason(picked: dict) -> str:
    """'cchclaude 不可用：…' for the runners skipped before the one picked."""
    return "；".join(s["reason"] for s in picked.get("skipped") or [])


def public_registry(availability: Optional[dict] = None) -> dict:
    """What HaloWebUI shows: runners (with availability), kinds with their default, the order."""
    avail = availability if availability is not None else check()
    return {
        "runners": [{**{k: v for k, v in (avail.get(s.name) or {}).items() if k != "layers"},
                     "name": s.name, "label": s.label, "engine": s.engine, "note": s.note, "native": s.native,
                     "quota_wait": s.quota_wait, "layers": (avail.get(s.name) or {}).get("layers") or []}
                    for s in SPECS],
        "kinds": [{"value": k, "label": v["label"], "hint": v["hint"], "default": kind_default(k)} for k, v in KINDS.items()],
        "order": list(fallback_order()),
        "cache_seconds": CACHE_SECONDS,
    }
