"""Keep one HaloWebUI message from starting the same background run twice.

Two parts, both scoped narrowly:

1. ``llm_request`` middleware for native Gemini endpoints (``.../v1beta``): an
   assistant turn that made several tool calls at once is replayed as one call
   followed by its result, then the next call and its result. Replayed as one
   parallel batch, the ``gemini-chat`` relay model did not see the second
   call's result: it either launched the runner again or made up a run id.
2. ``pre_tool_call`` / ``post_tool_call`` hooks: once a runner launch
   (``reclaude-run.sh`` / ``codex-run.sh`` / ``agy-run.sh`` ``run``/``answer``)
   has started in a turn, the identical command in the same turn is refused
   and the model is told which run is already going.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit


SOURCE = "halowebui-run-guard"

# ── Gemini: replay parallel tool calls one at a time ─────────────────────────


def _is_native_gemini_base_url(base_url: Any) -> bool:
    """Same test as hermes' ``is_native_gemini_base_url``: Google's endpoint or
    a relay speaking the native REST shape (``<base>/v1beta``), not ``/openai``."""
    normalized = str(base_url or "").strip().rstrip("/").lower()
    if not normalized or normalized.endswith("/openai"):
        return False
    if "generativelanguage.googleapis.com" in normalized:
        return True
    try:
        path = urlsplit(normalized).path.rstrip("/")
    except ValueError:
        return False
    return path.endswith("/v1beta") or path.endswith("/v1beta/models")


def _tool_call_id(tool_call: Any) -> str:
    if not isinstance(tool_call, dict):
        return ""
    return str(tool_call.get("id") or tool_call.get("call_id") or "")


def _sequential_tool_messages(messages: list) -> tuple[list, int]:
    """Split each assistant message with several tool calls into one message
    per call, each followed by its own tool result. Returns (messages, number
    of assistant messages split)."""
    result: list = []
    split = 0
    index = 0
    while index < len(messages):
        message = messages[index]
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if (
            not isinstance(message, dict)
            or message.get("role") != "assistant"
            or not isinstance(tool_calls, list)
            or len(tool_calls) < 2
        ):
            result.append(message)
            index += 1
            continue

        # The tool results that answer this message follow it directly.
        end = index + 1
        while (
            end < len(messages)
            and isinstance(messages[end], dict)
            and messages[end].get("role") in ("tool", "function")
        ):
            end += 1
        results = list(messages[index + 1 : end])

        for position, tool_call in enumerate(tool_calls):
            if position == 0:
                result.append({**message, "tool_calls": [tool_call]})
            else:
                result.append(
                    {"role": "assistant", "content": "", "tool_calls": [tool_call]}
                )
            call_id = _tool_call_id(tool_call)
            for result_index, tool_message in enumerate(results):
                if call_id and str(tool_message.get("tool_call_id") or "") == call_id:
                    result.append(results.pop(result_index))
                    break
        # Results that name no call of this message keep their place at the end.
        result.extend(results)
        split += 1
        index = end
    return result, split


def replay_gemini_tool_calls_one_by_one(**kwargs: Any) -> dict[str, Any] | None:
    if not _is_native_gemini_base_url(kwargs.get("base_url")):
        return None
    request = kwargs.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
        return None
    messages, split = _sequential_tool_messages(request["messages"])
    if not split:
        return None
    return {
        "request": {**request, "messages": messages},
        "source": SOURCE,
        "reason": f"replayed {split} parallel tool-call turn(s) one call at a time for a native Gemini endpoint",
    }


# ── Runner launches: at most one identical launch per turn ───────────────────

RUNNER_LAUNCH_RE = re.compile(
    r"(?:^|[\s/;&|(\"'])(reclaude-run\.sh|codex-run\.sh|agy-run\.sh)\s+(run|answer)(?=\s|$)"
)
RUN_ID_RE = re.compile(r"(?:====\s+\w+\s+run|detached:\s+\w+\s+run)\s+(\S+?)(?:\s|$)")
# A launch that never reports back (a crash between the two hooks) stops
# counting after this long; turns end long before it.
LAUNCH_TTL_SECONDS = 6 * 3600
MAX_TRACKED_LAUNCHES = 500

_launches: dict[tuple[str, str, str], dict[str, Any]] = {}
_lock = threading.Lock()


def _launch_key(tool_name: Any, args: Any, kwargs: dict) -> tuple[str, str, str] | None:
    """(session, turn, command) for a runner launch; None for anything else or
    when hermes gave no turn id (then nothing is guarded)."""
    if tool_name != "terminal" or not isinstance(args, dict):
        return None
    command = args.get("command")
    if not isinstance(command, str) or not RUNNER_LAUNCH_RE.search(command):
        return None
    turn = str(kwargs.get("turn_id") or "")
    session = str(kwargs.get("session_id") or kwargs.get("task_id") or "")
    if not turn or not session:
        return None
    return session, turn, " ".join(command.split())


def _prune(now: float) -> None:
    for key in [k for k, v in _launches.items() if now - v["at"] > LAUNCH_TTL_SECONDS]:
        del _launches[key]
    while len(_launches) > MAX_TRACKED_LAUNCHES:
        del _launches[min(_launches, key=lambda k: _launches[k]["at"])]


def _started(result: Any, status: Any) -> tuple[bool, str]:
    """Whether the launch went through, and the run id it printed."""
    if status not in (None, "ok"):
        return False, ""
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(parsed, dict) or parsed.get("error"):
        return False, ""
    if parsed.get("exit_code") not in (None, 0):
        return False, ""
    match = RUN_ID_RE.search(str(parsed.get("output") or ""))
    return True, match.group(1) if match else ""


def block_repeated_launch(
    tool_name: Any = None, args: Any = None, **kwargs: Any
) -> dict[str, Any] | None:
    key = _launch_key(tool_name, args, kwargs)
    if key is None:
        return None
    now = time.time()
    with _lock:
        _prune(now)
        earlier = _launches.get(key)
        if earlier is None:
            _launches[key] = {
                "at": now,
                "tool_call_id": str(kwargs.get("tool_call_id") or ""),
                "run_id": "",
            }
            return None
        run_id = earlier["run_id"]
    which = f"run {run_id}" if run_id else "that run"
    return {
        "action": "block",
        "message": (
            "Duplicate launch blocked: this turn already ran exactly this command and "
            f"{which} is under way. Do not start it again. Reply to the user now with "
            f"{'run id ' + run_id if run_id else 'the run id it printed'}, then end this turn."
        ),
    }


def record_launch_outcome(
    tool_name: Any = None,
    args: Any = None,
    result: Any = None,
    status: Any = None,
    **kwargs: Any,
) -> None:
    key = _launch_key(tool_name, args, kwargs)
    if key is None:
        return
    tool_call_id = str(kwargs.get("tool_call_id") or "")
    with _lock:
        entry = _launches.get(key)
        # Only the call that registered the launch settles it; a blocked
        # duplicate reports back too and must not clear the original.
        if entry is None or entry["tool_call_id"] != tool_call_id:
            return
        went_through, run_id = _started(result, status)
        if went_through:
            entry["run_id"] = run_id
        else:
            # Failed or refused (guard, approval, bad flags): a retry is fine.
            del _launches[key]


def register(ctx: Any) -> None:
    ctx.register_middleware("llm_request", replay_gemini_tool_calls_one_by_one)
    ctx.register_hook("pre_tool_call", block_repeated_launch)
    ctx.register_hook("post_tool_call", record_launch_outcome)
