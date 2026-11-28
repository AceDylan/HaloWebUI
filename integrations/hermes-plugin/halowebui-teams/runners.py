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
unavailable runner, with that reason. "kinds" may also start a kind on offiagy (it then falls back
to agy, see ``AUTO_THEN``); "offiagy_model" is the model offiagy runs with (agy_runner.py reads it;
empty = AGY's own default). HaloWebUI's 「Hermes 模型」 page edits "kinds.ui" and "offiagy_model"
(``agy_prefs`` / ``save_agy_prefs``).
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
    family: str = "hermes"  # engine family: claude / codex / agy / hermes
    native: bool = False    # Hermes: the gateway's Kanban dispatcher runs it
    script: str = ""        # <name>-run.sh in ~/.hermes/scripts
    command: str = ""       # the CLI it drives
    probe: str = ""         # account / reachability check, see _probe_account
    settings: str = ""      # fallback settings file of a relay; the wrapper's own --settings wins
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
    RunnerSpec("officlaude", "官方 Claude", "Claude Code", "Claude 家族首选（官网 claude.ai 订阅 OAuth）；自动模式不可用时按 Claude 家族顺延，手动指定后不自动顺延",
               family="claude", script="officlaude-run.sh", command="officlaude", probe="claude_official", max_turns=True),
    RunnerSpec("cchclaude", "cchclaude", "Claude Code", "Claude 家族第二顺位（自建 cch 中转）",
               family="claude", script="cchclaude-run.sh", command="cchclaude", probe="claude_settings",
               settings="/root/.claude-thirdparty/settings-cch.json", max_turns=True, quota_wait=True),
    RunnerSpec("anyclaude", "anyclaude", "Claude Code", "Claude 家族第三顺位（anyrouter 免费服务，较慢）",
               family="claude", script="anyclaude-run.sh", command="anyclaude", probe="claude_settings",
               settings="/root/.claude-thirdparty/settings-any.json", max_turns=True, quota_wait=True),
    RunnerSpec("reclaude", "reclaude", "Claude Code", "Claude 家族第四顺位（拼车账号，额度用完会等重置续跑）",
               family="claude", script="reclaude-run.sh", command="reclaude", probe="reclaude_quota", max_turns=True, quota_wait=True),
    RunnerSpec("codex", "codex", "Codex", "OpenAI Codex CLI（按 codex 自身设置运行）：成块后端开发与独立代码审查，不跨家族顺延",
               family="codex", script="codex-run.sh", command="codex", probe="codex_login"),
    RunnerSpec("offiagy", "offiagy", "Antigravity", "AGY 家族首选（Google 账号官方登录）：独立方案 / 交互文案审稿 / 前端视觉，自动模式不可用时顺延 agy，手动指定后不自动顺延",
               family="agy", script="offiagy-run.sh", command="offiagy", probe="agy_official", answer_sets_id=True),
    RunnerSpec("agy", "agy", "Antigravity", "AGY 家族第二顺位（Hermes gemini-chat 网关）：offiagy 不可用时的同家族备选",
               family="agy", script="agy-run.sh", command="agy", probe="agy_token", answer_sets_id=True),
    RunnerSpec("hermes", "Hermes", "Hermes", "Hermes 代理：联网搜索、调研、写作、生图、汇总",
               family="hermes", native=True, probe="hermes"),
)
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = tuple(BY_NAME)
EXTERNAL = tuple(spec.name for spec in SPECS if not spec.native)
assert set(EXTERNAL) == set(RUNNER_EXECUTORS), "common.RUNNER_EXECUTORS and runners.SPECS must list the same runners"

# Default auto-selection order for tasks without their own chain. Explicit user / goal choices
# never auto-fallback: when unavailable, the task pauses for the user to pick another runner.
DEFAULT_FAMILIES: dict[str, tuple[str, ...]] = {
    "claude": ("officlaude", "cchclaude", "anyclaude", "reclaude"),
    "codex": ("codex",),
    "agy": ("offiagy", "agy"),
    "hermes": ("hermes",),
}
FAMILY_LABELS: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "agy": "AGY",
    "hermes": "Hermes",
}
DEFAULT_ORDER = tuple(name for chain in DEFAULT_FAMILIES.values() for name in chain)
NAMED_ONLY: tuple[str, ...] = ()
AUTO_THEN: dict[str, str] = {}

