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
* **Runner members** (`reclaude`, `cchclaude`, `anyclaude`, `codex`, `agy`) are assigned to the
  runner's name, which the dispatcher leaves alone (not a profile). `reclaude.py` claims them
  and drives the runner script in `~/.hermes/scripts` (`<name>-run.sh`) directly — see its
  docstring for launch / follow / quota wait / QUESTION / notes / stop. Only reclaude-run.sh
  and its cchclaude/anyclaude wrappers park a run for a quota reset (`auto_resume`); codex and
  agy runs that hit a limit end as failed (retry from the 协作台). agy's progress.log has no
  tool lines, so agy members show no tool records. Runner runs it starts
  carry no `HERMES_SESSION_*`: no chat gets their completion notice and autopilot-supervisor
  does not resume them (it only resumes runs whose origin can get a report); only this
  bridge does.
* **Runners as data** (`runners.py`): the registry (reclaude, cchclaude, anyclaude, codex, agy,
  hermes), task kinds and the runner each starts on (code → cchclaude, ui → agy, complex →
  reclaude, research / writing → hermes), the fallback order reclaude → cchclaude → anyclaude →
  codex → agy → hermes, and layered availability checks (configured, installed, executable,
  account / quota, reachable, recent failure; cached 120 s). `fallback.py` moves a task forward
  along its chain at approval, before launch, on a runtime failure of the runner itself (quota,
  login, region, network, missing command; quota waits over 20 min) and on retry, and records
  every move. `~/.hermes/halo-teams-runners.json` overrides order / kinds / disabled / marks a
  runner down (`unavailable`), effective at once.
* **Roles are HaloWebUI assistant templates** (`assistants.py`): the 「协作」 group of
  `src/lib/data/agents-zh.json` (with `team_kind`) is the lead's catalog; a member's template
  prompt is its role in the task body.
* **The lead** (`plan.py`) runs on Hermes' `model.default` read on every call, then its
  `fallback_providers`; `auxiliary.halo_team_lead` overrides.
