"""The team lead's plan: one model call proposes members (each a HaloWebUI assistant template and
a task kind) and dependent tasks; a deterministic validator decides whether the plan can run
(names, references, cycles) and works out which runner each member starts on (task kind →
default runner → first available one along the fallback order, see ``runners.py``). The user
approves — and may change any member's runner — in HaloWebUI before anything starts.

The lead runs on Hermes' own default model (``model.default`` in config.yaml, read on every
call, so changing Hermes' model needs no change here), falling back along Hermes' configured
``fallback_providers``. ``auxiliary.halo_team_lead`` (provider + model) overrides that.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import assistants, runners
from .common import EXECUTORS, LEAD_NAME, logger, redact

LEAD_TASK = "halo_team_lead"  # auxiliary.halo_team_lead in config.yaml overrides the lead's model
MAX_MEMBERS = 6
MAX_TASKS = 10
DEFAULT_PARALLEL_CAP = 2
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}$")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
EXECUTOR_SOURCES = ("auto", "goal", "user")

SYSTEM_PROMPT = """你是一个多代理团队的负责人（team-lead）。用户给你一个协作目标，你要把它拆成：团队成员（角色）和带依赖关系的任务计划。

只输出一个 JSON 对象，不要输出任何其他文字。格式：
{
  "title": "不超过 20 个字的团队任务名",
  "summary": "一两句话说明你打算怎么分工",
  "members": [
    {"name": "backend-dev", "role": "后端开发", "assistant": "17", "kind": "code", "focus": "负责什么"}
  ],
  "tasks": [
    {"key": "T1", "title": "任务名", "description": "完整、可独立执行的任务说明", "member": "backend-dev", "depends_on": []}
  ]
}

成员：
- 人数跟着目标的分量走：一个简单问题或一次事实查询 1 个成员就够（不要评审）；一般的调研 / 写作 / 小功能 2 到 3 个；大的改动 3 到 4 个；最多 6 个。不要为了凑人数拆出没必要的角色。name 用小写英文和连字符（如 backend-dev、frontend-dev、qa-engineer、reviewer），role 用中文。
- assistant：优先从下面的「助手模板」里选最贴切的一个，填它的编号；同一个模板可以给多个成员。确实没有合适的模板时填 null，并在 role / focus 里写清这个角色做什么。
- kind：这个成员的任务类型，决定由哪种执行器（runner）来做：
{kinds}
- 只有用户在目标里明确点名用某个执行器做某部分时，那个成员才加 "executor"：{executors} 之一；否则不要写 executor，系统会按 kind 自动选择并检查可用性。

助手模板（编号：名称（类型）— 说明）：
{catalog}

任务：
- 和人数一样按分量来：简单目标 1 到 2 个任务，一般 2 到 6 个，最多 10 个；key 用 T1、T2…；每个任务只分给一个成员，member 必须是 members 里的 name。
- depends_on 写这个任务开始前必须完成的任务 key。互不依赖的任务要能并行；需要汇总或评审的任务依赖它要看的所有任务。不能有循环依赖。
- 合适时安排一个评审 / 测试成员在最后检查前面成员的产出。
- 每个任务的 description 要自成一体：写清楚要做什么、产出物写到工作目录下的哪个文件、完成标准。并行任务不能写同一个文件。
- 不要安排需要用户手动操作、需要密钥或会改动生产服务的任务。
- 如果给了「项目」：团队在这个 git 仓库的独立分支（一个 worktree）上工作，工作目录就是仓库根。任务要指向真实的文件和模块，description 写清改哪些文件、怎么验证（跑哪些测试 / 检查）；并行任务改不同的文件；不要安排 push、合并到主分支、部署、构建镜像的任务——合并和推送由用户在协作台里决定。"""

USER_TEMPLATE = """协作目标：
{goal}

