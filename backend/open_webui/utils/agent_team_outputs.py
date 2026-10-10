"""Where a team's conclusion goes once the lead has written it (协作台 → 对话 / 知识库).

- The chat a team was started from gets the conclusion as a finished reply: Hermes calls back
  when the lead has written it (the plugin's bridge → ``/teams/hermes/teams/{id}/concluded``), so
  the conversation carries on with the result in it. The notice above it names the team's
  workspace, so Hermes can open the files when asked about them.
- 「在对话里追问」: that chat, or — for a team started on its own — a new chat that opens with the
  conclusion as its first reply (and is the team's chat from then on).
- 「存入知识库」: the conclusion as a Markdown file in the user's own 「协作结论」 knowledge base,
  replacing the version saved before for the same team.
- The result's picture (结论配图), once drawn, is copied into the user's image studio gallery
  (Hermes calls back when it is ready, and the hand-over to the chat checks again).
"""

import asyncio
import io
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import quote, unquote

from open_webui.models.agent_teams import AgentTeamModel, AgentTeams
from open_webui.models.chats import ChatForm, Chats
from open_webui.utils import agent_teams
from open_webui.utils.agent_teams import HermesTarget, TeamsError
from open_webui.utils.image_studio_record import record_in_studio, team_image_studio_item

log = logging.getLogger(__name__)

KNOWLEDGE_NAME = "协作结论"
KNOWLEDGE_DESCRIPTION = "协作台各团队的结论报告（在结论页点「存入知识库」时存入）。"
# The conclusion is the task's complete result: it goes into the chat whole up to this size (the
# chat's next Hermes turn reads it as history), longer ones end with a pointer to the page.
CHAT_CONTENT_MAX_CHARS = 60000
CHAT_POST_MAX_CHARS = CHAT_CONTENT_MAX_CHARS + 4000
NOTICE_SOURCE = "team"

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK_RE = re.compile(r'(!?\[[^\]]*\]\()(\s*<?[^)\s>]+>?)((?:\s+"[^"]*")?\))')
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_IMAGE_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg|bmp|avif)$", re.IGNORECASE)
_UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_PROMPT_BLOCK_RE = re.compile(r"^## 提示词\s*\n+(`{3,})\n(.*?)\n\1", re.MULTILINE | re.DOTALL)
_gallery_locks: dict[str, asyncio.Lock] = {}


def run_id(team_id: str, generated_at: Any) -> str:
    """The id a posted conclusion carries in its chat (one post per written version)."""
    return f"team:{team_id}:{generated_at or 0}"


def file_url(team_id: str, path: str) -> str:
    return f"/api/v1/teams/{team_id}/files/" + "/".join(quote(part) for part in path.split("/"))


def _href(team_id: str, href: str, workspace: str) -> str:
    """A link in the report → a URL that works in a chat: workspace files go through the team's
    file route (the session cookie loads them); anything with a scheme or an anchor stays."""
    raw = re.sub(r"^<|>$", "", href.strip())
    if not raw or raw.startswith("#") or raw.startswith("//") or _SCHEME_RE.match(raw):
        return raw
    path = raw
    if path.startswith("/"):
        if not workspace or not (path == workspace or path.startswith(workspace + "/")):
            return raw
        path = path[len(workspace) + 1:]
    path = re.sub(r"^\./", "", path)
    if not path or ".." in path.split("/"):
        return raw
    clean, query = re.match(r"([^?#]*)(.*)", path, re.DOTALL).groups()
    return file_url(team_id, unquote(clean)) + query


def chat_links(team_id: str, markdown: str, workspace: str = "", files: Optional[list] = None) -> str:
    """The report with its workspace links and bare image paths pointed at the team's files
    (same rules as the conclusion page, model.ts prepareReport); code blocks stay as written."""
    known = set(files or [])
    workspace = (workspace or "").rstrip("/")
    fence: Optional[str] = None
    out = []
    for line in (markdown or "").replace("\r\n", "\n").split("\n"):
        marker = _FENCE_RE.match(line)
        if marker:
            if fence is None:
                fence = marker.group(1)[0]
            elif marker.group(1)[0] == fence:
                fence = None
            out.append(line)
            continue
        if fence is not None:
            out.append(line)
            continue
        bare = line.strip().strip("`")
        rel = bare[len(workspace) + 1:] if workspace and bare.startswith(workspace + "/") else bare
        if rel and rel in known and _IMAGE_RE.search(rel) and not re.search(r"\s", rel):
            out.append(f"![{rel}]({file_url(team_id, rel)})")
            continue
        out.append(_LINK_RE.sub(lambda m: m.group(1) + _href(team_id, m.group(2), workspace) + m.group(3), line))
    return "\n".join(out)


