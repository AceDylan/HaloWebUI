"""Jev (TypeSafe's System One model) behind an ordinary chat model.

Jev does not write text: ``POST /v1/systemone`` takes the material to judge (``state``) and typed
questions (choice / score / noul) and returns, per question, the chosen option, a probability for
every option and a confidence. A chat with a Jev model therefore runs in three steps:

1. **拟题** — gpt-chat (the user's own, else the model 精答 plans with) turns whatever the user
   says into the request: a claim becomes a yes/no question, an open question becomes candidate
   answers to choose from, a writing request becomes short drafts to pick, the material is copied
   as it is, questions in English (Jev is most accurate in English) with Chinese titles and option
   names for the table. A plan without a usable question, or one Jev rejects, goes back to the
   planner once with the reason; after that a plain yes/no question about the message stands in.
   A message that is itself the request JSON (``{"state": …, "questions": {…}}``) goes as it is.
2. **判断** — the request goes to the connection's ``/systemone``.
3. **结果** — only the conclusions, as a Markdown table under a heading: the chat's HTML card
   pass (AGY) designs around it like any other reply, and the heading keeps the escaped-source
   fallback card away when AGY fails.

Chat tasks (title, tags, follow-ups …) that land on a Jev model are answered by gpt-chat instead.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

TYPES = ("choice", "score", "noul")
MAX_QUESTIONS = 8
PLAN_ATTEMPTS = 2
LABEL_MAX_CHARS = 200
CONTEXT_MAX_CHARS = 6000
STATE_MAX_CHARS = 60000
REQUEST_TIMEOUT = 60
# metadata key of a 辅助决策 request (utils/decision_model.REQUEST_KEY): sent to /systemone as it is
DECISION_REQUEST_KEY = "systemone_request"

# jev-latest, also behind a connection prefix (94dae559.jev-latest) or a modelref (…::jev-latest)
_MODEL_RE = re.compile(r"(?:^|[/.:])jev(?:$|[-_.:@])", re.I)
_ID_RE = re.compile(r"[^a-z0-9_]+")

PLANNER_SYSTEM = """你把用户这次的消息变成 Jev 判断模型（TypeSafe System One）的请求，由 Jev 来回答。Jev 不写文字，也看不到对话，只对「材料」(state) 回答一组互相独立的判断题，每题是下面三种之一：
- choice：从几个互斥选项里选一个，返回每个选项的概率。criteria 是 {选项键: 英文描述}，2–12 个；选项可能覆盖不全时加 other。
- score：在有序等级上的位置。criteria 是 2–10 条英文等级描述，从低到高，每条描述一种具体情形，不要只写「中等」这类程度词。
- noul：是/否题，返回「是」的概率。criteria 通常省略；界限微妙时写 {"true": "英文：什么算是", "false": "英文：什么算否"}。

无论用户说什么，都要拆出至少 1 道 Jev 能回答、并且直接回应用户的题。不许拒绝，不许只让用户补充材料。按消息的类型：
A. 给了材料要判断（工单、评论、简历、方案、代码……）：材料放进 state，按用户想知道的出题；用户没说判断什么时，出最常见的几项（类别、质量、风险、是否需要处理）。
B. 是非题或一个说法（「1+1是2吗」「30岁每天睡8小时可以吗」）：第一题用 noul 直接判断这件事成立/可行与否；需要时再加 choice 或 score 说明程度或原因。
C. 开放问题、知识问答、求建议（「成年人每天该睡几小时」「Django 适不适合做内部平台」「选 A 还是 B」）：先想出覆盖主要可能的候选答案，做成 choice 选项（区间、方案、类别）或 score 等级；可以再加 1–2 题判断关键条件或风险。
D. 要你写东西、起名、翻译、出主意：在 state.candidates 里写 2–4 个各不相同的简短候选（每个不超过 150 字，键为 a、b、c…），出一道 choice 题让 Jev 选最好的；这题的 labels 写候选全文，用户才看得到选中的内容。
E. 打招呼、问「你是谁」「你能做什么」、闲聊：把下面「关于 Jev」的事实放进 state.facts，出题判断用户想知道的事，例如 choice「这是什么模型」、noul「能不能帮我写文章」。
F. 信息不全时不要追问：按最常见的情况作答，把你的假设写进 state.assumptions。

