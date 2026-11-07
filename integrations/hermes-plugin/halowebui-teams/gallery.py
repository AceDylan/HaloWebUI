"""Durable delivery of every successful GPT Image result, independent of its caller.

The provider's image_generated hook runs before its cache can expire. Only local
I/O happens there; the gateway bridge delivers one bounded batch per tick.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from . import link
from .common import logger, read_team

MAX_BYTES = 32 * 1024 * 1024
_owner = ContextVar("halo_image_owner", default=None)


@contextmanager
def owned_by(owner: str, team_id: str):
    token = _owner.set({"owner": owner, "team_id": team_id})
    try:
        yield
    finally:
        _owner.reset(token)


def root() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()) / "halo-image-outbox"


def settings() -> dict:
    value = link.config().get("image_gallery")
    return value if isinstance(value, dict) else {}


def event_id(result: dict) -> str:
    return hashlib.sha256(str(Path(str(result.get("image") or "")).resolve()).encode()).hexdigest()


def is_queued(result: dict) -> bool:
    event = event_id(result)
    return (root() / event).is_dir() or (root() / (event + ".sent")).is_file()


def context() -> dict:
    from gateway.session_context import get_session_env

    if _owner.get() is not None:
        return dict(_owner.get())
    board = os.environ.get("HERMES_KANBAN_BOARD", "")
    team = read_team(board) if board.startswith("halo-") else None
    if team:
        return {"owner": team.get("owner", ""), "team_id": team.get("team_id", "")}
    platform = get_session_env("HERMES_SESSION_PLATFORM")
    user = get_session_env("HERMES_SESSION_USER_ID")
    # An unlinked Telegram user must never fall back to somebody else's gallery.
    owner = (link.owner_for_telegram(user) if platform == "telegram"
             else settings().get("default_owner", ""))
    return {"owner": owner or "", "platform": platform, "platform_user": user,
            "session_id": get_session_env("HERMES_SESSION_ID"),
            "chat_id": get_session_env("HERMES_SESSION_CHAT_ID") if platform == "api_server" else ""}


def on_image_generated(result=None, **_kwargs) -> None:
    if not settings().get("enabled") or not isinstance(result, dict):
        return
    model = str(result.get("model") or "").lower().split("/")[-1]
    if not result.get("success") or not (model.startswith("gpt-image") or model == "chatgpt-image-latest"):
        return
    try:
        source = Path(str(result.get("image") or ""))
        if not source.is_file() or source.stat().st_size > MAX_BYTES:
            raise ValueError("generated image is not a bounded local file")
        # Stable across duplicate observers, different for independent generations.
        event = event_id(result)
        spool = root()
        spool.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (spool / event).exists() or (spool / (event + ".sent")).exists():
            return
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=spool) as tmp:
            staging = Path(tmp)
            shutil.copyfile(source, staging / "image")
            record = {**context(), "event_id": event, "model": str(result["model"]),
                      "prompt": str(result.get("prompt") or "")[:8000],
                      "size": str(result.get("actual_size") or result.get("aspect_ratio") or "auto")[:80],
                      "created_at_ms": int(time.time() * 1000)}
            (staging / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            try:
                staging.rename(spool / event)
            except FileExistsError:
                pass
    except Exception as exc:
        # The successful tool result must remain successful; never log prompts/paths.
        logger.warning("image gallery capture failed (%s)", type(exc).__name__)


def flush(limit: int = 4) -> int:
    if not settings().get("enabled") or not link.configured() or not root().exists():
        return 0
    delivered = 0
    with (root() / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        pending = sorted((p for p in root().iterdir() if p.is_dir() and not p.name.startswith(".")),
                         key=lambda p: p.stat().st_mtime)
        for entry in pending[:limit]:
            try:
                if (root() / (entry.name + ".sent")).exists():
                    shutil.rmtree(entry)
                    continue
                record = json.loads((entry / "record.json").read_text())
                if not record.get("owner") and record.get("platform") == "telegram":
                    record["owner"] = link.owner_for_telegram(record.get("platform_user"))
                if not record.get("owner"):
                    logger.warning("image gallery delivery pending: missing owner mapping")
                    entry.touch()
                    continue
                body = {k: v for k, v in record.items() if k not in {"owner", "platform_user"}}
                body["image_base64"] = base64.b64encode((entry / "image").read_bytes()).decode("ascii")
                response = link.call("POST", "/images", record["owner"], body, timeout=20)
                if not isinstance(response, dict) or not response.get("stored"):
                    raise ValueError("missing gallery acknowledgement")
                # Receipt precedes deletion so a crash after acknowledgement is harmless.
                (root() / (entry.name + ".sent")).touch(mode=0o600)
                shutil.rmtree(entry)
                delivered += 1
            except Exception as exc:
                logger.warning("image gallery delivery pending (%s)", type(exc).__name__)
                entry.touch()
                # A down server must not stall the team bridge for N timeouts.
                break
    return delivered
