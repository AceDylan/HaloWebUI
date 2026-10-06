"""协作台 (agent teams) — the HaloWebUI side of the Hermes ``halowebui-teams`` plugin.

HaloWebUI owns who may see and drive a team (``agent_team`` rows) and the plan the user
approves; Hermes owns execution (one Kanban board per team, workers, the reclaude bridge) and
the event history. Every Hermes call sends ``X-Halo-Owner`` and Hermes refuses teams recorded
for another owner, so ownership is checked on both sides.

ENABLE_AGENT_TEAMS=false turns the whole feature off (routes answer 404, the UI hides it).

助手库: a plan request carries a shortlist of the user's assistants; the lead records per member
which one it uses, upgrades or would create (``plan.assistant_proposals``) and writes nothing.
Approval (``start_team``, the one way in) carries those decisions out once
(``assistant_library.carry_out``), keeps the result on the plan (``assistants_applied``) before
Hermes is called — a retried start reuses it — and sends each member's assistant to Hermes as a
snapshot (name, version, full system prompt) for its task bodies.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any, Optional

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.models.agent_teams import AgentTeamModel, AgentTeams

log = logging.getLogger(__name__)

ENABLE_AGENT_TEAMS = os.environ.get("ENABLE_AGENT_TEAMS", "true").strip().lower() not in ("0", "false", "no", "off")
PLAN_TIMEOUT_SECONDS = 240
CALL_TIMEOUT_SECONDS = 30
PLANNING_STALE_SECONDS = 600     # a planning row this old lost its background job (restart)
STARTING_STALE_SECONDS = 120     # an approve that never recorded its outcome
GOAL_MAX_CHARS = 8000
FEEDBACK_MAX_CHARS = 2000
_background: set = set()


class TeamsError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class HermesTarget:
    """Where Hermes' api_server is for this user, captured while the request is alive."""

    def __init__(self, api_root: str, headers: dict, owner: str):
        self.api_root = api_root.rstrip("/")
        self.headers = {**headers, "X-Halo-Owner": owner, "Content-Type": "application/json"}

    def url(self, path: str) -> str:
        return f"{self.api_root}/v1/halo-teams{path}"


async def hermes_target(request, user) -> HermesTarget:
    from open_webui.utils.hermes_sessions import HermesSessionsError, _connection, resolve_hermes_model

    try:
        model = await resolve_hermes_model(request, user)
        api_root, headers = _connection(request, user, model)
    except HermesSessionsError as exc:
        raise TeamsError(exc.status_code if exc.status_code != 422 else 403, "你的账号没有可用的 Hermes 连接，不能使用协作台") from exc
    return HermesTarget(api_root, headers, str(user.id))


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
        if body.get("detail"):
            return str(body["detail"])[:500]
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return f"Hermes 返回 {status}"


async def hermes_call(target: HermesTarget, method: str, path: str, *, json_body: Any = None,
                      params: Optional[dict] = None, timeout: int = CALL_TIMEOUT_SECONDS) -> Any:
    """One call to the plugin API; TeamsError with Hermes' own message on any failure."""
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.request(method, target.url(path), headers=target.headers, json=json_body,
                                       params=params, ssl=AIOHTTP_CLIENT_SESSION_SSL) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = await resp.text()
                if resp.status == 404 and isinstance(body, str) and "halo-teams" not in body:
                    raise TeamsError(503, "Hermes 上没有协作台插件（halowebui-teams 未启用）")
                if resp.status >= 400:
                    raise TeamsError(resp.status if resp.status in (400, 404, 409) else 502, _message(body, resp.status))
                return body
    except TeamsError:
        raise
    except asyncio.TimeoutError as exc:
        raise TeamsError(504, f"Hermes 超过 {timeout} 秒没有响应") from exc
    except aiohttp.ClientError as exc:
        raise TeamsError(502, f"连不上 Hermes：{type(exc).__name__}") from exc


FILE_MAX_BYTES = 26 * 1024 * 1024


