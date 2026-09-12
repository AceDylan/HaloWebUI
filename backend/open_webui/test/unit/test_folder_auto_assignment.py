import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.models import chats as chats_mod  # noqa: E402
from open_webui.utils import folder_assignment as fa  # noqa: E402


####################
# Fakes
####################


def _chat(**overrides):
    base = dict(
        id="chat-1",
        user_id="user-1",
        title="Automatic title",
        chat={"title": "Automatic title", "history": {"messages": {}}},
        created_at=90,
        updated_at=100,
        share_id=None,
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
        assistant_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _folder(id, name, *, user_id="user-1", parent_id=None, description=None, created_at=0):
    meta = {"description": description} if description else None
    return SimpleNamespace(
        id=id,
        user_id=user_id,
        name=name,
        parent_id=parent_id,
        meta=meta,
        created_at=created_at,
    )


def _preset_folders(user_id="user-1"):
    return [
        _folder(f"f-{index}", preset["name"], user_id=user_id, description=preset["description"], created_at=index)
        for index, preset in enumerate(fa.DEFAULT_FOLDER_PRESETS, start=1)
    ]


def make_deps(
    *,
    chat,
    folders=None,
    user_info=None,
    model_answer=None,
    model_error=None,
    enabled=True,
    max_item_count=0,
    folder_counts=None,
    timeout=5.0,
    get_folder_override=None,
):
    state = {
        "chat": chat,
        "folders": list(folders or []),
        "info": dict(user_info or {}),
        "commits": [],
        "calls": [],
        "inserted": [],
    }

    async def call_model(payload):
        state["calls"].append(payload)
        if model_error is not None:
            raise model_error
        if callable(model_answer):
            return await model_answer(payload)
        return {"choices": [{"message": {"content": model_answer}}]}

    def get_chat(chat_id, user_id):
        chat = state["chat"]
        if chat is None or chat.id != chat_id or chat.user_id != user_id:
            return None
        return chat

    def get_folders(user_id):
        return [folder for folder in state["folders"] if folder.user_id == user_id]

    def get_folder(folder_id, user_id):
        if get_folder_override is not None:
            return get_folder_override(folder_id, user_id)
        return next(
            (
                folder
                for folder in state["folders"]
                if folder.id == folder_id and folder.user_id == user_id
            ),
            None,
        )

    def insert_folder(user_id, name, meta):
        folder = SimpleNamespace(
            id=f"new-{len(state['folders']) + 1}",
            user_id=user_id,
            name=name,
            parent_id=None,
            meta=meta,
            created_at=len(state["folders"]) + 1,
        )
        state["folders"].append(folder)
        state["inserted"].append(folder)
        return folder

    def count_folder_chats(folder_id, user_id):
        return (folder_counts or {}).get(folder_id, 0)

    def commit(
        chat_id,
        user_id,
        folder_id,
        *,
        apply_folder,
        evaluations,
        last_user_message_count=None,
        last_message_id=None,
    ):
        chat = state["chat"]
        meta = dict(chat.meta or {})
        assignment = dict(meta.get("folder_assignment") or {})
        if assignment.get("source") == "manual":
            return None
        if not assignment and chat.folder_id:
            return None
        assignment.update(
            source="auto",
            evaluations=evaluations,
            last_user_message_count=last_user_message_count,
            last_message_id=last_message_id,
        )
        if apply_folder:
            chat.folder_id = folder_id
            assignment["folder_id"] = folder_id
        meta["folder_assignment"] = assignment
        chat.meta = meta
        state["commits"].append(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "folder_id": folder_id,
                "apply_folder": apply_folder,
                "evaluations": evaluations,
            }
        )
        return chat

    def get_user_info(user_id):
        return state["info"]

    def patch_user_info(user_id, patch):
        state["info"].update(patch)
        return True

    deps = fa.FolderAssignmentDeps(
        call_model=call_model,
        get_chat=get_chat,
        get_folders=get_folders,
        get_folder=get_folder,
        insert_folder=insert_folder,
        count_folder_chats=count_folder_chats,
        commit_assignment=commit,
        get_user_info=get_user_info,
        patch_user_info=patch_user_info,
        enabled=enabled,
        timeout=timeout,
        max_item_count=max_item_count,
    )
    return deps, state


