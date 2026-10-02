"""Background loop in the gateway process (started once, when the api_server routes are wired).

Every few seconds, for each team board that is running (not paused/stopped):
* nudges the Kanban dispatcher for that board, so a task whose dependencies just finished
  starts within seconds instead of at the gateway's next 60 s tick (same settings, same
  per-board lock as the gateway's own tick);
* drives tasks assigned to an external runner — reclaude, cchclaude, anyclaude, codex, agy (see
  ``reclaude.py``): claim, launch, follow, finish;
* has the lead diagnose a task that failed or got blocked (see ``lead.py``);
* sends the team's Telegram notices (a member asks, a task fails, the team finished; see
  ``notify.py``).

Paused (board archived) and stopped teams are left alone: nothing new starts there.
HALO_TEAMS_BRIDGE=0 disables the loop (the gateway's own dispatcher still runs Hermes members).
"""

from __future__ import annotations

import os
import threading
import time

from .common import board_conn, logger, now, read_team, team_boards

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
            _commit_finished(slug, read_team(slug) or team)
            _catch_up_conclusion(slug, team)
            try:
                from . import lead

                lead.tick_board(slug, read_team(slug) or team)  # the lead diagnoses failed tasks
            except Exception:
                logger.warning("halowebui-teams: diagnosis tick failed for %s", slug, exc_info=True)
            try:
                from . import notify

                notify.tick_board(slug, read_team(slug) or team)
            except Exception:
                logger.warning("halowebui-teams: notice tick failed for %s", slug, exc_info=True)
        except Exception:
            logger.warning("halowebui-teams: bridge tick failed for %s", slug, exc_info=True)


def _commit_finished(slug: str, team: dict) -> None:
    """A team working on a project commits each finished task on its branch (see projects.py)."""
    if not (team.get("project") or {}).get("branch") or not team.get("tasks"):
        return
    committed = set(team.get("committed") or [])
    ids = [t for t in team["tasks"] if t not in committed]
    if not ids:
        return
    with board_conn(slug) as conn:
        done = {row[0]: row[1] or "" for row in conn.execute(
            f"SELECT id, title FROM tasks WHERE id IN ({','.join('?' * len(ids))}) AND status IN ('done','archived')",
            ids)}
    if not done:
        return
    from . import projects
    from .common import update_team

    rows = []
    for t in ids:
        if t in done:
            entry = team["tasks"][t]
            title = done[t]
            if entry.get("key") and title.startswith(entry["key"] + " "):
                title = title[len(entry["key"]) + 1:]
            rows.append({"id": t, **entry, "title": title})
    rows.sort(key=lambda r: r.get("seq") or 0)
    handled = projects.commit_finished(slug, team, rows)
    if handled:
        update_team(slug, lambda rec: rec.update({"committed": [*(rec.get("committed") or []), *handled]}))


CONCLUSION_CATCH_UP = 6 * 3600


def _catch_up_conclusion(slug: str, team: dict) -> None:
    """A team that finished while no snapshot was read, or whose report was being written when
    the gateway restarted, still gets its conclusion (recent teams only: older ones on request)."""
    if team.get("state") == "running" and team.get("tasks"):
        ids = list(team["tasks"])
        with board_conn(slug) as conn:
            open_tasks = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join('?' * len(ids))}) AND status NOT IN ('done','archived')",
                ids).fetchone()[0]
        if open_tasks == 0:
            from .teams import snapshot

            snapshot(team["team_id"])  # marks the team completed and starts its conclusion
        return
    if team.get("state") != "completed":
        return
    entry = team.get("conclusion") or {}
    from . import conclusion

    if entry.get("status") == "generating" and now() - int(entry.get("started_at") or 0) > conclusion.STALE_GENERATING:
        conclusion.start(slug, by="auto")
    elif not entry and now() - int(team.get("completed_at") or 0) < CONCLUSION_CATCH_UP:
        conclusion.start(slug, by="auto")


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
