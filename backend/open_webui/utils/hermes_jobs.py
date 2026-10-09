"""Hermes 定时任务 (cron jobs) for the 定时任务 page: a thin pass-through to hermes /api/jobs.

The jobs run on the hermes host with its tools (a job is an agent turn or a script), so only an
admin reaches these. A job is trimmed to what the page shows: hermes keeps scheduler bookkeeping
(fire claims, snapshots, origin) the page has no use for.
"""

import logging
import re
from typing import Any, Optional

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, SRC_LOG_LEVELS
from open_webui.utils.hermes_sessions import (
    HermesSessionsError,
    _connection,
    _hermes_error_message,
    resolve_hermes_model,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")
JOB_ACTIONS = ("pause", "resume", "run")
JOBS_TIMEOUT_SECONDS = 30
OUTPUTS_LIMIT_MAX = 10

_JOB_FIELDS = (
    "id",
    "name",
    "prompt",
    "script",
    "no_agent",
    "skills",
    "model",
    "provider",
    "schedule",
    "schedule_display",
    "repeat",
    "enabled",
    "state",
    "paused_at",
    "paused_reason",
    "created_at",
    "next_run_at",
    "last_run_at",
    "last_status",
    "last_error",
    "last_delivery_error",
    "deliver",
    "failure_streak",
)
_EXECUTION_FIELDS = ("status", "started_at", "finished_at", "error", "delivery_outcome")


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.match(job_id or ""):
        raise HermesSessionsError(400, "invalid job id")
    return job_id


def trim_job(job: Any) -> dict:
    if not isinstance(job, dict):
        return {}
    out = {key: job.get(key) for key in _JOB_FIELDS}
    execution = job.get("latest_execution")
    out["latest_execution"] = (
        {key: execution.get(key) for key in _EXECUTION_FIELDS}
        if isinstance(execution, dict)
        else None
    )
    return out


async def _jobs_call(
    request,
    user,
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    model = await resolve_hermes_model(request, user, None)
    root, headers = _connection(request, user, model)
    timeout = aiohttp.ClientTimeout(total=JOBS_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
            async with session.request(
                method,
                f"{root}/api/jobs{path}",
                json=json,
                params=params,
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {}
                if resp.status < 400:
                    return body if isinstance(body, dict) else {}
                message = _hermes_error_message(body)
                if resp.status == 404 and not message:
                    # an older hermes without this route
                    raise HermesSessionsError(501, "这个 Hermes 还不支持这项操作，更新 Hermes 并重启网关后再试")
                if resp.status in (400, 404, 424):
                    raise HermesSessionsError(resp.status, message or f"HTTP {resp.status}")
                if resp.status == 501:
                    raise HermesSessionsError(501, "Hermes 没有启用定时任务模块")
                raise HermesSessionsError(502, f"Hermes 返回 {resp.status}：{message or '未知错误'}")
    except (aiohttp.ClientError, TimeoutError) as e:
        raise HermesSessionsError(502, f"连不上 Hermes：{e}")


async def list_jobs(request, user) -> list[dict]:
    body = await _jobs_call(request, user, "GET", "", params={"include_disabled": "true"})
    return [trim_job(job) for job in body.get("jobs") or []]


async def create_job(request, user, fields: dict) -> dict:
    body = await _jobs_call(request, user, "POST", "", json=fields)
    return trim_job(body.get("job"))


async def update_job(request, user, job_id: str, fields: dict) -> dict:
    body = await _jobs_call(request, user, "PATCH", f"/{validate_job_id(job_id)}", json=fields)
    return trim_job(body.get("job"))


async def delete_job(request, user, job_id: str) -> None:
    await _jobs_call(request, user, "DELETE", f"/{validate_job_id(job_id)}")


async def job_action(request, user, job_id: str, action: str) -> dict:
    if action not in JOB_ACTIONS:
        raise HermesSessionsError(400, f"unknown action: {action}")
    body = await _jobs_call(request, user, "POST", f"/{validate_job_id(job_id)}/{action}")
    return trim_job(body.get("job"))


async def job_outputs(request, user, job_id: str, limit: int = 3) -> list[dict]:
    limit = max(1, min(int(limit), OUTPUTS_LIMIT_MAX))
    body = await _jobs_call(
        request, user, "GET", f"/{validate_job_id(job_id)}/outputs", params={"limit": str(limit)}
    )
    return [item for item in body.get("outputs") or [] if isinstance(item, dict)]


RUNNER_STATS_MAX_DAYS = 90


async def runner_stats(request, user, days: int = 30) -> dict:
    """Every background runner run of the last ``days`` days with its reported cost, duration,
    turns and project (hermes GET /v1/runners/stats), for the 后台任务 tab of the usage page."""
    days = max(1, min(int(days), RUNNER_STATS_MAX_DAYS))
    model = await resolve_hermes_model(request, user, None)
    root, headers = _connection(request, user, model)
    timeout = aiohttp.ClientTimeout(total=JOBS_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
            async with session.get(
                f"{root}/v1/runners/stats",
                params={"days": str(days)},
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {}
                if resp.status == 404:
                    raise HermesSessionsError(501, "这个 Hermes 还不支持后台任务统计，更新 Hermes 并重启网关后再试")
                if resp.status >= 400:
                    message = _hermes_error_message(body) or f"HTTP {resp.status}"
                    raise HermesSessionsError(502, f"Hermes 返回 {resp.status}：{message}")
    except (aiohttp.ClientError, TimeoutError) as e:
        raise HermesSessionsError(502, f"连不上 Hermes：{e}")
    if not isinstance(body, dict) or not isinstance(body.get("runs"), list):
        raise HermesSessionsError(502, "Hermes 后台任务统计返回格式异常")
    runs = [row for row in body["runs"] if isinstance(row, dict)]
    out = {"days": body.get("days") or days, "runs": runs}
    if isinstance(body.get("quota"), dict):
        out["quota"] = body["quota"]
    return out