state 规则：
1. state 是 JSON 对象。question 放用户这次的原话（照抄）。用户给的材料原样放进 material（几部分时分字段），不改写、不总结掉事实；判断要用到对话前文时，把相关前文放进 context。
2. 不要把你自己的结论写进 state，否则 Jev 只是在复述你；候选答案只出现在选项里（D 类的 candidates 除外）。

出题规则：
1. 第一题回答用户最想知道的那件事；一般 1–4 题，最多 8 题；每题只问一件一眼能判断的事。
2. instructions 和 criteria 用英文，题目写完整（Jev 看不到题目 ID 和中文名）；引用 state 字段用反引号路径，如 `material.text`。
3. title 是给用户看的中文问题，尽量用用户自己的说法；labels 是选项或等级的中文名：choice 为 {选项键: 中文}，score 为与 criteria 等长的中文数组。title 和 labels 里不用反引号和 Markdown。
4. 题目 ID 和选项键用小写英文和下划线。

关于 Jev：TypeSafe 的 System One 判断模型。擅长分类、打分和是非判断，给出每个选项的概率和把握；不写长文，不联网，主要用英文训练。

只输出一个 JSON 对象，不要其他文字：
{"state": {"question": "…"}, "questions": {"题目id": {"type": "choice", "title": "…", "instructions": "…", "criteria": {"…": "…"}, "labels": {"…": "…"}}}}"""

RETRY_PROMPT = """{problem}
按规则重新输出完整的 JSON 对象，至少 1 道合格的题，不要其他文字。"""

HELP = """### Jev 能做什么

Jev 是判断模型：不写文字，只给判断——选哪一类、落在哪个等级、是或否的概率，以及它有几成把握。

随便问就行，gpt-chat 会先把你的话拆成判断题再交给 Jev，例如：

- 是非：「1+1 等于 2 吗」「30 岁每天睡 7 小时够吗」
- 选择：「做内部平台用 Django 还是 FastAPI」
- 分类打分：「这条工单该交给哪个组、急不急」「这段评论是不是广告、有多负面」"""


class SystemOneError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Plan:
    body: dict  # what goes to /systemone
    display: dict  # question id -> {"title": str, "labels": dict | list}
    problems: tuple = ()  # why planner questions were dropped, for the retry


# ---------------------------------------------------------------------------
# Detection and endpoint
# ---------------------------------------------------------------------------


def is_system_one_model(model_id: Optional[str], url: str = "") -> bool:
    """A Jev model id (``jev-latest``, ``jev-1.14`` …), or any model on a ``/systemone`` connection."""
    return bool(_MODEL_RE.search(str(model_id or ""))) or (url or "").rstrip("/").endswith("/systemone")


def is_system_one_entry(model: Any) -> bool:
    """A models-map entry (or an assistant built on one) that is Jev: it judges, it does not write,
    so no workbench (讨论 seats, 精答, 协作, 自动分流, 拟题) may pick it."""
    if not isinstance(model, dict):
        return is_system_one_model(model)
    info = model.get("info") or {}
    ids = (model.get("id"), model.get("original_id"), model.get("model_id"), info.get("base_model_id"))
    return any(is_system_one_model(i) for i in ids if i)


def system_one_url(url: str) -> str:
    """The connection's System One endpoint: as entered when it already is one, else on its /v1."""
    base = (url or "").rstrip("/")
    if base.endswith("/systemone"):
        return base
    for suffix in ("/chat/completions", "/responses"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return f"{base}/systemone" if base.endswith("/v1") else f"{base}/v1/systemone"


# ---------------------------------------------------------------------------
# Conversation → request
# ---------------------------------------------------------------------------


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in ("text", "input_text")
        )
    return ""