async def hermes_file(target: HermesTarget, path: str, *, timeout: int = 60) -> tuple[bytes, dict]:
    """A raw (non-JSON) GET from the plugin API: (body, headers). TeamsError on failure."""
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(target.url(path), headers=target.headers, ssl=AIOHTTP_CLIENT_SESSION_SSL) as resp:
                if resp.status >= 400:
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = await resp.text()
                    raise TeamsError(resp.status if resp.status in (400, 404, 409) else 502, _message(body, resp.status))
                if (resp.content_length or 0) > FILE_MAX_BYTES:
                    raise TeamsError(413, "文件太大")
                # The whole body: StreamReader.read(n) returns only what has arrived so far (the first
                # chunk of a picture — a megabyte PNG came through as its first 14 KB, a broken image).
                data = bytearray()
                async for chunk in resp.content.iter_chunked(1 << 16):
                    data.extend(chunk)
                    if len(data) > FILE_MAX_BYTES:
                        raise TeamsError(413, "文件太大")
                return bytes(data), dict(resp.headers)
    except TeamsError:
        raise
    except asyncio.TimeoutError as exc:
        raise TeamsError(504, f"Hermes 超过 {timeout} 秒没有响应") from exc
    except aiohttp.ClientError as exc:
        raise TeamsError(502, f"连不上 Hermes：{type(exc).__name__}") from exc


# --- input files ------------------------------------------------------------------------------

INPUT_FILES_MAX = 20


def input_files(file_ids: Any, user) -> list[dict]:
    """[{name, path}] — the user's uploaded files (ids) as the Hermes host sees them, for a team's
    inputs/ (images too). Files that are not the user's, or not on the shared data volume, are left
    out (the caller says so)."""
    ids = [str(i).strip() for i in (file_ids or []) if str(i or "").strip()][:INPUT_FILES_MAX]
    if not ids:
        return []
    from open_webui.utils.hermes_agent import _attachment_host_paths

    items = [{"id": file_id, "type": "file"} for file_id in dict.fromkeys(ids)]
    return [{"name": name, "path": path} for name, path in _attachment_host_paths({"files": items}, user, images=True)]


def team_inputs(team: AgentTeamModel) -> list[dict]:
    inputs = (team.meta or {}).get("inputs")
    return [i for i in inputs if isinstance(i, dict) and i.get("path")] if isinstance(inputs, list) else []


# --- planning ---------------------------------------------------------------------------------

def _keep(task: "asyncio.Task") -> None:
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _plan_job(team: AgentTeamModel, target: HermesTarget, feedback: str, previous: Optional[dict],
                    access: Optional["AssistantAccess"] = None) -> None:
    try:
        request_body = {
            "goal": team.goal, "team_id": team.id, "feedback": feedback, "previous": previous,
            "lead_model": (team.meta or {}).get("lead_model") or "",
            "project": (team.meta or {}).get("project") or "",
            "inputs": [i["name"] for i in team_inputs(team)],
        }
        library = await plan_library(team, access) if access is not None else None
        if library is not None:
            request_body["library"] = library
        body = await hermes_call(target, "POST", "/plan", json_body=request_body, timeout=PLAN_TIMEOUT_SECONDS)
        ok = isinstance(body, dict) and body.get("ok") and isinstance(body.get("plan"), dict)
        if ok:
            plan = body["plan"]
            updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_ready",
                                        plan=plan, error=None, title=(plan.get("title") or team.title)[:60])
            if updated is not None and (team.meta or {}).get("auto_start") and auto_startable(plan):
                try:  # 「计划好直接开始」: no approval step
                    updated = await start_team(updated, target, access)
                except TeamsError as exc:
                    log.info("teams: auto-start of %s did not go through (%s)", team.id, exc.detail)
                    updated = AgentTeams.get(team.id, team.user_id) or updated
        else:
            error = (body or {}).get("error") if isinstance(body, dict) else None
            updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                        error=str(error or "负责人没有给出可用的计划")[:1000])
    except TeamsError as exc:
        updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                    error=exc.detail)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("agent team planning failed")
        updated = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                    error=f"规划出错：{type(exc).__name__}")
    if updated is not None and team_origin(updated):
        await _tell_origin(updated, target)


async def _tell_origin(team: AgentTeamModel, target: HermesTarget) -> None:
    """A team started from a chat outside HaloWebUI (Telegram): Hermes sends the plan (or why
    there is none) back there, with buttons to approve or cancel. Best effort."""
    try:
        await hermes_call(target, "POST", "/notify", json_body={"event": team.status, "team": public_team(team),
                                                              "origin": team_origin(team)},
                          timeout=CALL_TIMEOUT_SECONDS)
    except TeamsError as exc:
        log.info("teams: could not hand the plan of %s to Hermes for its chat (%s)", team.id, exc.detail)


def auto_startable(plan: dict) -> bool:
    """A plan starts without approval only when every member has a runner that can take it now
    (otherwise the user should see why first)."""
    members = [m for m in plan.get("members") or [] if isinstance(m, dict)]
    return bool(members) and all(m.get("runner") for m in members)


