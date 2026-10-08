"""「精答」 and 「讨论」 from a chat: the message — with what was said before it — is asked another
way, and the result comes back into the chat.

The chat's Hermes 派发方式 「精答」 / 「讨论」 (``hermes_options.dispatch`` ``"answer"`` /
``"discuss"``) lands here instead of a Hermes run, as 「协作台」 lands in agent_team_dispatch:

- the message becomes a 精答 run / a 讨论台 discussion in a chat of its own (it is in the history
  with its mark, as one started on its page): the conversation before the message is its
  background (the dispatcher and every seat read it), the message's files go on the discussion's
  table (精答 reads text only);
- this chat's reply finishes at once (no model turn) and carries ``mode_dispatch: {kind,
  chat_id}``, which the page shows as a live card (ModeDispatchCard);
- once the answer / the conclusion is written it comes back into this chat as a finished reply
  under a notice line, like a runner's report, so the conversation carries on with it (the next
  Hermes turn reads it). A chat busy answering something else gets it as soon as it is free.
"""

import asyncio
import logging
import re
import time
from typing import Any, Optional

from open_webui.models.chats import Chats

log = logging.getLogger(__name__)

MODES: dict[str, dict] = {
    "answer": {"label": "精答", "page": "/answer", "notice": "[精答结果]"},
    "discuss": {"label": "讨论", "page": "/discuss", "notice": "[讨论结论]"},
}
DEFAULT_TITLES = {"", "New Chat", "新对话", "新聊天"}
# what the run reads of the conversation before the message
CONTEXT_TURNS = 10
CONTEXT_TURN_CHARS = 2000
CONTEXT_CHARS = 8000
# the result as a reply: whole up to this size (the chat's next Hermes turn reads it)
REPORT_CONTENT_MAX_CHARS = 60000
REPORT_POST_MAX_CHARS = REPORT_CONTENT_MAX_CHARS + 4000
# a chat busy answering something else is tried again, for about ten minutes
RETRY_SECONDS = 15
RETRY_LIMIT = 40

_background: set = set()
# run chat id → the socket of the tab the message was sent from (in memory: only a hint for the
# away push, so a tab whose socket is not registered still counts as someone looking)
_sessions: dict[str, str] = {}


class ReportError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def conversation_of(messages: Any) -> tuple[str, str]:
    """(the user's own words in the last message, what was said before it as background)."""
    from open_webui.utils.agent_team_dispatch import split_conversation

    ask, lines = split_conversation(messages, turns=CONTEXT_TURNS, each=CONTEXT_TURN_CHARS, total=CONTEXT_CHARS)
    return ask, "\n\n".join(lines)


def message_file_ids(metadata: dict) -> list[str]:
    """The ids of the files (pictures too) attached to this message."""
    out: list[str] = []
    for item in (metadata or {}).get("files") or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "file", "image"):
            continue
        file_info = item.get("file") if isinstance(item.get("file"), dict) else {}
        file_id = str(item.get("id") or file_info.get("id") or "").strip()
        if not file_id:
            # a picture in the chat is referenced by its content url
            match = re.search(r"/files/([A-Za-z0-9_-]{1,128})/content", str(item.get("url") or ""))
            file_id = match.group(1) if match else ""
        if file_id and file_id not in out:
            out.append(file_id)
    return out


def card_text(kind: str, *, error: Optional[str] = None, files: int = 0) -> str:
    """The reply's words (what Hermes reads on the next turn, and what shows without the card)."""
    label = MODES[kind]["label"]
    if error:
        return f"没能交给{label}：{error}"
    if kind == "answer":
        extra = f"（附带的 {files} 个文件精答读不到，要连文件一起，用讨论或协作台）" if files else ""
        return (f"🎯 已交给精答：调度器在挑最合适的助手来回答{extra}。"
                "进度在下面的卡片里，答完后回答会发回这个对话。")
    extra = f"，附带的 {files} 个文件会放上讨论桌" if files else ""
    return (f"💬 已交给讨论台：几个模型按你上次的设置讨论这个问题{extra}，主持人最后写结论。"
            "进度在下面的卡片里，结论写好后会发回这个对话。")


