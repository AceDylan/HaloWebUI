# HaloWebUI run guard for Hermes

Keeps one HaloWebUI message from starting the same background run twice.

**Why.** On 2026-09-26 one `/reclaude` message ("服务器健康吗") on `gemini-chat`
started two reclaude runs and produced two reports. The model had written the
task file and launched the runner in one reply (two parallel tool calls, as the
`reclaude-launch` skill asks). Hermes' native Gemini client replays such a turn
as one model content with both calls and one user content with both results.
Replayed that way to the `gemini-chat` relay (`.../v1beta`), the model did not
see the second call's result. Of 27 replays of the recorded turn in that form
(with or without call ids), none quoted the real run id: 5 launched the runner
again, the rest made up a run id, a tool result or the health report itself.
The same history replayed as call, result, call, result quoted the real run id
in 14 of 14 replays. `gpt-chat` (Responses API) is not affected: every other
repeated launch within a turn in `state.db` (40 of them) followed a
launch the routing guard had refused or one that exited at once because its
task file did not exist yet.

**What it does.**

1. `llm_request` middleware, native Gemini endpoints only (Google's
   `generativelanguage.googleapis.com` or a base URL ending in `/v1beta`, not
   `/openai`): an assistant message with several tool calls is sent as one
   message per call, each followed by its own result. Nothing else in the
   request changes.
2. `pre_tool_call` / `post_tool_call`: a terminal command that launches a
   runner (`reclaude-run.sh`, `codex-run.sh` or `agy-run.sh` with `run` or
   `answer`) is remembered for its session and turn. The identical command
   (whitespace aside) in the same turn is refused while the first one is
   running or after it started, and the refusal names the run id. A launch that
   failed or was refused does not count, so a retry after an error still runs.
   Another turn, or a different command, is never blocked.

Hermes hands every `llm_request` middleware the same original request and keeps
the result of the one loaded last, so `halowebui-reasoning-sync` leaves native
Gemini requests alone (its effort field has no effect on them anyway); otherwise
the plugin load order would decide whether this rewrite survives.

## Logs

Each time the guard acts it writes one line to Hermes' logs (`agent.log` /
`gateway.log`, logger `…halowebui-run-guard…`):

- `blocked a repeated reclaude-run.sh run in session … turn …` (WARNING) — a duplicate
  was refused (the runner and subcommand only, never the command line);
- `session … turn … started run …` / `launch … did not start` (INFO) — a launch it tracks;
- `replayed N parallel tool-call turn(s) one call at a time` (INFO for the turn just
  made, DEBUG when the same old turn is resent with a later call).

`grep halowebui-run-guard ~/.hermes/logs/agent.log` shows whether it ever acted.

## Install

From the HaloWebUI repository:

```bash
ln -s "$PWD/integrations/hermes-plugin/halowebui-run-guard" \
  ~/.hermes/plugins/halowebui-run-guard
```

Add it to `plugins.enabled` in `~/.hermes/config.yaml`, keeping the plugins
already there, then restart the gateway once (`hermes gateway restart`):

```yaml
plugins:
  enabled:
    - halowebui-run-guard
```

Check it before restarting: `hermes plugins doctor --ci halowebui-run-guard`
should print `OK: runtime discovery, manifest parsing, import, and registration
passed`, and `hermes plugins show halowebui-run-guard` should say
`Status: enabled`. Plugins load when the gateway starts, so nothing changes
until the restart.

To turn it off, remove the line and restart the gateway.