IMAGE_TEMPLATE_LIMIT = 40


def image_templates(user_id: str, limit: int = IMAGE_TEMPLATE_LIMIT) -> list[dict]:
    """The user's own image templates (HaloWebUI 生图模板: name, tags, canvas, prompt) for a team's
    image members — the styles the user already uses in the image studio and in chats."""
    try:
        from open_webui.models.image_studio import ImageStudioItems

        items = ImageStudioItems.get_items_by_user_id(user_id, kind="template", limit=200)
    except Exception:  # noqa: BLE001 — a team starts without them rather than not at all
        log.warning("teams: could not read the image templates of %s", user_id, exc_info=True)
        return []
    out = []
    for item in items:
        data = item.data if isinstance(item.data, dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        prompt = str(config.get("prompt") or "").strip()
        name = str(data.get("name") or "").strip()
        if not prompt or not name:
            continue
        out.append({"id": str(item.id)[:80], "name": name[:60],
                    "tags": [str(t)[:20] for t in (data.get("tags") or []) if t][:4],
                    "aspect": str(config.get("aspectRatio") or "")[:10], "size": str(config.get("size") or "")[:20],
                    "prompt": prompt[:6000]})
        if len(out) >= limit:
            break
    return out


CONCLUSION_TEMPLATE_ID = "halo_hand_v1_auto_style"
CONCLUSION_TEMPLATE_NAME = "手绘万能图"


def conclusion_template(templates: list[dict]) -> Optional[dict]:
    """The template a finished team's result is drawn in on its own (「为结果配图」 right after the
    lead writes it): the user's 「手绘万能图 · 自动选画风与画幅」 (by id, else by name); None →
    Hermes' own hand-drawn infographic."""
    return (next((t for t in templates if t.get("id") == CONCLUSION_TEMPLATE_ID), None)
            or next((t for t in templates if CONCLUSION_TEMPLATE_NAME in str(t.get("name") or "")), None))


def plan_draws(plan: Optional[dict]) -> bool:
    """The plan has a member that generates images (kind ``image``)."""
    return any(isinstance(m, dict) and m.get("kind") == "image" for m in (plan or {}).get("members") or [])


async def start_team(team: AgentTeamModel, target: HermesTarget,
                     access: Optional["AssistantAccess"] = None) -> AgentTeamModel:
    """Hand the plan to Hermes: the board and its tasks are created and the members start.
    The approve button, Telegram's 批准 and 「计划好直接开始」 all go through here, and so does
    the only write to the assistant library a team makes (``access``: the user's library; None =
    the plan's assistants are not looked at — Hermes uses its template catalog as before)."""
    if not team.plan:
        raise TeamsError(409, "还没有可批准的计划")
    starting = AgentTeams.update(team.id, team.user_id, expect_status=("plan_ready", "start_failed"),
                                 status="starting", error=None)
    if starting is None:
        raise TeamsError(409, "这个计划已经批准过或状态已变化")
    team = starting
    try:
        plan = dict(team.plan or {})
        snapshots = None
        if access is not None and plan_has_assistants(plan):
            applied = plan.get("assistants_applied") if isinstance(plan.get("assistants_applied"), dict) else None
            if applied is None:  # the first start: carry the decisions out, once
                applied = await apply_assistants(team, plan, access)
                plan["assistants_applied"] = applied
                stored = AgentTeams.update(team.id, team.user_id, expect_status=("starting",), plan=plan)
                if stored is None:
                    log.warning("teams: the assistants applied for %s could not be recorded", team.id)
            snapshots = member_snapshots(applied)
        sent = {k: v for k, v in plan.items() if k != "assistants_applied"}
        body = {"team_id": team.id, "plan": sent, "goal": team.goal, "title": team.title,
                "chat_id": team.chat_id or "", "origin": team_origin(team)}
        if snapshots:
            body["member_assistants"] = snapshots
        templates = image_templates(team.user_id, limit=200)
        if plan_draws(team.plan):
            body["image_templates"] = templates[:IMAGE_TEMPLATE_LIMIT]
        picture = conclusion_template(templates)
        if picture:
            body["conclusion_template"] = picture
        if team_inputs(team):
            body["inputs"] = team_inputs(team)
        result = await hermes_call(target, "POST", "", json_body=body, timeout=60)
    except TeamsError as exc:
        AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="start_failed",
                          error=f"启动失败：{exc.detail}")
        raise TeamsError(exc.status_code if exc.status_code < 500 else 502, f"启动失败：{exc.detail}")
    updated = AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="running", phase="running",
                                board=(result or {}).get("board"), approved_at=int(time.time()), error=None)
    return updated or team


