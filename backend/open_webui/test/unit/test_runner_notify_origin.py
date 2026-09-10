import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

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
    report = json.loads(capsys.readouterr().out)
    assert report["chat_id"] == "origin"
    assert report["attempted"] is False
    assert receipt.read_text() == '{"attempted":false}'
    assert state.read_bytes() == original_db


def test_gateway_origin_is_reported_but_not_sent_to_webui(state):
    add_launch(state, source="telegram")
    add_poll(state)
    assert origin(state) == ("origin", "telegram")