def _run(deps, *, chat_id="chat-1", user_id="user-1", count=1, message_id="assistant-1", title="Automatic title", require_external=False):
    return asyncio.run(
        fa.assign_chat_folder(
            chat_id=chat_id,
            user_id=user_id,
            model_id="gpt-5",
            messages=[
                {"role": "user", "content": "帮我看看 hermes gateway 为什么起不来"},
                {"role": "assistant", "content": "先看 systemctl --user status"},
            ],
            user_message_count=count,
            message_id=message_id,
            title=title,
            deps=deps,
            require_external_task_model=require_external,
        )
    )


####################
# Eligibility rules
####################


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, False), (1, True), (2, False), (3, True), (4, False), (6, True), (9, True), (True, False), ("3", False)],
)
def test_milestones_follow_the_title_cadence(count, expected):
    assert fa.is_folder_assignment_milestone(count) is expected


@pytest.mark.parametrize("count", [1, 3, 6, 15])
def test_unmarked_unfoldered_chat_is_eligible_at_any_milestone(count):
    assert fa.can_auto_assign_folder(None, {}, count, "m") is True


def test_unmarked_chat_already_in_a_folder_counts_as_manual():
    assert fa.can_auto_assign_folder("f-1", {}, 1, "m") is False


def test_manual_marker_blocks_forever():
    meta = {"folder_assignment": {"source": "manual", "evaluations": 0}}
    for count in (1, 3, 6, 9, 30):
        assert fa.can_auto_assign_folder(None, meta, count, "m") is False
        assert fa.can_auto_assign_folder("f-1", meta, count, "m") is False


def test_auto_marker_allows_correction_until_budget_is_spent():
    two = {"folder_assignment": {"source": "auto", "evaluations": 2, "last_user_message_count": 3}}
    three = {"folder_assignment": {"source": "auto", "evaluations": 3, "last_user_message_count": 6}}
    assert fa.can_auto_assign_folder("f-1", two, 6, "m6") is True
    assert fa.can_auto_assign_folder("f-1", three, 9, "m9") is False


def test_auto_marker_dedups_same_message_and_stale_turn_counts():
    meta = {
        "folder_assignment": {
            "source": "auto",
            "evaluations": 1,
            "last_user_message_count": 3,
            "last_message_id": "assistant-3",
        }
    }
    assert fa.can_auto_assign_folder(None, meta, 3, "assistant-3") is False
    assert fa.can_auto_assign_folder(None, meta, 3, "assistant-3-regenerated") is False
    assert fa.can_auto_assign_folder(None, meta, 6, "assistant-6") is True


def test_unknown_marker_source_is_left_alone():
    assert fa.can_auto_assign_folder(None, {"folder_assignment": {"source": "weird"}}, 1, "m") is False


def test_old_chat_starts_at_its_next_milestone_and_gets_three_evaluations():
    """An unmarked legacy chat resumed at turn 14 is evaluated at 15, 18 and 21,
    never at 24 — the same budget as a new chat's 1, 3, 6."""
    meta = {}
    assert fa.can_auto_assign_folder(None, meta, 14, "m14") is False
    evaluated_at = []
    for count in range(15, 31):
        if fa.can_auto_assign_folder(None, meta, count, f"m{count}"):
            evaluated_at.append(count)
            meta = {
                "folder_assignment": {
                    "source": "auto",
                    "evaluations": fa.get_evaluation_count(meta) + 1,
                    "last_user_message_count": count,
                    "last_message_id": f"m{count}",
                }
            }
    assert evaluated_at == [15, 18, 21]


