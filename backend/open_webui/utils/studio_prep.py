"""提示词增强 for the video studio (/workspace/videos) and the image studio (/workspace/images).

Before a request is made, gpt-chat (the user's own, else the strongest text model) reads it:

1. **分析需求** — does making it well need facts looked up on the web, and (video only) does its
   content first need working out: a 精答 answer (an explanation, an analysis, a how-to that has
   to be right) or a 讨论 (a contested question the video should present from several sides)?
2. **联网搜索** — the discussion room's evidence pack (the app's own web search, with a second
   look), when the request needs facts and the user leaves 联网搜索 on;
   **精答 / 讨论** — or the question goes to 精答 / 讨论台 as one started there (a chat of its
   own the user can open), and its answer / conclusion is the material once it is written;
3. **增强** — gpt-chat rewrites the request on that material: complete, sized to the settings,
   facts only from the material, with the key facts as notes and the sources it used.

The studio then carries on as before (the video brief goes to Hermes, the image is generated)
with the enhanced text. A job lives in memory for an hour; the 精答 / 讨论 it started stays.

With a 辅助决策模型 (utils/decision_model.py) set, the video's two choices of 分析需求 — the web
or not, 精答 / 讨论 first or not — are its; gpt-chat still writes the texts (the question, what
to search) and decides as before when the decision fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

KINDS = ("video", "image")
IDEA_MAX_CHARS = 6000
SETTINGS_MAX_CHARS = 1500
# what the enhanced request and its notes may take (the video brief travels to the chat whole,
# at most 8000 characters with its fixed parts)
ENHANCED_MAX_CHARS = {"video": 2200, "image": 1200}
NOTES_MAX_CHARS = 1200
SOURCES_MAX = 6
SOURCE_EXCERPT_CHARS = 1400
MATERIAL_MAX_CHARS = 9000

PLAN_TIMEOUT_SECONDS = 60
SEARCH_TIMEOUT_SECONDS = 150
ENHANCE_TIMEOUT_SECONDS = 120
DEEPER_TIMEOUT_SECONDS = {"answer": 15 * 60, "discuss": 30 * 60}
DEEPER_POLL_SECONDS = 4

MAX_RUNNING_PER_USER = 2
JOB_TTL_SECONDS = 3600

DEEPER = {"answer": {"label": "精答", "page": "/answer/"}, "discuss": {"label": "讨论", "page": "/discuss/"}}
STEP_LABELS = {
    "plan": "分析需求",
    "search": "联网搜索",
    "answer": "精答",
    "discuss": "讨论",
    "enhance": "增强提示词",
}

WHAT = {
    "video": (
        "HaloWebUI's video studio: an AI agent makes the video itself (Remotion motion graphics, "
        "generated stills with camera moves, data animation or cutting the user's footage; "
        "narration by TTS, burned-in subtitles)."
    ),
    "image": "HaloWebUI's image studio: one picture from a text-to-image model (gpt-image class), optionally edited from reference images.",
}


def clean(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit].rstrip()


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


# --- 1. 分析需求 --------------------------------------------------------------------------------


def plan_messages(kind: str, idea: str, settings: str, *, research: bool, deeper: bool, texts: bool = False) -> list[dict]:
    """``texts``: a 辅助决策模型 makes the choices, so the question is written whatever this plan picks."""
    asks = []
    if research:
        asks.append(
            '"research": true when making it well needs facts that are current, specific or checkable on the web '
            "(news, data, statistics, product specs, prices, recent events, a real person's / place's / brand's / "
            "artwork's actual details, technical accuracy). false for fiction, moods, abstract or everyday scenes, "
            "a request whose own text (or attachments) already gives the content, or anything the maker can write from common knowledge."
        )
    if deeper:
        asks.append(
            '"deeper": "answer" when the video\'s content itself must first be worked out correctly by an expert answer '
            "(an explanation, analysis, tutorial, plan, or a question with a right answer the video then presents); "
            '"discuss" when it is contested, opinion-based or a prediction and the video should present several '
            "perspectives or a balanced conclusion (pros and cons, debates, choosing between options); "
            '"none" when the user already wrote the content, or it is a story, mood piece, montage, music video or an edit '
            "of their footage, or simple enough for the maker to write directly. Prefer none: pick answer / discuss only "
            "when the video would be wrong or shallow without it. "
            + ('Always write "question"' if texts else 'With answer / discuss, "question" is')
            + " the self-contained question (in the user's language) whose answer is the content the video presents."
        )
    keys = ['"research": bool' if research else None, '"deeper": "none" | "answer" | "discuss"' if deeper else None]
    keys += ['"question": ""' if deeper else None, '"search": "what to look up, one line"' if research else None]
    shape = ", ".join(k for k in keys + ['"reason": "一句中文"'] if k)
    system = (
        f"You prepare a request for {WHAT[kind]} Before it is enhanced and made, decide:\n- "
        + "\n- ".join(asks)
        + f"\nReply with one JSON object only: {{{shape}}}"
    )
    user = f"用户的需求：\n{idea}" + (f"\n\n已定的设置：\n{settings}" if settings else "")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize_plan(raw: Any, *, research: bool, deeper: bool, texts: bool = False) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("deeper") or "none").strip().lower() if deeper else "none"
    question = clean(raw.get("question"), 1500)
    if mode not in DEEPER or not question:
        mode = "none"
    return {
        "research": research and _bool(raw.get("research")),
        "deeper": mode,
        "question": question if mode != "none" or (texts and deeper) else "",
        "search": clean(raw.get("search"), 300),
        "reason": clean(raw.get("reason"), 200),
    }


# 辅助决策 (utils/decision_model.py): the plan's two choices as typed questions. Going to 精答 / 讨论
# takes minutes, so those options say so (a judge otherwise picks them for everything).
DECISION_DEEPER = {
    "none": "The maker writes the content directly: the user already wrote it, or it is a story, mood piece, montage, "
    "music video or an edit of their footage, or simple enough to write from common knowledge. The default when unsure.",
    "answer": "Slow (minutes): an expert answer first works out content that has to be right (an explanation, analysis, "
    "tutorial or plan the video presents). Only when the video would be wrong or shallow without it.",
    "discuss": "Slowest (up to half an hour): several models first discuss a contested, opinion-based or predictive topic "
    "the video should present from several sides or with a balanced conclusion. Only then.",
}


def decision_request(kind: str, idea: str, settings: str, *, research: bool, deeper: bool) -> tuple[dict, dict]:
    """(state, questions) for the decision model: only the choices the user left open."""
    from open_webui.utils import decision_model as dm

    questions: dict = {}
    if research:
        questions["research"] = dm.noul(
            "`request` is a user's request to `studio`, with the `settings` already decided. Does making it well need "
            "facts that are current, specific or checkable on the web (news, data, statistics, product specs, prices, "
            "recent events, a real person's / place's / brand's actual details, technical accuracy)? No for fiction, "
            "moods, abstract or everyday scenes, a request whose own text already gives the content, or anything the "
            "maker can write from common knowledge."
        )
    if deeper:
        questions["deeper"] = dm.choice(
            "`request` is a user's request to `studio`, with the `settings` already decided. Before it is enhanced and "
            "made, should its content first be worked out elsewhere?",
            DECISION_DEEPER,
        )
    return {"studio": WHAT[kind], "request": idea, "settings": settings}, questions


def decided_plan(plan: dict, answers: dict, idea: str) -> dict:
    """The plan with the decision's choices; the question falls back to the request itself."""
    out = dict(plan)
    if "research" in answers:
        out["research"] = answers["research"]["noul"] >= 0.5
    if "deeper" in answers:
        out["deeper"] = answers["deeper"]["choice"]
    out["question"] = (out["question"] or clean(idea, 1500)) if out["deeper"] != "none" else ""
    return out


