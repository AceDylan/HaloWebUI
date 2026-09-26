import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error

import pytest

SCRIPT = Path(
    os.environ.get(
        "HALO_RUNNER_NOTIFY_SOURCE",
        Path(__file__).resolve().parents[4]
        / "integrations/hermes-runner/reclaude-notify.py",
    )
)
spec = importlib.util.spec_from_file_location("runner_notify", SCRIPT)
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            create table sessions (id text, source text);
            create table messages (session_id text, role text, timestamp real,
                tool_calls text, tool_call_id text, tool_name text, content text);
        """
        )
    return path


def add_launch(path, session="origin", command=None, source="api_server"):
    command = (
        command
        or "/root/.hermes/scripts/codex-run.sh run --task '你能做什么' --sandbox read-only"
    )
    call_id = f"launch-{session}"
    with sqlite3.connect(path) as db:
        db.execute("insert into sessions values (?,?)", (session, source))
        calls = [
            {
                "id": call_id,
                "function": {
                    "name": "terminal",
                    "arguments": json.dumps({"command": command}),
                },
            }
        ]
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (session, "assistant", time.time(), json.dumps(calls), None, None, ""),
        )
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (
                session,
                "tool",
                time.time(),
                None,
                call_id,
                "terminal",
                json.dumps(
                    {
                        "session_id": f"proc-{session}",
                        "output": "",
                        "notify_on_complete": False,
                    }
                ),
            ),
        )


def add_poll(path, session="origin", run_id="run-123", process_id=None):
    with sqlite3.connect(path) as db:
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (
                session,
                "tool",
                time.time(),
                None,
                "poll-call",
                "process",
                json.dumps(
                    {
                        "session_id": process_id or f"proc-{session}",
                        "output_preview": f"==== codex run {run_id} started 2026-09-10 ====\n",
                    }
                ),
            ),
        )


def origin(path, **kwargs):
    return notify.find_origin(
        "run-123", "", "", tool_marker="codex-run.sh", db_path=str(path), **kwargs
    )


def test_inline_task_follows_process_result_to_launch_call(state):
    add_launch(state)
    add_poll(state)
    assert origin(state) == ("origin", "api_server")


def test_diagnostic_prompt_quoting_run_is_not_its_origin(state):
    add_launch(
        state,
        "wrong",
        "/root/.hermes/scripts/codex-run.sh answer unrelated --task 'investigate run-123 codex-run.sh'",
    )
    assert origin(state) is None
    add_launch(state)
    add_poll(state)
    assert origin(state) == ("origin", "api_server")


def test_poll_from_another_chat_cannot_claim_the_origin(state):
    add_launch(state)
    add_launch(state, "wrong")
    add_poll(state, "wrong", process_id="proc-origin")
    assert origin(state) is None
    add_poll(state)
    assert origin(state) == ("origin", "api_server")


def test_ambiguous_origins_fail_closed(state):
    for session in ["first", "second"]:
        add_launch(state, session)
        add_poll(state, session)
    assert origin(state) is None


@pytest.mark.parametrize(
    "command,task_file,parent",
    [
        ("codex-run.sh run --run-id run-123 --task hello", "", ""),
        (
            "set +m; /root/.hermes/scripts/codex-run.sh run --task-file /tmp/task.md",
            "/tmp/task.md",
            "",
        ),
        (
            "bash /root/.hermes/scripts/codex-run.sh answer old-run --task yes",
            "",
            "old-run",
        ),
    ],
)
def test_explicit_launch_options_remain_supported(state, command, task_file, parent):
    add_launch(state, command=command)
    assert notify.find_origin(
        "run-123", task_file, parent, "codex-run.sh", str(state)
    ) == ("origin", "api_server")


def test_task_file_mention_inside_prompt_does_not_match(state):
    add_launch(state, command="codex-run.sh run --task 'inspect /tmp/task.md run-123'")
    assert (
        notify.find_origin("run-123", "/tmp/task.md", "", "codex-run.sh", str(state))
        is None
    )


def test_dry_run_has_no_network_or_run_file_writes(
    state, tmp_path, monkeypatch, capsys
):
    add_launch(state)
    add_poll(state)
    receipt = tmp_path / "notify.json"
    receipt.write_text('{"attempted":false}')
    original_db = state.read_bytes()
    monkeypatch.setattr(
        notify,
        "post_notification",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not POST"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--run-id",
            "run-123",
            "--run-dir",
            str(tmp_path),
            "--status",
            "success",
            "--tool-marker",
            "codex-run.sh",
            "--state-db",
            str(state),
            "--dry-run",
        ],
    )
    assert notify.main() == 0
    # The notifier logs how it resolved the origin before printing the report.
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["chat_id"] == "origin"
    assert report["origin_resolved_by"] == "state.db"
    assert report["attempted"] is False
    assert receipt.read_text() == '{"attempted":false}'
    assert state.read_bytes() == original_db


def test_gateway_origin_is_reported_but_not_sent_to_webui(state):
    add_launch(state, source="telegram")
    add_poll(state)
    assert origin(state) == ("origin", "telegram")


# --- the origin the runner recorded at launch --------------------------------
# Reconstructing the origin from state.db afterwards is a race: the notifier runs within
# a second of the run finishing, often before the launching turn has been persisted, so a
# run nobody polled was never delivered.  Both runners now record the launching hermes
# session in meta.json at start and hand it to the notifier, which prefers it.


def meta(tmp_path, **values):
    (tmp_path / "meta.json").write_text(json.dumps(values))
    return notify.read_meta(str(tmp_path))


def test_the_runner_recorded_origin_is_used_without_any_state_db_lookup(state, tmp_path):
    add_launch(state, "wrong-session")
    add_poll(state, "wrong-session")
    with sqlite3.connect(state) as db:
        db.execute("insert into sessions values (?,?)", ("recorded", "api_server"))
    assert notify.recorded_origin(
        meta(tmp_path, origin_session_id="recorded", origin_platform="api_server"),
        db_path=str(state),
    ) == ("recorded", "api_server")


def test_state_db_source_overrides_a_stale_recorded_platform(state, tmp_path):
    """A misreported platform must never turn a telegram chat into a HaloWebUI POST."""
    with sqlite3.connect(state) as db:
        db.execute("insert into sessions values (?,?)", ("tg", "telegram"))
    assert notify.recorded_origin(
        meta(tmp_path, origin_session_id="tg", origin_platform="api_server"),
        db_path=str(state),
    ) == ("tg", "telegram")


def test_the_recorded_platform_stands_in_when_the_session_row_is_gone(state, tmp_path):
    assert notify.recorded_origin(
        meta(tmp_path, origin_session_id="pruned", origin_platform="api_server"),
        db_path=str(state),
    ) == ("pruned", "api_server")


def test_nothing_recorded_falls_back_to_the_provenance_lookup(state, tmp_path):
    assert notify.recorded_origin(meta(tmp_path), db_path=str(state)) is None
    add_launch(state)
    add_poll(state)
    assert origin(state) == ("origin", "api_server")


def test_dry_run_reports_the_recorded_origin_as_coming_from_the_runner(
    state, tmp_path, monkeypatch, capsys
):
    meta(tmp_path, origin_session_id="origin", origin_platform="api_server")
    with sqlite3.connect(state) as db:
        db.execute("insert into sessions values (?,?)", ("origin", "api_server"))
    monkeypatch.setattr(
        notify,
        "find_origin",
        lambda *_a, **_k: pytest.fail("the recorded origin must win"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--run-id", "run-123", "--run-dir", str(tmp_path), "--status",
         "success", "--tool-marker", "codex-run.sh", "--state-db", str(state), "--dry-run"],
    )
    assert notify.main() == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["origin_resolved_by"] == "runner"
    assert report["chat_id"] == "origin"


# --- the layered notification config -----------------------------------------
# codex-run.sh passes --config-file codex-runner.env --config-file reclaude-runner.env.
# When "the first file that exists wins", an empty or half-written codex-runner.env
# shadows the working one and every codex notification is skipped with "notify not
# configured" while reclaude keeps working.


@pytest.fixture
def configs(tmp_path):
    empty = tmp_path / "codex-runner.env"
    empty.write_text("")
    full = tmp_path / "reclaude-runner.env"
    full.write_text(
        "HALOWEBUI_NOTIFY_URL=http://127.0.0.1:3000/api/v1/hermes/notifications\n"
        "HALOWEBUI_NOTIFY_TOKEN=secret-token\n"
    )
    return empty, full


def test_an_empty_first_config_no_longer_shadows_the_working_one(configs, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    empty, full = configs
    config, sources = notify.load_config([str(empty), str(full)])
    assert notify.missing_config_keys(config) == []
    assert config["HALOWEBUI_NOTIFY_TOKEN"] == "secret-token"
    assert [entry["path"] for entry in sources] == [str(empty), str(full)]
    assert sources[0]["provided"] == []


def test_a_key_present_but_empty_does_not_claim_the_key(configs, tmp_path, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    _, full = configs
    half = tmp_path / "half.env"
    half.write_text("HALOWEBUI_NOTIFY_URL=\nHALOWEBUI_NOTIFY_TOKEN=\n")
    config, _ = notify.load_config([str(half), str(full)])
    assert notify.missing_config_keys(config) == []


def test_an_earlier_config_still_wins_for_the_keys_it_defines(configs, tmp_path, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    _, full = configs
    partial = tmp_path / "partial.env"
    partial.write_text("HALOWEBUI_NOTIFY_URL=http://127.0.0.1:9/hook\n")
    config, sources = notify.load_config([str(partial), str(full)])
    assert config["HALOWEBUI_NOTIFY_URL"] == "http://127.0.0.1:9/hook"
    assert config["HALOWEBUI_NOTIFY_TOKEN"] == "secret-token"
    assert sources[1]["provided"] == ["HALOWEBUI_NOTIFY_TOKEN"]


def test_no_usable_config_anywhere_names_both_missing_keys(configs, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    empty, _ = configs
    config, _ = notify.load_config([str(empty)])
    assert notify.missing_config_keys(config) == [
        "HALOWEBUI_NOTIFY_URL",
        "HALOWEBUI_NOTIFY_TOKEN",
    ]


def test_the_env_override_replaces_the_candidate_list(configs, monkeypatch):
    """A test config must never fall through to the production credentials."""
    empty, full = configs
    monkeypatch.setenv("RECLAUDE_NOTIFY_CONFIG", str(empty))
    assert notify.config_candidates([str(full)]) == [str(empty)]
    config, _ = notify.load_config([str(full)])
    assert notify.missing_config_keys(config) == [
        "HALOWEBUI_NOTIFY_URL",
        "HALOWEBUI_NOTIFY_TOKEN",
    ]


# --- the delivery retry budget ------------------------------------------------
# A 409 means only "that chat is mid-turn", and a turn always ends; a 5xx may be a server
# that stays broken.  The two deserve different patience, and running out of it is final:
# nothing redelivers a notice the notifier gave up on.


@pytest.fixture
def delivery(state, tmp_path, monkeypatch):
    """A configured notifier whose run belongs to a HaloWebUI chat.  Returns the sleeps."""
    meta(tmp_path, origin_session_id="origin", origin_platform="api_server")
    with sqlite3.connect(state) as db:
        db.execute("insert into sessions values (?,?)", ("origin", "api_server"))
    config = tmp_path / "notify.env"
    config.write_text(
        "HALOWEBUI_NOTIFY_URL=http://127.0.0.1:3000/api/v1/hermes/notifications\n"
        "HALOWEBUI_NOTIFY_TOKEN=secret-token\n"
    )
    monkeypatch.setenv("RECLAUDE_NOTIFY_CONFIG", str(config))
    slept = []
    monkeypatch.setattr(notify.time, "sleep", slept.append)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--run-id", "run-123", "--run-dir", str(tmp_path), "--status",
         "success", "--tool-marker", "codex-run.sh", "--state-db", str(state)],
    )
    return slept


def always(code):
    def post(*_args, **_kwargs):
        raise urllib.error.HTTPError("http://webui/hook", code, "nope", {}, None)

    return post


def receipt_of(tmp_path):
    return json.loads((tmp_path / "notify.json").read_text())


def test_a_busy_chat_is_waited_out_past_the_ordinary_budget(
    delivery, tmp_path, monkeypatch
):
    monkeypatch.setattr(notify, "post_notification", always(409))
    assert notify.main() == 0
    record = receipt_of(tmp_path)
    assert record["failed"] is True
    assert record["attempts"] == notify.BUSY_RETRY_ATTEMPTS
    assert record["busy_attempts"] == notify.BUSY_RETRY_ATTEMPTS
    # ~20 minutes of someone else's turn, and no pointless sleep after the last attempt.
    assert delivery == [notify.RETRY_INTERVAL_SECONDS] * (notify.BUSY_RETRY_ATTEMPTS - 1)


def test_a_broken_server_still_gives_up_on_the_ordinary_budget(
    delivery, tmp_path, monkeypatch
):
    monkeypatch.setattr(notify, "post_notification", always(503))
    assert notify.main() == 0
    record = receipt_of(tmp_path)
    assert record["failed"] is True
    assert record["attempts"] == notify.RETRY_ATTEMPTS
    assert record["busy_attempts"] == 0


def test_a_busy_chat_that_frees_up_late_is_still_delivered(
    delivery, tmp_path, monkeypatch
):
    """The run this fixes: ten attempts all landed mid-turn and the result was lost."""
    attempts = []

    def busy_until_the_turn_ends(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) <= notify.RETRY_ATTEMPTS + 5:
            raise urllib.error.HTTPError("http://webui/hook", 409, "busy", {}, None)
        return 200, "queued"

    monkeypatch.setattr(notify, "post_notification", busy_until_the_turn_ends)
    assert notify.main() == 0
    record = receipt_of(tmp_path)
    assert record["delivered_at"]
    assert "failed" not in record
    assert len(attempts) == notify.RETRY_ATTEMPTS + 6


def test_a_refused_notice_is_not_retried_at_all(delivery, tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "post_notification", always(404))
    assert notify.main() == 0
    record = receipt_of(tmp_path)
    assert record["attempts"] == 1
    assert record["busy_attempts"] == 0
    assert delivery == []


# --- The report text (build_digest) ---------------------------------------------------


def write_run(run_dir, result_md, summary=None):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.md").write_text(result_md, encoding="utf-8")
    if summary is not None:
        (run_dir / "result.json").write_text(json.dumps(summary), encoding="utf-8")


RECLAUDE_RESULT = """# reclaude run r1