WORK_STEPS = ("plan", "plan_review", "dev", "frontend", "review")
WORK_STEP_META = (
    {"key": "plan", "label": "规划 / 方案顾问", "hint": "单规划时读代码写 .halo/plan.md；开启双方案/UI 互审时兼任独立对比方案与交互文案审稿", "optional": False},
    {"key": "plan_review", "label": "规划审阅 / 主控", "hint": "单规划开启审阅时核查定稿；开启双方案或 UI 互审时负责摸底、双方案合成与设计定稿", "optional": True},
    {"key": "dev", "label": "后端 / 全栈开发", "hint": "开启前后端分拆时负责成块后端与单元测试；关闭分拆时完成全部前后端改动与测试", "optional": False},
    {"key": "frontend", "label": "前端开发", "hint": "开启前后端分拆时读后端改动与 diff，完成前端实现、联调与前端测试（纯后端需求自动跳过）", "optional": True},
    {"key": "review", "label": "审阅修复", "hint": "通读完整前后端 diff 与开发回执，审阅并直接修掉问题、运行受影响测试确认通过", "optional": False},
)
WORK_EXTRA_FLAGS = (
    ("dual_plan", "双方案并行"),
    ("plan_approval", "方案拍板闸门"),
    ("ui_review", "UI 交互审稿"),
    ("split_dev", "前后端分拆开发"),
    ("codex_review", "交付前 Codex 2 轮审查"),
)
WORK_PRESET_KEYS = ("deep", "fast")
WORK_PRESET_LABELS = {"default": "默认工作流", "deep": "深度多模型", "fast": "快速精简"}
WORK_PRESETS_META = (
    {"key": "default", "preset": "", "command": "/work", "label": "默认工作流",
     "hint": "直接发 /work 需求 时使用，可自由组合模块与全部环节执行器"},
    {"key": "deep", "preset": "deep", "command": "/work 深度", "label": "深度多模型",
     "hint": "发 /work 深度 需求 时使用，适合复杂或高风险需求，支持独立配置"},
    {"key": "fast", "preset": "fast", "command": "/work 快速", "label": "快速精简",
     "hint": "发 /work 快速 需求 时使用，适合轻量改动与小修小补，支持独立配置"},
)


def _default_work_steps() -> dict[str, dict[str, Any]]:
    return {
        "plan": {"runner": "offiagy", "fallback": ["agy"]},
        "plan_review": {"runner": "officlaude", "fallback": ["cchclaude", "anyclaude", "reclaude"]},
        "dev": {"runner": "codex", "fallback": []},
        "frontend": {"runner": "offiagy", "fallback": ["agy"]},
        "review": {"runner": "officlaude", "fallback": ["cchclaude", "anyclaude", "reclaude"]},
    }


DEFAULT_WORK_PRESETS = {
    "deep": {
        "plan_review": True,
        "dual_plan": True,
        "plan_approval": True,
        "ui_review": True,
        "split_dev": True,
        "codex_review": True,
        "steps": _default_work_steps(),
    },
    "fast": {
        "plan_review": False,
        "dual_plan": False,
        "plan_approval": False,
        "ui_review": False,
        "split_dev": False,
        "codex_review": False,
        "steps": _default_work_steps(),
    },
}
DEFAULT_WORK_CONFIG = {
    "plan_review": True,
    "dual_plan": False,
    "plan_approval": False,
    "ui_review": False,
    "split_dev": True,
    "codex_review": False,
    "steps": _default_work_steps(),
    "presets": {
        "deep": {**DEFAULT_WORK_PRESETS["deep"], "steps": _default_work_steps()},
        "fast": {**DEFAULT_WORK_PRESETS["fast"], "steps": _default_work_steps()},
    },
}

# Task kinds the lead labels every member with, and the runner each starts from.
KINDS: dict[str, dict] = {
    "code": {"label": "Claude 主控 / 通用代码", "default": "officlaude",
             "hint": "主控调研、方案合成、前端实现、测试联调、通用代码、修 bug 等（按 Claude 家族顺序）"},
    "codex": {"label": "Codex 后端 / 审查", "default": "codex",
              "hint": "成块后端代码开发、独立代码审查（固定走 Codex，使用 Codex 自身配置）"},
    "ui": {"label": "AGY 方案 / UI / UX", "default": "offiagy",
           "hint": "独立方案评审、交互与文案走查、前端视觉与 UX（按 AGY 家族顺序）"},
    "complex": {"label": "复杂任务", "default": "officlaude",
                "hint": "深度重构、跨多个项目修改、大规模架构调整、需要强自主执行能力的长任务（按 Claude 家族顺序）"},
    "research": {"label": "调研 / 分析", "default": "hermes",
                 "hint": "联网调研、资料搜集、数据分析、对比评估（不改代码）"},
    "writing": {"label": "写作 / 文档", "default": "hermes",
                "hint": "写文档、报告、方案、说明，汇总前面成员的产出"},
    # Only a Hermes worker has the image tool (image_generate → gpt-image): its chain is Hermes alone.
    "image": {"label": "生图 / 插画 / 信息图", "default": "hermes",
              "hint": "要生成图片：插画、配图、海报、封面、信息图、示意图（用 gpt-image 生图，只有 Hermes 成员能调用）"},
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
    "auth_required": "auth", "official_limit": "quota",
    "quota_window": "quota", "quota_reset": "quota", "model_limit": "quota",
    "device_unbound": "auth", "account_unavailable": "auth", "session_rebound": "auth",
    "upstream_transient": "network", "upstream_failed": "network",
}