def _said(plan: dict) -> str:
    if plan["deeper"] != "none":
        return f"先交给{DEEPER[plan['deeper']]['label']}"
    return "需要联网查资料" if plan["research"] else ""


# --- 3. 增强 ------------------------------------------------------------------------------------


def _material_text(sources: list[dict], conclusion: str) -> str:
    parts = []
    if conclusion:
        parts.append("结论（已写好的精答回答 / 讨论结论，内容以它为准）：\n" + conclusion)
    for source in sources:
        parts.append(f"[{source['n']}] {source.get('title') or source['url']}\n{source['url']}\n{source.get('excerpt') or ''}")
    return clean("\n\n".join(parts), MATERIAL_MAX_CHARS)


def enhance_messages(kind: str, idea: str, settings: str, *, sources: list[dict], conclusion: str) -> list[dict]:
    limit = ENHANCED_MAX_CHARS[kind]
    if kind == "video":
        task = (
            "Rewrite the user's video request into a clear, complete brief for the agent that will make the video. "
            "Keep everything the user asked for (topic, audience, tone, style, must-have details, wording they insist on). "
            "The settings listed are decided and stated separately in the brief (做法, 画幅, 时长, 配音, 字幕, 背景音乐, 附件, 视觉风格): "
            "never contradict them and do not repeat them as items, but size the content to the length. Add what a good maker "
            "needs: the core message and audience, an opening hook, a scene-by-scene outline (about one scene per 4-8 seconds; "
            "for each: what is on screen and, when narrated, the narration / subtitle line), the visual style (palette, type, motion) "
            "and pacing, and the ending. Follow the supplied visual-style and reference priority rules: explicit user visual "
            "requirements take priority over a preset; a preset takes priority over visual details you invent. "
            "When updating a previously enhanced draft, retain content and user edits but reconcile obsolete generated "
            "visual details and timing with the current settings. Reference attachments are not automatically footage to "
            "insert. If only attachment names are provided, leave visual extraction to the maker; do not pretend to have "
            "seen them. Style never changes the chosen recipe, frame, duration, voice, subtitle switch or music."
        )
    else:
        task = (
            "Rewrite the user's prompt for a text-to-image model. Keep the subject and every requirement; add the composition, "
            "camera angle and framing, lighting, color palette, medium / style, key details and mood; put any text that must appear "
            "in the picture in quotes, exactly. With reference images, keep the instructions about them. When the prompt is a "
            "structured template (sections, fields), keep its structure and refine only its content."
        )
    rules = (
        f"{task}\nWhen material (web findings or a 精答 / 讨论 conclusion) is given: use facts only from it, put the key facts, "
        "names and numbers where they belong, never invent figures; when it contradicts the user's assumption, follow the "
        "material and say so in notes. Write in the user's language (Chinese by default). Plain text with short headings or "
        f"lists, no code blocks, no Markdown tables, never the text \"MEDIA:\", at most {limit} characters.\n"
        'Reply with one JSON object only: {"idea": "the enhanced request", '
        f'"notes": "with material: the key facts it rests on, as short lines (at most {NOTES_MAX_CHARS} characters); otherwise \\"\\"", '
        '"sources": [numbers of the sources used]}'
    )
    material = _material_text(sources, conclusion)
    user = f"用户的需求：\n{idea}" + (f"\n\n已定的设置：\n{settings}" if settings else "")
    if material:
        user += f"\n\n资料：\n{material}"
    return [{"role": "system", "content": f"You enhance a request for {WHAT[kind]}\n{rules}"}, {"role": "user", "content": user}]


