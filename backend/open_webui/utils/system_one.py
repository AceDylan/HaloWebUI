"""Jev (TypeSafe's System One model) behind an ordinary chat model.

Jev does not write text: ``POST /v1/systemone`` takes the material to judge (``state``) and typed
questions (choice / score / noul) and returns, per question, the chosen option, a probability for
every option and a confidence. A chat with a Jev model therefore runs in three steps:

1. **拟题** — gpt-chat (the user's own, else the model 精答 plans with) turns the message into
   the request: the material copied as it is, questions in English (Jev is most accurate in
   English) with Chinese titles and option names for the table. A message that is itself the
   request JSON (``{"state": …, "questions": {…}}``) goes to Jev as it is.
2. **判断** — the request goes to the connection's ``/systemone``.
3. **结果** — the answers become a Markdown table, with the distribution and the request sent.

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
CONTEXT_MAX_CHARS = 6000
STATE_MAX_CHARS = 60000
REQUEST_TIMEOUT = 60

# jev-latest, also behind a connection prefix (94dae559.jev-latest) or a modelref (…::jev-latest)
_MODEL_RE = re.compile(r"(?:^|[/.:])jev(?:$|[-_.:@])", re.I)
_ID_RE = re.compile(r"[^a-z0-9_]+")

PLANNER_SYSTEM = """你把用户的话变成 Jev 判断模型（TypeSafe System One）的请求。Jev 不写文字，只对「材料」(state) 回答一组互相独立的判断题，每题是下面三种之一：
- choice：从几个互斥选项里选一个。criteria 是 {选项键: 英文描述}，2–12 个；选项可能覆盖不全时加 other。
- score：在有序等级上的位置。criteria 是 2–10 条英文等级描述，从低到高，每条描述一种具体情形，不要只写「中等」这类程度词。
- noul：是/否题，返回「是」的概率。criteria 通常省略；界限微妙时写 {"true": "英文：什么算是", "false": "英文：什么算否"}。

规则：
1. state 是要判断的材料：原样照抄用户给的内容，不改写、不总结掉事实；材料在对话前文里就从前文取。材料有几部分时用 JSON 对象分字段。
2. 每题只问一件一眼能判断的事；复杂的判断拆成几题。最多 8 题。
3. instructions 和 criteria 用英文写，题目写完整（Jev 看不到题目 ID）；引用 state 里的字段用反引号路径，如 `ticket.text`。
4. title 是给用户看的中文短问题；labels 是选项/等级的中文名：choice 为 {选项键: 中文}，score 为与 criteria 等长的中文数组。
5. 题目 ID 用小写英文和下划线。
6. 用户没给出可判断的材料或判断目标（只是打招呼、让你写东西、问知识）时，questions 留空，note 用中文一句话说明还需要什么。

只输出一个 JSON 对象，不要其他文字：
{"state": "…", "questions": {"题目id": {"type": "choice", "title": "…", "instructions": "…", "criteria": {"…": "…"}, "labels": {"…": "…"}}}, "note": ""}"""

HELP = """Jev 是判断模型：不写文字，只对一段材料回答判断题（选哪一类、落在哪个等级、是或否的概率）。

把**要判断的内容**和**想判断什么**一起发来，例如：

- 这条工单该交给哪个组、急不急：「我被扣了两次款，今天之内要退款」
- 这段评论是不是广告、语气有多负面：……

也可以直接发请求 JSON：`{"state": "…", "questions": {"q1": {"type": "noul", "instructions": "…"}}}`"""


class SystemOneError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Plan:
    body: dict  # what goes to /systemone
    display: dict  # question id -> {"title": str, "labels": dict | list}
    note: str = ""


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


def _question(raw: Any) -> Optional[tuple[dict, dict]]:
    """A planner question → (the question Jev gets, its display names), or None when malformed."""
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        return None
    kind = raw["type"]
    instructions = _str(raw.get("instructions"))
    if not instructions:
        return None
    question: dict = {"type": kind, "instructions": instructions}
    display: dict = {"title": _str(raw.get("title"), 200) or instructions[:200]}
    criteria, labels = raw.get("criteria"), raw.get("labels")
    if kind == "choice":
        if not isinstance(criteria, dict):
            return None
        options = {_str(k, 80): _str(v) for k, v in criteria.items() if _str(k, 80) and _str(v)}
        if len(options) < 2:
            return None
        question["criteria"] = dict(list(options.items())[:12])
        display["labels"] = {
            k: _str(labels.get(k), 80) for k in question["criteria"] if isinstance(labels, dict) and _str(labels.get(k))
        }
    elif kind == "score":
        if not isinstance(criteria, list):
            return None
        levels = [_str(v) for v in criteria if _str(v)][:10]
        if len(levels) < 2:
            return None
        question["criteria"] = levels
        names = [_str(v, 80) for v in labels] if isinstance(labels, list) else []
        display["labels"] = names if len(names) == len(levels) else []
    elif isinstance(criteria, dict) and _str(criteria.get("true")) and _str(criteria.get("false")):
        question["criteria"] = {"true": _str(criteria["true"]), "false": _str(criteria["false"])}
    return question, display


def plan_from(text: str, model: str, background: str, ask: str) -> Plan:
    """The planner's reply → a Plan; no valid question leaves only its note (or a default one)."""
    value = _json_object(text) or {}
    questions: dict = {}
    display: dict = {}
    raw_questions = value.get("questions") if isinstance(value.get("questions"), dict) else {}
    for raw_id, raw in raw_questions.items():
        parsed = _question(raw)
        if not parsed:
            continue
        qid = _ID_RE.sub("_", str(raw_id).lower()).strip("_")[:48] or f"q{len(questions) + 1}"
        while qid in questions:
            qid += "_"
        questions[qid], display[qid] = parsed
        if len(questions) >= MAX_QUESTIONS:
            break
    state = value.get("state")
    if state in (None, "", {}, []):
        state = "\n\n".join(t for t in (background, ask) if t)
    if isinstance(state, str):
        state = state[:STATE_MAX_CHARS]
    return Plan(
        body={"model": model, "state": state, "questions": questions},
        display=display,
        note=_str(value.get("note"), 300),
    )