# --- override file / order ------------------------------------------------------------------

_override_cache: dict[str, Any] = {"mtime": None, "data": {}}
_override_lock = threading.RLock()


def overrides() -> dict:
    with _override_lock:
        try:
            mtime = OVERRIDE_FILE.stat().st_mtime_ns
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


def _read_override_for_write() -> dict:
    try:
        data = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError(f"{OVERRIDE_FILE} 不是合法 JSON，先手动修好再改") from None
    return data if isinstance(data, dict) else {}


def _write_override(data: dict) -> None:
    if data:
        tmp = OVERRIDE_FILE.with_name(OVERRIDE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, OVERRIDE_FILE)
    else:
        OVERRIDE_FILE.unlink(missing_ok=True)
    _override_cache.update(mtime=None, data={})


def _known_runners(raw: list) -> list[str]:
    return list(dict.fromkeys(n for n in raw if isinstance(n, str) and n in BY_NAME))


def _normalize_work_profile(
    raw: Any,
    default_profile: dict,
    *,
    strict: bool = False,
    scope_label: str = "",
    fallback_steps: Optional[dict] = None,
) -> dict:
    prefix = f"{scope_label}：" if scope_label else ""
    if strict and not isinstance(raw, dict):
        raise ValueError(f"{prefix}配置必须是对象")
    raw = raw if isinstance(raw, dict) else {}
    plan_review = raw.get("plan_review")
    if strict and not isinstance(plan_review, bool):
        raise ValueError(f"{prefix}规划后审阅开关必须为布尔值")
    flags: dict[str, bool] = {
        "plan_review": (plan_review is True) if "plan_review" in raw else bool(default_profile["plan_review"])
    }
    for key, label in WORK_EXTRA_FLAGS:
        val = raw.get(key)
        if strict and key in raw and not isinstance(val, bool):
            raise ValueError(f"{prefix}{label}开关必须为布尔值")
        flags[key] = (val is True) if key in raw else bool(default_profile[key])
    steps = raw.get("steps")
    if strict and (not isinstance(steps, dict) or set(steps) != set(WORK_STEPS)):
        raise ValueError(f"{prefix}请提供规划、规划审阅、后端/全栈开发、前端开发、审阅修复五个环节的配置")
    steps = steps if isinstance(steps, dict) else {}
    step_defaults = fallback_steps if isinstance(fallback_steps, dict) else default_profile["steps"]
    result = {}
    for meta in WORK_STEP_META:
        key, label = meta["key"], meta["label"]
        default = step_defaults.get(key) or default_profile["steps"][key]
        step = steps.get(key)
        step = step if isinstance(step, dict) else {}
        runner = step.get("runner")
        if not isinstance(runner, str) or runner not in BY_NAME:
            if strict:
                raise ValueError(f"{prefix}{label}的首选执行器不受支持")
            runner = default["runner"]
        fallback = step.get("fallback")
        if not isinstance(fallback, list):
            if strict:
                raise ValueError(f"{prefix}{label}的兜底必须是列表")
            fallback = list(default["fallback"])
        chain = [n for n in _known_runners(fallback) if n != runner]
        if strict and len(chain) != len(fallback):
            raise ValueError(f"{prefix}{label}的兜底只能包含有效且互不重复的执行器，不能包含首选执行器")
        result[key] = {"runner": runner, "fallback": chain}
    return {**flags, "steps": result}