####################
# Candidates, prompt, parsing
####################


def test_candidates_are_top_level_only_ordered_by_creation_with_description():
    folders = [
        _folder("f-2", "图片生成", description="出图", created_at=2),
        _folder("f-3", "子分组", parent_id="f-2", created_at=3),
        _folder("f-1", "服务器与 Hermes 运维", description="运维", created_at=1),
        _folder("f-4", "  ", created_at=4),
    ]
    assert fa.build_folder_candidates(folders) == [
        {"id": "f-1", "name": "服务器与 Hermes 运维", "description": "运维"},
        {"id": "f-2", "name": "图片生成", "description": "出图"},
    ]


def test_prompt_lists_folders_title_and_clipped_history():
    candidates = fa.build_folder_candidates(_preset_folders())
    messages = [
        {"role": "user", "content": "x" * 900},
        {
            "role": "assistant",
            "content": '<details type="reasoning">secret thinking</details>回答内容 ![img](data:image/png;base64,AAAA)',
        },
        {"role": "user", "content": [{"type": "text", "text": "第二个问题"}, {"type": "image_url", "image_url": {"url": "data:..."}}]},
    ]
    prompt = fa.folder_assignment_template(
        "F:\n{{FOLDER_OPTIONS}}\nT:{{CHAT_TITLE}}\nH:\n{{CHAT_HISTORY}}",
        candidates,
        "  Hermes 网关故障  ",
        messages,
    )
    assert "- 图片生成: 出图、写真、图解、图像模型调试与分辨率排查" in prompt
    assert "T:Hermes 网关故障" in prompt
    assert "USER: " + "x" * 500 + "…" in prompt
    assert "secret thinking" not in prompt
    assert "ASSISTANT: 回答内容" in prompt
    assert "USER: 第二个问题" in prompt
    assert "base64" not in prompt


def test_prompt_uses_placeholder_when_title_missing():
    assert fa.folder_assignment_template("{{CHAT_TITLE}}", [], None, []) == "(none)"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"folder": "图片生成"}', "f-4"),
        ('```json\n{ "folder": "HaloWebUI 开发" }\n```', "f-2"),
        ('{"folder": null}', None),
        ('{"folder": "none"}', None),
        ("图片生成", "f-4"),
        ("halowebui 开发", "f-2"),
        ("null", None),
        ("", None),
        ("不归类", None),
        ('{"folder": "其他"}', None),
        ('{"folder": "图片"}', None),
        ('{"title": "图片生成"}', None),
        ('{"folder": ["图片生成"]}', None),
        ("这个对话应该放到 图片生成 分组", None),
    ],
)
def test_parse_folder_choice_only_accepts_exact_existing_names(text, expected):
    candidates = fa.build_folder_candidates(_preset_folders())
    choice = fa.parse_folder_choice(text, candidates)
    assert (choice["id"] if choice else None) == expected


def test_parse_folder_choice_rejects_ambiguous_case_insensitive_matches():
    candidates = [
        {"id": "a", "name": "Ops", "description": ""},
        {"id": "b", "name": "OPS", "description": ""},
    ]
    assert fa.parse_folder_choice('{"folder": "ops"}', candidates) is None
    assert fa.parse_folder_choice('{"folder": "OPS"}', candidates)["id"] == "b"


def test_parse_folder_choice_cannot_reach_another_users_folder():
    mine = fa.build_folder_candidates([_folder("mine", "图片生成")])
    theirs = fa.build_folder_candidates([_folder("theirs", "资讯与热点", user_id="user-2")])
    assert fa.parse_folder_choice('{"folder": "资讯与热点"}', mine) is None
    assert fa.parse_folder_choice('{"folder": "资讯与热点"}', theirs)["id"] == "theirs"


