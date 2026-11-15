"""结论卡片 for the modes whose result is not an ordinary chat reply (精答, 讨论台, 协作台): the same
HTML card an ordinary Web Chat reply gets (AGY designs it from the finished text, the chat frame
draws it with the hv-* design kit — utils/html_visual_prompt.py).

The card is made on request (「生成 HTML 卡片」 on the result, or under its reply in the chat), like
the picture (utils/mode_illustrate.py); nothing designs one on its own. The run keeps it
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


async def design(text: str, *, allow_brief: bool = False) -> dict:
    """The card for a finished result: ``{"status": "ready", "html"}``, ``{"status": "failed",
    "reason"}``, or ``{"status": "skipped"}`` (a few plain sentences need no card, unless
    ``allow_brief``: the person asked for this one). Never raises but for cancellation."""
    from open_webui.utils.html_visual_prompt import is_brief_plain_reply

    text = _ILLUSTRATION_RE.sub("", text or "").strip()
    if not text or (not allow_brief and is_brief_plain_reply(text)):
        return {"status": "skipped"}
    _, entry = await design_merged(text, allow_brief=allow_brief)
    return entry


async def design_merged(text: str, *, allow_brief: bool = True) -> tuple[str, dict]:
    """*text* with its card merged in (any HTML the model wrote replaced by AGY's), and the card
    entry (``ready`` with ``html``, else ``failed`` with ``reason``); *text* unchanged when it
    failed. Never raises but for cancellation."""
    from open_webui.utils.html_visual_prompt import (
        HTML_VISUAL_AGY_HTML_METADATA_KEY,
        HTML_VISUAL_FEATURE_KEY,
        HTML_VISUAL_SURFACE_KEY,
        HTML_VISUAL_WEB_SURFACE,
        design_html_visual_artifact_with_agy,
    )

    started = now_ms()
    metadata: dict[str, Any] = {
        "server_surface": HTML_VISUAL_WEB_SURFACE,
        "features": {HTML_VISUAL_FEATURE_KEY: "force", HTML_VISUAL_SURFACE_KEY: HTML_VISUAL_WEB_SURFACE},
    }
    try:
        merged = await design_html_visual_artifact_with_agy(text, metadata, allow_brief=allow_brief)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — the text stays as it is
        log.warning("mode card: design failed: %s", exc)
        return text, {"status": "failed", "reason": type(exc).__name__, "startedAt": started, "endedAt": now_ms()}
    record = metadata.get(HTML_VISUAL_AGY_HTML_METADATA_KEY) or {}
    ended = now_ms()
    if record.get("status") == "success" and isinstance(record.get("html"), str):
        return merged, {"status": "ready", "html": record["html"], "startedAt": started, "endedAt": ended}
    reason = str(record.get("reason") or record.get("status") or "unknown")[:80]
    return text, {"status": "failed", "reason": reason, "startedAt": started, "endedAt": ended}


async def make(text: str, on_change, *, allow_brief: bool = False) -> Optional[dict]:
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
    entry = await design(text, allow_brief=allow_brief)
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


# A card still "designing" after this was lost (a restart): it may be asked for again.
STALE_MS = 6 * 60 * 1000


def busy(card: Optional[dict]) -> bool:
    """Whether this card is being designed right now."""
    card = card if isinstance(card, dict) else {}
    return card.get("status") == "designing" and now_ms() - int(card.get("startedAt") or 0) < STALE_MS


async def settle() -> None:
    """Wait for the background jobs started so far (tests)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)
