"""Background loop in the gateway process (started once, when the api_server routes are wired).

Every few seconds, for each team board that is running (not paused/stopped):
* nudges the Kanban dispatcher for that board, so a task whose dependencies just finished
  starts within seconds instead of at the gateway's next 60 s tick (same settings, same
  per-board lock as the gateway's own tick);
* drives tasks assigned to an external runner — reclaude, cchclaude, anyclaude, codex, agy (see
  ``reclaude.py``): claim, launch, follow, finish.

Paused (board archived) and stopped teams are left alone: nothing new starts there.
HALO_TEAMS_BRIDGE=0 disables the loop (the gateway's own dispatcher still runs Hermes members).
"""

from __future__ import annotations

import os
import threading
import time

from .common import board_conn, logger, read_team, team_boards

INTERVAL = float(os.environ.get("HALO_TEAMS_BRIDGE_INTERVAL", "8") or 8)
_started = {"thread": None}
_stop = threading.Event()


def _active(slug: str) -> bool:
    team = read_team(slug)
    return bool(team) and not team.get("archived") and team.get("state") == "running"


def _has_ready_native(slug: str) -> bool:
    with board_conn(slug) as conn:
        row = conn.execute(
            "SELECT 1 FROM tasks WHERE status IN ('ready','review') AND assignee = 'default' AND claim_lock IS NULL LIMIT 1"
        ).fetchone()
    return row is not None


def tick() -> None:
    from .teams import nudge_dispatch

    for slug in team_boards():
        try:
            team = read_team(slug)
            if not team:
                continue
            try:
                from . import reclaude

                reclaude.tick_board(slug, team)
            except Exception:
                logger.warning("halowebui-teams: runner tick failed for %s", slug, exc_info=True)
            if _active(slug) and _has_ready_native(slug):
                nudge_dispatch(slug)
        except Exception:
            logger.warning("halowebui-teams: bridge tick failed for %s", slug, exc_info=True)


def _loop() -> None:
    logger.info("halowebui-teams: bridge loop started (every %.0fs)", INTERVAL)
    while not _stop.wait(INTERVAL):
        try:
            tick()
        except Exception:
            logger.warning("halowebui-teams: bridge loop error", exc_info=True)


def start_bridge() -> None:
    if os.environ.get("HALO_TEAMS_BRIDGE", "1") == "0" or _started["thread"] is not None:
        return
    thread = threading.Thread(target=_loop, name="halowebui-teams-bridge", daemon=True)
    _started["thread"] = thread
    thread.start()


def stop_task_runner(slug: str, conn, task_id: str) -> bool:
    from . import reclaude

    return reclaude.stop_task(slug, conn, task_id)


def _sleep_for_tests(seconds: float) -> None:  # pragma: no cover
    time.sleep(seconds)
