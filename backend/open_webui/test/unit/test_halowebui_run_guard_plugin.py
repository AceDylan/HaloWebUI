import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / "integrations"
    / "hermes-plugin"
    / "halowebui-run-guard"
    / "__init__.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "halowebui_run_guard_plugin", _PLUGIN_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
plugin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(plugin)

GEMINI_RELAY = "https://relay.example:23001/v1beta"
LAUNCH = (
    "/root/.hermes/scripts/reclaude-run.sh run --detach --cwd /root "
    "--task-file /root/.hermes/reclaude-runs/tasks/server-health-check.md --max-turns 150"
)
STARTED = json.dumps(
    {
        "output": (
            "==== reclaude run 20260926-200514-5f8303dd started 2026-09-26 20:05:14 +0800 ====\n"
            "[runner] 额度预检通过。\n"
            "detached: reclaude run 20260926-200514-5f8303dd keeps running in the background.\n"
            "NEXT: reply to the user now with run id 20260926-200514-5f8303dd, then end this turn."
        ),
        "exit_code": 0,
        "error": None,
    }
)


def _call(call_id, name, arguments, signature=None):
    call = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    if signature:
        call["extra_content"] = {"google": {"thought_signature": signature}}
    return call


def _result(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


WRITE = _call("call_1", "write_file", {"path": "/tmp/task.md", "content": "x"}, "sig-1")
RUN = _call("call_2", "terminal", {"command": LAUNCH})
WRITE_RESULT = _result("call_1", "write_file", '{"bytes_written": 1}')
RUN_RESULT = _result("call_2", "terminal", STARTED)


def _messages(*tail):
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "服务器健康吗"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": "plan",
            "tool_calls": [WRITE, RUN],
        },
        *tail,
    ]


# ── Gemini replay ────────────────────────────────────────────────────────────


def test_parallel_calls_are_replayed_as_call_result_pairs_for_gemini():
    request = {"model": "gemini-chat", "messages": _messages(WRITE_RESULT, RUN_RESULT)}
    original = deepcopy(request)

    result = plugin.replay_gemini_tool_calls_one_by_one(
        request=request, base_url=GEMINI_RELAY, api_mode="chat_completions"
    )

    messages = result["request"]["messages"]
    assert [
        (m["role"], [c["id"] for c in m.get("tool_calls", [])] or m.get("tool_call_id"))
        for m in messages
    ] == [
        ("system", None),
        ("user", None),
        ("assistant", ["call_1"]),
        ("tool", "call_1"),
        ("assistant", ["call_2"]),
        ("tool", "call_2"),
    ]
    # The first call keeps the message's own fields and its thought signature.
    assert messages[2]["reasoning"] == "plan"
    assert messages[2]["tool_calls"][0]["extra_content"] == WRITE["extra_content"]
    assert messages[4] == {"role": "assistant", "content": "", "tool_calls": [RUN]}
    assert result["request"]["model"] == "gemini-chat"
    assert result["source"] == "halowebui-run-guard"
    assert request == original


def test_results_follow_their_own_call_whatever_order_they_came_in():
    request = {
        "messages": _messages(
            RUN_RESULT, WRITE_RESULT, {"role": "user", "content": "next"}
        )
    }

    messages = plugin.replay_gemini_tool_calls_one_by_one(
        request=request, base_url=GEMINI_RELAY
    )["request"]["messages"]

    assert [m.get("tool_call_id") or m["role"] for m in messages[2:]] == [
        "assistant",
        "call_1",
        "assistant",
        "call_2",
        "user",
    ]


def test_a_call_without_a_result_stays_in_place():
    request = {"messages": _messages(WRITE_RESULT)}

    messages = plugin.replay_gemini_tool_calls_one_by_one(
        request=request, base_url=GEMINI_RELAY
    )["request"]["messages"]

    assert [m.get("tool_call_id") or m["role"] for m in messages[2:]] == [
        "assistant",
        "call_1",
        "assistant",
    ]


@pytest.mark.parametrize(
    "base_url",
    [
        "https://relay.example:23001/v1",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "",
        None,
    ],
)
def test_other_endpoints_are_left_alone(base_url):
    request = {"messages": _messages(WRITE_RESULT, RUN_RESULT)}

    assert (
        plugin.replay_gemini_tool_calls_one_by_one(request=request, base_url=base_url)
        is None
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://generativelanguage.googleapis.com/v1beta",
        "https://relay.example:23001/v1beta/models/",
    ],
)
def test_google_and_model_listing_urls_count_as_native_gemini(base_url):
    request = {"messages": _messages(WRITE_RESULT, RUN_RESULT)}

    assert plugin.replay_gemini_tool_calls_one_by_one(
        request=request, base_url=base_url
    )


