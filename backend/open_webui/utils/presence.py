"""Who is looking at HaloWebUI right now, and what to do when nobody is.

A finished reply (and a pending command approval) is pushed to the user's
notification webhook - the settings page promises "任务在没有打开页面时完成，
会推送到这里" - so the push must fire exactly when no tab shows the person the
reply. "A tab" is a live socket, but the socket registry alone gets this wrong:

- ``USER_POOL`` only lists sockets whose handshake token decoded. The browser
  presents the token it was built with on every reconnect; after a re-login
  (secret rotation, expiry) that token is stale, so a reconnected tab streams
  the reply fine yet is invisible there. The tab that sent the request is known
  by its ``session_id``, and the socket.io server itself knows whether that
  socket is still connected, registered or not.
- Phones drop the socket the moment the browser goes to the background and
  reconnect on resume; a server restart makes every tab reconnect. A completion
  that lands in such a gap must not read as "the person left".

So a tab counts when the user has a registered socket *or* the requesting
session is still connected, and a push waits a short grace window for a tab
to come back before it goes out. The push runs off the event loop and never
delays the chat completion event or the post-response bookkeeping.

Environment:
- CHAT_WEBHOOK_GRACE_SECONDS: how long a finished reply waits for a tab before
  the webhook is posted (default 30; 0 posts at once).
"""

import asyncio
import logging
import os
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.users import Users
from open_webui.socket.main import get_active_status_by_user_id, sio
from open_webui.utils.webhook import post_webhook

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))


def _grace_from_env(default: int) -> int:
    try:
        return max(0, int(os.environ.get("CHAT_WEBHOOK_GRACE_SECONDS", str(default))))
    except ValueError:
        return default


# A finished reply can wait this long for a tab to (re)connect.
WEBHOOK_GRACE_SECONDS = _grace_from_env(30)
# An approval auto-denies after HERMES_AGENT_APPROVAL_TIMEOUT; only ride out a
# reconnect here, the rest of that window belongs to the person.
APPROVAL_WEBHOOK_GRACE_SECONDS = min(WEBHOOK_GRACE_SECONDS, 10)
POLL_SECONDS = 2.0

# Strong references: asyncio keeps only weak ones, and a push waiting out its
# grace window must not be garbage-collected mid-wait.
_PENDING: set = set()


def has_live_tab(user_id: Optional[str], session_id: Optional[str] = None) -> bool:
    """True when a tab can show the user something right now: a registered
    socket of theirs, or the very socket that sent the request still open."""
    if user_id and get_active_status_by_user_id(user_id):
        return True
    if session_id:
        try:
            return bool(sio.manager.is_connected(session_id, "/"))
        except Exception:
            return False
    return False


async def wait_for_live_tab(
    user_id: Optional[str],
    session_id: Optional[str] = None,
    *,
    grace_seconds: Optional[float] = None,
    poll_seconds: float = POLL_SECONDS,
) -> bool:
    """Wait up to *grace_seconds* for a tab; True as soon as one is there."""
    grace = (
        float(WEBHOOK_GRACE_SECONDS)
        if grace_seconds is None
        else max(0.0, float(grace_seconds))
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + grace
    while True:
        if has_live_tab(user_id, session_id):
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(max(poll_seconds, 0.01), remaining))


def schedule_away_webhook(
    *,
    user_id: str,
    session_id: Optional[str],
    name: str,
    message: str,
    event_data: dict,
    grace_seconds: Optional[float] = None,
    log_tag: str = "chat",
) -> Optional[asyncio.Task]:
    """Post *message* to the user's notification webhook unless a tab is, or
    within the grace window becomes, connected.

    Returns the background task, or None when the user has no webhook. Must be
    called from a running event loop; it never raises for delivery problems.
    """
    try:
        webhook_url = Users.get_user_webhook_url_by_id(user_id)
    except Exception as e:
        log.warning(f"{log_tag} webhook skipped: cannot read the webhook url: {e}")
        return None
    if not webhook_url:
        return None

    async def _push():
        try:
            if await wait_for_live_tab(
                user_id, session_id, grace_seconds=grace_seconds
            ):
                log.debug(
                    f"{log_tag} webhook skipped: a tab of user {user_id} is connected"
                )
                return
            await asyncio.to_thread(
                post_webhook, name, webhook_url, message, event_data
            )
        except Exception as e:
            log.warning(f"{log_tag} webhook failed: {e}")

    task = asyncio.create_task(_push())
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return task
