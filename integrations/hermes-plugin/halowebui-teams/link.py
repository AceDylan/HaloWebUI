"""The 协作台 outside HaloWebUI: settings and the calls back into HaloWebUI.

A team started from Telegram is still a HaloWebUI team (its owner, plan and approval live in
HaloWebUI's ``agent_team`` table), so Hermes asks HaloWebUI to create, approve, cancel or re-plan
it — ``/api/v1/teams/hermes/*``, authenticated with this gateway's own API key (the key
HaloWebUI uses to call it) and the HaloWebUI user named in ``X-Halo-Owner``. Once a team runs,
everything happens on its board here and needs no call back.

Settings: ``~/.hermes/halo-teams.json`` (``HALO_TEAMS_LINK_FILE`` overrides), read again when it
changes::

    {
      "halowebui": {"url": "http://127.0.0.1:3000", "public_url": "https://host.acedylan.us:3001"},
      "telegram": {"owners": {"<telegram user id>": "<HaloWebUI user id>"},
                   "notify_web_teams": true}
    }

``owners`` is who may drive teams from Telegram (and whose teams notify which chat: a private
chat's id is the user's id). ``notify_web_teams`` (default true): teams started in the browser
also tell the owner's Telegram when a member asks something, a task fails, or the team finishes —
unless the team's page is open in front of them.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .common import logger

_cache: dict = {"mtime": None, "data": {}}
_lock = threading.Lock()


def config_path() -> Path:
    override = os.environ.get("HALO_TEAMS_LINK_FILE")
    if override:
        return Path(override)
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "halo-teams.json"


def config() -> dict:
    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("halowebui-teams: %s is not valid JSON; Telegram link off", path)
                data = {}
            _cache.update(mtime=mtime, data=data if isinstance(data, dict) else {})
        return _cache["data"]


def _section(name: str) -> dict:
    value = config().get(name)
    return value if isinstance(value, dict) else {}


def owners() -> dict[str, str]:
    raw = _section("telegram").get("owners")
    return {str(k): str(v) for k, v in raw.items() if k and v} if isinstance(raw, dict) else {}


def owner_for_telegram(user_id: Any) -> Optional[str]:
    """The HaloWebUI user a Telegram user drives teams as (None: not linked)."""
    return owners().get(str(user_id or "")) if user_id not in (None, "") else None


def telegram_chat_for(owner: Any) -> Optional[str]:
    """The private chat of the Telegram user linked to a HaloWebUI user."""
    for tg_user, halo_user in owners().items():
        if halo_user == str(owner or ""):
            return tg_user
    return None


def notify_web_teams() -> bool:
    return _section("telegram").get("notify_web_teams", True) is not False


def public_url(path: str = "") -> str:
    base = str(_section("halowebui").get("public_url") or "").rstrip("/")
    return base + path if base else ""


def team_url(team_id: str, suffix: str = "") -> str:
    return public_url(f"/teams/{team_id}{suffix}")


class HaloError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _api_key() -> str:
    return os.environ.get("API_SERVER_KEY", "").strip()


def call(method: str, path: str, owner: str, body: Any = None, *, timeout: float = 30) -> Any:
    """One call to HaloWebUI's ``/api/v1/teams/hermes`` routes as *owner*."""
    base = str(_section("halowebui").get("url") or "").rstrip("/")
    key = _api_key()
    if not base or not key:
        raise HaloError(503, "协作台和 Telegram 还没有接通（halo-teams.json 缺 halowebui.url 或网关没有 API_SERVER_KEY）")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base}/api/v1/teams/hermes{path}", data=data, method=method,
        headers={"X-Hermes-Key": key, "X-Halo-Owner": str(owner), "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    # HaloWebUI is local: never through a proxy from the environment.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read() or b"{}")
            detail = payload.get("detail") if isinstance(payload, dict) else ""
        except (ValueError, OSError):
            pass
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "；".join(str(d.get("msg") or d) for d in detail if isinstance(d, dict))[:300]
        raise HaloError(exc.code, str(detail or f"HaloWebUI 返回 {exc.code}")[:500]) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise HaloError(502, f"连不上 HaloWebUI：{type(exc).__name__}") from None
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise HaloError(502, "HaloWebUI 返回的不是 JSON") from None


def create(owner: str, goal: str, origin: dict) -> dict:
    return call("POST", "/teams", owner, {"goal": goal, "origin": origin}, timeout=60)


def get(owner: str, team_id: str) -> dict:
    return call("GET", f"/teams/{team_id}", owner)


def recent(owner: str) -> list:
    body = call("GET", "/teams", owner, timeout=40)
    return body.get("teams") or [] if isinstance(body, dict) else []


def approve(owner: str, team_id: str) -> dict:
    return call("POST", f"/teams/{team_id}/approve", owner, {}, timeout=90)


def cancel(owner: str, team_id: str) -> dict:
    return call("POST", f"/teams/{team_id}/cancel", owner, {})


def replan(owner: str, team_id: str, feedback: str) -> dict:
    return call("POST", f"/teams/{team_id}/replan", owner, {"feedback": feedback[:2000]})