- status: success
- session_id: sid-1
- model: claude-opus-5-5[1m]
- turns: 7 | duration: 2m12s | cost_usd: 9.229317000000002
- tool calls: 195 (errors: 1)

---

上一批改动已经上线。

## 部署状态

- 一切正常
"""


def test_the_report_leaves_out_the_result_header_it_already_says(tmp_path):
    write_run(
        tmp_path,
        RECLAUDE_RESULT,
        {"model": "claude-opus-5-5[1m]", "num_turns": 7, "duration_human": "2m12s",
         "total_cost_usd": 9.229317000000002},
    )
    digest = notify.build_digest("r1", "success", str(tmp_path), "sid-1")
    lines = digest.splitlines()
    assert lines[0] == "✅ reclaude 运行 r1 · 已完成"
    # Who answered and what it took, on the line the web UI reads the duration from.
    assert lines[1] == "claude-opus-5-5[1m] · Claude 会话 sid-1 · $9.23 · 7 轮 · 2m12s"
    assert lines[3] == "上一批改动已经上线。"
    assert "# reclaude run" not in digest
    assert "cost_usd" not in digest
    assert "## 部署状态" in digest


def test_a_codex_result_loses_its_header_too(tmp_path):
    write_run(
        tmp_path,
        "# codex run c1\n\n- status: success\n- thread_id: t\n"
        "- tokens: input=1 cached=0 output=2 reasoning=0\n\n---\n\n答案\n",
        {"model": "", "num_turns": 1, "duration_human": "0m43s", "total_cost_usd": None},
    )
    digest = notify.build_digest("c1", "success", str(tmp_path), "t", agent="codex")
    assert digest.splitlines()[1] == "codex thread t · 1 轮 · 0m43s"
    assert digest.endswith("答案")
    assert "tokens:" not in digest


def test_a_result_without_the_header_is_kept_whole(tmp_path):
    # agy writes no header, and its "---" is part of the answer.
    body = "我是 Antigravity。\n\n---\n\n### 1. 代码开发"
    write_run(tmp_path, body)
    digest = notify.build_digest("a1", "success", str(tmp_path), "conv", agent="agy")
    assert digest.endswith(body)
    # Another run's header is not this run's header.
    write_run(tmp_path, "# reclaude run other\n\n- status: success\n\n---\n\nx")
    assert "# reclaude run other" in notify.build_digest("r1", "success", str(tmp_path), "s")


def test_the_quota_footer_still_ends_the_report(tmp_path):
    footer = "**reclaude 额度**：剩余 $29.29 / $80.00"
    write_run(tmp_path, RECLAUDE_RESULT + "\n---\n\n" + footer + "\n")
    digest = notify.build_digest("r1", "success", str(tmp_path), "sid-1")
    assert digest.splitlines()[-1] == footer
    assert "# reclaude run" not in digest
