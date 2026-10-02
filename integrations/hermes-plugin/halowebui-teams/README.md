# halowebui-teams — HaloWebUI 协作台 on the Hermes Kanban

HaloWebUI's 协作台 (agent teams: a lead, members with roles, a shared task board with
dependencies, member messages and logs, live view and replay) runs on Hermes. This plugin
is the Hermes side. It adds no service, port or second task store:

* **One Kanban board per team** (`halo-<16 hex of the HaloWebUI team id>`). Tasks,
  dependencies, attempts (`task_runs`), comments and events are the Kanban's own tables.
  The team record (members, which member owns which task, executor per member, owner,
  chat, workspace, paused/stopped) is `board.json` → `halowebui_team`.
* **Hermes members** are assigned to the `default` profile and run by the gateway's
  built-in Kanban dispatcher (`hermes -p default chat -q "work kanban task <id>"`). The
  member identity is the team record, not a profile.
* **reclaude members** are assigned to `reclaude`, which the dispatcher leaves alone (not a
  profile). `reclaude.py` claims them and drives `reclaude-run.sh` directly — see its
  docstring for launch / follow / quota wait / QUESTION / notes / stop. Runner runs it starts
  carry no `HERMES_SESSION_*`: no chat gets their completion notice and autopilot-supervisor
  does not resume them (it only resumes runs whose origin can get a report); only this
  bridge does.
* **Member activity** (`hooks.py`, inside each Kanban worker of a team board): tool calls,
  native subagent start/stop, and the moment a user's note reached the running member, as
  `halo_*` events in the same `task_events` sequence.

## HTTP API (api_server, same key as `/v1/runs`)

HaloWebUI sends `X-Halo-Owner: <user id>`; a team recorded for another owner is a 404.

| Route | |
|---|---|
| `POST /v1/halo-teams/plan` `{goal, feedback?, previous?, team_id?}` | the lead's plan: one `auxiliary.kanban_decomposer` call + deterministic validation (names, executors, references, cycles), one retry with the errors |
| `POST /v1/halo-teams` `{team_id, plan, goal, title?, chat_id?}` | create the board and tasks from an approved plan (idempotent per team id) |
| `GET /v1/halo-teams/{id}` | authoritative snapshot: team, lead, members (status), tasks (status, sub_status, parents, attempts, current run) |
| `GET /v1/halo-teams/{id}/events?after=&limit=` | normalized events after a cursor; each event carries the task status after it, so a replay is a plain fold; `reconcile` lists tasks whose folded history disagrees with the live row |
| `GET /v1/halo-teams/{id}/tasks/{task}?log=1` | attempts, comments, redacted log tail |
| `POST /v1/halo-teams/{id}/tasks/{task}/messages` `{body, author_name}` | a user note on the task (a Kanban comment) |
| `POST /v1/halo-teams/{id}/tasks/{task}/retry` | unblock a failed / blocked task: a new attempt; finished tasks are not touched |
| `POST /v1/halo-teams/{id}/control` `{action: pause|resume|stop}` | pause = board archived (the dispatcher skips it, running members go on); stop = final: running members reclaimed / runner stopped, tasks blocked |

`sub_status` values: `queued` (ready, waiting for a slot), `waiting_deps`, `running`,
`quota_wait`, `waiting_user`, `failed`, `blocked`, `stopped`, `done`.

## Install

```sh
ln -s /root/HaloWebUI/integrations/hermes-plugin/halowebui-teams /root/.hermes/plugins/halowebui-teams
# config.yaml: plugins.enabled += halowebui-teams
#              kanban: {max_in_progress: 2, auto_decompose: false}
hermes gateway restart
```

`kanban.max_in_progress` is host-wide (every board, reclaude members included).
`auto_decompose: false` because a task that keeps getting blocked lands in `triage`, and the
gateway would otherwise ask a model to split it into new tasks on the team's board.

Environment knobs: `HALO_TEAMS_BRIDGE=0` (no bridge loop), `HALO_TEAMS_BRIDGE_INTERVAL`
(8 s), `HALO_TEAMS_RECLAUDE_MAX` (1 concurrent reclaude member), `HALO_TEAMS_WORKSPACE_ROOT`
(`/root/work/agent-teams`), `HALO_TEAMS_NATIVE_MAX_RUNTIME` (3600 s per Hermes attempt),
`HALO_TEAMS_MAX_TOOL_EVENTS` (400 tool events per attempt, then one "truncated" note).

## Tests

```sh
cd integrations/hermes-plugin/halowebui-teams
/usr/local/lib/hermes-agent/venv/bin/python -m pytest tests -q -p no:cacheprovider
```

They run real Kanban operations against a throwaway `HERMES_KANBAN_HOME` and a fake runner.

## Remove

Drop the name from `plugins.enabled` and restart the gateway. Team boards stay on disk
(`~/.hermes/kanban/boards/halo-*`) and are skipped by nothing else; `hermes kanban boards rm`
archives one.
