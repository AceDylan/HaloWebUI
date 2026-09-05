import asyncio

import pytest

from open_webui.utils import hermes_agent
from open_webui.utils.hermes_agent import (
    HermesSteerError,
    _serialize_blocks,
    list_active_runs,
    steer_active_run,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    hermes_agent._ACTIVE_RUNS.clear()
    yield
    hermes_agent._ACTIVE_RUNS.clear()


def _register(chat_id="chat-1", user_id="user-1", run_id="run-1", steer=None):
    calls = []

    async def _default_steer(text):
        calls.append(text)

    hermes_agent._register_run(
        chat_id,
        {
            "user_id": user_id,
            "message_id": "msg-1",
            "run_id": run_id,
            "started_at": 100.0,
            "steers": 0,
            "steer": steer or _default_steer,
        },
    )
    return calls


def test_steer_forwards_text_to_the_registered_run_and_counts_it():
    calls = _register()

    result = asyncio.run(
        steer_active_run(chat_id="chat-1", user_id="user-1", text="  focus on tests  ")
    )

    assert calls == ["focus on tests"]
    assert result == {
        "status": True,
        "chat_id": "chat-1",
        "run_id": "run-1",
        "accepted": True,
    }
    assert hermes_agent._ACTIVE_RUNS["chat-1"]["steers"] == 1


def test_steer_is_a_404_without_a_run_or_for_another_users_chat():
    with pytest.raises(HermesSteerError) as no_run:
        asyncio.run(steer_active_run(chat_id="chat-1", user_id="user-1", text="x"))
    assert no_run.value.status_code == 404

    _register(user_id="owner")
    with pytest.raises(HermesSteerError) as wrong_user:
        asyncio.run(steer_active_run(chat_id="chat-1", user_id="intruder", text="x"))
    assert wrong_user.value.status_code == 404


def test_steer_rejects_blank_text_before_touching_hermes():
    calls = _register()

    with pytest.raises(HermesSteerError) as blank:
        asyncio.run(steer_active_run(chat_id="chat-1", user_id="user-1", text="   "))

    assert blank.value.status_code == 400
    assert calls == []


def test_unregister_only_removes_the_matching_run():
    _register(run_id="run-old")

    hermes_agent._unregister_run("chat-1", "run-new")
    assert "chat-1" in hermes_agent._ACTIVE_RUNS

    hermes_agent._unregister_run("chat-1", None)
    assert "chat-1" in hermes_agent._ACTIVE_RUNS

    hermes_agent._unregister_run("chat-1", "run-old")
    assert "chat-1" not in hermes_agent._ACTIVE_RUNS


def test_list_active_runs_is_scoped_to_the_user(monkeypatch):
    monkeypatch.setattr(
        hermes_agent.Chats, "get_chat_title_by_id", lambda chat_id: f"title:{chat_id}"
    )
    _register(chat_id="mine", user_id="user-1", run_id="run-a")
    _register(chat_id="theirs", user_id="user-2", run_id="run-b")

    runs = list_active_runs("user-1")

    assert [run["chat_id"] for run in runs] == ["mine"]
    assert runs[0]["title"] == "title:mine"
    assert runs[0]["run_id"] == "run-a"
    assert "steer" not in runs[0]


def test_serialize_blocks_renders_a_steer_as_a_quoted_marker():
    content = _serialize_blocks(
        [
            {"type": "text", "content": "Working on it."},
            {"type": "steer", "content": "skip the docs\nfocus on tests"},
            {"type": "text", "content": "Understood."},
        ]
    )

    assert "> \U0001f9ed skip the docs\n> focus on tests" in content
    assert content.index("Working on it.") < content.index("skip the docs") < content.index(
        "Understood."
    )