def test_parse_completion_text_handles_list_content_and_bad_shapes():
    assert fa.parse_completion_text({"choices": [{"message": {"content": [{"type": "text", "text": " hi "}]}}]}) == "hi"
    assert fa.parse_completion_text({"choices": []}) == ""
    assert fa.parse_completion_text(None) == ""
    assert fa.parse_completion_text("nope") == ""


####################
# Default folders (once per user)
####################


def test_presets_are_created_once_for_a_user_without_folders():
    deps, state = make_deps(chat=_chat())

    created = asyncio.run(fa.ensure_default_folders("user-1", deps))

    assert created == len(fa.DEFAULT_FOLDER_PRESETS) == 6
    assert [folder.name for folder in state["inserted"]] == [preset["name"] for preset in fa.DEFAULT_FOLDER_PRESETS]
    assert state["inserted"][0].meta["description"] == fa.DEFAULT_FOLDER_PRESETS[0]["description"]
    assert state["inserted"][0].meta["auto_assignment"]["preset"] == "ops"
    marker = state["info"][fa.USER_INFO_KEY]
    assert marker["presets_created"] == 6
    assert marker["presets_initialized_at"] > 0

    assert asyncio.run(fa.ensure_default_folders("user-1", deps)) == 0
    assert len(state["inserted"]) == 6


def test_presets_are_not_created_when_user_already_has_folders():
    deps, state = make_deps(chat=_chat(), folders=[_folder("own", "我的分组")])

    assert asyncio.run(fa.ensure_default_folders("user-1", deps)) == 0
    assert state["inserted"] == []
    assert state["info"][fa.USER_INFO_KEY]["presets_created"] == 0


def test_deleted_presets_are_never_recreated():
    deps, state = make_deps(
        chat=_chat(),
        user_info={fa.USER_INFO_KEY: {"presets_initialized_at": 1, "presets_created": 6, "version": 1}},
    )

    assert asyncio.run(fa.ensure_default_folders("user-1", deps)) == 0
    assert state["inserted"] == []


def test_preset_initialisation_is_deduplicated_under_concurrency():
    deps, state = make_deps(chat=_chat())

    async def scenario():
        lock = fa._INIT_LOCKS.setdefault("user-1", asyncio.Lock())
        await lock.acquire()
        tasks = [asyncio.create_task(fa.ensure_default_folders("user-1", deps)) for _ in range(4)]
        await asyncio.sleep(0)  # let every task pass the unlocked marker check
        lock.release()
        return await asyncio.gather(*tasks)

    results = asyncio.run(scenario())
    fa._INIT_LOCKS.pop("user-1", None)

    assert sorted(results) == [0, 0, 0, 6]
    assert len(state["inserted"]) == 6


def test_presets_are_isolated_per_user():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders("user-2"))

    assert asyncio.run(fa.ensure_default_folders("user-1", deps)) == 6
    assert all(folder.user_id == "user-1" for folder in state["inserted"])


####################
# Orchestration
####################


def test_first_evaluation_creates_presets_and_moves_the_chat():
    deps, state = make_deps(chat=_chat(), model_answer='{"folder": "服务器与 Hermes 运维"}')

    result = _run(deps)

    assert result.status == "assigned" and result.changed is True
    assert result.folder_name == "服务器与 Hermes 运维"
    assert result.presets_created == 6
    assert state["chat"].folder_id == result.folder_id == state["inserted"][0].id
    assignment = state["chat"].meta["folder_assignment"]
    assert assignment == {
        "source": "auto",
        "evaluations": 1,
        "last_user_message_count": 1,
        "last_message_id": "assistant-1",
        "folder_id": result.folder_id,
    }

    payload = state["calls"][0]
    assert payload["model"] == "gpt-5"
    assert payload["chat_id"] == "chat-1"
    assert payload["title"] == "Automatic title"
    assert [folder["name"] for folder in payload["folders"]] == [preset["name"] for preset in fa.DEFAULT_FOLDER_PRESETS]
    assert payload["folders"][3]["description"].startswith("出图")
    assert "require_external_task_model" not in payload


