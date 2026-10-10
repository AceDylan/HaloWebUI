import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.image_studio_record import (  # noqa: E402
    chat_image_studio_items,
    team_image_studio_item,
)


def _items(**overrides):
    kwargs = dict(
        chat_id="chat-1",
        message_id="msg-1",
        prompt="a lighthouse at dusk",
        options={"model": "gpt-image", "size": "1536x1024", "quality": "high", "n": 2},
        images=[
            {"url": "/api/v1/files/a/content"},
            {"url": "/api/v1/files/b/content"},
        ],
        completed_at_ms=61_000,
    )
    kwargs.update(overrides)
    return chat_image_studio_items(**kwargs)


def test_a_chat_generation_becomes_gallery_entries_only():
    forms = _items()

    # The history is the workbench's own runs: a chat adds to the gallery only.
    assert {form.kind for form in forms} == {"gallery"}
    assert [form.data["url"] for form in forms] == [
        "/api/v1/files/a/content",
        "/api/v1/files/b/content",
    ]
    assert forms[0].data["chatId"] == "chat-1"
    assert forms[0].data["size"] == "1536x1024"
    assert forms[0].data["createdAt"] == 61_000
    assert forms[0].id == forms[0].data["id"] == "gallery_chat_msg-1_0"


def test_the_same_reply_overwrites_its_entries_instead_of_adding_more():
    assert [form.id for form in _items()] == [form.id for form in _items()]


def test_nothing_for_temporary_chats_or_runs_without_an_image():
    assert _items(chat_id="local:abc") == []
    assert _items(chat_id=None) == []
    assert _items(images=[]) == []
    assert _items(images=[{"url": ""}, "x"]) == []


def test_an_automatic_size_is_saved_as_auto():
    forms = _items(options={"model": "gpt-image"})
    assert forms[0].data["size"] == "auto"


def test_a_team_result_picture_is_one_gallery_entry_linked_to_its_team():
    form = team_image_studio_item(
        team_id="team-1",
        picture_id="images/result-2.png@1700000000",
        url="/api/v1/files/f/content",
        prompt="手绘信息图",
        model="gpt-image",
        created_at_ms=1_700_000_000_000,
    )
    assert form.kind == "gallery"
    assert form.id == form.data["id"] == "gallery_team_team-1_imagesresult-2png1700000000"
    assert form.data["teamId"] == "team-1" and "chatId" not in form.data
    assert form.data["url"] == "/api/v1/files/f/content"
    assert team_image_studio_item(
        team_id="team-1", picture_id="x", url="", prompt="", model="", created_at_ms=0
    ) is None