def _normalize_work_config(raw: Any, *, strict: bool = False) -> dict:
    raw_dict = raw if isinstance(raw, dict) else {}
    base = _normalize_work_profile(raw_dict, DEFAULT_WORK_CONFIG, strict=strict)
    raw_presets = raw_dict.get("presets")
    if strict and "presets" in raw_dict:
        if not isinstance(raw_presets, dict) or set(raw_presets) != set(WORK_PRESET_KEYS):
            raise ValueError("presets 必须包含深度（deep）和快速（fast）两档配置")
    presets: dict[str, dict] = {}
    for key in WORK_PRESET_KEYS:
        default_p = DEFAULT_WORK_PRESETS[key]
        if isinstance(raw_presets, dict) and key in raw_presets:
            presets[key] = _normalize_work_profile(
                raw_presets.get(key),
                default_p,
                strict=strict,
                scope_label=WORK_PRESET_LABELS[key],
                fallback_steps=base["steps"],
            )
        else:
            # Inherit top-level steps when an older config has no explicit preset overrides.
            presets[key] = _normalize_work_profile(
                {},
                default_p,
                strict=False,
                fallback_steps=base["steps"],
            )
    return {**base, "presets": presets}


def work_config() -> dict:
    return _normalize_work_config(overrides().get("work"))


def work_config_public() -> dict:
    return {
        "config": work_config(),
        "defaults": _normalize_work_config(DEFAULT_WORK_CONFIG),
        "runners": [{"name": s.name, "label": s.label, "engine": s.engine, "family": s.family,
                     "note": s.note, "native": s.native} for s in SPECS],
        "steps_meta": [dict(meta) for meta in WORK_STEP_META],
        "presets_meta": [dict(meta) for meta in WORK_PRESETS_META],
    }


def save_work_config(payload: dict) -> dict:
    config = _normalize_work_config(payload, strict=True)
    with _override_lock:
        data = _read_override_for_write()
        if config == DEFAULT_WORK_CONFIG:
            data.pop("work", None)
        else:
            data["work"] = config
        _write_override(data)
        return work_config_public()


def family_of(name: Any) -> str:
    spec = BY_NAME.get(str(name or ""))
    return spec.family if spec else "hermes"


def is_auto(source: Any) -> bool:
    """Whether a member's runner was picked automatically (by its kind or by the decision model), so
    it falls back within its family. A runner the user, the goal or an applied lead suggestion named
    never does."""
    return (source or "auto") in ("auto", "decision")


def family_start(family: str) -> str:
    """The runner automatic work of *family* starts on: a kind's configured default in it, else
    the head of the family's order."""
    for kind in KINDS:
        name = kind_default(kind)
        if BY_NAME[name].family == family:
            return name
    return family_orders()[family][0]


def family_orders() -> dict[str, tuple[str, ...]]:
    """Per-family auto order, overridable via ``halo-teams-runners.json`` ``families``."""
    raw = overrides().get("families")
    out: dict[str, tuple[str, ...]] = {}
    for fam, default_chain in DEFAULT_FAMILIES.items():
        custom = raw.get(fam) if isinstance(raw, dict) else None
        if isinstance(custom, list):
            names = [n for n in custom if n in BY_NAME and BY_NAME[n].family == fam]
            if names:
                out[fam] = tuple(dict.fromkeys(names))
                continue
        out[fam] = default_chain
    return out


def fallback_order() -> tuple[str, ...]:
    order = overrides().get("order")
    if isinstance(order, list):
        names = [n for n in order if n in BY_NAME]
        if names:
            return tuple(dict.fromkeys(names))
    fams = family_orders()
    return tuple(n for fam in DEFAULT_FAMILIES for n in fams[fam])


def _startable(name: Any) -> bool:
    """Any configured runner can be a kind's starting runner."""
    return name in BY_NAME


def kind_default(kind: str) -> str:
    custom = overrides().get("kinds")
    if isinstance(custom, dict) and _startable(custom.get(kind)):
        return custom[kind]
    return KINDS.get(kind, KINDS[DEFAULT_KIND])["default"]


# --- AGY preferences (HaloWebUI 「Hermes 模型」 page) --------------------------------------------

AGY_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
OFFIAGY_MODELS_TTL = 3600
_offiagy_models_cache: dict[str, Any] = {"at": 0.0, "models": [], "error": ""}
_offiagy_models_lock = threading.Lock()


def _parse_offiagy_models(out: str) -> list[dict]:
    models: list[dict] = []
    seen: set[str] = set()
    for raw_line in out.splitlines():
        line = raw_line.rsplit("\r", 1)[-1].strip()
        if not line:
            continue
        if "\t" in line:
            model_id, _, name = line.partition("\t")
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=1)
            if len(parts) != 2:
                continue
            model_id, name = parts
        model_id, name = model_id.strip(), name.strip()
        if name and model_id not in seen and AGY_MODEL_RE.fullmatch(model_id):
            seen.add(model_id)
            models.append({"id": model_id, "name": name})
    return models