* **The conclusion** (`conclusion.py`): when a team finishes, the lead hands over the task's
  **complete result** — the full answer / document / images the goal asked for, not a report on
  who did what — from every task's full result and the workspace files. A member's finished
  document is placed in full (`<!-- halo:include path -->`, expanded by `expand_includes`: links
  rebased, headings under the result's title), never rewritten or shortened. Assembled from the
  deliverables and records when no model answers; stored in `<workspace>/.halo/conclusion.md`
  (entry `format: 2`, `included`).
* **The lead stays in the loop** (`lead.py`): 「对负责人说」 — the user says something while the
  team works or after it finished; the lead reads the team's state and answers, proposing a plan
  change when needed (new members, new tasks that may build on finished ones, cancelling or
  rewriting tasks that have not started, rewriting a failed one → retried). Nothing changes until
  the user applies it; new work on a finished team reopens it and its conclusion is rewritten.
  A task that fails or gets blocked is diagnosed by the lead (cause + one action: retry, retry with
  a note, another runner, skip, ask the user), applied in one click. After the conclusion the
  lead checks the result against the goal; 「让团队补上」 turns the gaps into a change request.
* **Models of Hermes members** (`plan.member_model` / `task_model`): every member carries a
  `model` (one Hermes has configured; the lead recommends one per member from `hermes_models()`
  with a hint each, else Hermes' default; the user can change it before approval, 「恢复推荐」 goes
  back). Every Kanban task is created with its member's model **and provider** pinned
  (`model_override` / `provider_override`), so a Hermes worker — the member's own runner or the
  fallback at the end of a runner chain — runs exactly that model and never depends on the CLI's
  own resolution of the default (which used to land on the first fallback, deepseek-chat).
* **Member activity** (`hooks.py`, inside each Kanban worker of a team board): tool calls,
  native subagent start/stop, and the moment a user's note reached the running member, as
  `halo_*` events in the same `task_events` sequence.

* **Stage and estimate** (`progress.py`): every snapshot carries `team.stage` — the step
  (计划 → 批准 → 执行 → 整理结果 → 验收), what is happening now (each running member's latest tool
  call / runner event, in words), since when, and about how long is left. Estimates come from this
  machine's own history (cached 10 min): finished attempts on every team board by executor *and*
  task kind (Hermes research ≈ 4× Hermes writing), the lead's conclusions, acceptance checks and
  plans (`~/.hermes/halo-teams/plan-times.json`); the remaining tasks are replayed on their
  dependencies with the parallel cap and one member per runner kind; the high end is ≥ 1.35×.
  While the lead plans, `GET /plan/progress?team_id=` says its current step (which model, retry and
  why); a plan comes with `estimate` (how long it takes once approved). Telegram's `/team` list
  shows the same line.
* **Projects** (`projects.py`): a plan can work in a git repository on this machine (chosen in
  HaloWebUI, or the one the goal names — HERMES_DISPATCH_PROJECTS and where recent runner runs
  worked; never the home directory or the Hermes home). At approval the team gets the branch
  `halo/<board>` from the repository's HEAD as a linked worktree at its usual workspace path;
  every finished task is committed there (`[T2 · member] title`), the conclusion lists the
  changed files and the change set, and merge into the base branch / push / discard are explicit
  user actions (`/changes/*`). Nothing pushes on its own; a merge needs a clean checkout of the
  base branch (fast-forward, else a merge commit, a conflict is aborted and reported).
* **Telegram** (`tg.py`, `notify.py`, `link.py`): `/team <目标>` starts a team from Telegram
  (HaloWebUI creates and plans it through its `/api/v1/teams/hermes/*` routes; the plan card comes
  back with 批准 / 取消 buttons, a reply re-plans), `/team` lists recent teams; the bridge loop sends
  a notice when a member asks something, a task fails, or the team finishes (with the start of
  the conclusion) — to the chat the team came from, else the owner's linked chat — and holds it
  back while the team's page is open (`events?visible=1`). Replies to notices answer the member /
  add a note and retry. Settings and the user link: `~/.hermes/halo-teams.json` (see `link.py`).
  The hook runs before the gateway's auth: only Telegram users listed there are handled.
* **Where the conclusion goes** (`bridge.report_conclusion`, `link.concluded`): once the lead has
  written a conclusion when the team finished (after its acceptance check, bounded wait), the
  bridge tells HaloWebUI (`POST /api/v1/teams/hermes/teams/{id}/concluded`), which posts it as a
  finished reply in the chat the team was started from (one post per written version; a rewrite
  the user asked for is not re-sent; conclusions from before this existed are not sent). The
  finish notice in Telegram has 「存入知识库」 (HaloWebUI saves it in the owner's 「协作结论」
  knowledge base); the conclusion page has the same plus 「在对话里追问」.

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
| `POST /v1/halo-teams/{id}/adjust` `{text, actor}` | 对负责人说: the lead proposes a plan change in the background (202; snapshot `team.change`) |
| `POST /v1/halo-teams/{id}/adjust/gaps` | the acceptance gaps as a change request |
| `POST /v1/halo-teams/{id}/change/{change}/{apply,discard}` | the user decides on the proposal (apply re-checks it against the board first) |
| `POST /v1/halo-teams/{id}/tasks/{task}/diagnosis/{apply,again}` | do what the lead suggested for a failed task / diagnose again |
| `GET /v1/halo-teams/meta` | the lead's model, runners with availability, task kinds, assistant templates |
| `POST /v1/halo-teams/runners/check` `{names?}` | re-run the availability checks now |
| `POST /v1/halo-teams/plan/resolve` `{plan}` | the plan with every member's runner worked out again (after a user edit), with its `estimate` |
| `GET /v1/halo-teams/plan/progress?team_id=` | while the lead plans: its current step and how long plans take here |
| `GET /v1/halo-teams/{id}/conclusion` | the report (markdown), its status / model, every task's full result, workspace files |
| `POST /v1/halo-teams/{id}/conclusion` | (re)write the report now |
| `GET /v1/halo-teams/{id}/files[/{path}]` | the workspace listing / one file (confined to the workspace; HTML served as text) |
| `GET /v1/halo-teams/{id}/changes` | a project team's branch: commits, files (+/−), not yet committed, merged / pushed |
| `GET /v1/halo-teams/{id}/changes/diff?path=` | one file's diff against the base |
| `POST /v1/halo-teams/{id}/changes/{merge,push,discard}` | user actions once the team is completed or stopped; push `{what: branch|base}` |
| `POST /v1/halo-teams/notify` `{event, team, origin}` | HaloWebUI hands over a finished plan (or why there is none) of a team started from Telegram; the plan card goes to that chat |

`sub_status` values: `queued` (ready, waiting for a slot), `waiting_deps`, `running`,
`quota_wait`, `waiting_user`, `failed`, `blocked`, `stopped`, `done`.

## Install

```sh
ln -s /root/HaloWebUI/integrations/hermes-plugin/halowebui-teams /root/.hermes/plugins/halowebui-teams
# config.yaml: plugins.enabled += halowebui-teams
#              kanban: {max_in_progress: 2, auto_decompose: false}
hermes gateway restart
```

`kanban.max_in_progress` is host-wide (every board, runner members included).
`auto_decompose: false` because a task that keeps getting blocked lands in `triage`, and the
gateway would otherwise ask a model to split it into new tasks on the team's board.

Environment knobs: `HALO_TEAMS_BRIDGE=0` (no bridge loop), `HALO_TEAMS_BRIDGE_INTERVAL`
(8 s), `HALO_TEAMS_RUNNER_MAX` (1 concurrent member per runner kind; old name `HALO_TEAMS_RECLAUDE_MAX`), `HALO_TEAMS_WORKSPACE_ROOT`
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