def start_planning(team: AgentTeamModel, target: HermesTarget, feedback: str = "", previous: Optional[dict] = None,
                   access: Optional["AssistantAccess"] = None) -> None:
    _keep(asyncio.create_task(_plan_job(team, target, feedback, previous, access)))


def default_title(goal: str) -> str:
    first = " ".join(goal.split())
    return (first[:28] + "…") if len(first) > 28 else first or "协作任务"


# --- 助手库 (the user's assistants) -------------------------------------------------------------

PREFERRED_MAX = 3


class AssistantAccess:
    """The user's assistant library, read through the request that started the step (planning
    and auto-start run after the response, as 精答 does with its run)."""

    def __init__(self, request, user):
        self.request = request
        self.user = user

    def may_write(self) -> bool:
        """Whether the user may save assistants (same rule as 精答: admin or workspace.models)."""
        from open_webui.utils.access_control import has_permission

        if getattr(self.user, "role", None) == "admin":
            return True
        return has_permission(self.user.id, "workspace.models", self.request.app.state.config.USER_PERMISSIONS)

    async def library(self) -> dict:
        """{assistants, bases, default_base, may_write} — fresh from the model list."""
        from open_webui.utils import assistant_library as lib
        from open_webui.utils.models import get_all_models

        await get_all_models(self.request, user=self.user)
        models_map = getattr(self.request.state, "MODELS", None) or {}
        assistants, bases = lib.library(models_map, self.user)
        strong = next((b for b in bases if re.search(r"claude|gpt", b["name"], re.I)), bases[0] if bases else None)
        return {"assistants": assistants, "bases": bases, "default_base": strong["id"] if strong else "",
                "may_write": self.may_write()}


def preferred_refs(value: Any) -> list[str]:
    """「用于协作」: assistant refs the user asked a team to use (model:<id> / builtin:<id>)."""
    out = []
    for ref in value if isinstance(value, list) else []:
        ref = str(ref or "").strip()[:220]
        if ref.startswith(("model:", "builtin:")) and len(ref) > len("model:") and ref not in out:
            out.append(ref)
    return out[:PREFERRED_MAX]


def _compact(entry: dict) -> dict:
    from open_webui.utils import assistant_library as lib

    prompt = str(entry.get("prompt") or "")
    excerpt = prompt[: lib.PROMPT_EXCERPT_CHARS] + ("…" if len(prompt) > lib.PROMPT_EXCERPT_CHARS else "")
    out = {"ref": entry["ref"], "name": entry.get("name") or "", "emoji": entry.get("emoji") or "",
           "description": entry.get("description") or "", "prompt": excerpt}
    if entry["ref"].startswith("model:"):
        out.update(domain=entry.get("domain") or "", editable=bool(entry.get("editable")), version=entry.get("version"))
    return out


async def plan_library(team: AgentTeamModel, access: "AssistantAccess") -> Optional[dict]:
    """The shortlist of the user's library sent with a plan request; None when it cannot be read
    (the lead then plans with the template catalog only)."""
    from open_webui.utils import assistant_library as lib

    try:
        ctx = await access.library()
    except Exception:  # noqa: BLE001 — a plan without the library beats no plan
        log.warning("teams: could not read the assistant library for %s", team.id, exc_info=True)
        return None
    wanted = preferred_refs((team.meta or {}).get("assistants"))
    refs = {a["ref"] for a in ctx["assistants"]}
    preferred = [r for r in wanted if r in refs or (r.startswith("builtin:") and lib.builtin_by_ref(r))]
    assistants, templates = lib.shortlist(team.goal, ctx["assistants"], favorites=lib.favorites_of(access.user),
                                          must=preferred)
    return {
        "may_write": ctx["may_write"],
        "assistants": [_compact(a) for a in assistants],
        "templates": [_compact(t) for t in templates],
        "preferred": preferred,
        "max_create": lib.MAX_CREATE_PER_RUN,
        "max_update": lib.MAX_UPDATE_PER_RUN,
    }


def _member_assistant(member: dict) -> Optional[dict]:
    assistant = member.get("assistant")
    if not isinstance(assistant, dict):
        return None
    out = dict(assistant)
    # a plan from before the library: {id, name, ...} of a 「协作」 template
    out.setdefault("action", "template")
    if not out.get("ref") and out.get("id") and out["action"] == "template":
        out["ref"] = f"builtin:{out['id']}"
    return out


