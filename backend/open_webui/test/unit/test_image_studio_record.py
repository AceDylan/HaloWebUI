import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.image_studio_record import chat_image_studio_items  # noqa: E402


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
        source_urls=["/api/v1/files/src/content", "data:image/png;base64,AAAA"],
        started_at_ms=1_000,
        completed_at_ms=61_000,
    )
    kwargs.update(overrides)
    return chat_image_studio_items(**kwargs)


def test_a_chat_generation_becomes_gallery_entries_and_one_history_entry():
    forms = _items()
    gallery = [form for form in forms if form.kind == "gallery"]
    history = [form for form in forms if form.kind == "history"]

    assert [form.data["url"] for form in gallery] == [
        "/api/v1/files/a/content",
        "/api/v1/files/b/content",
    ]
    assert gallery[0].data["chatId"] == "chat-1"
    assert gallery[0].data["size"] == "1536x1024"
    assert gallery[0].id == gallery[0].data["id"] == "gallery_chat_msg-1_0"

    (entry,) = history
    assert entry.id == "history_chat_msg-1"
    assert entry.data["status"] == "success"
    assert entry.data["images"] == [form.data["url"] for form in gallery]
    assert (entry.data["createdAt"], entry.data["completedAt"]) == (1_000, 61_000)
    assert entry.data["parameters"] == {
        "modelId": "gpt-image",
        "size": "1536x1024",
        "quality": "high",
        "numberOfImages": 2,
        "references": ["/api/v1/files/src/content"],
        "origin": "chat",
        "chatId": "chat-1",
        "messageId": "msg-1",
    }


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
    assert "size" not in forms[-1].data["parameters"]


def test_references_are_addresses_the_studio_can_load():
    forms = _items(
        source_urls=[
            "openwebui-file://src",
            "/api/v1/files/src/content",
            "data:image/png;base64,AAAA",
            "/api/v1/files/other/content",
        ]
    )
    assert forms[-1].data["parameters"]["references"] == [
        "/api/v1/files/src/content",
        "/api/v1/files/other/content",
    ]
