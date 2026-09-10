import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from open_webui.utils.chat_snapshot import merge_chat_snapshot


def snapshot():
    return {
        "history": {
            "currentId": "a",
            "messages": {
                "a": {
                    "id": "a",
                    "role": "assistant",
                    "content": "old",
                    "done": False,
                    "childrenIds": [],
                }
            },
        },
        "composer_state": {"toolIds": []},
    }


def test_stale_device_save_preserves_completed_content_and_images():
    base = snapshot()
    current = copy.deepcopy(base)
    current["history"]["messages"]["a"].update(
        content="final", done=True, files=[{"id": "image", "url": "/image.png"}]
    )
    incoming = copy.deepcopy(base)
    incoming["composer_state"]["toolIds"] = ["tool"]
    result = merge_chat_snapshot(current, incoming, base)
    assert result["history"] == current["history"]
    assert result["composer_state"]["toolIds"] == ["tool"]


def test_concurrent_appends_preserve_both_branches_without_duplicates():
    base = snapshot()
    current, incoming = copy.deepcopy(base), copy.deepcopy(base)
    for value, message_id in [(current, "b"), (incoming, "c")]:
        value["history"]["messages"][message_id] = {"id": message_id, "parentId": "a"}
        value["history"]["messages"]["a"]["childrenIds"] = [message_id]
        value["history"]["currentId"] = message_id
    result = merge_chat_snapshot(current, incoming, base)
    assert set(result["history"]["messages"]) == {"a", "b", "c"}
    assert result["history"]["messages"]["a"]["childrenIds"] == ["b", "c"]
    assert result["history"]["currentId"] == "b"
    assert merge_chat_snapshot(result, incoming, base) == result


def test_unseen_background_turn_survives_old_device_save():
    base = snapshot()
    current = copy.deepcopy(base)
    current["history"]["messages"]["notify"] = {
        "id": "notify",
        "content": "[后台任务完成通知]",
    }
    current["history"]["currentId"] = "notify"
    assert merge_chat_snapshot(current, base, base) == current


def test_explicit_edits_and_deletes_work_when_the_server_has_not_changed():
    base = snapshot()
    incoming = copy.deepcopy(base)
    incoming["history"]["messages"]["a"]["content"] = "edited"
    assert merge_chat_snapshot(base, incoming, base) == incoming
    incoming["history"]["messages"].pop("a")
    incoming["history"]["currentId"] = None
    assert merge_chat_snapshot(base, incoming, base) == incoming


def test_stale_save_cannot_resurrect_a_remotely_deleted_message():
    base = snapshot()
    current = copy.deepcopy(base)
    current["history"]["messages"].pop("a")
    incoming = copy.deepcopy(base)
    incoming["history"]["messages"]["a"]["content"] = "stale edit"
    assert (
        "a" not in merge_chat_snapshot(current, incoming, base)["history"]["messages"]
    )


def test_independent_message_fields_merge_and_conflicting_text_keeps_server():
    base = snapshot()
    current, incoming = copy.deepcopy(base), copy.deepcopy(base)
    current["history"]["messages"]["a"]["content"] = "server edit"
    incoming["history"]["messages"]["a"].update(
        content="stale edit", feedback="helpful"
    )
    message = merge_chat_snapshot(current, incoming, base)["history"]["messages"]["a"]
    assert message["content"] == "server edit"
    assert message["feedback"] == "helpful"


def test_concurrent_files_merge_by_identity():
    base = {"files": []}
    current = {"files": [{"id": "a", "url": "/a"}]}
    incoming = {"files": [{"id": "b", "url": "/b"}]}
    merged = merge_chat_snapshot(current, incoming, base)
    assert {file["id"] for file in merged["files"]} == {"a", "b"}
    assert merge_chat_snapshot(merged, incoming, base) == merged


def test_merge_does_not_mutate_or_alias_input_snapshots():
    base = snapshot()
    original = copy.deepcopy(base)
    result = merge_chat_snapshot(base, base, base)
    result["history"]["messages"]["a"]["content"] = "different"
    assert base == original