def offiagy_models(*, force: bool = False) -> list[dict]:
    """``offiagy models`` as [{id, name}] (cached for an hour; [] when it cannot be listed)."""
    now = time.time()
    if not force and _offiagy_models_cache["models"] and now - _offiagy_models_cache["at"] < OFFIAGY_MODELS_TTL:
        return _offiagy_models_cache["models"]
    with _offiagy_models_lock:
        now = time.time()
        if not force and _offiagy_models_cache["models"] and now - _offiagy_models_cache["at"] < OFFIAGY_MODELS_TTL:
            return _offiagy_models_cache["models"]
        command = _which("offiagy") or "offiagy"
        try:
            proc = subprocess.run(
                [command, "models"],
                capture_output=True,
                text=True,
                timeout=40,
                env={**os.environ, "PATH": _gateway_path() + ":/root/.local/bin"},
            )
            out = proc.stdout or ""
            rc = getattr(proc, "returncode", 0)
            stderr = getattr(proc, "stderr", "") or ""
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("halowebui-teams: offiagy models failed: %s", exc)
            _offiagy_models_cache["error"] = f"无法运行 offiagy models：{redact(str(exc), 120)}"
            return _offiagy_models_cache["models"]
        models = _parse_offiagy_models(out)
        if models:
            _offiagy_models_cache.update(at=time.time(), models=models, error="")
            return models
        detail = failure_line(stderr) or (f"退出码 {rc}" if rc else "返回列表为空")
        _offiagy_models_cache["error"] = f"未获取到 offiagy 模型列表（{detail}）"
        return _offiagy_models_cache["models"]


def agy_prefs(*, refresh: bool = False) -> dict:
    data = overrides()
    model = data.get("offiagy_model")
    models = offiagy_models(force=refresh)
    return {
        "ui_runner": kind_default("ui"),
        "ui_runner_default": KINDS["ui"]["default"],
        "ui_chain": chain_from(kind_default("ui"), auto=True),
        "ui_choices": [{"name": n, "label": BY_NAME[n].label, "note": BY_NAME[n].note,
                        "chain": chain_from(n, auto=True)} for n in NAMES if _startable(n)],
        "offiagy_model": model if isinstance(model, str) and AGY_MODEL_RE.fullmatch(model) else "",
        "offiagy_models": models,
        "offiagy_models_at": int(_offiagy_models_cache["at"]) if _offiagy_models_cache["at"] else 0,
        "offiagy_models_error": str(_offiagy_models_cache.get("error") or ""),
    }


def save_agy_prefs(ui_runner: Any = None, offiagy_model: Any = None) -> dict:
    """Write ``kinds.ui`` / ``offiagy_model`` into the override file (other keys untouched).
    ``ui_runner`` equal to the built-in default drops the override; ``offiagy_model`` "" too."""
    with _override_lock:
        data = _read_override_for_write()
        if ui_runner is not None:
            if not _startable(ui_runner):
                raise ValueError(f"界面任务不能从 {ui_runner} 开始")
            kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
            if ui_runner == KINDS["ui"]["default"]:
                kinds.pop("ui", None)
            else:
                kinds["ui"] = ui_runner
            if kinds:
                data["kinds"] = kinds
            else:
                data.pop("kinds", None)
        if offiagy_model is not None:
            model = str(offiagy_model).strip()
            if model and not AGY_MODEL_RE.fullmatch(model):
                raise ValueError("offiagy 模型不是合法的模型 ID")
            if model:
                data["offiagy_model"] = model
            else:
                data.pop("offiagy_model", None)
        _write_override(data)
    return agy_prefs()


def normalize_kind(kind: Any) -> str:
    value = str(kind or "").strip().lower()
    aliases = {"backend": "code", "server": "code", "general": "code", "coding": "code", "review": "codex",
               "codex": "codex", "gpt": "codex",
               "test": "code", "qa": "code", "frontend": "ui", "design": "ui", "ux": "ui", "visual": "ui",
               "docs": "writing", "doc": "writing", "report": "writing", "analysis": "research",
               "data": "research", "illustration": "image", "picture": "image", "img": "image", "art": "image",
               "poster": "image", "infographic": "image"}
    value = aliases.get(value, value)
    return value if value in KINDS else ""


