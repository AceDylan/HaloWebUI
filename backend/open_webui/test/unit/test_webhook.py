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


def test_telegram_webhook_forwards_a_topic_and_caps_the_text():
    with patch.object(webhook.requests, "post", return_value=_post_ok()) as post:
        webhook.post_webhook(
            "HaloWebUI",
            "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=-100&message_thread_id=7",
            "x" * 5000,
            {},
        )

    payload = post.call_args.kwargs["json"]
    assert payload["message_thread_id"] == "7"
    assert len(payload["text"]) <= webhook.TELEGRAM_MESSAGE_MAX_CHARS
    assert payload["text"].endswith("... (truncated)")


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