def test_single_calls_need_no_rewrite():
    request = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": [RUN]},
            RUN_RESULT,
        ]
    }

    assert (
        plugin.replay_gemini_tool_calls_one_by_one(
            request=request, base_url=GEMINI_RELAY
        )
        is None
    )


# ── Runner launches ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_remembered_launches():
    plugin._launches.clear()
    yield
    plugin._launches.clear()


def _ids(call_id, turn="turn-1", session="chat-1"):
    return {
        "session_id": session,
        "turn_id": turn,
        "tool_call_id": call_id,
        "task_id": "task",
    }


def test_identical_launch_in_the_same_turn_is_refused_with_the_run_id():
    args = {"command": LAUNCH}
    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
        is None
    )
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=STARTED, status="ok", **_ids("call_2")
    )

    directive = plugin.block_repeated_launch(
        tool_name="terminal",
        args={"command": "  " + LAUNCH.replace(" ", "   ")},
        **_ids("call_3"),
    )

    assert directive["action"] == "block"
    assert "20260926-200514-5f8303dd" in directive["message"]


def test_a_second_copy_in_the_same_batch_is_refused_and_does_not_clear_the_first():
    args = {"command": LAUNCH}
    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
        is None
    )
    duplicate = plugin.block_repeated_launch(
        tool_name="terminal", args=args, **_ids("call_3")
    )
    assert duplicate["action"] == "block"
    # hermes reports the refused call back too.
    plugin.record_launch_outcome(
        tool_name="terminal",
        args=args,
        result=json.dumps({"error": duplicate["message"]}),
        status="blocked",
        **_ids("call_3"),
    )
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=STARTED, status="ok", **_ids("call_2")
    )

    again = plugin.block_repeated_launch(
        tool_name="terminal", args=args, **_ids("call_4")
    )

    assert "20260926-200514-5f8303dd" in again["message"]


@pytest.mark.parametrize(
    "result,status",
    [
        (
            json.dumps(
                {"output": "Error: --detach needs --cwd", "exit_code": 2, "error": None}
            ),
            "ok",
        ),
        (
            json.dumps({"error": "ACE routing guard blocked this specialist launch."}),
            "ok",
        ),
        (json.dumps({"error": "denied"}), "blocked"),
        ("not json", "error"),
    ],
)
def test_a_launch_that_did_not_start_can_be_retried(result, status):
    args = {"command": LAUNCH}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=result, status=status, **_ids("call_2")
    )

    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_3"))
        is None
    )


def test_the_outcome_is_matched_by_call_id_when_the_command_was_rewritten():
    # Another pre_tool_call hook (rtk-rewrite) may rewrite the command in place,
    # so the call reports back with a command the launch was not keyed on.
    plugin.block_repeated_launch(
        tool_name="terminal", args={"command": LAUNCH}, **_ids("call_2")
    )
    plugin.record_launch_outcome(
        tool_name="terminal",
        args={"command": "rtk " + LAUNCH},
        result=json.dumps({"output": "Error: bad flag", "exit_code": 2, "error": None}),
        status="ok",
        **_ids("call_2"),
    )

    assert (
        plugin.block_repeated_launch(
            tool_name="terminal", args={"command": LAUNCH}, **_ids("call_3")
        )
        is None
    )


def test_background_launch_without_a_run_id_still_counts():
    args = {"command": LAUNCH, "background": True}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
    plugin.record_launch_outcome(
        tool_name="terminal",
        args=args,
        result=json.dumps(
            {"output": "Background process started", "exit_code": 0, "error": None}
        ),
        status="ok",
        **_ids("call_2"),
    )

    directive = plugin.block_repeated_launch(
        tool_name="terminal", args=args, **_ids("call_3")
    )

    assert directive["action"] == "block"
    assert "the run id it printed" in directive["message"]


