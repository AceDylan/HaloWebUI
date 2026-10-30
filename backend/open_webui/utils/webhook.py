import json
import logging
import os
from urllib.parse import parse_qsl, urlparse, urlunparse

import requests
from open_webui.config import WEBUI_FAVICON_URL
from open_webui.env import SRC_LOG_LEVELS, VERSION

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["WEBHOOK"])

# Telegram rejects sendMessage bodies longer than this.
TELEGRAM_MESSAGE_MAX_CHARS = 4096
# A longer push goes out as several messages of at most this many characters (Telegram counts
# UTF-16 units; this leaves room for emoji), split at line breaks where it can.
TELEGRAM_CHUNK_CHARS = 3900
# Past this many messages the rest of a push is left to the page its link opens.
TELEGRAM_MAX_MESSAGES = 10
# Bot API upload limits: any file 50MB, a photo 10MB (bigger pictures go as documents).
TELEGRAM_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024


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


def _telegram_media_method(content_type: str, size: int) -> tuple[str, str]:
    content_type = (content_type or "").lower()
    if content_type.startswith("video/"):
        return "sendVideo", "video"
    if content_type.startswith("audio/"):
        return "sendAudio", "audio"
    if (
        content_type in ("image/png", "image/jpeg", "image/webp")
        and size <= TELEGRAM_PHOTO_MAX_BYTES
    ):
        return "sendPhoto", "photo"
    return "sendDocument", "document"


def _send_telegram_media(post_url: str, chat_id, thread_id, media: list) -> None:
    """Attach files after a Telegram push (sendVideo / sendAudio / sendPhoto /
    sendDocument). A file that is gone, too big or refused is skipped; the
    message already points at the chat. Never logs the URL: it carries the token."""
    api_base = post_url.rsplit("/", 1)[0]
    for item in media or []:
        path = item.get("path") or ""
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > TELEGRAM_UPLOAD_MAX_BYTES:
            log.info(f"post_webhook: {item.get('name')} is over Telegram's 50MB, not attached")
            continue
        method, field = _telegram_media_method(item.get("content_type", ""), size)
        data = {"chat_id": chat_id}
        if thread_id:
            data["message_thread_id"] = thread_id
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    f"{api_base}/{method}",
                    data=data,
                    files={field: (item.get("name") or "file", handle, item.get("content_type") or None)},
                    timeout=300,
                )
            if not response.ok:
                log.warning(f"post_webhook: Telegram {method} failed with HTTP {response.status_code}")
        except Exception as e:
            log.warning(f"post_webhook: Telegram {method} failed: {type(e).__name__}")


def telegram_chunks(message: str) -> list[str]:
    """*message* in parts Telegram takes, at paragraph or line breaks where it can."""
    text = message or ""
    parts: list[str] = []
    while len(text) > TELEGRAM_CHUNK_CHARS:
        if len(parts) == TELEGRAM_MAX_MESSAGES - 1:
            text = text[: TELEGRAM_CHUNK_CHARS - 20].rstrip() + "\n…（后面的在网页看）"
            break
        cut = text.rfind("\n\n", 0, TELEGRAM_CHUNK_CHARS)
        if cut < TELEGRAM_CHUNK_CHARS // 2:
            cut = text.rfind("\n", 0, TELEGRAM_CHUNK_CHARS)
        if cut < TELEGRAM_CHUNK_CHARS // 2:
            cut = TELEGRAM_CHUNK_CHARS
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return [p for p in parts if p.strip()] or [text]


def post_webhook(
    name: str, url: str, message: str, event_data: dict, media: list | None = None
) -> bool:
    """*media* (``{"path", "name", "content_type"}``, Telegram only): files sent after
    the message, e.g. the video a Hermes run made."""
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
            chunks = telegram_chunks(message)
            payload = {
                "chat_id": chat_id,
                "text": chunks[0],
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
        if telegram is not None:
            # the rest of a long push, in order, as messages of their own
            for chunk in chunks[1:]:
                requests.post(url, json={**payload, "text": chunk}).raise_for_status()
        if telegram is not None and media:
            _send_telegram_media(url, payload["chat_id"], payload.get("message_thread_id"), media)
        return True
    except Exception as e:
        log.exception(e)
        return False