def plan_has_assistants(plan: Optional[dict]) -> bool:
    return any(isinstance(m, dict) and _member_assistant(m) for m in (plan or {}).get("members") or [])


def _gone(member: dict, assistant: dict) -> dict:
    name = assistant.get("name") or assistant.get("ref") or "这个助手"
    return {"action": "generic", "saved": False, "reason": "", "change": "", "name": assistant.get("name") or "",
            "ref": assistant.get("ref") or "", "emoji": assistant.get("emoji") or "",
            "note": f"「{name}」已不在助手库（删除或归档），按角色「{member.get('role') or member.get('name')}」执行"}


async def apply_assistants(team: AgentTeamModel, plan: dict, access: "AssistantAccess") -> dict:
    """Carry out the plan's assistant decisions for the user (the only writes a team makes to the
    library): {run_ref, at, members: {member name: choice}} — a choice as
    ``assistant_library.carry_out`` returns it, or ``generic`` with a note when the assistant is
    gone. Members whose template HaloWebUI does not have are left to Hermes' own catalog."""
    from open_webui.utils import assistant_library as lib

    try:
        ctx = await access.library()
    except Exception as exc:  # noqa: BLE001
        log.warning("teams: could not read the assistant library to start %s", team.id, exc_info=True)
        raise TeamsError(502, f"读取助手库失败：{type(exc).__name__}") from exc
    assistants, bases, default_base = ctx["assistants"], ctx["bases"], ctx["default_base"]
    may_write = ctx["may_write"]
    proposals = {p.get("key"): p for p in plan.get("assistant_proposals") or [] if isinstance(p, dict)}
    by_ref = {a["ref"]: a for a in assistants}
    units, raw, templates = [], [], []
    temporary: dict[str, dict] = {}
    fallback: dict[str, dict] = {}
    pending: dict[str, dict] = {}  # member → its proposal (a create the dispatcher rules dropped)

    for member in plan.get("members") or []:
        if not isinstance(member, dict) or not member.get("name"):
            continue
        assistant = _member_assistant(member)
        if assistant is None:
            continue
        name, action, ref = member["name"], assistant["action"], str(assistant.get("ref") or "")
        reason = str(assistant.get("reason") or "")
        if action == "template":
            template = lib.builtin_by_ref(ref)
            if template is None:
                continue  # not in HaloWebUI's copy: Hermes looks it up itself
            templates.append(template)
            units.append({"key": name})
            raw.append({"key": name, "action": "use", "ref": ref, "reason": reason})
            continue
        target = by_ref.get(ref) if ref.startswith("model:") else None
        if ref.startswith("model:") and target is None:
            fallback[name] = _gone(member, assistant)  # deleted, archived or no longer shared
            continue
        if action == "use":
            units.append({"key": name})
            raw.append({"key": name, "action": "use", "ref": ref, "reason": reason})
            continue
        proposal = proposals.get(assistant.get("proposal"))
        if proposal is None:
            if target is not None:
                units.append({"key": name})
                raw.append({"key": name, "action": "use", "ref": ref, "reason": reason})
            continue
        spec_raw = {k: proposal.get(k) for k in ("name", "emoji", "domain", "description", "system_prompt", "from")}
        if action == "temporary":
            spec = lib.spec_of(spec_raw, bases, default_base)
            if target is not None:
                spec.update(name=target["name"], emoji=target.get("emoji") or spec["emoji"], base=target.get("base") or spec["base"])
            temporary[name] = {"action": "temporary", "target": target, "template": None, "spec": spec, "reason": reason,
                               "change": str(proposal.get("change") or ""), "note": str(assistant.get("note") or "")}
            continue
        units.append({"key": name})
        raw.append({"key": name, "action": action, "ref": ref if action == "update" else "", "reason": reason,
                    "change": str(proposal.get("change") or ""), "assistant": spec_raw})
        pending[name] = proposal

    decisions = lib.normalize_decisions({"units": raw}, units, assistants, templates, bases, default_base=default_base,
                                        may_write=may_write)
    for name, decision in decisions.items():
        proposal = pending.get(name)
        # an upgrade is written over the version the lead read, not over a later edit (CAS → this run only)
        if decision["action"] == "update" and proposal and isinstance(proposal.get("version"), int) and decision["target"]:
            decision["target"] = {**decision["target"], "version": proposal["version"]}
    for unit in units:
        name = unit["key"]
        if name in decisions:
            continue
        member = next(m for m in plan["members"] if isinstance(m, dict) and m.get("name") == name)
        proposal = pending.get(name)
        if proposal is not None:  # e.g. no base model to save it on: still this run's role
            spec = lib.spec_of({k: proposal.get(k) for k in ("name", "emoji", "domain", "description", "system_prompt")},
                               bases, default_base)
            temporary[name] = {"action": "temporary", "target": None, "template": None, "spec": spec, "reason": "",
                               "change": str(proposal.get("change") or ""), "note": "没能保存这个助手，本次临时使用"}
        else:
            fallback[name] = _gone(member, _member_assistant(member) or {})
    try:
        choices = lib.carry_out(access.user, {**decisions, **temporary}, source="team", run_ref=f"team:{team.id}",
                                question=team.goal, may_write=may_write)
    except Exception as exc:  # noqa: BLE001 — carry_out answers its own refusals; this is the database
        log.exception("teams: writing the assistants of %s failed", team.id)
        raise TeamsError(500, f"写入助手库失败：{type(exc).__name__}") from exc
    return {"run_ref": f"team:{team.id}", "at": int(time.time()), "members": {**fallback, **choices}}