工作目录（所有成员共用，产出物写在这里）：{workspace}
{project}{extra}"""


def system_prompt() -> str:
    kinds = "\n".join(f"  - \"{k}\"：{v['label']}（{v['hint']}）" for k, v in runners.KINDS.items())
    catalog = assistants.catalog_text() or "（没有可用的助手模板，assistant 一律填 null）"
    executors = " / ".join(f'"{n}"' for n in EXECUTORS)
    # str.replace, not format: the prompt's JSON example has braces of its own.
    return SYSTEM_PROMPT.replace("{kinds}", kinds).replace("{catalog}", catalog).replace("{executors}", executors)


def build_messages(goal: str, workspace: str, feedback: str = "", previous: Optional[dict] = None,
                   project: Optional[dict] = None) -> list:
    extra = ""
    if previous:
        extra += "\n上一版计划（用户要求修改）：\n" + json.dumps(_plan_for_lead(previous), ensure_ascii=False)[:6000] + "\n"
    if feedback:
        extra += "\n用户对计划的修改意见：\n" + feedback.strip()[:2000] + "\n"
    project_text = ""
    if project and project.get("path"):
        from . import projects

        project_text = ("\n在项目里做（团队分支，工作目录是它的一个 worktree）：\n"
                        + (projects.context_text(project["path"]) or project["path"]) + "\n")
    user = USER_TEMPLATE.format(goal=goal.strip()[:6000], workspace=workspace, project=project_text, extra=extra)
    return [{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}]


def _plan_for_lead(plan: dict) -> dict:
    """A previous plan the way the lead writes one (no availability details)."""
    members = []
    for m in plan.get("members") or []:
        entry = {k: m.get(k) for k in ("name", "role", "kind", "focus") if m.get(k)}
        entry["assistant"] = (m.get("assistant") or {}).get("id") if isinstance(m.get("assistant"), dict) else m.get("assistant")
        if m.get("executor_source") in ("goal", "user") and m.get("executor"):
            entry["executor"] = m["executor"]
        members.append(entry)
    return {"title": plan.get("title"), "summary": plan.get("summary"), "members": members,
            "tasks": [{k: t.get(k) for k in ("key", "title", "description", "member", "depends_on")}
                      for t in plan.get("tasks") or []]}


def extract_json(raw: str) -> Optional[dict]:
    """The first JSON object in a model reply (code fences and chatter tolerated)."""
    if not raw:
        return None
    candidates = [m.group(1) for m in _FENCE_RE.finditer(raw)] + [raw]
    for text in candidates:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            value = json.loads(text[start : end + 1])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


# --- the lead's model -----------------------------------------------------------------------------

def _config() -> dict:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


def configured_models(cfg: Optional[dict] = None) -> list[dict]:
    """Models Hermes has configured that a lead can run on: [{model, provider, default}] — the
    main default first, then each custom provider's own model and the fallback models."""
    cfg = _config() if cfg is None else cfg
    out: list[dict] = []

    def add(provider: Any, model: Any, default: bool = False) -> None:
        model = str(model or "").strip()
        if model and not any(m["model"] == model for m in out):
            out.append({"model": model, "provider": str(provider or "main"), "default": default})

    main = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    add(main.get("provider"), main.get("default"), True)
    customs = cfg.get("custom_providers") if isinstance(cfg.get("custom_providers"), list) else []
    for entry in customs:
        if isinstance(entry, dict) and entry.get("name") and entry.get("model"):
            add(f"custom:{entry['name']}", entry["model"])
    for entry in cfg.get("fallback_providers") or []:
        if isinstance(entry, dict) and entry.get("provider") not in (None, "", "custom"):
            add(entry.get("provider"), entry.get("model"))
    return out