def chain_from(start: str, *, auto: bool = False) -> list[str]:
    """Runners to try starting at *start*.

    * ``auto=False`` (explicitly specified by the user or goal): **never auto-fallback**. Returns
      ``[start]`` only, so when it is unavailable the task pauses and lets the user choose.
    * ``auto=True`` (automatic kind/family selection): walks only within *start*'s engine family
      (Claude: officlaude→cchclaude→anyclaude→reclaude; AGY: offiagy→agy; Codex: codex; Hermes:
      hermes) — or an explicit ``order`` override when configured without ``families``.
    """
    if start not in BY_NAME:
        return ["hermes"]
    if not auto:
        return [start]
    over = overrides()
    if isinstance(over.get("order"), list) and not isinstance(over.get("families"), dict):
        order = [n for n in over["order"] if n in BY_NAME]
        if start in order:
            return order[order.index(start):]
    fam_chain = list(family_orders().get(BY_NAME[start].family, (start,)))
    if start in fam_chain:
        return fam_chain[fam_chain.index(start):]
    return [start]


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


def _http_probe(url: str, headers: dict, proxy: str = "") -> tuple[str, str]:
    """('ok' | 'account' | 'quota' | 'unreachable', detail)."""
    req = urllib.request.Request(url, headers=headers)
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=PROBE_TIMEOUT) as resp:
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


_SETTINGS_FLAG = re.compile(r"--settings[ =]+[\"']?([^\s\"']+)")


def _settings_file(spec: RunnerSpec) -> str:
    """The settings file the runner really uses: the ``--settings`` its wrapper passes (wrappers
    move, e.g. ~/.claude → ~/.claude-thirdparty), else the registry default."""
    command = _which(spec.command)
    if command:
        try:
            match = _SETTINGS_FLAG.search(Path(command).read_text(encoding="utf-8", errors="replace")[:20000])
        except OSError:
            match = None
        if match and os.path.isfile(match.group(1)):
            return match.group(1)
    return spec.settings


# --- which model a runner runs with ---------------------------------------------------------------

_EFFORT_KEY = re.compile(r'"effortLevel"\s*:\s*"([A-Za-z]+)"')
CODEX_CONFIG = Path(os.environ.get("HALO_TEAMS_CODEX_CONFIG") or
                    os.path.join(os.environ.get("CODEX_HOME") or "/root/.codex", "config.toml"))
AGY_SETTINGS = Path(os.environ.get("HALO_TEAMS_AGY_SETTINGS", "/root/.gemini/antigravity-cli/settings.json"))


def _json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def with_effort(model: str, effort: str) -> str:
    """「gpt-6.2-sol (xhigh)」; a label that already says its effort (AGY's 「… (XHigh)」) stays."""
    model, effort = str(model or "").strip(), str(effort or "").strip()
    if not model or not effort or effort.lower() in model.lower():
        return model
    return f"{model} ({effort})"


def _claude_effort(spec: RunnerSpec) -> str:
    """The effort a Claude runner starts with: the inline ``--settings`` JSON of its wrapper
    (officlaude), else the settings file the wrapper passes (cchclaude / anyclaude)."""
    command = _which(spec.command)
    try:
        text = Path(command).read_text(encoding="utf-8", errors="replace")[:20000] if command else ""
    except OSError:
        text = ""
    if match := _EFFORT_KEY.search(text):
        return match.group(1)
    settings = _settings_file(spec)
    return str(_json_file(Path(settings)).get("effortLevel") or "") if settings else ""


def _codex_config() -> tuple[str, str]:
    import tomllib

    try:
        data = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    return str(data.get("model") or ""), str(data.get("model_reasoning_effort") or "")


def _run_model(run_dir: Optional[Path]) -> str:
    """The model a run reported: result.json (Claude, AGY), meta.json (AGY started with --model),
    the stream's init event (Claude while it is still running)."""
    if run_dir is None:
        return ""
    for name in ("result.json", "meta.json"):
        if model := str(_json_file(run_dir / name).get("model") or ""):
            return model
    try:
        with (run_dir / "events.jsonl").open(encoding="utf-8") as events:
            first = json.loads(events.readline() or "{}")
    except (OSError, ValueError):
        return ""
    return str(first.get("model") or "") if isinstance(first, dict) and first.get("type") == "system" else ""