SNAPSHOT_KEYS = ("action", "ref", "id", "name", "emoji", "version", "system", "description")


def member_snapshots(applied: Optional[dict]) -> dict:
    """What Hermes gets per member at start: the assistant as applied (full system prompt), or
    ``generic`` (the plain role) with why."""
    out = {}
    for name, choice in ((applied or {}).get("members") or {}).items():
        if not isinstance(choice, dict):
            continue
        if choice.get("action") == "generic":
            out[name] = {"action": "generic", "note": choice.get("note") or ""}
        else:
            out[name] = {k: choice.get(k) for k in SNAPSHOT_KEYS}
    return out


def public_assistants_applied(applied: Any) -> Optional[dict]:
    """The applied choices as the page sees them: the system prompt only of an upgrade (to view
    it and undo it), never the version before."""
    if not isinstance(applied, dict):
        return None
    members = {}
    for name, choice in (applied.get("members") or {}).items():
        if not isinstance(choice, dict):
            continue
        shown = {k: v for k, v in choice.items() if k not in ("system", "before")}
        shown["hasSystem"] = bool(choice.get("system"))
        if choice.get("action") == "update":
            shown["system"] = choice.get("system") or ""
        members[name] = shown
    return {"run_ref": applied.get("run_ref"), "at": applied.get("at"), "members": members}


def mark_reverted(team: AgentTeamModel, assistant_id: str) -> Optional[AgentTeamModel]:
    """Record on the team that its upgrade of ``assistant_id`` was undone (every member that used it)."""
    plan = dict(team.plan or {})
    applied = plan.get("assistants_applied") if isinstance(plan.get("assistants_applied"), dict) else None
    if not applied:
        return None
    members = {}
    hit = False
    for name, choice in (applied.get("members") or {}).items():
        if isinstance(choice, dict) and choice.get("action") == "update" and choice.get("id") == assistant_id:
            choice = {**choice, "reverted": True}
            hit = True
        members[name] = choice
    if not hit:
        return None
    plan["assistants_applied"] = {**applied, "members": members}
    return AgentTeams.update(team.id, team.user_id, plan=plan)


# --- reconciliation ---------------------------------------------------------------------------

async def reconcile(team: AgentTeamModel, target: Optional[HermesTarget]) -> tuple[AgentTeamModel, Optional[dict], Optional[str]]:
    """Fix rows whose background step died with the process, and read the live snapshot.

    Returns (team, snapshot or None, live error or None)."""
    now = int(time.time())
    if team.status == "planning" and now - team.updated_at > PLANNING_STALE_SECONDS:
        team = AgentTeams.update(team.id, team.user_id, expect_status=("planning",), status="plan_failed",
                                 error="规划被中断（服务重启或超时），请重新生成计划") or team
    if team.status not in ("running", "starting") or target is None:
        return team, None, None
    try:
        snap = await hermes_call(target, "GET", f"/{team.id}")
    except TeamsError as exc:
        if team.status == "starting" and exc.status_code == 404 and now - team.updated_at > STARTING_STALE_SECONDS:
            team = AgentTeams.update(team.id, team.user_id, expect_status=("starting",), status="start_failed",
                                     error="启动没有完成（Hermes 上找不到这个团队），请重新批准") or team
        return team, None, exc.detail
    live = snap.get("team") if isinstance(snap, dict) else None
    phase = (live or {}).get("phase")
    fields: dict = {}
    if team.status == "starting":
        fields.update(status="running", board=(live or {}).get("board"), approved_at=team.approved_at or now, error=None)
    if phase and phase != team.phase:
        fields["phase"] = phase
        if phase in ("completed", "stopped") and not team.finished_at:
            fields["finished_at"] = now
        elif phase not in ("completed", "stopped") and team.finished_at:
            fields["finished_at"] = None  # a finished team that got new work runs again
    progress = snapshot_progress(snap)
    meta = dict(team.meta or {})
    if progress is not None and progress != meta.get("progress"):
        meta["progress"] = progress
    # A finished team is "settled" once its result is written and checked: nothing more happens
    # on its own, so the list stops asking Hermes about it.
    settled = phase in ("completed", "stopped") and result_settled(live)
    if settled != bool(meta.get("settled")):
        meta["settled"] = settled
    if meta != (team.meta or {}):
        fields["meta"] = meta
    if fields:
        team = AgentTeams.update(team.id, team.user_id, **fields) or team
    return team, snap, None