def _plain(text: str) -> str:
    """No line the chat would take as a file to hand over, no code fences."""
    text = re.sub(r"MEDIA:", "MEDIA：", text, flags=re.I)
    return text.replace("```", "")


def normalize_enhanced(raw: Any, kind: str, sources: list[dict]) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    enhanced = _plain(clean(raw.get("idea"), ENHANCED_MAX_CHARS[kind]))
    if not enhanced:
        raise ValueError("增强结果是空的")
    used = {int(n) for n in raw.get("sources") or [] if str(n).isdigit()} if isinstance(raw.get("sources"), list) else set()
    sources = [s for s in sources if re.match(r"https?://", str(s.get("url") or ""), re.I)]
    picked = [s for s in sources if s["n"] in used] or sources
    return {
        "idea": enhanced,
        "notes": _plain(clean(raw.get("notes"), NOTES_MAX_CHARS)),
        "sources": [{"n": s["n"], "title": clean(s.get("title"), 120), "url": s["url"]} for s in picked[:SOURCES_MAX]],
    }


# --- the job ------------------------------------------------------------------------------------


@dataclass
class Tools:
    """What a job calls (the router builds them on the request; tests stub them)."""

    # (messages) -> the model's reply text
    ask: Callable[[list[dict]], Awaitable[str]]
    # (what to look up) -> {"queries", "docs", "skipped"?} (discussions._search)
    search: Optional[Callable[[str], Awaitable[dict]]] = None
    # (kind, question, context) -> the 精答 / 讨论 chat id
    open_deeper: Optional[Callable[[str, str, str], Awaitable[str]]] = None
    # (kind, chat id) -> None while it runs, else {"status", "content", "sources"}
    deeper_result: Optional[Callable[[str, str], Awaitable[Optional[dict]]]] = None
    model_name: str = ""
    # the user's 辅助决策模型 (decision_model.decide bound to the request): (run) -> (result, trace);
    # None when none is set — the plan is then gpt-chat's alone
    decide: Optional[Callable[[Callable], Awaitable[tuple[Any, Optional[dict]]]]] = None


