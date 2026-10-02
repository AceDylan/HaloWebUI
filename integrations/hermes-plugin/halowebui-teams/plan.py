"""The team lead's plan: one auxiliary-model call proposes members and dependent tasks, and a
deterministic validator decides whether the plan can run (names, executors, references,
cycles). The user approves the validated plan in HaloWebUI before anything starts."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .common import EXECUTORS, LEAD_NAME, redact

AUX_TASK = "kanban_decomposer"  # auxiliary.kanban_decomposer in config.yaml (provider/model)
MAX_MEMBERS = 6
MAX_TASKS = 10
DEFAULT_PARALLEL_CAP = 2
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}$")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

SYSTEM_PROMPT = """你是一个多代理团队的负责人（team-lead）。用户给你一个协作目标，你要把它拆成：团队成员（角色）和带依赖关系的任务计划。

只输出一个 JSON 对象，不要输出任何其他文字。格式：
{
  "title": "不超过 20 个字的团队任务名",
  "summary": "一两句话说明你打算怎么分工",
  "members": [
    {"name": "backend-dev", "role": "后端开发", "executor": "hermes", "focus": "负责什么"}
  ],
  "tasks": [
    {"key": "T1", "title": "任务名", "description": "完整、可独立执行的任务说明", "member": "backend-dev", "depends_on": []}
  ]
}

要求：
- 成员 2 到 4 个为宜，最多 6 个；name 用小写英文和连字符（如 backend-dev、frontend-dev、qa-engineer、reviewer），role 用中文。
- 任务 2 到 8 个为宜，最多 10 个；key 用 T1、T2…；每个任务只分给一个成员，member 必须是 members 里的 name。
- depends_on 写这个任务开始前必须完成的任务 key。互不依赖的任务要能并行；需要汇总或评审的任务依赖它要看的所有任务。不能有循环依赖。
- 合适时安排一个 reviewer 或 qa 成员在最后检查前面成员的产出。
- 每个任务的 description 要自成一体：写清楚要做什么、产出物写到工作目录下的哪个文件、完成标准。并行任务不能写同一个文件。
- executor 默认 "hermes"（Hermes 代理）。只有用户明确要求用 reclaude / Claude Code 执行某部分时，那个成员才用 "reclaude"。
- 不要安排需要用户手动操作、需要密钥或会改动生产服务的任务。"""

USER_TEMPLATE = """协作目标：
{goal}

工作目录（所有成员共用，产出物写在这里）：{workspace}
{extra}"""


def build_messages(goal: str, workspace: str, feedback: str = "", previous: Optional[dict] = None) -> list:
    extra = ""
    if previous:
        extra += "\n上一版计划（用户要求修改）：\n" + json.dumps(previous, ensure_ascii=False)[:6000] + "\n"
    if feedback:
        extra += "\n用户对计划的修改意见：\n" + feedback.strip()[:2000] + "\n"
    user = USER_TEMPLATE.format(goal=goal.strip()[:6000], workspace=workspace, extra=extra)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


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


def call_model(messages: list, timeout: int = 150) -> tuple[Optional[str], str]:
    """One auxiliary LLM call; ``(text, "")`` or ``(None, reason)``. Never raises."""
    try:
        from agent.auxiliary_client import call_llm
    except Exception as exc:  # pragma: no cover - import smoke
        return None, f"auxiliary client unavailable: {type(exc).__name__}"
    try:
        resp = call_llm(task=AUX_TASK, messages=messages, temperature=0.3, max_tokens=4000, timeout=timeout)
    except Exception as exc:
        return None, f"模型调用失败：{type(exc).__name__}: {redact(exc, 200)}"
    try:
        return resp.choices[0].message.content or "", ""
    except Exception:
        return None, "模型没有返回内容"


def _clean_text(value: Any, limit: int, *, one_line: bool = True) -> str:
    return redact(value, limit, one_line=one_line) if value is not None else ""


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


def validate_plan(raw: Any, *, parallel_cap: int = DEFAULT_PARALLEL_CAP) -> tuple[Optional[dict], list[str]]:
    """Normalize a proposed plan. Returns ``(plan, [])`` or ``(None, errors)`` (Chinese, user-facing)."""
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
        executor = str(entry.get("executor") or "hermes").strip().lower()
        if executor not in EXECUTORS:
            errors.append(f"成员「{name}」的执行来源「{executor}」不支持（只支持 {'、'.join(EXECUTORS)}）")
            continue
        names.add(name)
        members.append({
            "name": name,
            "role": _clean_text(entry.get("role"), 40) or name,
            "executor": executor,
            "focus": _clean_text(entry.get("focus"), 300),
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
    layers = layers_of(tasks)
    widest = max((len(layer) for layer in layers), default=0)
    plan = {
        "title": _clean_text(raw.get("title"), 40) or (tasks[0]["title"] if tasks else "协作任务"),
        "summary": _clean_text(raw.get("summary"), 400, one_line=False),
        "lead": {"name": LEAD_NAME, "role": "负责人"},
        "members": members,
        "tasks": tasks,
        "layers": layers,
        "max_parallel": min(widest, parallel_cap) if widest else 0,
        "widest_layer": widest,
        "executors": sorted({m["executor"] for m in members}),
    }
    return plan, []


def propose_plan(goal: str, workspace: str, *, feedback: str = "", previous: Optional[dict] = None,
                 parallel_cap: int = DEFAULT_PARALLEL_CAP, timeout: int = 150) -> dict:
    """Ask the lead model for a plan, then validate it. One retry when the reply is not usable."""
    messages = build_messages(goal, workspace, feedback, previous)
    last_errors: list[str] = []
    for attempt in range(2):
        text, reason = call_model(messages, timeout=timeout)
        if text is None:
            return {"ok": False, "error": reason}
        parsed = extract_json(text)
        if parsed is None:
            last_errors = ["负责人返回的不是 JSON"]
        else:
            plan, last_errors = validate_plan(parsed, parallel_cap=parallel_cap)
            if plan is not None:
                return {"ok": True, "plan": plan, "attempts": attempt + 1}
        messages = messages + [
            {"role": "assistant", "content": text[:6000]},
            {"role": "user", "content": "这个计划不能用：" + "；".join(last_errors) + "。请改正后只输出 JSON。"},
        ]
    return {"ok": False, "error": "负责人给出的计划两次都没通过检查：" + "；".join(last_errors)}
