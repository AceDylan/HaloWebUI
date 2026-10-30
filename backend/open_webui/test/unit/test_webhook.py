from unittest.mock import MagicMock, patch

from open_webui.utils import webhook


def _post_ok():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = "{}"
    return response


def test_telegram_webhook_posts_chat_id_and_text_without_the_query():
    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        ok = webhook.post_webhook(
            "HaloWebUI",
            "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=5231512201",
            "title - https://x/c/1\n\nbody",
            {"action": "chat", "message": "body", "title": "title", "url": "https://x/c/1"},
        )

    assert ok is True
    post.assert_called_once()
    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload == {
        "chat_id": "5231512201",
        "text": "title - https://x/c/1\n\nbody",
        "disable_web_page_preview": True,
    }


def test_telegram_webhook_sends_a_long_push_whole_in_several_messages():
    paragraphs = [f"第{i}段 " + "字" * 900 for i in range(9)]
    message = "title - https://x/c/1\n\n" + "\n\n".join(paragraphs)
    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        webhook.post_webhook(
            "HaloWebUI",
            "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=-100&message_thread_id=7",
            message,
            {},
        )

    payloads = [c.kwargs["json"] for c in post.call_args_list]
    assert len(payloads) == 3
    assert all(p["message_thread_id"] == "7" and p["chat_id"] == "-100" for p in payloads)
    assert all(len(p["text"]) <= webhook.TELEGRAM_CHUNK_CHARS for p in payloads)
    assert payloads[0]["text"].startswith("title - https://x/c/1")
    # nothing lost, cut between paragraphs
    assert "\n\n".join(p["text"] for p in payloads) == message


def test_telegram_chunks_cut_a_very_long_line_and_stop_at_the_message_cap():
    chunks = webhook.telegram_chunks("x" * (webhook.TELEGRAM_CHUNK_CHARS * 2 + 5))
    assert [len(c) for c in chunks] == [webhook.TELEGRAM_CHUNK_CHARS, webhook.TELEGRAM_CHUNK_CHARS, 5]
    many = webhook.telegram_chunks("y" * (webhook.TELEGRAM_CHUNK_CHARS * (webhook.TELEGRAM_MAX_MESSAGES + 3)))
    assert len(many) == webhook.TELEGRAM_MAX_MESSAGES
    assert many[-1].endswith("后面的在网页看）") and all(len(c) <= webhook.TELEGRAM_CHUNK_CHARS for c in many)
    assert webhook.telegram_chunks("短") == ["短"]


def test_telegram_webhook_without_chat_id_fails_before_posting():
    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        ok = webhook.post_webhook(
            "HaloWebUI", "https://api.telegram.org/bot123:ABC/sendMessage", "m", {}
        )

    assert ok is False
    post.assert_not_called()


def test_other_targets_keep_the_default_payload():
    event = {"action": "chat", "message": "body", "title": "t", "url": "https://x/c/1"}
    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        webhook.post_webhook("HaloWebUI", "https://example.com/hook?x=1", "m", event)

    assert post.call_args.args[0] == "https://example.com/hook?x=1"
    assert post.call_args.kwargs["json"] == event

    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        webhook.post_webhook(
            "HaloWebUI", "https://discord.com/api/webhooks/1/abc", "d" * 2500, event
        )

    assert post.call_args.kwargs["json"]["content"].endswith("... (truncated)")


def test_telegram_push_attaches_what_the_run_made(tmp_path):
    video = tmp_path / "长征.mp4"
    video.write_bytes(b"v" * 10)
    big = tmp_path / "big.mp4"
    big.write_bytes(b"")
    media = [
        {"path": str(video), "name": "长征.mp4", "content_type": "video/mp4"},
        {"path": str(tmp_path / "gone.png"), "name": "gone.png", "content_type": "image/png"},
        {"path": str(big), "name": "big.mp4", "content_type": "video/mp4"},
    ]
    sent = []

    def post(url, **kwargs):
        if "files" in kwargs:
            field, (name, handle, content_type) = next(iter(kwargs["files"].items()))
            sent.append((url, field, name, handle.read(), content_type, kwargs["data"]))
        return _post_ok()

    with patch.object(webhook, "TELEGRAM_UPLOAD_MAX_BYTES", 5), patch.object(
        webhook.requests, "post", side_effect=post
    ):
        video.write_bytes(b"v" * 5)
        big.write_bytes(b"b" * 6)
        ok = webhook.post_webhook(
            "HaloWebUI",
            "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=9&message_thread_id=7",
            "done",
            {},
            media,
        )

    assert ok is True
    assert sent == [
        (
            "https://api.telegram.org/bot123:ABC/sendVideo",
            "video",
            "长征.mp4",
            b"v" * 5,
            "video/mp4",
            {"chat_id": "9", "message_thread_id": "7"},
        )
    ]
    assert webhook._telegram_media_method("image/png", 100) == ("sendPhoto", "photo")
    assert webhook._telegram_media_method("image/png", 11 * 1024 * 1024) == ("sendDocument", "document")
    assert webhook._telegram_media_method("audio/mpeg", 1) == ("sendAudio", "audio")
    assert webhook._telegram_media_method("application/pdf", 1) == ("sendDocument", "document")