def lead_routes(cfg: Optional[dict] = None, preferred: Optional[str] = None) -> list[dict]:
    """The models the lead tries, in order: [{provider, model, source, label}]. Read from Hermes'
    config on every call — the lead follows Hermes' default model, it does not pin one. A team
    may prefer another configured model (``preferred``); the default chain follows it."""
    cfg = _config() if cfg is None else cfg
    routes: list[dict] = []

    def add(provider: Any, model: Any, source: str, **extra: Any) -> None:
        provider, model = str(provider or "").strip(), str(model or "").strip()
        if not model or any(r["model"] == model and r["provider"] == provider for r in routes):
            return
        routes.append({"provider": provider or "main", "model": model, "source": source, **extra})

    if preferred:
        match = next((m for m in configured_models(cfg) if m["model"] == preferred), None)
        if match:
            add(match["provider"], match["model"], "team")
    aux = ((cfg.get("auxiliary") or {}).get(LEAD_TASK) or {}) if isinstance(cfg.get("auxiliary"), dict) else {}
    if isinstance(aux, dict) and aux.get("model"):
        add(aux.get("provider"), aux.get("model"), "config")
    main = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    if main.get("default"):
        add(main.get("provider"), main.get("default"), "hermes_default")
    customs = cfg.get("custom_providers") if isinstance(cfg.get("custom_providers"), list) else []
    for entry in cfg.get("fallback_providers") or []:
        if not isinstance(entry, dict) or not entry.get("model"):
            continue
        model = str(entry["model"])
        named = next((c for c in customs if isinstance(c, dict) and (c.get("name") == model or c.get("model") == model)), None)
        if named:
            add(f"custom:{named.get('name')}", model, "hermes_fallback")
        elif entry.get("provider") and entry.get("provider") != "custom":
            add(entry.get("provider"), model, "hermes_fallback")
    return routes


SOURCE_LABEL = {"team": "这个协作任务指定", "config": "协作台配置", "hermes_default": "Hermes 默认模型",
                "hermes_fallback": "Hermes 备用模型"}


def lead_model_info(cfg: Optional[dict] = None) -> dict:
    """What the lead will use now (shown in HaloWebUI before a plan is made) and the models a
    team can pick instead."""
    cfg = _config() if cfg is None else cfg
    routes = lead_routes(cfg)
    choices = [m["model"] for m in configured_models(cfg)]
    if not routes:
        return {"model": "", "source": "", "label": "没有配置模型", "fallbacks": [], "choices": choices}
    first = routes[0]
    return {"model": first["model"], "source": first["source"], "label": SOURCE_LABEL.get(first["source"], ""),
            "fallbacks": [r["model"] for r in routes[1:]], "choices": choices}


def call_model(messages: list, timeout: int = 150, *, max_tokens: int = 4000,
               temperature: float = 0.3, preferred: Optional[str] = None) -> tuple[Optional[str], str, dict]:
    """One lead call along ``lead_routes``: ``(text, "", used)`` or ``(None, reason, used)``. Never raises."""
    try:
        from agent.auxiliary_client import call_llm
    except Exception as exc:  # pragma: no cover - import smoke
        return None, f"auxiliary client unavailable: {type(exc).__name__}", {}
    routes = lead_routes(preferred=preferred)
    if not routes:
        return None, "Hermes 没有配置默认模型（config.yaml 的 model.default）", {}
    failures: list[str] = []
    for route in routes:
        try:
            resp = call_llm(task=None, provider=route["provider"], model=route["model"], messages=messages,
                            temperature=temperature, max_tokens=max_tokens, timeout=timeout)
            text = resp.choices[0].message.content or ""
        except Exception as exc:
            failures.append(f"{route['model']}：{type(exc).__name__}: {redact(exc, 160)}")
            logger.warning("halowebui-teams: lead model %s failed: %s", route["model"], type(exc).__name__)
            continue
        if not text.strip():
            failures.append(f"{route['model']}：没有返回内容")
            continue
        used = {"model": route["model"], "source": route["source"], "label": SOURCE_LABEL.get(route["source"], ""),
                "fallback_from": [f.split("：", 1)[0] for f in failures], "fallback_reason": "；".join(failures),
                **({"requested": preferred} if preferred else {})}
        return text, "", used
    return None, "负责人模型都调用失败：" + "；".join(failures), {"model": "", "fallback_reason": "；".join(failures)}


# --- validation ----------------------------------------------------------------------------------

def _clean_text(value: Any, limit: int, *, one_line: bool = True) -> str:
    return redact(value, limit, one_line=one_line) if value is not None else ""