def test_disabled_feature_does_nothing():
    deps, state = make_deps(chat=_chat(), model_answer='{"folder": "图片生成"}', enabled=False)

    assert _run(deps).status == "disabled"
    assert state["calls"] == [] and state["commits"] == [] and state["inserted"] == []


def test_ineligible_chat_skips_model_and_presets():
    deps, state = make_deps(chat=_chat(folder_id="somewhere"), model_answer='{"folder": "图片生成"}')

    assert _run(deps).status == "ineligible"
    assert state["calls"] == [] and state["commits"] == [] and state["inserted"] == []


def test_null_answer_counts_but_never_moves():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer='{"folder": null}')

    result = _run(deps)

    assert result.status == "no_match" and result.changed is False
    assert state["chat"].folder_id is None
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 1
    assert state["chat"].meta["folder_assignment"]["source"] == "auto"


def test_model_error_counts_and_leaves_chat_in_place():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_error=RuntimeError("upstream 502"))

    result = _run(deps)

    assert result.status == "error" and "502" in result.detail
    assert state["chat"].folder_id is None
    assert state["commits"][-1]["evaluations"] == 1


def test_model_timeout_counts_and_leaves_chat_in_place():
    async def slow(_payload):
        await asyncio.sleep(0.5)
        return {"choices": [{"message": {"content": '{"folder": "图片生成"}'}}]}

    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer=slow, timeout=0.01)

    result = _run(deps)

    assert result.status == "timeout"
    assert state["chat"].folder_id is None
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 1


def test_bad_completion_shape_counts_as_empty():
    async def weird(_payload):
        return {"detail": "External task model required", "skipped": True}

    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer=weird)

    assert _run(deps).status == "empty"
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 1


def test_unknown_or_invented_folder_is_ignored():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer='{"folder": "新建一个分组"}')

    assert _run(deps).status == "no_match"
    assert state["chat"].folder_id is None
    assert state["inserted"] == []


def test_candidate_deleted_while_model_was_thinking_is_not_applied():
    deps, state = make_deps(
        chat=_chat(),
        folders=_preset_folders(),
        model_answer='{"folder": "图片生成"}',
        get_folder_override=lambda _folder_id, _user_id: None,
    )

    result = _run(deps)

    assert result.status == "candidate_gone"
    assert state["chat"].folder_id is None
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 1


def test_folder_capacity_limit_is_respected():
    deps, state = make_deps(
        chat=_chat(),
        folders=_preset_folders(),
        model_answer='{"folder": "图片生成"}',
        max_item_count=2,
        folder_counts={"f-4": 2},
    )

    assert _run(deps).status == "folder_full"
    assert state["chat"].folder_id is None


def test_manual_move_during_model_call_wins():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders())

    async def move_manually_then_answer(_payload):
        state["chat"].folder_id = "f-6"
        state["chat"].meta = {"folder_assignment": {"source": "manual", "folder_id": "f-6"}}
        return {"choices": [{"message": {"content": '{"folder": "图片生成"}'}}]}

    deps.call_model = move_manually_then_answer

    result = _run(deps)

    assert result.status == "skipped_manual" and result.changed is False
    assert state["chat"].folder_id == "f-6"
    assert state["chat"].meta["folder_assignment"]["source"] == "manual"
    assert state["commits"] == []