def planner_messages(ask: str, background: str) -> list[dict]:
    return [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": f"对话前文：\n{background or '（无）'}\n\n这次的消息：\n{ask}"},
    ]


# ---------------------------------------------------------------------------
# Answers → Markdown
# ---------------------------------------------------------------------------


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip() or "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _choice_name(key: str, labels: Any) -> str:
    name = labels.get(key) if isinstance(labels, dict) else None
    return f"{name}（{key}）" if name and name != key else key


def _level_names(question: dict, answer: dict, labels: Any) -> list[str]:
    levels = question.get("criteria") if isinstance(question.get("criteria"), list) else []
    if not levels and isinstance(answer.get("legend"), dict):
        levels = [answer["legend"][k] for k in sorted(answer["legend"], key=lambda k: int(k) if str(k).isdigit() else 0)]
    if isinstance(labels, list) and len(labels) == len(levels):
        return [str(v) for v in labels]
    return [str(v) for v in levels]


def _distribution(probabilities: Any, name: Callable[[str], str], top: int = 4) -> str:
    if not isinstance(probabilities, dict):
        return ""
    ranked = [kv for kv in sorted(probabilities.items(), key=lambda kv: -float(kv[1] or 0))[:top] if float(kv[1] or 0) >= 0.01]
    # a single option at ~100% says nothing the table doesn't
    return " · ".join(f"{name(str(k))} {_pct(v)}" for k, v in ranked) if len(ranked) > 1 else ""


def _row(qid: str, question: dict, answer: dict, display: dict) -> tuple[str, str, str, str]:
    """(问题, 结论, 把握, 分布) for one answer."""
    title = display.get("title") or question.get("instructions") or qid
    labels = display.get("labels")
    kind = answer.get("type") or question.get("type")
    confidence = _pct(answer["confidence"]) if answer.get("confidence") is not None else "—"
    if kind == "choice":
        choice = str(answer.get("choice") or "")
        name = lambda k: _choice_name(k, labels)  # noqa: E731
        return title, name(choice) if choice else "—", confidence, _distribution(answer.get("probabilities"), name)
    if kind == "score":
        names = _level_names(question, answer, labels)
        try:
            score = float(answer.get("score"))
        except (TypeError, ValueError):
            return title, "—", confidence, ""
        nearest = min(max(round(score), 0), len(names) - 1) if names else None
        verdict = f"{names[nearest]}（{score:.2f} / {len(names) - 1}）" if nearest is not None else f"{score:.2f}"
        level = lambda k: names[int(k)] if k.isdigit() and int(k) < len(names) else k  # noqa: E731
        return title, verdict, confidence, _distribution(answer.get("probabilities"), level)
    if kind == "noul":
        try:
            p = float(answer.get("noul"))
        except (TypeError, ValueError):
            return title, "—", "—", ""
        verdict = "是" if p >= 0.7 else "否" if p <= 0.3 else "拿不准"
        return title, f"{verdict}（是的概率 {_pct(p)}）", "—", ""
    return title, _cell(json.dumps(answer, ensure_ascii=False)[:200]), confidence, ""


def render(plan: Plan, response: dict) -> str:
    answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
    questions = plan.body.get("questions") or {}
    rows = [_row(qid, questions.get(qid) or {}, a, plan.display.get(qid) or {}) for qid, a in answers.items() if isinstance(a, dict)]
    model = response.get("model") or plan.body.get("model")
    lines = [f"**Jev 判断结果**（{model}）", "", "| 判断 | 结论 |", "| --- | --- |"]
    # 把握 rides in the verdict cell: a third column wraps "100%" on a phone
    lines += [f"| {_cell(t)} | {_cell(v if c == '—' else f'{v} · 把握 {c}')} |" for t, v, c, _ in rows]
    spread = [f"- {t}：{d}" for t, _, _, d in rows if d]
    if spread:
        lines += ["", "各选项概率：", *spread]
    usage = response.get("usage") or {}
    if usage.get("input_tokens") is not None:
        lines += ["", f"*输入 {usage.get('input_tokens')} tokens；「把握」是 Jev 自带的置信度，越低越该人工复核。*"]
    # plain Markdown only: the reply card shows raw HTML (<details>, <sub>) as text
    request_json = json.dumps(plan.body, ensure_ascii=False, indent=2)
    lines += ["", "发给 Jev 的请求（改了直接发回来就按它再判断）：", "", "```json", request_json, "```"]
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


async def judge(messages: Any, model: str, *, ask_planner: Planner, post: Poster, status: Status, planner_name: str) -> tuple[str, dict]:
    """The chat → (the reply in Markdown, Jev's usage)."""
    ask, background = conversation(messages)
    if not ask:
        return HELP, {}
    plan = direct_request(ask, background, model)
    if plan is None:
        await status(f"{planner_name} 正在把消息拆成判断题", False)
        plan = plan_from(await ask_planner(planner_messages(ask, background)), model, background, ask)
    if not plan.body["questions"]:
        await status("没有可判断的内容", True)
        return (f"{plan.note}\n\n" if plan.note else "") + HELP, {}
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