def _acceptance_lines(entry: dict) -> list[str]:
    acceptance = entry.get("acceptance") if isinstance(entry.get("acceptance"), dict) else {}
    if acceptance.get("status") != "ready":
        return []
    summary = str(acceptance.get("summary") or "").strip()
    if acceptance.get("verdict") == "met":
        return [f"> 🎯 负责人验收：目标已达成{' · ' + summary if summary else ''}"]
    verdict = "目标没有达成" if acceptance.get("verdict") == "unmet" else "部分达成"
    lines = [f"> 🎯 负责人验收：{verdict}{' · ' + summary if summary else ''}"]
    for gap in (acceptance.get("gaps") or [])[:6]:
        if isinstance(gap, dict):
            detail = str(gap.get("detail") or "").strip()
            lines.append(f"> - **{str(gap.get('title') or '').strip()}**{'：' + detail if detail else ''}")
    lines.append("> （在协作台点「让团队补上」，负责人会按这些缺口加任务）")
    return lines


def chat_content(team: AgentTeamModel, conclusion: dict) -> str:
    """The conclusion as a chat reply: the report, the lead's acceptance, where the rest is."""
    markdown = chat_links(team.id, conclusion.get("markdown") or "", conclusion.get("workspace") or "",
                          [f.get("path") for f in conclusion.get("files") or [] if isinstance(f, dict)]).strip()
    if len(markdown) > CHAT_CONTENT_MAX_CHARS:
        markdown = markdown[:CHAT_CONTENT_MAX_CHARS].rstrip() + "\n\n…（结果较长，后面的部分请在协作台看）"
    tail = ["---", *_acceptance_lines(conclusion.get("entry") or {})]
    if len(tail) > 1:
        tail.append("")
    # The page shows this line as buttons that open each part in place (TeamResultBar).
    page = f"/teams/{team.id}/conclusion"
    tail.append(f"在协作台看：[结果页]({page}) · [产出文件]({page}#files) · [过程记录]({page}#process)")
    return markdown + "\n\n" + "\n".join(tail)


def notice_text(team: AgentTeamModel, conclusion: dict) -> str:
    """The line above the report. Hermes reads it on the next turn: what the team was and where
    its files are."""
    title = (team.title or "协作任务").strip()
    state = "已停止" if team.phase == "stopped" else "已完成"
    head = f"[协作任务结论] 「{title}」{state}，下面是负责人整理的完整结果。"
    parts = []
    workspace = str(conclusion.get("workspace") or "").strip()
    if workspace:
        parts.append(f"团队工作目录：{workspace}")
    project = (team.plan or {}).get("project") if isinstance((team.plan or {}).get("project"), dict) else None
    if project and project.get("branch"):
        parts.append(f"项目 {project.get('name') or ''} · 分支 {project['branch']}（还没合并）")
    parts.append(f"协作台：/teams/{team.id}")
    return (head + "；".join(parts) + "。")[:900]


async def read_conclusion(target: HermesTarget, team: AgentTeamModel) -> dict:
    body = await agent_teams.hermes_call(target, "GET", f"/{team.id}/conclusion", timeout=40)
    return body if isinstance(body, dict) else {}


def _generated_at(conclusion: dict) -> int:
    try:
        return int((conclusion.get("entry") or {}).get("generated_at") or 0)
    except (TypeError, ValueError):
        return 0


def _set_meta(team: AgentTeamModel, key: str, value: Any) -> Optional[AgentTeamModel]:
    fresh = AgentTeams.get(team.id, team.user_id) or team
    return AgentTeams.update(team.id, team.user_id, meta={**(fresh.meta or {}), key: value})


def _notify_error(exc) -> TeamsError:
    status = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None) or str(exc)
    if status == 409:
        return TeamsError(409, "这个对话正在回答别的问题，等它答完再试")
    return TeamsError(status if status in (400, 404, 409, 422) else 502, f"结论没能放进对话：{detail}")


# --- into a chat -----------------------------------------------------------------------------------