def test_other_turns_commands_and_tools_are_never_blocked():
    args = {"command": LAUNCH}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=STARTED, status="ok", **_ids("call_2")
    )

    # The next message asks for the same check again.
    assert (
        plugin.block_repeated_launch(
            tool_name="terminal", args=args, **_ids("c", turn="turn-2")
        )
        is None
    )
    # Another chat.
    assert (
        plugin.block_repeated_launch(
            tool_name="terminal", args=args, **_ids("c", session="chat-2")
        )
        is None
    )
    # Another task in the same turn.
    other = {"command": LAUNCH.replace("server-health-check", "disk-check")}
    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=other, **_ids("c"))
        is None
    )
    # Reading a run's status is not a launch.
    status = {
        "command": "/root/.hermes/scripts/reclaude-run.sh status 20260926-200514-5f8303dd"
    }
    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=status, **_ids("c"))
        is None
    )
    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=status, **_ids("d"))
        is None
    )
    assert (
        plugin.block_repeated_launch(tool_name="write_file", args=args, **_ids("c"))
        is None
    )


def test_nothing_is_guarded_without_a_turn_id():
    args = {"command": LAUNCH}
    ids = {"session_id": "chat-1", "turn_id": "", "tool_call_id": "call_2"}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **ids)
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=STARTED, status="ok", **ids
    )

    assert (
        plugin.block_repeated_launch(
            tool_name="terminal", args=args, **{**ids, "tool_call_id": "call_3"}
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "/root/.hermes/scripts/codex-run.sh run --detach --cwd /root --task-file /tmp/t.md",
        "/root/.hermes/scripts/agy-run.sh run --detach --cwd /root --task-file /tmp/t.md",
        "bash -lc '/root/.hermes/scripts/reclaude-run.sh answer 20260926-200514-5f8303dd --task more'",
    ],
)
def test_every_runner_launch_is_recognised(command):
    args = {"command": command}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))

    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_3"))[
            "action"
        ]
        == "block"
    )


def test_old_launches_are_forgotten(monkeypatch):
    args = {"command": LAUNCH}
    now = [1000.0]
    monkeypatch.setattr(plugin.time, "time", lambda: now[0])
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))

    now[0] += plugin.LAUNCH_TTL_SECONDS + 1

    assert (
        plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_3"))
        is None
    )


def test_registers_middleware_and_hooks():
    registrations = []
    context = SimpleNamespace(
        register_middleware=lambda kind, callback: registrations.append(
            ("middleware", kind, callback)
        ),
        register_hook=lambda name, callback: registrations.append(
            ("hook", name, callback)
        ),
    )

    plugin.register(context)

    assert registrations == [
        ("middleware", "llm_request", plugin.replay_gemini_tool_calls_one_by_one),
        ("hook", "pre_tool_call", plugin.block_repeated_launch),
        ("hook", "post_tool_call", plugin.record_launch_outcome),
    ]


# ── What the guard leaves in the logs ────────────────────────────────────────


def test_each_action_leaves_one_log_line(caplog):
    caplog.set_level("DEBUG", logger=plugin.logger.name)
    args = {"command": LAUNCH}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result=STARTED, status="ok", **_ids("call_2")
    )
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_3"))

    started, blocked = [r for r in caplog.records if r.levelname in ("INFO", "WARNING")]
    assert started.levelname == "INFO"
    assert "started run 20260926-200514-5f8303dd" in started.getMessage()
    assert blocked.levelname == "WARNING"
    assert "blocked a repeated reclaude-run.sh run in session chat-1 turn turn-1" in blocked.getMessage()
    assert "--task-file" not in blocked.getMessage()


def test_a_failed_launch_is_logged_as_retryable(caplog):
    caplog.set_level("INFO", logger=plugin.logger.name)
    args = {"command": LAUNCH}
    plugin.block_repeated_launch(tool_name="terminal", args=args, **_ids("call_2"))
    plugin.record_launch_outcome(
        tool_name="terminal", args=args, result='{"exit_code": 2}', status="ok", **_ids("call_2")
    )
    assert "did not start" in caplog.records[-1].getMessage()


def test_a_split_of_the_turn_just_made_is_logged_once_old_turns_quietly(caplog):
    caplog.set_level("DEBUG", logger=plugin.logger.name)
    fresh = {"messages": _messages(WRITE_RESULT, RUN_RESULT)}
    plugin.replay_gemini_tool_calls_one_by_one(request=fresh, base_url=GEMINI_RELAY)
    assert caplog.records[-1].levelname == "INFO"
    assert "replayed 1 parallel tool-call turn(s)" in caplog.records[-1].getMessage()

    later = {
        "messages": _messages(
            WRITE_RESULT, RUN_RESULT,
            {"role": "assistant", "content": "已启动"},
            {"role": "user", "content": "进度？"},
        )
    }
    plugin.replay_gemini_tool_calls_one_by_one(request=later, base_url=GEMINI_RELAY)
    assert caplog.records[-1].levelname == "DEBUG"
