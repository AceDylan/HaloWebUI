import json
import logging
from urllib.parse import parse_qsl, urlparse, urlunparse

import requests
from open_webui.config import WEBUI_FAVICON_URL
from open_webui.env import SRC_LOG_LEVELS, VERSION

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["WEBHOOK"])

# Telegram rejects sendMessage bodies longer than this.
TELEGRAM_MESSAGE_MAX_CHARS = 4096


def _telegram_target(url: str):
    """(post_url, chat_id, thread_id) for a Telegram Bot API webhook URL.

    Configured as https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>
    (optionally &message_thread_id=<topic>). The parameters move into the JSON
    body so Telegram sees them exactly once.
    """
    parsed = urlparse(url)
    if not (parsed.netloc == "api.telegram.org" and parsed.path.startswith("/bot")):
        return None
    query = dict(parse_qsl(parsed.query))
    post_url = urlunparse(parsed._replace(query="", fragment=""))
    return post_url, query.get("chat_id"), query.get("message_thread_id")


def post_webhook(name: str, url: str, message: str, event_data: dict) -> bool:
    try:
        log.debug(f"post_webhook: {url}, {message}, {event_data}")
        payload = {}
        telegram = _telegram_target(url)

        # Telegram Bot API (sendMessage)
        if telegram is not None:
            url, chat_id, thread_id = telegram
            if not chat_id:
                log.error("post_webhook: Telegram webhook URL needs ?chat_id=<id>")
                return False
            payload = {
                "chat_id": chat_id,
                "text": (
                    message
                    if len(message) <= TELEGRAM_MESSAGE_MAX_CHARS
                    else f"{message[: TELEGRAM_MESSAGE_MAX_CHARS - 20]}... (truncated)"
                ),
                "disable_web_page_preview": True,
            }
            if thread_id:
                payload["message_thread_id"] = thread_id
        # Slack and Google Chat Webhooks
        elif "https://hooks.slack.com" in url or "https://chat.googleapis.com" in url:
            payload["text"] = message
        # Discord Webhooks
        elif "https://discord.com/api/webhooks" in url:
            payload["content"] = (
                message
                if len(message) < 2000
                else f"{message[: 2000 - 20]}... (truncated)"
            )
        # Microsoft Teams Webhooks
        elif "webhook.office.com" in url:
            action = event_data.get("action", "undefined")
            raw_user = event_data.get("user")
            if isinstance(raw_user, str):
                user_dict = json.loads(raw_user)
            elif isinstance(raw_user, dict):
                user_dict = raw_user
            else:
                user_dict = {}
            facts = [
                {"name": name, "value": value}
                for name, value in user_dict.items()
            ]
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": "0076D7",
                "summary": message,
                "sections": [
                    {
                        "activityTitle": message,
                        "activitySubtitle": f"{name} ({VERSION}) - {action}",
                        "activityImage": WEBUI_FAVICON_URL,
                        "facts": facts,
                        "markdown": True,
                    }
                ],
            }
        # Default Payload
        else:
            payload = {**event_data}

        log.debug(f"payload: {payload}")
        r = requests.post(url, json=payload)
        r.raise_for_status()
        log.debug(f"r.text: {r.text}")
        return True
    except Exception as e:
        log.exception(e)
        return False
