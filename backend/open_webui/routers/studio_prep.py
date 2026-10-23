"""提示词增强 for the video and image studios (utils/studio_prep.py): start a job, read it while
it runs, cancel it. gpt-chat analyses and rewrites; the web search is the discussion room's; a
精答 / 讨论 it needs is opened as one started on its own page (no chat of origin)."""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.models.chats import Chats
from open_webui.utils import studio_prep as prep
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)
router = APIRouter()


class StartForm(BaseModel):
    kind: Literal["video", "image"]
    idea: str = Field(min_length=1, max_length=prep.IDEA_MAX_CHARS * 2)
    # the decided settings, as the studio words them (做法, 画幅, 时长 …)
    settings: str = Field(default="", max_length=prep.SETTINGS_MAX_CHARS * 2)
    # may it look things up on the web (it decides whether the request needs it)
    research: bool = True
    # video: may it ask 精答 / 讨论 first (it decides whether the request needs it)
    deeper: bool = True


async def prep_model(request: Request, user) -> tuple[str, str]:
    """(id, name) of the user's gpt-chat, else the model 精答 plans with."""
    from open_webui.routers import answers
    from open_webui.utils import assistant_library as lib
    from open_webui.utils.auto_routing import preferred_routing_model

    models, ambiguous = await answers._models(request, user)
    _, bases = lib.library(models, user)
    preferred = preferred_routing_model(bases, models)
    if preferred:
        return preferred, lib.base_name(bases, preferred) or "gpt-chat"
    planner = answers._resolve_planner(None, models, ambiguous, user)
    return planner["model"], planner.get("name") or planner["model"]


def _tools(request: Request, user, model_id: str, model_name: str, kind: str) -> prep.Tools:
    from open_webui.utils import decision_model as dm
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.discussion_room import iterate_completion

    async def ask(messages: list[dict]) -> str:
        payload = {"model": model_id, "stream": True, "messages": messages, "metadata": {"task": "studio_prep"}}
        text = ""
        async for kind, part in iterate_completion(await generate_chat_completion(request, payload, user)):
            if kind == "content":
                text += part
        return text

    async def search(text: str) -> dict:
        from open_webui.routers import discussions

        return await discussions._search(request, user, model_id, text, [])

    async def open_deeper(kind: str, question: str, context: str) -> str:
        from open_webui.routers import answers, discussions

        opener = answers.open_for_chat if kind == "answer" else discussions.open_for_chat
        return await opener(request, user, question=question, context={"text": context, "title": "视频工作台"}, origin=None)

    async def deeper_result(kind: str, chat_id: str) -> Optional[dict]:
        return run_result(kind, chat_id, user.id)

    async def decide(run):
        return await dm.decide(request, user, "video", run, timeout=45)

    # 视频工作台's choices (web / 精答 / 讨论 first) go to the user's 辅助决策模型 when one is set
    assisted = kind == "video" and bool(dm.current(user))
    return prep.Tools(ask=ask, search=search, open_deeper=open_deeper, deeper_result=deeper_result, model_name=model_name,
                      decide=decide if assisted else None)


def run_result(kind: str, chat_id: str, user_id: str) -> Optional[dict]:
    """The 精答 / 讨论 in ``chat_id``: None while it runs, else its status and answer / conclusion."""
    from open_webui.utils import answer_desk as desk
    from open_webui.utils import discussion_room as room
    from open_webui.utils.mode_dispatch import report_of

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    if chat is None:
        return {"status": "deleted", "content": ""}
    if kind == "answer":
        from open_webui.routers import answers

        if chat.id in desk.LIVE:
            return None
        run = answers._stored_run(chat)
        terminal = desk.TERMINAL_STATUSES
    else:
        from open_webui.routers import discussions

        if chat.id in room.LIVE:
            return None
        asks = discussions._asks_of(chat)
        run = asks[-1] if asks else None
        terminal = room.TERMINAL_STATUSES
    if not isinstance(run, dict):
        return {"status": "error", "content": ""}
    if run.get("status") not in terminal:
        return None
    _, content, _ = report_of(kind, chat_id, run)
    return {"status": run.get("status"), "content": content}


def _own(job_id: str, user) -> prep.Job:
    job = prep.get_job(job_id, user.id)
    if job is None:
        raise HTTPException(404, "这次增强已经不在了")
    return job


@router.post("/")
async def start(request: Request, form: StartForm, user=Depends(get_verified_user)):
    if not form.idea.strip():
        raise HTTPException(400, "先写下需求")
    if prep.running_for(user.id) >= prep.MAX_RUNNING_PER_USER:
        raise HTTPException(429, f"已有 {prep.MAX_RUNNING_PER_USER} 个增强在进行，等它们完成再试")
    research = form.research and bool(getattr(request.app.state.config, "ENABLE_WEB_SEARCH", True))
    try:
        model_id, model_name = await prep_model(request, user)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.info("studio prep: no model (%s)", type(exc).__name__)
        raise HTTPException(400, "没有可用来增强的文本模型")
    job = prep.start_job(
        user.id,
        kind=form.kind,
        idea=form.idea,
        settings=form.settings,
        research=research,
        deeper=form.deeper,
        tools=_tools(request, user, model_id, model_name, form.kind),
    )
    return job.public()


@router.get("/{job_id}")
async def get(job_id: str, user=Depends(get_verified_user)):
    return _own(job_id, user).public()


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, user=Depends(get_verified_user)):
    job = _own(job_id, user)
    prep.cancel_job(job)
    return job.public()