async def post_to_chat(request, team: AgentTeamModel, conclusion: dict, *, quiet: bool = False,
                       push: bool = True) -> dict:
    """Put the conclusion in the team's chat as a finished reply (once per written version).

    ``quiet``: the user asked for it and is about to look (no unread mark, no push). ``push``:
    whether the away push may go out (Hermes already tells Telegram about finished teams)."""
    from open_webui.utils.hermes_notify import HermesNotifyError, show_notification_report

    markdown = (conclusion.get("markdown") or "").strip()
    if not markdown:
        raise TeamsError(409, "还没有结论")
    generated_at = _generated_at(conclusion)
    try:
        result = await show_notification_report(
            request,
            chat_id=team.chat_id,
            content=chat_content(team, conclusion),
            notice=notice_text(team, conclusion),
            source=NOTICE_SOURCE,
            run_id=run_id(team.id, generated_at),
            quiet=quiet,
            push=push,
            design=False,
            max_chars=CHAT_POST_MAX_CHARS,
        )
    except HermesNotifyError as exc:
        raise _notify_error(exc) from exc
    _set_meta(team, "chat_posted", {"generated_at": generated_at, "at": int(time.time())})
    return result


async def concluded(request, team: AgentTeamModel, target: HermesTarget, *, telegram: bool = False) -> dict:
    """Hermes: the lead has written this team's conclusion. Into the team's chat, if it has one."""
    if not team.chat_id:
        return {"posted": False, "reason": "no chat"}
    if Chats.get_chat_by_id_and_user_id(team.chat_id, team.user_id) is None:
        return {"posted": False, "reason": "chat gone"}
    conclusion = await read_conclusion(target, team)
    if conclusion.get("status") != "ready" or not (conclusion.get("markdown") or "").strip():
        return {"posted": False, "reason": "no conclusion"}
    result = await post_to_chat(request, team, conclusion, push=not telegram)
    return {"posted": True, "chat_id": team.chat_id, "duplicate": bool(result.get("duplicate"))}


def _new_chat(user_id: str, title: str, model: dict, notice: str, content: str, *, source: str,
              run: str) -> str:
    from open_webui.utils.hermes_notify import append_report_turn
    from open_webui.utils.model_identity import get_model_selection_id

    # The id the model picker stores for this model (modelref::…), as a chat started in the page has.
    selection = get_model_selection_id(model)
    model_info = {"model": selection, "modelName": model.get("name") or selection, "modelIdx": 0}
    if model.get("model_ref") is not None:
        model_info["model_ref"] = model["model_ref"]
    chat: dict = {
        "id": "",
        "title": title,
        "models": [selection],
        "params": {},
        "files": [],
        "history": {"messages": {}, "currentId": None},
        "messages": [],
        "tags": [],
        "timestamp": int(time.time() * 1000),
    }
    user_message, assistant_message = append_report_turn(chat, notice, content, model_info, source=source, run_id=run)
    messages = chat["history"]["messages"]
    messages[user_message]["models"] = [selection]
    chat["messages"] = [messages[user_message], messages[assistant_message]]
    created = Chats.insert_new_chat(user_id, ChatForm(chat=chat, title_auto_generated=False))
    if created is None:
        raise TeamsError(500, "新对话没有建成")
    return created.id


async def follow_up(request, user, team: AgentTeamModel, target: HermesTarget) -> dict:
    """「在对话里追问」: the chat to go to, with the conclusion in it.

    The team's own chat when it still exists (the conclusion is added there if it is not yet);
    otherwise a new chat that opens with the conclusion, answered by the user's Hermes model."""
    conclusion = await read_conclusion(target, team)
    if not (conclusion.get("markdown") or "").strip():
        raise TeamsError(409, "还没有结论，等负责人写好再追问")
    if team.chat_id and Chats.get_chat_by_id_and_user_id(team.chat_id, user.id) is not None:
        try:
            result = await post_to_chat(request, team, conclusion, quiet=True)
            return {"chat_id": team.chat_id, "created": False, "posted": not result.get("duplicate")}
        except TeamsError as exc:
            if exc.status_code == 409:
                # busy answering something else: go there anyway, the conclusion follows later
                return {"chat_id": team.chat_id, "created": False, "posted": False, "busy": True}
            if exc.status_code != 422:
                raise
            # a chat with no reply to continue from: the conclusion gets a chat of its own

    from open_webui.utils.hermes_sessions import HermesSessionsError, resolve_hermes_model

    try:
        model = await resolve_hermes_model(request, user)
    except HermesSessionsError as exc:
        raise TeamsError(403, "你的账号没有可用的 Hermes 模型，开不了追问对话") from exc
    generated_at = _generated_at(conclusion)
    chat_id = _new_chat(user.id, (team.title or "协作任务")[:60], model, notice_text(team, conclusion),
                        chat_content(team, conclusion), source=NOTICE_SOURCE, run=run_id(team.id, generated_at))
    fresh = AgentTeams.get(team.id, team.user_id) or team
    AgentTeams.update(team.id, team.user_id, chat_id=chat_id,
                      meta={**(fresh.meta or {}), "chat_posted": {"generated_at": generated_at, "at": int(time.time())}})
    log.info("teams: opened chat %s to follow up on team %s", chat_id, team.id)
    return {"chat_id": chat_id, "created": True, "posted": True}