async def run_mode_dispatch(request, form_data: dict, user, metadata: dict, model_id: str, kind: str) -> dict:
    """The chat's message → a 精答 run / a discussion. Finishes the reply at once (no model turn)."""
    from fastapi import HTTPException

    from open_webui.socket.main import get_event_emitter
    from open_webui.tasks import create_task
    from open_webui.utils.agent_teams import default_title
    from open_webui.utils.hermes_agent import is_temporary_chat_id

    chat_id, message_id = metadata["chat_id"], metadata["message_id"]
    emitter = get_event_emitter(metadata)
    ask, background = conversation_of(form_data.get("messages"))
    files = message_file_ids(metadata)
    label = MODES[kind]["label"]

    async def handler():
        run_chat_id = None
        error = None
        if is_temporary_chat_id(chat_id):
            error = "临时对话不保存，结果没处发回；关掉临时对话再试"
        elif not ask:
            error = f"{label}要一个写出来的问题，光有附件不够" if files else "消息是空的"
        else:
            try:
                title = (Chats.get_chat_title_by_id(chat_id) or "").strip()
                context = {"text": background, "title": "" if title in DEFAULT_TITLES else title, "chat_id": chat_id}
                origin = {"chatId": chat_id, "messageId": message_id}
                if kind == "answer":
                    from open_webui.routers import answers

                    run_chat_id = await answers.open_for_chat(request, user, question=ask, context=context, origin=origin)
                else:
                    from open_webui.routers import discussions

                    run_chat_id = await discussions.open_for_chat(
                        request, user, question=ask, context=context, origin=origin, files=files
                    )
            except HTTPException as exc:
                error = str(exc.detail)
            except Exception as exc:  # noqa: BLE001
                log.exception("mode dispatch (%s) failed", kind)
                error = type(exc).__name__
        if run_chat_id and metadata.get("session_id"):
            _sessions[run_chat_id] = str(metadata["session_id"])
        content = card_text(kind, error=error, files=len(files))
        fields: dict = {"content": content, "done": True, "completedAt": int(time.time()), "model": model_id}
        if run_chat_id:
            fields["mode_dispatch"] = {"kind": kind, "chat_id": run_chat_id}
        if error:
            fields["error"] = {"content": content}
        try:
            Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, fields)
        except Exception:  # noqa: BLE001
            log.warning("mode dispatch: could not save the reply", exc_info=True)
        data = dict(fields)
        if run_chat_id:
            try:  # a new chat is named after its question (no model turn ran to name it)
                if (Chats.get_chat_title_by_id(chat_id) or "").strip() in DEFAULT_TITLES:
                    Chats.update_chat_title_by_id(chat_id, default_title(ask))
                data["title"] = Chats.get_chat_title_by_id(chat_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            await emitter({"type": "chat:completion", "data": data})
        except Exception:  # noqa: BLE001
            log.debug("mode dispatch: reply emit failed", exc_info=True)
        if run_chat_id:
            # and into a folder (对话分组), as an ordinary chat is at this turn
            from open_webui.utils.team_chats import sort_into_folder

            asks = [m for m in (form_data.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"]
            try:
                await sort_into_folder(request, user, chat_id, model_id=model_id,
                                       messages=[{"role": "user", "content": ask}],
                                       message_id=message_id, user_message_count=max(1, len(asks)))
            except Exception:  # noqa: BLE001
                log.debug("mode dispatch: folder assignment failed", exc_info=True)

    task_id, _ = create_task(handler(), id=chat_id, owner_id=user.id)
    return {"status": True, "task_id": task_id}


# --- the result, back into the chat -----------------------------------------------------------------

def _quote(text: Any, limit: int = 60) -> str:
    line = " ".join(str(text or "").split())
    return line[:limit] + ("…" if len(line) > limit else "")


def _sources_tail(sources: list[dict]) -> str:
    lines = [f"{s['n']}. [{s.get('title') or s['url']}]({s['url']})" for s in sources if s.get("url")]
    return "\n\n---\n**资料来源**\n\n" + "\n".join(lines) if lines else ""


def report_of(kind: str, chat_id: str, run: dict) -> tuple[str, str, str]:
    """(notice, content, run id) of a finished run, as its chat of origin shows it. The notice is
    what Hermes reads on the next turn: what was asked, who answered, where the run is."""
    question = _quote(run.get("question"))
    if kind == "answer":
        from open_webui.utils import answer_desk as desk

        assistant = run.get("assistant") or {}
        name = f"{assistant.get('emoji') or ''}{assistant.get('name') or '助手'}".strip()
        web = "（查了网上的资料）" if (run.get("research") or {}).get("sources") else ""
        notice = f"{MODES[kind]['notice']} 「{question}」由「{name}」回答{web}，下面是它的回答。精答：/answer/{chat_id}"
        content = desk.stored_content(run)
    else:
        from open_webui.utils import discussion_room as room

        seats = [s.get("label") or s.get("name") or "" for s in run.get("seats") or []]
        mode = room.MODES.get(run.get("mode") or "", {}).get("label") or "讨论"
        moderator = ((run.get("conclusion") or {}).get("name") or (run.get("moderator") or {}).get("name") or "主持人")
        notice = (f"{MODES[kind]['notice']} 「{question}」：{len(seats)} 个模型{mode}（{'、'.join(seats)}），"
                  f"下面是 {moderator} 整理的结论。讨论台：/discuss/{chat_id}")
        content = ((run.get("conclusion") or {}).get("content") or "").strip()
        content += _sources_tail(room.research_sources(run))
    content = content.strip()
    if len(content) > REPORT_CONTENT_MAX_CHARS:
        content = content[:REPORT_CONTENT_MAX_CHARS].rstrip() + f"\n\n…（太长了，后面的部分请到{MODES[kind]['label']}页看）"
    return notice[:900], content, f"{kind}:{chat_id}:{run.get('id') or ''}"[:128]


async def report_back(request, kind: str, chat_id: str, run: dict, *, quiet: bool = False) -> dict:
    """The answer / conclusion of the run in ``chat_id`` into the chat it was dispatched from (once
    per run). ``quiet``: the user asked for it and is looking (no unread mark, no push)."""
    from open_webui.utils.hermes_notify import HermesNotifyError, show_notification_report

    origin = run.get("origin") or {}
    origin_id = str(origin.get("chatId") or "")
    source = Chats.get_chat_by_id(chat_id)
    if not origin_id or source is None or Chats.get_chat_by_id_and_user_id(origin_id, source.user_id) is None:
        raise ReportError(404, "派发它的那个对话已经不在了")
    notice, content, run_id = report_of(kind, chat_id, run)
    if not content:
        raise ReportError(409, "还没有可以放进对话的内容")
    try:
        result = await show_notification_report(
            request,
            chat_id=origin_id,
            content=content,
            notice=notice,
            source=kind,
            run_id=run_id,
            quiet=quiet,
            design=False,
            max_chars=REPORT_POST_MAX_CHARS,
            session_id=_sessions.get(chat_id),
        )
    except HermesNotifyError as exc:
        if exc.status_code == 409:
            raise ReportError(409, "这个对话正在回答别的问题，等它答完再试") from exc
        raise ReportError(exc.status_code if exc.status_code in (404, 422) else 502,
                          f"没能放进对话：{exc.detail}") from exc
    _sessions.pop(chat_id, None)
    return {"chat_id": origin_id, "posted": not result.get("duplicate"), "duplicate": bool(result.get("duplicate"))}


def report_back_later(request, kind: str, chat_id: str, run: dict) -> None:
    """report_back after the run's own wrap-up, tried again while the chat is busy."""

    async def go():
        for _ in range(RETRY_LIMIT):
            try:
                await report_back(request, kind, chat_id, run)
                return
            except ReportError as exc:
                if exc.status_code != 409:
                    log.info("mode dispatch: %s %s not reported back: %s", kind, chat_id, exc.detail)
                    return
            except Exception:  # noqa: BLE001
                log.exception("mode dispatch: reporting %s %s back failed", kind, chat_id)
                return
            await asyncio.sleep(RETRY_SECONDS)
        log.info("mode dispatch: %s %s not reported back, the chat stayed busy", kind, chat_id)

    task = asyncio.create_task(go())
    _background.add(task)
    task.add_done_callback(_background.discard)
