"""Multi-model development pipeline templates for HaloWebUI 协作台.

Implements the reference collaboration workflow on top of the existing Kanban + worktree + runner
infrastructure:
  - ``dev_pipeline``: Claude 主控摸底 → Claude & AGY 并行独立出方案 → Claude 逐条对比合成并
    通过 QUESTION: 协议暂停等你拍板 → （可选 UI 环节）Claude 出设计稿 → AGY 审交互和文案 →
    Claude 取舍改稿并定接口/派活单 → Codex 写成块后端交回执 → Claude 读改动写前端跑测试；
    完成后交付流水线自动执行 Codex 审查（最多 2 轮 + Claude 自动修复）→ 直接合并主分支推送
    → CI → 自动拉取更新部署 → 清理分支 → 核实线上。
  - ``dev_lite``: 跳过双方案与设计稿的轻量研发模式（主控摸底定接口 → Codex 写后端 → Claude
    读改动写前端跑测试 → 审查与上线）。
  - ``auto``: 现有自由协作（负责人动态拆解，适合非代码任务或定制分工）。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import runners
from .common import redact

WORKFLOWS = ("auto", "dev_pipeline", "dev_lite")
WORKFLOW_LABELS = {
    "auto": "自由协作",
    "dev_pipeline": "多模型研发（完整）",
    "dev_lite": "快速研发（精简）",
}

_SKIP_DESIGN_RE = re.compile(
    r"纯后端|仅后端|不改前端|没有前端|无前端|跳过设计|不需要设计稿|不用设计稿|backend[- ]only|no[- ]ui",
    re.I,
)
_READONLY_GOAL_RE = re.compile(
    r"不要改代码|不改代码|只读|只看|仅分析|仅调研|只分析|代码审查报告|只做审查|只查|帮我看下|解释一下|"
    r"分析一下.*架构|审查.*(?:提交|代码|改动).*(?:报告|建议|清单)|(?:仅|只)做.*(?:审查|调研|分析|总结)",
    re.I,
)
_REPO_EDIT_RE = re.compile(
    r"改|修改|修复|修一下|修个|新增|增加|添加|加上|实现|开发|重构|优化|删除|去掉|移除|替换|升级|适配|接入|"
    r"支持|部署|提交代码|推送部署|推送上线|写(?:一个|个|新|代码|接口|页面|组件|测试|单测|脚本|函数|功能)|"
    r"做个|做一个|调整|完善|打通|落地|补齐|迁移|改造|"
    r"fix|add|implement|refactor|update|remove|feat|upgrade|deploy|build|create",
    re.I,
)


def should_promote_to_dev_lite(goal: str, project: Optional[dict]) -> bool:
    """When workflow is default ``auto`` (自由协作) but targets a git project and intends to change
    repository code, promote directly to ``dev_lite`` (and auto-deploy on completion)."""
    if not (isinstance(project, dict) and project.get("path")):
        return False
    text = str(goal or "").strip()
    if not text or _READONLY_GOAL_RE.search(text):
        return False
    return bool(_REPO_EDIT_RE.search(text))


def normalize_workflow(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in WORKFLOWS else "auto"


def normalize_runner_prefs(raw: Any) -> dict[str, str]:
    """Validate per-family runner overrides: ``{"claude": "cchclaude", "agy": "agy"}``.
    Empty value = auto family order; non-empty value = explicit runner (no auto-fallback)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for fam in ("claude", "agy", "codex"):
        val = str(raw.get(fam) or "").strip().lower()
        if val and val in runners.BY_NAME and runners.BY_NAME[val].family == fam:
            out[fam] = val
    return out


def apply_runner_prefs(members: list[dict], runner_prefs: Optional[dict[str, str]]) -> None:
    """Apply task-level per-family overrides onto members that were not already explicitly named."""
    prefs = normalize_runner_prefs(runner_prefs)
    if not prefs:
        return
    for m in members:
        if m.get("kind") == "image":
            continue
        if m.get("executor_source") in ("user", "goal"):
            continue
        default_exec = m.get("executor") or runners.kind_default(m.get("kind") or runners.DEFAULT_KIND)
        fam = runners.family_of(default_exec)
        chosen = prefs.get(fam)
        if chosen:
            m["executor"] = chosen
            m["executor_source"] = "user"