@dataclass
class Job:
    id: str
    user_id: str
    kind: str
    idea: str
    settings: str
    research: bool
    deeper: bool
    status: str = "running"
    steps: list[dict] = field(default_factory=list)
    plan: Optional[dict] = None
    run: Optional[dict] = None
    result: Optional[dict] = None
    error: str = ""
    model: str = ""
    created_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None

    def step(self, key: str, status: str = "running", detail: str = "") -> dict:
        for item in self.steps:
            if item["key"] == key:
                item.update({"status": status, **({"detail": detail} if detail else {})})
                return item
        item = {"key": key, "label": STEP_LABELS[key], "status": status, "detail": detail}
        self.steps.append(item)
        return item

    def public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "idea": self.idea,
            "steps": [dict(s) for s in self.steps],
            "plan": self.plan,
            "run": self.run,
            "result": self.result,
            "error": self.error,
            "model": self.model,
            "createdAt": int(self.created_at * 1000),
        }


JOBS: dict[str, Job] = {}
_tasks: dict[str, asyncio.Task] = {}


def _sweep(now: Optional[float] = None) -> None:
    now = now or time.time()
    for job_id, job in list(JOBS.items()):
        if job.status != "running" and now - (job.ended_at or job.created_at) > JOB_TTL_SECONDS:
            JOBS.pop(job_id, None)


def running_for(user_id: str) -> int:
    return sum(1 for job in JOBS.values() if job.user_id == user_id and job.status == "running")


def get_job(job_id: str, user_id: str) -> Optional[Job]:
    job = JOBS.get(job_id)
    return job if job and job.user_id == user_id else None


async def _deeper(job: Job, tools: Tools, mode: str, question: str) -> str:
    """The question to 精答 / 讨论, waited for; returns its answer / conclusion ('' when there is none)."""
    label = DEEPER[mode]["label"]
    context = f"这是为下面的{'视频' if job.kind == 'video' else '图片'}准备内容。用户的需求：\n{job.idea}"
    chat_id = await tools.open_deeper(mode, question, context)
    job.run = {"kind": mode, "chatId": chat_id, "href": DEEPER[mode]["page"] + chat_id, "label": label}
    job.step(mode, "running", f"已交给{label}：{question[:80]}")
    deadline = time.time() + DEEPER_TIMEOUT_SECONDS[mode]
    while time.time() < deadline:
        found = await tools.deeper_result(mode, chat_id)
        if found is not None:
            if found.get("status") == "done" and found.get("content"):
                job.step(mode, "done", f"{label}已完成")
                return clean(found["content"], MATERIAL_MAX_CHARS)
            job.step(mode, "error", f"{label}没有完成（{found.get('status') or '出错'}），按现有信息继续")
            return ""
        await asyncio.sleep(DEEPER_POLL_SECONDS)
    job.step(mode, "error", f"{label}超过 {DEEPER_TIMEOUT_SECONDS[mode] // 60} 分钟没完成，按现有信息继续（它会在{label}页接着写）")
    return ""


async def _drafted(job: Job, tools: Tools) -> Optional[dict]:
    """gpt-chat's plan, or None when it failed."""
    from open_webui.utils.assistant_library import parse_json_object

    texts = tools.decide is not None
    try:
        text = await asyncio.wait_for(
            tools.ask(plan_messages(job.kind, job.idea, job.settings, research=job.research, deeper=job.deeper, texts=texts)),
            PLAN_TIMEOUT_SECONDS,
        )
        return normalize_plan(parse_json_object(text), research=job.research, deeper=job.deeper, texts=texts)
    except Exception as exc:  # noqa: BLE001 — enhanced without looking anything up
        log.info("studio prep %s: plan failed: %s", job.id, type(exc).__name__)
        return None


async def _decided(job: Job, tools: Tools) -> tuple[Optional[dict], Optional[dict]]:
    """({answers, reason} of the 辅助决策模型, its trace); (None, None) without one, (None, trace) when it failed."""
    if tools.decide is None:
        return None, None

    async def run(decider):
        state, questions = decision_request(job.kind, job.idea, job.settings, research=job.research, deeper=job.deeper)
        answers, reason = await decider.judge(state, questions)
        if not reason and "deeper" in answers and answers["deeper"].get("confidence") is not None:
            reason = f"把握 {answers['deeper']['confidence'] * 100:.0f}%"
        summary = {"research": answers["research"]["noul"] >= 0.5} if "research" in answers else {}
        if "deeper" in answers:
            summary["deeper"] = answers["deeper"]["choice"]
        return {"answers": answers, "reason": reason}, summary

    return await tools.decide(run)