_KIND_WORDS = (
    ("complex", re.compile(r"重构|跨.{0,6}项目|架构调整|大规模|迁移|整体改造", re.I)),
    ("ui", re.compile(r"前端|界面|\bui\b|\bux\b|视觉|设计稿|页面|组件|样式|交互|css|frontend|design", re.I)),
    ("code", re.compile(r"后端|服务端|接口|\bapi\b|数据库|脚本|测试|代码|bug|修复|实现|开发|部署|运维|backend|server|test|code|review|评审", re.I)),
    ("research", re.compile(r"调研|研究|搜集|资料|分析|对比|评估|research|survey|analy", re.I)),
    ("writing", re.compile(r"文档|报告|撰写|写作|总结|汇总|方案|说明|doc|report|writ", re.I)),
)


def infer_kind(*texts: Any) -> str:
    joined = " ".join(str(t or "") for t in texts)
    for kind, pattern in _KIND_WORDS:
        if pattern.search(joined):
            return kind
    return runners.DEFAULT_KIND


def assign_runners(members: list[dict], availability: Optional[dict] = None) -> None:
    """Work out each member's runner in place: ``executor`` = where its chain starts (the user's
    or the goal's explicit choice, else the kind's default), ``runner`` = what will actually run
    it now, ``runner_note`` = why that differs. ``availability=None`` checks live."""
    starts = []
    for m in members:
        source = m.get("executor_source") if m.get("executor_source") in EXECUTOR_SOURCES else "auto"
        default = runners.kind_default(m["kind"])
        start = m.get("executor") if source in ("goal", "user") and m.get("executor") in EXECUTORS else default
        m.update(executor_source=source, recommended=default, executor=start)
        starts.append(start)
    if availability is None:
        needed = sorted({name for start in starts for name in runners.chain_from(start)})
        availability = runners.check(needed)
    for m in members:
        picked = runners.select(m["executor"], availability)
        m["runner"] = picked["executor"]
        m["runner_note"] = runners.fallback_reason(picked) if picked["executor"] != m["executor"] else ""
        if picked["executor"] is None:
            m["runner_note"] = "执行链上没有可用的 runner：" + (m["runner_note"] or "全部不可用")