def conversation(messages: Any) -> tuple[str, str]:
    """(the last user message, the turns before it as 「用户：/助手：」 text, latest kept)."""
    turns = [m for m in messages or [] if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    ask = ""
    while turns:
        last = turns.pop()
        if last.get("role") == "user":
            ask = _text(last.get("content")).strip()
            break
    lines = []
    for m in turns:
        text = _text(m.get("content")).strip()
        if text:
            lines.append(f"{'用户' if m['role'] == 'user' else '助手'}：{text}")
    background = "\n\n".join(lines)
    if len(background) > CONTEXT_MAX_CHARS:
        background = "…" + background[-CONTEXT_MAX_CHARS:]
    return ask, background


def _json_object(text: str) -> Optional[dict]:
    """The first JSON object in a reply (fenced or not; whatever follows it is ignored)."""
    text = text or ""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for start in ([fenced.start(1)] if fenced else []) + [m.start() for m in re.finditer(r"\{", text)][:20]:
        try:
            value, _ = json.JSONDecoder().raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def direct_request(ask: str, background: str, model: str) -> Optional[Plan]:
    """The message is the request JSON itself (questions required, state defaults to the chat)."""
    value = _json_object(ask) if ask.lstrip().startswith(("{", "```")) else None
    if not value or not isinstance(value.get("questions"), dict) or not value["questions"]:
        return None
    state = value.get("state")
    if state in (None, ""):
        state = background
    return Plan(body={"model": model, "state": state, "questions": value["questions"]}, display={})


def _str(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _question(raw: Any) -> tuple[dict, dict] | str:
    """A planner question → (the question Jev gets, its display names), or why it is unusable."""
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        return f"type 必须是 {' / '.join(TYPES)}"
    kind = raw["type"]
    instructions = _str(raw.get("instructions"))
    if not instructions:
        return "缺 instructions"
    question: dict = {"type": kind, "instructions": instructions}
    display: dict = {"title": _str(raw.get("title"), 200) or instructions[:200]}
    criteria, labels = raw.get("criteria"), raw.get("labels")
    if kind == "choice":
        if not isinstance(criteria, dict):
            return "choice 的 criteria 必须是 {选项键: 英文描述}"
        options = {_str(k, 80): _str(v) for k, v in criteria.items() if _str(k, 80) and _str(v)}
        if len(options) < 2:
            return "choice 至少要 2 个选项"
        question["criteria"] = dict(list(options.items())[:12])
        display["labels"] = {
            k: _str(labels.get(k), LABEL_MAX_CHARS)
            for k in question["criteria"]
            if isinstance(labels, dict) and _str(labels.get(k))
        }
    elif kind == "score":
        if not isinstance(criteria, list):
            return "score 的 criteria 必须是从低到高的英文等级数组"
        levels = [_str(v) for v in criteria if _str(v)][:10]
        if len(levels) < 2:
            return "score 至少要 2 个等级"
        question["criteria"] = levels
        names = [_str(v, LABEL_MAX_CHARS) for v in labels] if isinstance(labels, list) else []
        display["labels"] = names if len(names) == len(levels) else []
    elif isinstance(criteria, dict) and _str(criteria.get("true")) and _str(criteria.get("false")):
        question["criteria"] = {"true": _str(criteria["true"]), "false": _str(criteria["false"])}
    return question, display


def plan_from(text: str, model: str, background: str, ask: str) -> Plan:
    """The planner's reply → a Plan with its usable questions; ``problems`` says what was dropped."""
    value = _json_object(text)
    if value is None:
        return Plan(body={"model": model, "state": ask, "questions": {}}, display={}, problems=("回复里没有 JSON 对象",))
    questions: dict = {}
    display: dict = {}
    problems: list[str] = []
    raw_questions = value.get("questions") if isinstance(value.get("questions"), dict) else {}
    for raw_id, raw in raw_questions.items():
        parsed = _question(raw)
        if isinstance(parsed, str):
            problems.append(f"{raw_id}：{parsed}")
            continue
        qid = _ID_RE.sub("_", str(raw_id).lower()).strip("_")[:48] or f"q{len(questions) + 1}"
        while qid in questions:
            qid += "_"
        questions[qid], display[qid] = parsed
        if len(questions) >= MAX_QUESTIONS:
            break
    if not raw_questions:
        problems.append("questions 是空的")
    state = value.get("state")
    if state in (None, "", {}, []):
        state = "\n\n".join(t for t in (background, ask) if t)
    if isinstance(state, dict):
        # the user's own words, not the planner's copy of its prompt (「对话前文：…这次的消息：…」)
        state = {**state, "question": ask[:STATE_MAX_CHARS]}
    elif isinstance(state, str):
        state = state[:STATE_MAX_CHARS]
    return Plan(body={"model": model, "state": state, "questions": questions}, display=display, problems=tuple(problems))


def fallback_plan(ask: str, background: str, model: str) -> Plan:
    """The last resort when the planner gives nothing Jev takes: one yes/no question on the message."""
    state: dict = {"question": ask[:STATE_MAX_CHARS]}
    if background:
        state["context"] = background
    question = {
        "type": "noul",
        "instructions": (
            "`question` is the user's message. If it asks a yes/no question, is the answer yes? "
            "If it states a claim or proposes something, is the claim true or the proposal reasonable?"
        ),
    }
    title = re.sub(r"\s+", " ", ask).strip()
    title = title if len(title) <= 60 else title[:60] + "…"
    return Plan(body={"model": model, "state": state, "questions": {"answer": question}}, display={"answer": {"title": title}})


def planner_messages(ask: str, background: str) -> list[dict]:
    return [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": f"对话前文：\n{background or '（无）'}\n\n这次的消息：\n{ask}"},
    ]


# ---------------------------------------------------------------------------
# Answers → Markdown
# ---------------------------------------------------------------------------


def _cell(value: Any) -> str:
    # no backticks: the HTML card designer copies them, and a card with backticks is rejected
    return str(value).replace("`", "").replace("|", "\\|").replace("\n", " ").strip() or "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _choice_name(key: str, labels: Any) -> str:
    name = labels.get(key) if isinstance(labels, dict) else None
    return str(name) if name else key


def _level_names(question: dict, answer: dict, labels: Any) -> list[str]:
    levels = question.get("criteria") if isinstance(question.get("criteria"), list) else []
    if not levels and isinstance(answer.get("legend"), dict):
        levels = [answer["legend"][k] for k in sorted(answer["legend"], key=lambda k: int(k) if str(k).isdigit() else 0)]
    if isinstance(labels, list) and len(labels) == len(levels):
        return [str(v) for v in labels]
    return [str(v) for v in levels]


def _alternatives(probabilities: Any, name: Callable[[str], str], top: int = 4) -> str:
    """The options worth a look when Jev is split (the runner-up has 10% or more); else ""."""
    if not isinstance(probabilities, dict):
        return ""
    try:
        ranked = sorted(((k, float(v or 0)) for k, v in probabilities.items()), key=lambda kv: -kv[1])
    except (TypeError, ValueError):
        return ""
    if len(ranked) < 2 or ranked[1][1] < 0.1:
        return ""
    return " · ".join(f"{name(str(k))} {_pct(v)}" for k, v in ranked[:top] if v >= 0.01)


def _row(qid: str, question: dict, answer: dict, display: dict) -> tuple[str, str, Optional[float], str]:
    """(问题, 结论, 把握, 其他可能) for one answer."""
    title = display.get("title") or question.get("instructions") or qid
    labels = display.get("labels")
    kind = answer.get("type") or question.get("type")
    try:
        confidence = float(answer["confidence"]) if answer.get("confidence") is not None else None
    except (TypeError, ValueError):
        confidence = None
    if kind == "choice":
        choice = str(answer.get("choice") or "")
        name = lambda k: _choice_name(k, labels)  # noqa: E731
        return title, name(choice) if choice else "—", confidence, _alternatives(answer.get("probabilities"), name)
    if kind == "score":
        names = _level_names(question, answer, labels)
        try:
            score = float(answer.get("score"))
        except (TypeError, ValueError):
            return title, "—", confidence, ""
        if not names:
            return title, f"{score:.2f}", confidence, ""
        verdict = names[min(max(round(score), 0), len(names) - 1)]
        level = lambda k: names[int(k)] if k.isdigit() and int(k) < len(names) else k  # noqa: E731
        return title, verdict, confidence, _alternatives(answer.get("probabilities"), level)
    if kind == "noul":
        try:
            p = float(answer.get("noul"))
        except (TypeError, ValueError):
            return title, "—", None, ""
        if p >= 0.7:
            return title, f"是（{_pct(p)}）", None, ""
        if p <= 0.3:
            return title, f"否（{_pct(1 - p)}）", None, ""
        return title, f"拿不准（是的概率 {_pct(p)}）", None, ""
    return title, json.dumps(answer, ensure_ascii=False)[:200], confidence, ""


def render(plan: Plan, response: dict) -> str:
    """Jev's answers as the conclusions only: a heading, a two-column table, the split votes."""
    answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
    questions = plan.body.get("questions") or {}
    rows = [_row(qid, questions.get(qid) or {}, a, plan.display.get(qid) or {}) for qid, a in answers.items() if isinstance(a, dict)]
    # the heading makes this "structured Markdown": no escaped-source fallback card when AGY fails
    lines = ["### Jev 的判断", "", "| 问题 | 结论 |", "| --- | --- |"]
    # 把握 rides in the verdict cell: a third column wraps "100%" on a phone
    lines += [f"| {_cell(t)} | {_cell(v if c is None else f'{v} · 把握 {_pct(c)}')} |" for t, v, c, _ in rows]
    split = [f"- {_cell(t)}：{_cell(alt)}" for t, _, _, alt in rows if alt]
    if split:
        lines += ["", "**各选项概率**", "", *split]
    if any(c is not None and c < 0.6 for _, _, c, _ in rows):
        lines += ["", "把握不到 60% 的结论，建议再人工看一眼。"]
    # plain Markdown only: the reply card shows raw HTML (<details>, <sub>) as text
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Upstream call and the chat-completion envelope
# ---------------------------------------------------------------------------


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if body.get("detail"):
            detail = body["detail"]
            return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        if body.get("message"):
            return str(body["message"])
    return str(body or "")


async def post_system_one(url: str, headers: dict, body: dict) -> dict:
    import aiohttp

    from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL

    async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as session:
        async with session.post(url, json=body, headers=headers, ssl=AIOHTTP_CLIENT_SESSION_SSL) as r:
            raw = await r.text()
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = {"error": raw[:600]}
            if r.status >= 400:
                raise SystemOneError(f"Jev 返回 HTTP {r.status}：{_error_text(data)[:600]}", r.status)
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                raise SystemOneError(f"Jev 的回复里没有 answers：{raw[:300]}")
            return data


Planner = Callable[[list[dict]], Awaitable[str]]
Poster = Callable[[dict], Awaitable[dict]]
Status = Callable[[str, bool], Awaitable[None]]


async def _plan_and_post(ask: str, background: str, model: str, *, ask_planner: Planner, post: Poster, status: Status, planner_name: str) -> tuple[Plan, dict]:
    """Plan until Jev takes it: a plan without a usable question, or one Jev rejects as malformed,
    goes back to the planner with the reason; the last resort is ``fallback_plan``."""
    history = planner_messages(ask, background)
    for attempt in range(PLAN_ATTEMPTS):
        await status(f"{planner_name} 正在{'重新' if attempt else ''}把消息拆成判断题", False)
        reply = await ask_planner(history)
        plan = plan_from(reply, model, background, ask)
        if not plan.body["questions"]:
            problem = "上一版没有一道合格的题：" + "；".join(plan.problems or ("questions 是空的",))
        else:
            await status(f"Jev 正在判断 {len(plan.body['questions'])} 道题", False)
            try:
                return plan, await post(plan.body)
            except SystemOneError as exc:
                if exc.status not in (400, 422):
                    raise
                problem = f"Jev 拒绝了上一版请求：{exc}"
        log.info("[JEV] plan attempt %d unusable: %s", attempt + 1, problem[:300])
        history = [*history, {"role": "assistant", "content": reply[:8000]}, {"role": "user", "content": RETRY_PROMPT.format(problem=problem)}]
    plan = fallback_plan(ask, background, model)
    await status("Jev 正在判断 1 道题", False)
    return plan, await post(plan.body)


async def judge(messages: Any, model: str, *, ask_planner: Planner, post: Poster, status: Status, planner_name: str) -> tuple[str, dict]:
    """The chat → (the reply in Markdown, Jev's usage)."""
    ask, background = conversation(messages)
    if not ask:
        return HELP, {}
    plan = direct_request(ask, background, model)
    if plan is None:
        plan, response = await _plan_and_post(
            ask, background, model, ask_planner=ask_planner, post=post, status=status, planner_name=planner_name
        )
    else:
        await status(f"Jev 正在判断 {len(plan.body['questions'])} 道题", False)
        response = await post(plan.body)
    await status(f"Jev 已判断 {len(response.get('answers') or {})} 道题", True)
    return render(plan, response), response.get("usage") or {}


def _usage(usage: dict) -> Optional[dict]:
    if not usage:
        return None
    prompt, completion = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def completion_body(model: str, content: str, usage: dict) -> dict:
    body = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    if _usage(usage):
        body["usage"] = _usage(usage)
    return body


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_body(model: str, run: Callable[[], Awaitable[tuple[str, dict]]]):
    """SSE for the chat: one content chunk, then usage, then [DONE]; a failure is an error event."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    base = {"id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
    try:
        content, usage = await run()
    except Exception as exc:  # surfaced in the chat like any upstream error
        log.warning("[JEV] %s", exc)
        code = f"http_{exc.status}" if isinstance(exc, SystemOneError) else "jev_error"
        yield _sse({"error": {"message": str(exc) or exc.__class__.__name__, "type": "api_error", "code": code}})
        yield "data: [DONE]\n\n"
        return
    yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]})
    final = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    if _usage(usage):
        final["usage"] = _usage(usage)
    yield _sse(final)
    yield "data: [DONE]\n\n"


async def chat_completion(request, user, *, form_data: dict, model: str, url: str, headers: dict, metadata: Optional[dict]):
    """The OpenAI router's answer for a Jev model (``model`` without the connection prefix)."""
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    from open_webui.routers.studio_prep import prep_model
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.discussion_room import iterate_completion

    metadata = metadata if isinstance(metadata, dict) else {}
    native = metadata.get(DECISION_REQUEST_KEY)
    if isinstance(native, dict):
        # 辅助决策 (utils/decision_model.py): its own typed questions go as they are and the raw
        # answers come back — no drafting, no gpt-chat stand-in for the task, no Markdown
        try:
            response = await post_system_one(system_one_url(url), headers, {**native, "model": model})
        except SystemOneError as exc:
            raise HTTPException(status_code=exc.status if 400 <= exc.status < 600 else 502, detail="Jev 判断失败")
        return {"object": "systemone.response", "model": model, "answers": response["answers"], "usage": response.get("usage") or {}}

    planner_id, planner_name = await prep_model(request, user)
    if is_system_one_entry(planner_id):
        raise HTTPException(status_code=400, detail="Jev 需要一个文字模型来拟判断题，但没有找到可用的文字模型")

    if metadata.get("task"):  # title / tags / follow-ups: a text model's job
        return await generate_chat_completion(request, {**form_data, "model": planner_id, "metadata": metadata}, user)

    async def ask_planner(messages: list[dict]) -> str:
        payload = {"model": planner_id, "stream": True, "messages": messages, "metadata": {"task": "jev_plan"}}
        text = ""
        async for kind, part in iterate_completion(await generate_chat_completion(request, payload, user)):
            if kind == "content":
                text += part
        return text

    endpoint = system_one_url(url)

    async def post(body: dict) -> dict:
        return await post_system_one(endpoint, headers, body)

    emitter = None
    if metadata.get("chat_id") and metadata.get("message_id"):
        from open_webui.socket.main import get_event_emitter

        emitter = get_event_emitter(metadata)

    async def status(description: str, done: bool) -> None:
        if emitter:
            await emitter({"type": "status", "data": {"action": "jev", "description": description, "done": done}})

    async def run() -> tuple[str, dict]:
        try:
            return await judge(
                form_data.get("messages"), model, ask_planner=ask_planner, post=post, status=status, planner_name=planner_name
            )
        except Exception:
            await status("Jev 判断没有完成", True)
            raise

    if form_data.get("stream"):
        return StreamingResponse(stream_body(model, run), media_type="text/event-stream")
    try:
        content, usage = await run()
    except SystemOneError as exc:
        raise HTTPException(status_code=exc.status if 400 <= exc.status < 600 else 502, detail=str(exc))
    return completion_body(model, content, usage)