async def run_job(job: Job, tools: Tools) -> None:
    from open_webui.utils.assistant_library import parse_json_object
    from open_webui.utils.mode_chats import sources_from_docs

    sources: list[dict] = []
    conclusion = ""
    try:
        plan = {"research": False, "deeper": "none", "question": "", "search": "", "reason": ""}
        if job.research or job.deeper:
            job.step("plan")
            drafted, (decided, trace) = await asyncio.gather(_drafted(job, tools), _decided(job, tools))
            if drafted is None and decided is None:
                job.step("plan", "error", "分析没成功，直接增强")
            else:
                plan = decided_plan(drafted or plan, decided["answers"] if decided else {}, job.idea)
                reason = decided["reason"] if decided else plan["reason"]
                detail = "；".join(part for part in (_said(plan), reason) if part) or "不需要额外资料"
                if trace and trace["used"]:
                    detail = f"辅助决策 {trace['name']}：{detail}"
                elif trace:
                    detail += f"（辅助决策没用上：{trace.get('reason') or '调用失败'}，按原来的方式判断）"
                job.step("plan", "done", detail)
            if trace:
                plan = {**plan, "decider": trace}
            job.plan = plan

        if plan["deeper"] != "none" and tools.open_deeper and tools.deeper_result:
            try:
                conclusion = await _deeper(job, tools, plan["deeper"], plan["question"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                detail = getattr(exc, "detail", None) or type(exc).__name__
                log.info("studio prep %s: %s failed: %s", job.id, plan["deeper"], detail)
                job.step(plan["deeper"], "error", f"没能交给{DEEPER[plan['deeper']]['label']}：{str(detail)[:120]}")
        elif plan["research"] and tools.search:
            job.step("search")
            try:
                found = await asyncio.wait_for(tools.search(plan["search"] or job.idea[:600]), SEARCH_TIMEOUT_SECONDS)
                sources = sources_from_docs(found, SOURCES_MAX, SOURCE_EXCERPT_CHARS, question=f"{plan['search']} {job.idea[:300]}")
                job.step("search", "done" if sources else "skipped",
                         f"查到 {len(sources)} 个来源" if sources else "没有查到可用的资料")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.info("studio prep %s: search failed: %s", job.id, exc)
                job.step("search", "error", f"搜索没成功：{str(exc)[:120]}")

        job.step("enhance", "running", f"{tools.model_name or '模型'} 在改写")
        text = await asyncio.wait_for(
            tools.ask(enhance_messages(job.kind, job.idea, job.settings, sources=sources, conclusion=conclusion)),
            ENHANCE_TIMEOUT_SECONDS,
        )
        result = normalize_enhanced(parse_json_object(text), job.kind, sources)
        if job.run and conclusion:
            result["run"] = dict(job.run)
        job.result = result
        job.step("enhance", "done", f"{len(result['idea'])} 字")
        job.status = "done"
    except asyncio.CancelledError:
        job.status = "cancelled"
        for item in job.steps:
            if item["status"] == "running":
                item["status"] = "skipped"
        raise
    except Exception as exc:  # noqa: BLE001
        log.info("studio prep %s failed: %s", job.id, type(exc).__name__)
        job.status = "error"
        job.error = "增强超时" if isinstance(exc, asyncio.TimeoutError) else f"增强没成功：{str(exc)[:160] or type(exc).__name__}"
        for item in job.steps:
            if item["status"] == "running":
                item.update({"status": "error"})
    finally:
        job.ended_at = time.time()
        _tasks.pop(job.id, None)


def start_job(user_id: str, *, kind: str, idea: str, settings: str, research: bool, deeper: bool, tools: Tools) -> Job:
    _sweep()
    job = Job(
        id=uuid.uuid4().hex,
        user_id=user_id,
        kind=kind,
        idea=clean(idea, IDEA_MAX_CHARS),
        settings=clean(settings, SETTINGS_MAX_CHARS),
        research=research,
        deeper=deeper and kind == "video",
        model=tools.model_name,
    )
    JOBS[job.id] = job
    _tasks[job.id] = asyncio.create_task(run_job(job, tools))
    return job


def cancel_job(job: Job) -> bool:
    task = _tasks.get(job.id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


# --- the video brief: enhanced on the chat's Hermes turn ------------------------------------------
# 开始制作 starts the job and sends the brief at once with this line in it: the chat's Hermes turn
# (hermes_agent.run_hermes_agent) waits for the job — on the server, so nobody has to stay on the
# studio page — shows its steps as the reply's status, and puts the result in place of the line
# before the brief reaches Hermes or the runner.
PREP_MARK = "（制作前准备：HaloWebUI 正在增强需求，编号 {id}）"
PREP_MARK_RE = re.compile(r"^（制作前准备：HaloWebUI 正在增强需求，编号 ([0-9a-f]{32})）[ \t]*\n?", re.M)
WAIT_POLL_SECONDS = 1.0
TEXT_PARTS = ("text", "input_text")


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") in TEXT_PARTS)
    return str(content or "")


def prep_job_in(content: Any) -> Optional[str]:
    """The job id a brief waits for, or None."""
    found = PREP_MARK_RE.search(_text_of(content))
    return found.group(1) if found else None


def brief_sections(result: Optional[dict]) -> str:
    """What the enhancement adds to the brief (src/lib/utils/video-brief.ts writes the same for an
    enhancement done on the page): the enhanced request, the key facts and their sources."""
    if not result or not result.get("idea"):
        return ""
    lines = ["## 增强后的需求（按当前制作设置执行；用户原话中的明确要求优先，旧增强草稿不覆盖新设置）", result["idea"].strip()]
    sources = [s for s in result.get("sources") or [] if re.match(r"https?://", str(s.get("url") or ""), re.I)]
    run = result.get("run")
    if (result.get("notes") or "").strip() or sources or run:
        lines += ["", "## 资料与依据（制作前已查好：事实和数字以此为准，不要编造）"]
        if (result.get("notes") or "").strip():
            lines.append(result["notes"].strip())
        if run:
            lines.append(f"- {run['label']}结论：HaloWebUI {run['href']}（完整内容在那里）")
        if sources:
            lines.append("- 来源：")
            for i, s in enumerate(sources, 1):
                title = " ".join(str(s.get("title") or "").split()).replace("MEDIA:", "MEDIA：")[:120] or s["url"]
                url = "".join(str(s["url"]).split())
                lines.append(f"  {i}. {title} {url}")
    return "\n".join(lines) + "\n"


def fill_brief(content: Any, result: Optional[dict]) -> Any:
    """The brief with the job's line replaced by its result (or just taken out without one)."""
    sections = brief_sections(result)

    def fill(text: str) -> str:
        return PREP_MARK_RE.sub(lambda _m: sections, text, count=1)

    if isinstance(content, list):
        return [{**part, "text": fill(str(part.get("text") or ""))} if isinstance(part, dict) and part.get("type") in TEXT_PARTS else part
                for part in content]
    return fill(str(content or ""))


def status_line(job: Job) -> str:
    """The reply's status while the job runs: its current step."""
    step = next((s for s in reversed(job.steps) if s["status"] == "running"), None) or (job.steps[-1] if job.steps else None)
    if step is None:
        return "制作前先增强需求…"
    detail = f"：{step['detail']}" if step.get("detail") else ""
    return f"制作前先增强需求 · {step['label']}{detail}"[:200]


def outcome_line(job: Optional[Job]) -> str:
    if job is None:
        return "增强任务已不在（服务重启过），按原文制作"
    if job.status != "done" or not job.result:
        return f"{job.error or '增强没成功'}，按原文制作"
    parts = [f"需求已增强（{job.model or 'gpt-chat'}）"]
    if job.result.get("run"):
        parts.append(f"参考了{job.result['run']['label']}结论")
    if job.result.get("sources"):
        parts.append(f"{len(job.result['sources'])} 个网上来源")
    return " · ".join(parts) + "，交给制作者"


async def wait_for(job: Job, on_status: Callable[[str], Awaitable[Any]]) -> Job:
    """Waits for the job, telling each new status line. Cancelled (the reply stopped): the job too."""
    said = ""
    try:
        while job.status == "running":
            line = status_line(job)
            if line != said:
                said = line
                await on_status(line)
            await asyncio.sleep(WAIT_POLL_SECONDS)
    except asyncio.CancelledError:
        cancel_job(job)
        raise
    return job