def test_auto_assignment_can_be_corrected_until_budget_is_spent():
    chat = _chat(
        folder_id="f-3",
        meta={
            "keep": "me",
            "title_generation": {"auto_generated": True},
            "folder_assignment": {"source": "auto", "evaluations": 1, "last_user_message_count": 1, "last_message_id": "assistant-1", "folder_id": "f-3"},
        },
    )
    deps, state = make_deps(chat=chat, folders=_preset_folders(), model_answer='{"folder": "HaloWebUI 开发"}')

    result = _run(deps, count=3, message_id="assistant-3")

    assert result.status == "assigned" and state["chat"].folder_id == "f-2"
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 2
    assert state["chat"].meta["keep"] == "me"
    assert state["chat"].meta["title_generation"] == {"auto_generated": True}

    deps.call_model = make_deps(chat=chat, model_answer='{"folder": null}')[0].call_model
    result = _run(deps, count=6, message_id="assistant-6")
    assert result.status == "no_match" and state["chat"].folder_id == "f-2"
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 3

    result = _run(deps, count=9, message_id="assistant-9")
    assert result.status == "ineligible"


def test_same_folder_answer_is_recorded_as_unchanged():
    chat = _chat(folder_id="f-4", meta={"folder_assignment": {"source": "auto", "evaluations": 1, "last_user_message_count": 1}})
    deps, state = make_deps(chat=chat, folders=_preset_folders(), model_answer='{"folder": "图片生成"}')

    result = _run(deps, count=3, message_id="assistant-3")

    assert result.status == "unchanged" and result.changed is False
    assert state["chat"].folder_id == "f-4"
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 2


def test_duplicate_request_for_same_message_is_idempotent():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer='{"folder": "图片生成"}')

    first = _run(deps)
    second = _run(deps)

    assert first.status == "assigned"
    assert second.status == "ineligible"
    assert len(state["calls"]) == 1


def test_no_candidates_after_user_deleted_everything_counts_without_model_call():
    deps, state = make_deps(
        chat=_chat(),
        user_info={fa.USER_INFO_KEY: {"presets_initialized_at": 1, "presets_created": 6, "version": 1}},
        model_answer='{"folder": "图片生成"}',
    )

    result = _run(deps)

    assert result.status == "no_candidates"
    assert state["calls"] == [] and state["inserted"] == []
    assert state["chat"].meta["folder_assignment"]["evaluations"] == 1


def test_image_and_discussion_chats_pass_the_external_task_model_flag():
    deps, state = make_deps(chat=_chat(), folders=_preset_folders(), model_answer='{"folder": "图片生成"}')

    result = _run(deps, require_external=True)

    assert result.status == "assigned"
    assert state["calls"][0]["require_external_task_model"] is True


def test_chat_of_another_user_is_not_touched():
    deps, state = make_deps(chat=_chat(user_id="user-2"), folders=_preset_folders(), model_answer='{"folder": "图片生成"}')

    assert _run(deps).status == "missing"
    assert state["calls"] == [] and state["commits"] == []


####################
# Persistence (chats model)
####################


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _model, _id):
        return self.row

    def query(self, _model):
        row = self.row

        class Query:
            def filter(self, *_args):
                return self

            def with_for_update(self):
                return self

            def first(self):
                return row

        return Query()

    def commit(self):
        self.commits += 1

    def refresh(self, _row):
        return None


def _install_db(monkeypatch, row):
    db = _FakeDb(row)
    monkeypatch.setattr(chats_mod, "get_db", lambda: db)
    monkeypatch.setattr(chats_mod, "flag_modified", lambda *_a, **_k: None)
    return db


def test_manual_move_marks_chat_manual_and_keeps_other_meta(monkeypatch):
    table = chats_mod.ChatTable()
    row = _chat(meta={"keep": 1, "folder_assignment": {"source": "auto", "evaluations": 2, "folder_id": "f-1"}})
    db = _install_db(monkeypatch, row)
    monkeypatch.setattr(table, "_next_user_chat_timestamp", lambda _db, _user_id: 101)

    result = table.update_chat_folder_id_by_id_and_user_id("chat-1", "user-1", "f-2")

    assert result is not None and result.folder_id == "f-2"
    assert row.meta["keep"] == 1
    assert row.meta["folder_assignment"]["source"] == "manual"
    assert row.meta["folder_assignment"]["folder_id"] == "f-2"
    assert row.meta["folder_assignment"]["evaluations"] == 2
    assert db.commits == 1