# --- into the knowledge base -----------------------------------------------------------------------

def _file_name(team: AgentTeamModel) -> str:
    title = _UNSAFE_NAME_RE.sub(" ", (team.title or "协作任务")).strip()[:60] or "协作任务"
    return f"{title} · 结论.md"


def knowledge_markdown(team: AgentTeamModel, conclusion: dict) -> str:
    """The saved file: what the team was asked, when, where its files are, then the report."""
    entry = conclusion.get("entry") or {}
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(_generated_at(conclusion) or time.time()))
    head = [f"# {team.title or '协作任务'} · 结论", "", f"- 目标：{' '.join((team.goal or '').split())[:600]}",
            f"- 结论写于：{stamp}" + (f"（{entry.get('model')}）" if entry.get("model") else "")]
    if conclusion.get("workspace"):
        head.append(f"- 工作目录：{conclusion['workspace']}")
    head += ["", "---", ""]
    return "\n".join(head) + (conclusion.get("markdown") or "").strip() + "\n"


def _own_knowledge(user_id: str):
    """The user's own 「协作结论」 base (not one shared with them under the same name)."""
    from open_webui.internal.db import get_db
    from open_webui.models.knowledge import Knowledge, KnowledgeModel

    with get_db() as db:
        row = (db.query(Knowledge).filter_by(user_id=user_id, name=KNOWLEDGE_NAME)
               .order_by(Knowledge.created_at.asc()).first())
        return KnowledgeModel.model_validate(row) if row else None


def _save_sync(request, user, team: AgentTeamModel, content: str, previous: Optional[str]) -> dict:
    from fastapi import HTTPException, UploadFile
    from starlette.datastructures import Headers

    from open_webui.models.knowledge import KnowledgeForm, Knowledges
    from open_webui.routers.files import upload_file
    from open_webui.routers.knowledge import (
        KnowledgeFileIdForm,
        add_file_to_knowledge_by_id,
        remove_file_from_knowledge_by_id,
    )
    from open_webui.utils.access_control import has_permission

    kb = _own_knowledge(user.id)
    if kb is None:
        if user.role != "admin" and not has_permission(user.id, "workspace.knowledge",
                                                       request.app.state.config.USER_PERMISSIONS):
            raise TeamsError(403, "你的账号没有建知识库的权限")
        kb = Knowledges.insert_new_knowledge(
            user.id, KnowledgeForm(name=KNOWLEDGE_NAME, description=KNOWLEDGE_DESCRIPTION, access_control={}))
        if kb is None:
            raise TeamsError(500, "「协作结论」知识库没有建成")
    upload = UploadFile(file=io.BytesIO(content.encode("utf-8")), filename=_file_name(team),
                        headers=Headers({"content-type": "text/markdown"}))
    try:
        stored = upload_file(request, upload, user=user, file_metadata={"agent_team": team.id}, process=False,
                             processing_mode=None)
        add_file_to_knowledge_by_id(request, kb.id, KnowledgeFileIdForm(file_id=stored.id), user=user)
    except HTTPException as exc:
        raise TeamsError(exc.status_code if exc.status_code in (400, 403, 404) else 502,
                         f"存入知识库失败：{exc.detail}") from exc
    replaced = False
    if previous and previous != stored.id and previous in ((kb.data or {}).get("file_ids") or []):
        try:  # the version saved before for this team: one file per team in the base
            remove_file_from_knowledge_by_id(kb.id, KnowledgeFileIdForm(file_id=previous), user=user)
            replaced = True
        except Exception:  # noqa: BLE001 — the new version is in; an old copy left behind is harmless
            log.info("teams: could not remove the previous conclusion file %s of team %s", previous, team.id)
    return {"knowledge_id": kb.id, "knowledge_name": kb.name, "file_id": stored.id, "replaced": replaced}