def validate_plan(raw: Any, *, parallel_cap: int = DEFAULT_PARALLEL_CAP,
                  availability: Optional[dict] = None, check_runners: bool = True) -> tuple[Optional[dict], list[str]]:
    """Normalize a proposed plan. Returns ``(plan, [])`` or ``(None, errors)`` (Chinese, user-facing).
    ``check_runners=False`` skips the runner assignment (no availability probe)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["计划不是一个 JSON 对象"]
    members_in = raw.get("members")
    tasks_in = raw.get("tasks")
    if not isinstance(members_in, list) or not members_in:
        errors.append("计划里没有成员")
        members_in = []
    if not isinstance(tasks_in, list) or not tasks_in:
        errors.append("计划里没有任务")
        tasks_in = []
    if len(members_in) > MAX_MEMBERS:
        errors.append(f"成员最多 {MAX_MEMBERS} 个（计划里有 {len(members_in)} 个）")
    if len(tasks_in) > MAX_TASKS:
        errors.append(f"任务最多 {MAX_TASKS} 个（计划里有 {len(tasks_in)} 个）")

    members: list[dict] = []
    names: set[str] = set()
    for index, entry in enumerate(members_in[:MAX_MEMBERS], 1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 个成员格式不对")
            continue
        name = str(entry.get("name") or "").strip().lower().replace("_", "-").replace(" ", "-")
        if not _NAME_RE.match(name) or name == LEAD_NAME:
            errors.append(f"成员名「{name or '(空)'}」不合法（小写英文、数字、连字符，2–31 个字符，不能叫 {LEAD_NAME}）")
            continue
        if name in names:
            errors.append(f"成员名「{name}」重复")
            continue
        executor = str(entry.get("executor") or "").strip().lower()
        source = str(entry.get("executor_source") or "").strip()
        if executor and executor not in EXECUTORS:
            errors.append(f"成员「{name}」的执行来源「{executor}」不支持（只支持 {'、'.join(EXECUTORS)}）")
            continue
        if source not in EXECUTOR_SOURCES:
            # The lead only writes an executor when the goal named one; a plan stored before
            # sources existed keeps exactly the runners the user reviewed.
            source = "goal" if executor else "auto"
        template = assistants.resolve(entry.get("assistant"))
        role = _clean_text(entry.get("role"), 40) or (template["name"] if template else name)
        focus = _clean_text(entry.get("focus"), 300)
        kind = runners.normalize_kind(entry.get("kind")) or (template["kind"] if template else "") or infer_kind(role, focus)
        names.add(name)
        members.append({
            "name": name,
            "role": role,
            "focus": focus,
            "kind": kind,
            "assistant": assistants.public(template),
            "executor": executor or "",
            "executor_source": source,
        })

    tasks: list[dict] = []
    keys: set[str] = set()
    for index, entry in enumerate(tasks_in[:MAX_TASKS], 1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 个任务格式不对")
            continue
        key = str(entry.get("key") or f"T{index}").strip()
        if not _KEY_RE.match(key):
            errors.append(f"任务编号「{key}」不合法")
            continue
        if key in keys:
            errors.append(f"任务编号「{key}」重复")
            continue
        title = _clean_text(entry.get("title"), 80)
        if not title:
            errors.append(f"任务 {key} 没有标题")
            continue
        member = str(entry.get("member") or "").strip().lower().replace("_", "-")
        if member not in names:
            errors.append(f"任务 {key} 分给了不存在的成员「{member or '(空)'}」")
            continue
        deps_raw = entry.get("depends_on") or []
        if isinstance(deps_raw, str):
            deps_raw = [deps_raw]
        if not isinstance(deps_raw, list):
            errors.append(f"任务 {key} 的依赖格式不对")
            continue
        deps = []
        for dep in deps_raw:
            dep = str(dep).strip()
            if dep and dep not in deps:
                deps.append(dep)
        keys.add(key)
        tasks.append({
            "key": key,
            "title": title,
            "description": _clean_text(entry.get("description"), 2000, one_line=False) or title,
            "member": member,
            "depends_on": deps,
        })
    for task in tasks:
        for dep in task["depends_on"]:
            if dep == task["key"]:
                errors.append(f"任务 {task['key']} 依赖了它自己")
            elif dep not in keys:
                errors.append(f"任务 {task['key']} 依赖了不存在的任务 {dep}")
    if not errors:
        cycle = _find_cycle(tasks)
        if cycle:
            errors.append("任务之间有循环依赖：" + " → ".join(cycle))
    if errors:
        return None, errors

    used = {t["member"] for t in tasks}
    members = [m for m in members if m["name"] in used]
    for m in members:
        # A member without an explicit kind is classified by what it is asked to do.
        if not m["kind"]:
            m["kind"] = infer_kind(m["role"], m["focus"], *(t["title"] for t in tasks if t["member"] == m["name"]))
    if check_runners:
        assign_runners(members, availability)
    else:
        for m in members:
            m.setdefault("recommended", runners.kind_default(m["kind"]))
            if not m["executor"]:
                m["executor"] = m["recommended"]
            m.setdefault("runner", m["executor"])
            m.setdefault("runner_note", "")
    layers = layers_of(tasks)
    widest = max((len(layer) for layer in layers), default=0)
    plan = {
        "title": _clean_text(raw.get("title"), 40) or (tasks[0]["title"] if tasks else "协作任务"),
        "summary": _clean_text(raw.get("summary"), 400, one_line=False),
        "lead": {"name": LEAD_NAME, "role": "负责人", **({"model": raw["lead"].get("model")} if isinstance(raw.get("lead"), dict) and raw["lead"].get("model") else {})},
        "members": members,
        "tasks": tasks,
        "layers": layers,
        "max_parallel": min(widest, parallel_cap) if widest else 0,
        "widest_layer": widest,
        "executors": sorted({m["runner"] or m["executor"] for m in members}),
    }
    if isinstance(raw.get("lead_model"), dict):
        plan["lead_model"] = raw["lead_model"]
    if isinstance(raw.get("project"), dict) and raw["project"].get("path"):
        plan["project"] = {k: raw["project"].get(k) for k in ("path", "name", "branch", "head", "dirty", "auto")
                           if raw["project"].get(k) not in (None, "")}
    return plan, []


def layers_of(tasks: list[dict]) -> list[list[str]]:
    """Tasks grouped by longest dependency path (depth 0 = no dependencies)."""
    by_key = {t["key"]: t for t in tasks}
    depth: dict[str, int] = {}

    def depth_of(key: str, trail: tuple = ()) -> int:
        if key in depth:
            return depth[key]
        if key in trail:
            return 0
        deps = [d for d in by_key[key]["depends_on"] if d in by_key]
        value = 0 if not deps else 1 + max(depth_of(d, trail + (key,)) for d in deps)
        depth[key] = value
        return value

    for t in tasks:
        depth_of(t["key"])
    out: list[list[str]] = []
    for t in tasks:
        d = depth[t["key"]]
        while len(out) <= d:
            out.append([])
        out[d].append(t["key"])
    return out


def _find_cycle(tasks: list[dict]) -> Optional[list[str]]:
    graph = {t["key"]: list(t["depends_on"]) for t in tasks}
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> Optional[list[str]]:
        state[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if state.get(dep) == 1:
                return stack[stack.index(dep):] + [dep]
            if state.get(dep) is None:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for key in graph:
        if state.get(key) is None:
            found = visit(key)
            if found:
                return found
    return None


def resolve_project(goal: str, choice: str) -> Optional[dict]:
    """The project a plan works in: "none" → none; a path → that repository; "" → the project the
    goal names, if any (``auto``). Raises ValueError for a path that is not a usable repository."""
    from . import projects

    choice = (choice or "").strip()
    if choice == "none":
        return None
    if choice:
        described = projects.describe(choice)
        if described is None:
            raise ValueError(f"{choice} 不是可以协作的 git 仓库（要是本机某个仓库的根目录，不能是主目录）")
        return described
    suggested = projects.suggest(goal)
    described = projects.describe(suggested["path"]) if suggested else None
    return {**described, "auto": True} if described else None


def propose_plan(goal: str, workspace: str, *, feedback: str = "", previous: Optional[dict] = None,
                 parallel_cap: int = DEFAULT_PARALLEL_CAP, timeout: int = 150, lead_model: str = "",
                 project: Optional[dict] = None) -> dict:
    """Ask the lead model for a plan, then validate it. One retry when the reply is not usable."""
    if project and project.get("path"):
        workspace = project["path"] + "（团队分支的 worktree，批准时创建）"
    messages = build_messages(goal, workspace, feedback, previous, project)
    last_errors: list[str] = []
    for attempt in range(2):
        text, reason, used = call_model(messages, timeout=timeout, preferred=lead_model or None)
        if text is None:
            return {"ok": False, "error": reason, "lead_model": used}
        parsed = extract_json(text)
        if parsed is None:
            last_errors = ["负责人返回的不是 JSON"]
        else:
            parsed["lead_model"] = used
            if project:
                parsed["project"] = project
            parsed.setdefault("lead", {})
            if isinstance(parsed["lead"], dict):
                parsed["lead"]["model"] = used.get("model")
            plan, last_errors = validate_plan(parsed, parallel_cap=parallel_cap)
            if plan is not None:
                return {"ok": True, "plan": plan, "attempts": attempt + 1}
        messages = messages + [
            {"role": "assistant", "content": text[:6000]},
            {"role": "user", "content": "这个计划不能用：" + "；".join(last_errors) + "。请改正后只输出 JSON。"},
        ]
    return {"ok": False, "error": "负责人给出的计划两次都没通过检查：" + "；".join(last_errors)}