def model_label(name: str, run_dir: Optional[Path] = None) -> tuple[str, bool]:
    """(label, final): the model an external runner works with and its thinking effort, e.g.
    「claude-opus-5-5 (high)」「gpt-6.2-sol (xhigh)」「Gemini 4 Neon (XHigh)」. ``final``: the run
    itself said which model (or the runner has no other source), so a later look adds nothing.
    ("", False) while it is not known yet."""
    spec = BY_NAME.get(name)
    if spec is None or spec.native:
        return "", False
    if spec.family == "codex":
        model, effort = _codex_config()
        return with_effort(model, effort), True
    reported = _run_model(run_dir)
    if spec.family == "claude":
        return with_effort(reported, _claude_effort(spec)), bool(reported)
    # AGY: the model it was started with, else the one AGY itself has selected (its label carries the effort)
    configured = str(_json_file(OVERRIDE_FILE).get("offiagy_model") or "") if name == "offiagy" else ""
    model = reported or configured or str(_json_file(AGY_SETTINGS).get("model") or "")
    return model, bool(run_dir is not None and (run_dir / "meta.json").exists())


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
        settings = _settings_file(spec)
        try:
            env = (json.loads(Path(settings).read_text(encoding="utf-8")).get("env") or {})
        except (OSError, ValueError):
            return "account", f"读不到设置文件 {settings}", None
        base = str(env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
        key = str(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or "")
        if not base or not key:
            return "account", "设置文件里没有中转地址或密钥", None
        state, detail = _http_probe(base + "/v1/models", {
            "x-api-key": key, "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01",
            "User-Agent": "halowebui-teams/runner-check"},
            proxy=str(env.get("HTTPS_PROXY") or env.get("https_proxy") or ""))
        host = re.sub(r"^https?://", "", base).split("/")[0]
        return state, f"{host}：{detail}", None
    if spec.probe == "claude_official":
        # The wrapper selects ~/.claude-official; auth status is a read-only local probe.
        rc, out = _run([_which("officlaude") or "officlaude", "auth", "status", "--json"])
        try:
            auth = json.loads(out)
        except (ValueError, TypeError):
            return "account", "官方 Claude 登录状态无法确认；请在服务器终端运行 officlaude 并输入 /login", None
        if not (rc == 0 and isinstance(auth, dict) and auth.get("loggedIn") and auth.get("authMethod") == "claude.ai"):
            return "account", "官方 Claude 未登录或登录已失效：在服务器终端运行 officlaude，输入 /login 完成浏览器授权", None
        quota_script = os.path.join(_SCRIPTS, "officlaude-quota.py")
        if os.path.isfile(quota_script):
            qrc, qout = _run(["python3", quota_script, "--timeout", "8"], timeout=PROBE_TIMEOUT)
            qline = (qout or "").strip().splitlines()[-1] if (qout or "").strip() else ""
            if qrc == 0 and qline and "⚠️" not in qline:
                clean = qline.replace("**", "").strip()
                # Flag quota exhausted when either 5h or weekly window shows 0% remaining.
                # Several windows used up: the last one listed (weekly) resets last.
                used_up = re.findall(r"剩余\s*0%(?:（([^）]+?)\s*重置）)?", clean)
                if used_up:
                    return "quota", redact(clean, 200), used_up[-1] or None
                return "ok", redact(clean, 180), None
        return "ok", "官方 Claude 已登录（claude.ai 订阅 OAuth）；实际请求以 runner 结果为准", None
    if spec.probe == "codex_login":
        rc, out = _run([_which("codex") or "codex", "login", "status"])
        if rc == 0:
            return "ok", "已登录", None
        return "account", "codex 没有登录（codex login status 失败）", None
    if spec.probe == "agy_token":
        explicit_token = os.environ.get("HALO_TEAMS_AGY_TOKEN")
        if explicit_token:
            token = Path(explicit_token)
            try:
                if token.stat().st_size > 0:
                    return "ok", "已登录（有 OAuth 令牌）", None
            except OSError:
                pass
            return "account", "agy 没有登录（找不到 OAuth 令牌）", None
        # agy uses Hermes gemini-chat gateway when ~/.gemini/antigravity-cli/settings.json enables
        # modelProvider=gemini, independent of offiagy's Google OAuth login.
        gateway_script = os.path.join(_SCRIPTS, "agy_gateway.py")
        if os.path.isfile(gateway_script):
            try:
                import importlib.util

                g_spec = importlib.util.spec_from_file_location("_halo_agy_gateway", gateway_script)
                if g_spec and g_spec.loader:
                    g_mod = importlib.util.module_from_spec(g_spec)
                    g_spec.loader.exec_module(g_mod)
                    env = {**os.environ, "HERMES_HOME": _HOME}
                    if g_mod.api_key_mode(env):
                        details = g_mod.provider_details(env, need_key=True)
                        host = re.sub(r"^https?://", "", str(details.get("base_url") or "")).split("/")[0]
                        return "ok", f"Hermes 网关模式（{details.get('provider') or 'gemini-chat'} · {host or 'local'}）", None
            except Exception as exc:
                return "account", f"agy 网关配置不可用：{redact(str(exc), 160)}", None
        token = Path("/root/.gemini/antigravity-cli/antigravity-oauth-token")
        try:
            if token.stat().st_size > 0:
                return "ok", "已登录（有 OAuth 令牌）", None
        except OSError:
            pass
        return "account", "agy 没有登录（未启用网关模式且找不到 OAuth 令牌）", None
    if spec.probe == "agy_official":
        # offiagy signs in with the Google account; its OAuth token file is the sign-in.
        token = Path(os.environ.get("HALO_TEAMS_AGY_TOKEN", "/root/.gemini/antigravity-cli/antigravity-oauth-token"))
        try:
            if token.stat().st_size > 0:
                return "ok", "Google 账号已登录（有 OAuth 令牌）；实际请求以 runner 结果为准", None
        except OSError:
            pass
        return "account", "offiagy 没有登录：在服务器终端运行 offiagy，按提示在浏览器授权", None
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


def failure_line(text: Any, limit: int = 160) -> str:
    """The one line of a runner's error worth showing ("error: X\nAGY_ERROR: {json}" → "X")."""
    for line in str(text or "").splitlines():
        line = re.sub(r"^\s*(error|Error|ERROR)\s*:\s*", "", line).strip()
        if line and not line.startswith(("AGY_ERROR", "{", "Traceback")):
            return redact(line, limit)
    return ""


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


def _override_mtime() -> Optional[int]:
    try:
        return OVERRIDE_FILE.stat().st_mtime_ns
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

def _effective_chain(start: str, *, auto: bool, chain: Optional[list[str]]) -> list[str]:
    start = start if start in BY_NAME else "hermes"
    if not auto:
        return [start]
    custom = _known_runners(chain) if chain is not None else []
    return custom or chain_from(start, auto=True)


def select(start: str, availability: Optional[dict] = None, *, skip: tuple = (), auto: bool = False,
           chain: Optional[list[str]] = None) -> dict:
    """Walk the fallback chain from *start* (``auto``: see ``chain_from``):
    {executor, start, chain, skipped:[{name, reason}]}. ``executor`` is None when nothing in the
    chain can run."""
    chain = _effective_chain(start, auto=auto, chain=chain)
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


def select_after(start: str, current: str, availability: Optional[dict] = None, *, auto: bool = False,
                 chain: Optional[list[str]] = None) -> dict:
    """The next available runner *after* ``current`` on the chain that starts at ``start`` (a
    fallback only moves forward). When ``auto=False`` (explicitly chosen by user/goal), never
    auto-fallback: returns ``executor=None`` so the user can pick another runner."""
    effective = _effective_chain(start if start in BY_NAME else current, auto=auto, chain=chain)
    if current in effective:
        rest = effective[effective.index(current) + 1:]
    elif auto and chain is None:
        rest = chain_from(current, auto=True)[1:]
    else:
        rest = []
    chain = effective
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
    picked = select(default, availability, auto=True)
    return {"kind": kind, "default": default, **picked}


def fallback_reason(picked: dict) -> str:
    """'cchclaude 不可用：…' for the runners skipped before the one picked."""
    return "；".join(s["reason"] for s in picked.get("skipped") or [])


def public_registry(availability: Optional[dict] = None) -> dict:
    """What HaloWebUI shows: runners (with availability), kinds with their default, families and order."""
    avail = availability if availability is not None else check()
    fams = family_orders()
    return {
        "runners": [{**{k: v for k, v in (avail.get(s.name) or {}).items() if k != "layers"},
                     "name": s.name, "label": s.label, "engine": s.engine, "family": s.family,
                     "note": s.note, "native": s.native,
                     "quota_wait": s.quota_wait, "layers": (avail.get(s.name) or {}).get("layers") or []}
                    for s in SPECS],
        "kinds": [{"value": k, "label": v["label"], "hint": v["hint"], "default": kind_default(k)} for k, v in KINDS.items()],
        "order": list(fallback_order()),
        "families": {k: list(v) for k, v in fams.items()},
        "family_labels": dict(FAMILY_LABELS),
        "cache_seconds": CACHE_SECONDS,
    }
