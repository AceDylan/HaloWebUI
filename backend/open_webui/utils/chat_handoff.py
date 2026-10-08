"""总结后在新对话继续: a long chat hands over to a new one through a summary.

The chat's own model reads the branch on screen (newest messages first, as
many as fit) and writes a summary for whoever picks the work up. The new chat
starts with that exchange, a request to summarize and the summary as the reply,
so the next question has the earlier context without the earlier length. It
keeps the folder, assistant, models and chat settings of the old one.
"""

import re
import time
import uuid
from typing import Any, Optional

HANDOFF_PROMPT = """下面是一段对话的记录。之后会开一个新对话接着做，新对话只能看到你写的这份交接摘要，看不到原对话。

请写这份交接摘要：
- 用这段对话主要使用的语言书写。
- 按顺序分节：目标与背景；已确定的结论和决定；关键细节（文件路径、命令、代码、数字、链接、名称原样保留）；还没解决的问题和下一步。没有内容的小节直接省略。
- 只写对话里出现过的内容，不要补充、不要猜。
- 直接输出摘要正文，不要寒暄，不要提到"摘要"这个任务本身。

对话记录：
"""

# What fits: the transcript gets this share of the model's context window,
# the prompt and the summary itself need the rest.
TRANSCRIPT_SHARE = 0.7
DEFAULT_CONTEXT_TOKENS = 128_000
MAX_TRANSCRIPT_TOKENS = 600_000
MAX_MESSAGE_CHARS = 24_000

_DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.S | re.I)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?:data:[^)]*|[^)]{0,2000})\)")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")


def estimate_tokens(text: str) -> int:
    """Rough count: a CJK character is about a token, other text about four
    characters a token. Only used to decide how much of a chat fits."""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    text = _IMAGE_RE.sub("[图片]", _DETAILS_RE.sub("", str(content or ""))).strip()
    if len(text) > MAX_MESSAGE_CHARS:
        half = MAX_MESSAGE_CHARS // 2
        text = text[:half] + "\n…（中间省略）…\n" + text[-half:]
    return text


def branch_messages(chat: dict) -> list[dict]:
    """The messages on screen, oldest first."""
    history = chat.get("history") if isinstance(chat, dict) else None
    messages = history.get("messages") if isinstance(history, dict) else None
    if not isinstance(messages, dict):
        legacy = chat.get("messages") if isinstance(chat, dict) else None
        return [m for m in legacy if isinstance(m, dict)] if isinstance(legacy, list) else []

    branch: list[dict] = []
    seen: set[str] = set()
    current = history.get("currentId")
    while isinstance(current, str) and current in messages and current not in seen:
        seen.add(current)
        message = messages[current]
        if not isinstance(message, dict):
            break
        branch.append(message)
        current = message.get("parentId")
    branch.reverse()
    return branch


def build_transcript(messages: list[dict], context_tokens: Optional[int] = None) -> tuple[str, int]:
    """(transcript, number of older messages left out). Newest messages are
    kept first; whatever no longer fits is left out from the oldest end."""
    window = context_tokens if isinstance(context_tokens, int) and context_tokens > 0 else DEFAULT_CONTEXT_TOKENS
    budget = min(int(window * TRANSCRIPT_SHARE), MAX_TRANSCRIPT_TOKENS)

    rows: list[str] = []
    used = 0
    kept = 0
    candidates = [m for m in messages if m.get("role") in ("user", "assistant")]
    for message in reversed(candidates):
        text = _message_text(message)
        if not text:
            kept += 1
            continue
        row = f"{'用户' if message.get('role') == 'user' else '助手'}：{text}"
        cost = estimate_tokens(row)
        if rows and used + cost > budget:
            break
        rows.append(row)
        used += cost
        kept += 1
    rows.reverse()
    return "\n\n".join(rows), len(candidates) - kept


def handoff_request_messages(transcript: str, omitted: int) -> list[dict]:
    note = f"（更早的 {omitted} 条消息因篇幅没有放进来。）\n\n" if omitted > 0 else ""
    return [{"role": "user", "content": f"{HANDOFF_PROMPT}{note}{transcript}"}]


def build_handoff_chat(
    source_chat: dict,
    source_chat_id: str,
    summary: str,
    model_id: str,
    now: Optional[int] = None,
) -> dict:
    """The new chat: the request to summarize and the summary as its reply."""
    now = int(now if now is not None else time.time())
    title = str(source_chat.get("title") or "").strip() or "对话"
    models = source_chat.get("models")
    if not isinstance(models, list) or not models:
        models = [model_id]

    user_id = str(uuid.uuid4())
    reply_id = str(uuid.uuid4())
    user_message = {
        "id": user_id,
        "parentId": None,
        "childrenIds": [reply_id],
        "role": "user",
        "content": f"总结一下「{title}」这段对话，我要在新对话里接着聊。",
        "timestamp": now,
        "models": models,
    }
    reply = {
        "id": reply_id,
        "parentId": user_id,
        "childrenIds": [],
        "role": "assistant",
        "content": summary,
        "model": model_id,
        "modelIdx": 0,
        "timestamp": now,
        "done": True,
    }

    chat: dict[str, Any] = {
        "title": f"{title}（续）",
        "models": models,
        "params": source_chat.get("params") if isinstance(source_chat.get("params"), dict) else {},
        "history": {"currentId": reply_id, "messages": {user_id: user_message, reply_id: reply}},
        "messages": [user_message, reply],
        "tags": [],
        "files": [],
        "timestamp": now * 1000,
        "handoffFrom": {"chatId": source_chat_id, "title": title},
    }
    if isinstance(source_chat.get("assistant"), dict):
        chat["assistant"] = source_chat["assistant"]
    return chat