def test_manual_remove_from_folder_also_marks_manual(monkeypatch):
    table = chats_mod.ChatTable()
    row = _chat(folder_id="f-1", meta={})
    _install_db(monkeypatch, row)
    monkeypatch.setattr(table, "_next_user_chat_timestamp", lambda _db, _user_id: 101)

    result = table.update_chat_folder_id_by_id_and_user_id("chat-1", "user-1", None)

    assert result is not None and result.folder_id is None
    assert row.meta["folder_assignment"]["source"] == "manual"
    assert fa.can_auto_assign_folder(None, row.meta, 3, "m") is False


def test_manual_move_refuses_other_users_chat(monkeypatch):
    table = chats_mod.ChatTable()
    row = _chat(user_id="user-2")
    db = _install_db(monkeypatch, row)

    assert table.update_chat_folder_id_by_id_and_user_id("chat-1", "user-1", "f-2") is None
    assert row.folder_id is None and db.commits == 0


def test_auto_commit_writes_folder_and_marker_without_touching_other_meta(monkeypatch):
    table = chats_mod.ChatTable()
    row = _chat(meta={"title_generation": {"auto_generated": True, "last_user_message_count": 1}, "tags": ["x"]})
    db = _install_db(monkeypatch, row)

    result = table.update_chat_folder_assignment_by_id_and_user_id(
        "chat-1", "user-1", "f-4", apply_folder=True, evaluations=1, last_user_message_count=1, last_message_id="assistant-1"
    )

    assert result is not None and row.folder_id == "f-4"
    assert row.pinned is False and row.updated_at == 100
    assert row.meta["title_generation"] == {"auto_generated": True, "last_user_message_count": 1}
    assert row.meta["tags"] == ["x"]
    assignment = row.meta["folder_assignment"]
    assert assignment["source"] == "auto" and assignment["evaluations"] == 1
    assert assignment["folder_id"] == "f-4" and assignment["last_message_id"] == "assistant-1"
    assert db.commits == 1


def test_auto_commit_without_apply_only_counts(monkeypatch):
    table = chats_mod.ChatTable()
    row = _chat(folder_id="f-1", meta={"folder_assignment": {"source": "auto", "evaluations": 1, "folder_id": "f-1"}})
    _install_db(monkeypatch, row)

    result = table.update_chat_folder_assignment_by_id_and_user_id(
        "chat-1", "user-1", None, apply_folder=False, evaluations=2, last_user_message_count=3, last_message_id="assistant-3"
    )

    assert result is not None and row.folder_id == "f-1"
    assert row.meta["folder_assignment"]["folder_id"] == "f-1"
    assert row.meta["folder_assignment"]["evaluations"] == 2


def test_auto_commit_respects_manual_marker_and_legacy_folders(monkeypatch):
    table = chats_mod.ChatTable()

    manual = _chat(folder_id="f-1", meta={"folder_assignment": {"source": "manual"}})
    db = _install_db(monkeypatch, manual)
    assert table.update_chat_folder_assignment_by_id_and_user_id("chat-1", "user-1", "f-2", apply_folder=True, evaluations=1) is None
    assert manual.folder_id == "f-1" and db.commits == 0

    legacy = _chat(folder_id="f-1", meta={})
    db = _install_db(monkeypatch, legacy)
    assert table.update_chat_folder_assignment_by_id_and_user_id("chat-1", "user-1", "f-2", apply_folder=True, evaluations=1) is None
    assert legacy.folder_id == "f-1" and legacy.meta == {} and db.commits == 0

    other = _chat(user_id="user-2")
    db = _install_db(monkeypatch, other)
    assert table.update_chat_folder_assignment_by_id_and_user_id("chat-1", "user-1", "f-2", apply_folder=True, evaluations=1) is None
    assert other.folder_id is None and db.commits == 0
