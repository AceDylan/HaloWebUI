"""A folder's instructions (分组指令) reach every completion of a chat filed in
it: outer folders first, the person's own system prompt kept after them, and
nothing for chats outside a folder, temporary chats or other people's folders."""

import uuid

from open_webui.models.chats import ChatForm, Chats
from open_webui.models.folders import Folders
from open_webui.utils.folder_instructions import (
    apply_folder_instructions_to_body,
    folder_instructions_for_chat,
)


def _user() -> str:
    # The unit DB persists between runs: fresh ids keep earlier runs' rows out.
    return f"folder-instr-{uuid.uuid4().hex[:8]}"


def _folder(user_id: str, name: str, prompt: str | None, parent_id: str | None = None) -> str:
    folder = Folders.insert_new_folder(user_id, name, parent_id)
    assert folder is not None
    if prompt is not None:
        Folders.update_folder_system_prompt_by_id_and_user_id(folder.id, user_id, prompt)
    return folder.id


def _chat(user_id: str, folder_id: str | None) -> str:
    chat = Chats.insert_new_chat(user_id, ChatForm(chat={"title": "t"}))
    assert chat is not None
    if folder_id:
        Chats.update_chat_folder_id_by_id_and_user_id(chat.id, user_id, folder_id)
    return chat.id


def test_chat_in_a_sub_folder_reads_outer_instructions_first():
    user = _user()
    outer = _folder(user, "HaloWebUI", "Project: HaloWebUI.")
    inner = _folder(user, "Frontend", "Svelte 4 only.", parent_id=outer)
    chat_id = _chat(user, inner)

    assert folder_instructions_for_chat(chat_id, user) == "Project: HaloWebUI.\n\nSvelte 4 only."


def test_instructions_go_before_the_persons_own_system_prompt():
    user = _user()
    chat_id = _chat(user, _folder(user, "Ops", "Servers run Debian."))
    form_data = {
        "messages": [
            {"role": "system", "content": "Answer in Chinese."},
            {"role": "user", "content": "hi"},
        ]
    }

    apply_folder_instructions_to_body(form_data, {"chat_id": chat_id}, user)

    assert form_data["messages"][0] == {
        "role": "system",
        "content": "Servers run Debian.\nAnswer in Chinese.",
    }
    assert len(form_data["messages"]) == 2


def test_nothing_changes_without_instructions():
    user = _user()
    plain = _chat(user, None)
    empty_folder = _chat(user, _folder(user, "Empty", "   "))
    for chat_id in (plain, empty_folder, "local:abc", None):
        form_data = {"messages": [{"role": "user", "content": "hi"}]}
        apply_folder_instructions_to_body(form_data, {"chat_id": chat_id}, user)
        assert form_data["messages"] == [{"role": "user", "content": "hi"}]


def test_another_persons_chat_does_not_read_the_folder():
    owner = _user()
    chat_id = _chat(owner, _folder(owner, "Private", "secret context"))

    assert folder_instructions_for_chat(chat_id, _user()) is None