async def save_to_knowledge(request, user, team: AgentTeamModel, target: HermesTarget) -> dict:
    from starlette.concurrency import run_in_threadpool

    conclusion = await read_conclusion(target, team)
    if not (conclusion.get("markdown") or "").strip():
        raise TeamsError(409, "还没有结论可以存")
    generated_at = _generated_at(conclusion)
    saved = (team.meta or {}).get("knowledge") if isinstance((team.meta or {}).get("knowledge"), dict) else {}
    kb = _own_knowledge(user.id)
    if (saved.get("generated_at") == generated_at and kb is not None and kb.id == saved.get("id")
            and saved.get("file_id") in ((kb.data or {}).get("file_ids") or [])):
        return {"knowledge_id": kb.id, "knowledge_name": kb.name, "file_id": saved["file_id"], "replaced": False,
                "duplicate": True, "generated_at": generated_at}
    result = await run_in_threadpool(_save_sync, request, user, team, knowledge_markdown(team, conclusion),
                                     saved.get("file_id") if kb is not None and kb.id == saved.get("id") else None)
    _set_meta(team, "knowledge", {"id": result["knowledge_id"], "file_id": result["file_id"],
                                  "generated_at": generated_at, "at": int(time.time())})
    return {**result, "duplicate": False, "generated_at": generated_at}



# --- into the image studio gallery -----------------------------------------------------------------

def snapshot_illustration(snap: Any) -> Optional[dict]:
    """The result's picture as the live snapshot shows it (``team.conclusion.illustration``)."""
    live = snap.get("team") if isinstance(snap, dict) else None
    conclusion = (live or {}).get("conclusion") if isinstance(live, dict) else None
    illustration = conclusion.get("illustration") if isinstance(conclusion, dict) else None
    return illustration if isinstance(illustration, dict) else None


async def _illustration_prompt(target: HermesTarget, team: AgentTeamModel, illustration: dict) -> str:
    """The prompt gpt-image was given (kept next to the picture), else a line naming the picture."""
    fallback = f"协作结论配图（{illustration.get('template') or '模板'}）：{team.title or '协作任务'}"
    prompt_path = str(illustration.get("prompt_path") or "")
    if not prompt_path:
        return fallback
    try:
        data, _headers = await agent_teams.hermes_file(target, f"/{team.id}/files/{quote(prompt_path)}", timeout=20)
    except TeamsError:
        return fallback
    match = _PROMPT_BLOCK_RE.search(data.decode("utf-8", errors="replace"))
    return match.group(2).strip() if match and match.group(2).strip() else fallback


async def illustration_to_gallery(request, team: AgentTeamModel, target: HermesTarget,
                                  illustration: Optional[dict]) -> dict:
    """The result's picture into the owner's image studio gallery, once per drawn picture: the
    image is copied into HaloWebUI's own files, so it stays when the team is deleted. Best effort."""
    from open_webui.models.users import Users
    from open_webui.routers.images import upload_image

    illustration = illustration or {}
    path = str(illustration.get("path") or "")
    if illustration.get("status") != "ready" or not path or not _IMAGE_RE.search(path):
        return {"added": False, "reason": "no picture"}
    key = f"{path}@{illustration.get('at') or 0}"
    lock = _gallery_locks.setdefault(team.id, asyncio.Lock())
    async with lock:
        fresh = AgentTeams.get(team.id, team.user_id) or team
        if (fresh.meta or {}).get("gallery_image") == key:
            return {"added": False, "reason": "already"}
        user = Users.get_user_by_id(team.user_id)
        if user is None:
            return {"added": False, "reason": "no user"}
        try:
            data, headers = await agent_teams.hermes_file(target, f"/{team.id}/files/{quote(path)}")
            content_type = str(headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/") or content_type == "image/svg+xml":
                return {"added": False, "reason": "not an image"}
            prompt = await _illustration_prompt(target, team, illustration)
            url = await asyncio.to_thread(upload_image, request, {"agent_team": team.id, "path": path},
                                          data, content_type, user)
        except Exception as exc:  # noqa: BLE001 — the picture is still in the team's workspace
            log.warning("teams: picture of team %s did not reach the image studio: %s", team.id, exc)
            return {"added": False, "reason": "copy failed"}
        at = int(illustration.get("at") or time.time())
        form = team_image_studio_item(team_id=team.id, picture_id=key, url=url, prompt=prompt,
                                      model="gpt-image", created_at_ms=at * 1000)
        if not record_in_studio(team.user_id, [form]):
            return {"added": False, "reason": "gallery write failed"}
        _set_meta(fresh, "gallery_image", key)
        log.info("teams: picture of team %s added to the image studio gallery", team.id)
        return {"added": True, "url": url}