def result_settled(live: Optional[dict]) -> bool:
    """The lead is done with a finished team: the result is written (or failed) and not being checked."""
    conclusion = (live or {}).get("conclusion") if isinstance(live, dict) else None
    if not isinstance(conclusion, dict):
        return False
    acceptance = conclusion.get("acceptance") if isinstance(conclusion.get("acceptance"), dict) else {}
    illustration = conclusion.get("illustration") if isinstance(conclusion.get("illustration"), dict) else {}
    return (conclusion.get("status") in ("ready", "failed") and acceptance.get("status") != "checking"
            and illustration.get("status") != "generating")


def snapshot_progress(snap: Any) -> Optional[dict]:
    """How far a running team is, for the list: tasks done / running / needing you / total."""
    tasks = snap.get("tasks") if isinstance(snap, dict) else None
    if not isinstance(tasks, list):
        return None
    out = {"done": 0, "running": 0, "attention": 0, "total": len(tasks)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        sub = task.get("sub_status") or task.get("status")
        if task.get("status") in ("done", "archived"):
            out["done"] += 1
        elif sub in ("running", "review"):
            out["running"] += 1
        elif sub in ("failed", "blocked", "waiting_user", "stopped", "triage") or task.get("status") == "triage":
            out["attention"] += 1
    return out


# --- stage (阶段 + 现在在做什么 + 预计时间) ----------------------------------------------------------

PLAN_TYPICAL_DEFAULT = {"median": 45, "p75": 80, "basis": "经验值"}
STAGE_LABELS = {"planning": "负责人制定计划", "approval": "等你批准", "starting": "启动成员",
                "plan_failed": "计划没做成", "start_failed": "启动失败", "cancelled": "已取消"}


async def planning_progress(team: AgentTeamModel, target: Optional[HermesTarget]) -> Optional[dict]:
    """The lead's current planning step on Hermes, and how long plans take there. Best effort."""
    if target is None:
        return None
    try:
        body = await hermes_call(target, "GET", "/plan/progress", params={"team_id": team.id}, timeout=4)
    except TeamsError:
        return None
    return body if isinstance(body, dict) else None


def stage_of(team: AgentTeamModel, snap: Any = None, planning: Optional[dict] = None) -> Optional[dict]:
    """Where the team stands, the same shape for every status: {key, label, now, started_at, at,
    eta?: {seconds, high, overtime, basis} counted from ``at``, steps?}. Running teams take Hermes'
    own (the snapshot's ``team.stage``); before that HaloWebUI knows the stage itself."""
    now = int(time.time())
    if team.status in ("running", "starting") and isinstance(snap, dict):
        live = (snap.get("team") or {}).get("stage")
        if isinstance(live, dict) and live.get("key"):
            return {**live, "at": int(snap.get("generated_at") or now)}
    if team.status == "planning":
        typical = {**PLAN_TYPICAL_DEFAULT, **((planning or {}).get("typical") or {})}
        step = (planning or {}).get("progress") or {}
        started = int(team.updated_at or team.created_at or now)
        spent = max(0, now - started)
        left = int(typical["median"]) - spent
        return {"key": "planning", "label": STAGE_LABELS["planning"], "started_at": started, "at": now,
                "now": step.get("text") or "负责人在理解目标、挑选成员、拆分带依赖的任务",
                "model": step.get("model") or None, "attempt": step.get("attempt") or None,
                "eta": {"seconds": max(5, left), "high": max(5, int(typical["p75"]) - spent, left),
                        "overtime": left <= 0, "basis": f"按{typical.get('basis') or '经验值'}做计划的用时估算"},
                "steps": _steps(0)}
    if team.status == "plan_ready":
        estimate = (team.plan or {}).get("estimate") if isinstance(team.plan, dict) else None
        return {"key": "approval", "label": STAGE_LABELS["approval"], "at": now, "started_at": team.updated_at,
                "now": "计划好了：看一下成员和任务，批准后才开始执行", "after_approval": estimate or None,
                "steps": _steps(1)}
    if team.status == "starting":
        return {"key": "starting", "label": STAGE_LABELS["starting"], "at": now, "started_at": team.updated_at,
                "now": "正在把计划交给 Hermes：建任务板、启动第一批成员", "steps": _steps(2)}
    if team.status in ("plan_failed", "start_failed", "cancelled"):
        return {"key": team.status, "label": STAGE_LABELS[team.status], "at": now,
                "now": (team.error or "")[:200] or STAGE_LABELS[team.status]}
    return None


def _steps(position: int) -> list[dict]:
    order = ["plan", "approve", "run", "conclude", "check"]
    return [{"key": k, "state": "done" if i < position else ("active" if i == position else "pending")}
            for i, k in enumerate(order)]


def stage_brief(stage: Optional[dict]) -> Optional[dict]:
    """What the team list shows of a stage."""
    if not isinstance(stage, dict) or not stage.get("key"):
        return None
    eta = stage.get("eta") if isinstance(stage.get("eta"), dict) else {}
    after = stage.get("after_approval") if isinstance(stage.get("after_approval"), dict) else {}
    out = {"key": stage["key"], "label": stage.get("label"), "now": str(stage.get("now") or "")[:160],
           "at": stage.get("at"), "started_at": stage.get("started_at"),
           "eta": eta.get("seconds"), "eta_high": eta.get("high"), "overtime": bool(eta.get("overtime")),
           "after_approval": after.get("seconds"), "after_approval_high": after.get("high")}
    return {k: v for k, v in out.items() if v not in (None, "", False)}


def team_origin(team: AgentTeamModel) -> Optional[dict]:
    """Where the team was started from when that was not the browser (Telegram via Hermes)."""
    origin = (team.meta or {}).get("origin")
    return origin if isinstance(origin, dict) and origin.get("platform") else None


def deletable(team: AgentTeamModel) -> bool:
    """Only a team nothing is happening in can go: never planned, cancelled, failed, or finished."""
    if team.status in ("plan_ready", "plan_failed", "start_failed", "cancelled"):
        return True
    return team.status == "running" and team.phase in ("completed", "stopped")


def public_team(team: AgentTeamModel, *, with_plan: bool = True) -> dict:
    data = team.model_dump()
    data.pop("user_id", None)
    meta = data.pop("meta", None) or {}
    if isinstance(data.get("plan"), dict) and "assistants_applied" in data["plan"]:
        data["plan"] = {**data["plan"], "assistants_applied": public_assistants_applied(data["plan"]["assistants_applied"])}
    data["preferred_assistants"] = preferred_refs(meta.get("assistants"))
    data["lead_model"] = meta.get("lead_model")
    data["auto_start"] = bool(meta.get("auto_start"))
    plan = data.get("plan") or {}
    data["member_count"] = len(plan.get("members") or [])
    data["task_count"] = len(plan.get("tasks") or [])
    data["executors"] = plan.get("executors") or []
    data["progress"] = meta.get("progress")
    data["origin"] = (meta.get("origin") or {}).get("platform") if isinstance(meta.get("origin"), dict) else None
    project = plan.get("project") if isinstance(plan.get("project"), dict) else None
    data["project"] = {"name": project.get("name"), "path": project.get("path")} if project else None
    data["deletable"] = deletable(team)
    data["inputs"] = [str(i.get("name") or "")[:120] for i in team_inputs(team)]
    # Where the conclusion went (the chat it was posted to, the knowledge base it was saved in).
    knowledge = meta.get("knowledge") if isinstance(meta.get("knowledge"), dict) else None
    posted = meta.get("chat_posted") if isinstance(meta.get("chat_posted"), dict) else None
    data["outputs"] = {
        "knowledge": {"id": knowledge.get("id"), "generated_at": knowledge.get("generated_at")} if knowledge else None,
        "chat_posted": {"generated_at": posted.get("generated_at")} if posted else None,
    }
    # Who is on the team, for the list's avatar stack (names and roles only).
    data["roster"] = [
        {"name": str(m.get("name") or "")[:40], "role": str(m.get("role") or "")[:40]}
        for m in (plan.get("members") or [])[:8]
        if isinstance(m, dict)
    ]
    if not with_plan:
        data.pop("plan", None)
    return data
