"""结论卡片 for the modes whose result is not an ordinary chat reply (精答, 讨论台, 协作台): the same
HTML card an ordinary Web Chat reply gets (AGY designs it from the finished text, the chat frame
draws it with the hv-* design kit — utils/html_visual_prompt.py).

The card is a step after the text, next to the picture (utils/mode_illustrate.py): the run keeps it
as ``card`` ({status: designing|ready|failed|skipped, html, ...}) and the chat's message gets it as
a fenced ````html block after the text. A chat in card mode shows the card, and the text's images
(the picture) above it; the text stays behind 「显示原文」, and is what the models read again.
HALO_MODES_HTML_CARD=0 turns it off.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

AUTO_ENV = "HALO_MODES_HTML_CARD"
# 协作台's picture block in its conclusion (hermes plugin illustrate.py): not text to design
_ILLUSTRATION_RE = re.compile(r"<!-- halo:illustration -->.*?<!-- /halo:illustration -->\n*", re.S)


def now_ms() -> int:
    return int(time.time() * 1000)


def enabled() -> bool:
    return os.environ.get(AUTO_ENV, "1") != "0"


def block(card: Optional[dict]) -> str:
    """The card as the chat's message carries it (a fenced html block), "" when there is none."""
    html = (card or {}).get("html") if (card or {}).get("status") == "ready" else None
    return f"````html\n{html}\n````" if isinstance(html, str) and html.strip() else ""


def with_card(markdown: str, card: Optional[dict]) -> str:
    """*markdown* with its ready card after it."""
    markdown = (markdown or "").rstrip()
    fence = block(card)
    if not fence or not markdown:
        return markdown
    return f"{markdown}\n\n{fence}"


async def design(text: str) -> dict:
    """The card for a finished result: ``{"status": "ready", "html"}``, ``{"status": "failed",
    "reason"}``, or ``{"status": "skipped"}`` (a few plain sentences need no card). Never raises
    but for cancellation."""
    from open_webui.utils.html_visual_prompt import (
        HTML_VISUAL_AGY_HTML_METADATA_KEY,
        HTML_VISUAL_FEATURE_KEY,
        HTML_VISUAL_SURFACE_KEY,
        HTML_VISUAL_WEB_SURFACE,
        design_html_visual_artifact_with_agy,
        is_brief_plain_reply,
    )

    text = _ILLUSTRATION_RE.sub("", text or "").strip()
    started = now_ms()
    if not text or is_brief_plain_reply(text):
        return {"status": "skipped"}
    metadata: dict[str, Any] = {
        "server_surface": HTML_VISUAL_WEB_SURFACE,
        "features": {HTML_VISUAL_FEATURE_KEY: "force", HTML_VISUAL_SURFACE_KEY: HTML_VISUAL_WEB_SURFACE},
    }
    try:
        await design_html_visual_artifact_with_agy(text, metadata)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — the text stays as it is
        log.warning("mode card: design failed: %s", exc)
        return {"status": "failed", "reason": type(exc).__name__, "endedAt": now_ms()}
    record = metadata.get(HTML_VISUAL_AGY_HTML_METADATA_KEY) or {}
    ended = now_ms()
    if record.get("status") == "success" and isinstance(record.get("html"), str):
        return {"status": "ready", "html": record["html"], "startedAt": started, "endedAt": ended}
    return {"status": "failed", "reason": str(record.get("reason") or record.get("status") or "unknown")[:80],
            "startedAt": started, "endedAt": ended}


async def make(text: str, on_change) -> Optional[dict]:
    """Design the card for *text*; ``on_change`` gets the card entry as it moves (designing, then
    ready / failed / skipped). Returns the last entry, None when cards are off."""
    if not enabled() or not (text or "").strip():
        return None

    async def change(entry: dict) -> None:
        try:
            await on_change(entry)
        except Exception:  # noqa: BLE001
            log.warning("mode card: could not record the card", exc_info=True)

    await change({"status": "designing", "startedAt": now_ms()})
    entry = await design(text)
    await change(entry)
    return entry


_background: set = set()


def later(job) -> None:
    """Run *job* on its own (the caller does not wait for the card)."""

    async def guarded() -> None:
        try:
            await job
        except Exception:  # noqa: BLE001
            log.exception("mode card: background job failed")

    task = asyncio.create_task(guarded())
    _background.add(task)
    task.add_done_callback(_background.discard)