def _title_from_goal(goal: str, workflow: str) -> str:
    first = " ".join(str(goal or "").split())
    prefix = "研发：" if workflow == "dev_pipeline" else "快研："
    if not first:
        return prefix + "协作开发"
    max_body = 24 - len(prefix)
    body = first[:max_body].rstrip("，。；：、,. ") + ("…" if len(first) > max_body else "")
    return redact(prefix + body, 40)


def _member_spec(name: str, role: str, kind: str, focus: str, prefs: dict[str, str]) -> dict:
    default_exec = runners.kind_default(kind)
    fam = runners.family_of(default_exec)
    chosen = prefs.get(fam)
    entry: dict[str, Any] = {
        "name": name,
        "role": role,
        "kind": kind,
        "focus": focus,
        "assistant": None,
    }
    if chosen:
        entry["executor"] = chosen
        entry["executor_source"] = "user"
    return entry


def build_pipeline_plan(
    goal: str,
    *,
    workflow: str,
    project: Optional[dict] = None,
    feedback: str = "",
    runner_prefs: Optional[dict[str, str]] = None,
    inputs: Optional[list[str]] = None,
    promoted_from: str = "",
) -> dict:
    """Build a deterministic raw plan dict matching the reference diagram, ready for ``validate_plan``."""
    wf = normalize_workflow(workflow)
    prefs = normalize_runner_prefs(runner_prefs)
    extra_feedback = f"\n\n用户补充意见：\n{feedback.strip()}" if feedback and feedback.strip() else ""
    input_note = (
        f"\n用户随目标附带了参考文件（在工作目录 {'.halo/inputs/' if project else 'inputs/'} 下）："
        + "、".join(inputs[:12])
        if inputs
        else ""
    )
    ctx_tail = extra_feedback + input_note
    skip_design = bool(_SKIP_DESIGN_RE.search(goal + "\n" + (feedback or "")))

    if wf == "dev_lite":
        members = [
            _member_spec("claude-lead", "Claude 主控", "code",
                         "理解需求、查代码定接口与派活单；读 Codex 改动、写前端并跑完整测试（按默认配置）", prefs),
            _member_spec("codex-dev", "Codex 后端", "codex",
                         "按派活单写成块后端代码与单元测试，提交回执（按默认配置）", prefs),
        ]
        tasks = [
            {
                "key": "T1",
                "title": "主控摸底并定接口与派活单",
                "member": "claude-lead",
                "depends_on": [],
                "description": (
                    "作为 Claude 主控，先真实阅读项目代码、数据/配置与现状，整理实现方案、接口契约、"
                    "文件边界与验收标准，写入 `.halo/backend-spec.md`（写清 Codex 负责哪些后端文件、"
                    "接口输入输出、边界条件与必须通过的单元测试；以及前端/联调留给主控处理的部分）。"
                    "本阶段只读分析并写派活单，不改业务代码。" + ctx_tail
                ),
            },
            {
                "key": "T2",
                "title": "Codex 写成块后端并交回执",
                "member": "codex-dev",
                "depends_on": ["T1"],
                "description": (
                    "严格按照 `.halo/backend-spec.md` 的派活单实现后端代码与对应单元测试并运行验证。"
                    "完成后把改动文件清单、接口契约核对、测试命令与实际结果写入 `.halo/backend-receipt.md`，"
                    "只改派活单指定的后端文件，不要推远端或合并分支。"
                ),
            },
            {
                "key": "T3",
                "title": "主控读改动、写前端并跑全套测试",
                "member": "claude-lead",
                "depends_on": ["T2"],
                "description": (
                    "通读 `.halo/backend-receipt.md` 与当前分支的 git diff，逐项核对后端实现是否符合验收标准；"
                    "如有前端改动由你完成前端实现与联调；最后运行完整的后端/前端测试与构建检查，"
                    "把修改汇总和实测命令结果写入最终回答（不要 push、不要合并主分支、不要部署）。"
                ),
            },
        ]
        summary = (
            ("检测到需改动仓库代码，已自动晋升为快速研发并开启完成后自动部署：" if promoted_from == "auto" else "快速研发模式：")
            + "Claude 主控摸底定接口 → Codex 写后端交回执 → Claude 读改动、写前端并跑测试；完成后自动走 Codex 审查（最多 2 轮）→ 直合主分支推送、自动拉取部署、清理分支与核实线上。"
        )
    else:
        members = [
            _member_spec("claude-lead", "Claude 主控", "code",
                         "理解需求查代码/线上、对比合成方案等你拍板、出设计稿、定接口、写前端、读改动跑测试（按默认配置）", prefs),
            _member_spec("agy-advisor", "AGY 方案与交互顾问", "ui",
                         "独立出对比方案（与 Claude 并行），以及审查设计稿的交互与文案（按默认配置）", prefs),
            _member_spec("codex-dev", "Codex 后端", "codex",
                         "按派活单写成块后端代码与单元测试并提交回执（按默认配置）", prefs),
        ]
        tasks = [
            {
                "key": "T1",
                "title": "主控摸底（查代码 / 查数据 / 查线上）",
                "member": "claude-lead",
                "depends_on": [],
                "description": (
                    "作为 Claude 主控，先完整理解需求并做事实摸底：查阅相关代码文件、数据结构/配置、"
                    "现有测试及线上约束（只读核查，不改任何业务代码）。\n"
                    "把关键事实、涉及模块路径、约束与待决策问题清晰写入 `.halo/context.md`，供下一步"
                    "Claude 与 AGY 各自独立出方案使用。" + ctx_tail
                ),
            },
            {
                "key": "T2",
                "title": "Claude 独立出方案",
                "member": "claude-lead",
                "depends_on": ["T1"],
                "description": (
                    "阅读 `.halo/context.md`，**独立**产出一份完整技术与实现方案，写入 `.halo/proposal-claude.md`。\n"
                    "要求：不要读取或等待 AGY 的方案；写清架构取舍、涉及文件、前后端边界、风险与测试策略。"
                    "本步骤只写方案文档，不改业务代码。"
                ),
            },
            {
                "key": "T3",
                "title": "AGY 独立出方案",
                "member": "agy-advisor",
                "depends_on": ["T1"],
                "description": (
                    "阅读 `.halo/context.md`，**独立**产出一份完整技术与交互方案，写入 `.halo/proposal-agy.md`。\n"
                    "要求：不要读取或参考 `.halo/proposal-claude.md`；重点从全局架构、交互体验、边界条件、"
                    "可维护性和替代方案角度给出独立判断。本步骤只写方案文档，不改业务代码。"
                ),
            },
            {
                "key": "T4",
                "title": "逐条对比合成方案并请你拍板",
                "member": "claude-lead",
                "depends_on": ["T2", "T3"],
                "description": (
                    "同时阅读 `.halo/proposal-claude.md` 与 `.halo/proposal-agy.md`，逐条对比并合成为一份最终方案，"
                    "写入 `.halo/plan-final.md`。\n"
                    "必须在方案里**逐条标清**：① 采纳了谁的方案；② 没采纳的原因；③ 最终改动范围、前后端分工与验收标准。\n"
                    "**拍板闸门（必须遵守）**：写完 `.halo/plan-final.md` 后，先不要结束任务，请以 `QUESTION:` 开头"
                    "把最终方案要点和采纳对比发给用户，请用户「拍板确认进入开发」或「提出修改意见」。"
                    "如果用户提出修改意见，先修订 `.halo/plan-final.md` 并再次用 `QUESTION:` 确认；"
                    "收到用户明确拍板同意后，再输出最终确认结果完成本任务。"
                ),
            },
        ]
        if not skip_design:
            tasks += [
                {
                    "key": "T5",
                    "title": "出设计稿（交互与文案）",
                    "member": "claude-lead",
                    "depends_on": ["T4"],
                    "description": (
                        "基于已拍板的 `.halo/plan-final.md`，产出交互流程、界面布局、状态反馈与关键文案设计稿，"
                        "写入 `.halo/design.md`（若某项改动确实不涉及界面，请在文件里简要说明后供审稿确认）。"
                    ),
                },
                {
                    "key": "T6",
                    "title": "AGY 审交互和文案",
                    "member": "agy-advisor",
                    "depends_on": ["T5"],
                    "description": (
                        "对照 `.halo/plan-final.md` 审查 `.halo/design.md`：重点挑出交互断点、多余步骤、"
                        "边界状态遗漏、文案晦涩或与现有产品风格不一致之处，给出具体修改建议，写入 `.halo/design-review.md`。"
                    ),
                },
                {
                    "key": "T7",
                    "title": "取舍改稿并定接口与验收标准",
                    "member": "claude-lead",
                    "depends_on": ["T6"],
                    "description": (
                        "1) 阅读 `.halo/design-review.md`，对建议做取舍并定版 `.halo/design-final.md`（注明采纳与舍弃理由）；\n"
                        "2) 制定完整接口契约、数据模型、验收标准与文件边界，写出清晰可执行的后端派活单到 `.halo/backend-spec.md`，"
                        "明确告诉 Codex 负责实现哪些后端模块与单元测试，以及前端和总验证留给主控处理。"
                    ),
                },
                {
                    "key": "T8",
                    "title": "Codex 写成块后端并交回执",
                    "member": "codex-dev",
                    "depends_on": ["T7"],
                    "description": (
                        "严格按照 `.halo/backend-spec.md` 的派活单实现成块后端代码与单元测试并跑通验证。\n"
                        "完成后将改动文件、关键设计、测试命令及实测结果写入回执 `.halo/backend-receipt.md`。"
                        "只改派活单范围内的后端代码，不要 push、不要合并主分支。"
                    ),
                },
                {
                    "key": "T9",
                    "title": "主控读改动、写前端并跑全套测试",
                    "member": "claude-lead",
                    "depends_on": ["T8"],
                    "description": (
                        "1) 通读 `.halo/backend-receipt.md` 和分支 git diff，核查后端代码质量与接口契约；\n"
                        "2) 按 `.halo/design-final.md` 完成前端代码实现与前后端联调；\n"
                        "3) 自己运行全套相关单元测试、类型/构建检查，修掉发现的问题，把实测命令与结果写入最终回答。"
                        "不要 git push、不要合并主分支、不要部署（后续由交付流水线执行 Codex 审查并上线）。"
                    ),
                },
            ]
        else:
            tasks += [
                {
                    "key": "T5",
                    "title": "定接口与验收标准（派活单）",
                    "member": "claude-lead",
                    "depends_on": ["T4"],
                    "description": (
                        "按已拍板的 `.halo/plan-final.md`，制定接口契约、文件边界与验收标准，"
                        "写清晰可执行的后端派活单到 `.halo/backend-spec.md`。"
                    ),
                },
                {
                    "key": "T6",
                    "title": "Codex 写成块后端并交回执",
                    "member": "codex-dev",
                    "depends_on": ["T5"],
                    "description": (
                        "严格按照 `.halo/backend-spec.md` 的派活单实现后端代码与单元测试并跑通验证，"
                        "将改动清单与实测结果写入回执 `.halo/backend-receipt.md`。不要 push 或合并主分支。"
                    ),
                },
                {
                    "key": "T7",
                    "title": "主控读改动、联调并跑全套测试",
                    "member": "claude-lead",
                    "depends_on": ["T6"],
                    "description": (
                        "通读 `.halo/backend-receipt.md` 与 git diff，完成联调与补充修复，"
                        "自己跑通全套测试并输出实测证据。不要 push、不要合并主分支、不要部署。"
                    ),
                },
            ]
        summary = (
            "多模型研发流水线：Claude 主控摸底 → Claude & AGY 并行独立出方案 → 逐条对比合成并等你拍板 → "
            + ("出设计稿 & AGY 审交互文案 → 取舍定接口 → " if not skip_design else "定接口派活 → ")
            + "Codex 写成块后端交回执 → Claude 读改动、写前端并跑测试；完成后自动走 Codex 审查（最多 2 轮）→ 直合主分支推送、部署更新与线上核实。"
        )

    plan: dict[str, Any] = {
        "title": _title_from_goal(goal, wf),
        "summary": summary,
        "workflow": wf,
        "runner_prefs": prefs,
        "members": members,
        "tasks": tasks,
        "lead": {"name": "team-lead", "role": "负责人"},
        "lead_model": {"model": "pipeline-template", "source": "workflow", "label": WORKFLOW_LABELS[wf]},
    }
    if promoted_from:
        plan["promoted_from"] = promoted_from
    if project:
        plan["project"] = project
        plan["auto_deploy"] = True
    return plan
