"""HTTP routes on Hermes' api_server (same port and API key as /v1/runs), for HaloWebUI only.

HaloWebUI keeps who owns which team; it sends the owner as ``X-Halo-Owner`` and every route
refuses a team whose recorded owner differs (404), so a bug on the HaloWebUI side cannot read
or drive another user's team through this API either.

  POST /v1/halo-teams/plan                         {goal, feedback?, previous?, team_id?}
  POST /v1/halo-teams                              {team_id, plan, goal, title?, chat_id?}
  GET  /v1/halo-teams/{team_id}                    snapshot
  GET  /v1/halo-teams/{team_id}/events?after=&limit=
  GET  /v1/halo-teams/{team_id}/tasks/{task_id}?log=1
  POST /v1/halo-teams/{team_id}/tasks/{task_id}/messages {body, author_name}
  POST /v1/halo-teams/{team_id}/tasks/{task_id}/retry
  POST /v1/halo-teams/{team_id}/control           {action: pause|resume|stop}
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from .common import board_slug, logger, valid_team_id
from .teams import TeamError, default_workspace

_installed = {"done": False}


def _json_response(data: Any, status: int = 200):
    from aiohttp import web

    return web.json_response(data, status=status, dumps=lambda v: json.dumps(v, ensure_ascii=False))


def _error(status: int, message: str):
    return _json_response({"error": {"message": message}}, status=status)


async def _body(request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _owner(request) -> str | None:
    owner = (request.headers.get("X-Halo-Owner") or "").strip()
    return owner or None


def _wrap(adapter: Any, handler: Callable):
    async def route(request):
        denied = adapter._check_auth(request)
        if denied is not None:
            return denied
        team_id = request.match_info.get("team_id")
        if team_id is not None and not valid_team_id(team_id):
            return _error(404, "team not found")
        try:
            return await handler(request)
        except TeamError as exc:
            return _error(exc.status, exc.message)
        except ValueError as exc:
            return _error(400, str(exc)[:300])
        except Exception:
            logger.exception("halowebui-teams: %s %s failed", request.method, request.path)
            return _error(500, "internal error")

    return route


async def _plan(request):
    from . import plan as plan_mod

    data = await _body(request)
    goal = str(data.get("goal") or "").strip()
    if not goal:
        return _error(400, "goal is required")
    if len(goal) > 8000:
        return _error(400, "目标最多 8000 字")
    team_id = str(data.get("team_id") or "")
    workspace = default_workspace(board_slug(team_id)) if valid_team_id(team_id) else default_workspace("halo-<新团队>")
    previous = data.get("previous") if isinstance(data.get("previous"), dict) else None
    result = await asyncio.to_thread(
        plan_mod.propose_plan, goal, workspace, feedback=str(data.get("feedback") or ""), previous=previous,
    )
    return _json_response(result, status=200 if result.get("ok") else 502)


async def _create(request):
    from .teams import create_team

    data = await _body(request)
    team_id = str(data.get("team_id") or "")
    owner = _owner(request)
    if not valid_team_id(team_id):
        return _error(400, "team_id is required")
    if not owner:
        return _error(400, "X-Halo-Owner is required")
    if not isinstance(data.get("plan"), dict):
        return _error(400, "plan is required")
    result = await asyncio.to_thread(
        create_team, team_id, data["plan"], owner=owner, chat_id=str(data.get("chat_id") or ""),
        goal=str(data.get("goal") or ""), title=str(data.get("title") or ""),
    )
    return _json_response(result, status=201 if result.get("created") else 200)


async def _snapshot(request):
    from .teams import snapshot

    return _json_response(await asyncio.to_thread(snapshot, request.match_info["team_id"], _owner(request)))


async def _events(request):
    from .teams import timeline

    try:
        after = int(request.query.get("after") or 0)
        limit = int(request.query.get("limit") or 500)
    except ValueError:
        return _error(400, "after/limit must be integers")
    return _json_response(
        await asyncio.to_thread(timeline, request.match_info["team_id"], _owner(request), after, limit)
    )


async def _task(request):
    from .teams import task_detail

    log = request.query.get("log") in ("1", "true")
    return _json_response(await asyncio.to_thread(
        task_detail, request.match_info["team_id"], request.match_info["task_id"], _owner(request), log=log,
    ))


async def _message(request):
    from .teams import post_message

    data = await _body(request)
    return _json_response(await asyncio.to_thread(
        post_message, request.match_info["team_id"], request.match_info["task_id"], str(data.get("body") or ""),
        author_name=str(data.get("author_name") or ""), owner=_owner(request),
    ), status=201)


async def _retry(request):
    from .teams import retry

    data = await _body(request)
    return _json_response(await asyncio.to_thread(
        retry, request.match_info["team_id"], request.match_info["task_id"], owner=_owner(request),
        actor=str(data.get("actor") or ""),
    ))


async def _control(request):
    from .teams import control

    data = await _body(request)
    return _json_response(await asyncio.to_thread(
        control, request.match_info["team_id"], str(data.get("action") or ""), owner=_owner(request),
        actor=str(data.get("actor") or ""),
    ))


def install(app: Any, adapter: Any) -> None:
    """api_server platform handler factory: add the routes, start the bridge (gateway only)."""
    if app is None or adapter is None:
        return
    router = app.router
    base = "/v1/halo-teams"
    router.add_post(base + "/plan", _wrap(adapter, _plan))
    router.add_post(base, _wrap(adapter, _create))
    router.add_get(base + "/{team_id}", _wrap(adapter, _snapshot))
    router.add_get(base + "/{team_id}/events", _wrap(adapter, _events))
    router.add_get(base + "/{team_id}/tasks/{task_id}", _wrap(adapter, _task))
    router.add_post(base + "/{team_id}/tasks/{task_id}/messages", _wrap(adapter, _message))
    router.add_post(base + "/{team_id}/tasks/{task_id}/retry", _wrap(adapter, _retry))
    router.add_post(base + "/{team_id}/control", _wrap(adapter, _control))
    if not _installed["done"]:
        _installed["done"] = True
        from .bridge import start_bridge

        start_bridge()
    logger.info("halowebui-teams: routes installed under %s", base)
