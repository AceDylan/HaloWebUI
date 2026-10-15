"""Files Hermes hands over in a reply or a runner report, shown where the chat shows text.

A reply or report names a file it made as ``MEDIA:<absolute path>`` (Hermes' own
convention, which the runners' protocol asks for too). This container cannot read
Hermes' paths, so each one is fetched from Hermes (``GET /v1/media``, local Hermes
patch), stored as one of the user's files, and the tag becomes what shows the file in
place (:func:`media_markdown`): a video or audio player, the picture, an HTML page's
preview, or a download link. The same Markdown renders in the reply and, in the HTML
card view, next to the card (frontend collectHtmlArtifactCompanionImages).
"""

import logging
import mimetypes
import os
import re
import tempfile
from typing import Awaitable, Callable, Optional
from urllib.parse import quote

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

# Same cap as Hermes' GET /v1/media.
MEDIA_FETCH_MAX_BYTES = 200 * 1024 * 1024
MEDIA_FETCH_TIMEOUT_SECONDS = 120
# A report that names more is listing files, not handing them over.
MEDIA_TAGS_MAX = 12

# ``MEDIA:/path``, ``MEDIA:`/path with spaces```, ``MEDIA:"/path"``; the whole tag may sit
# in backticks (runners write it as code despite being asked not to).
_MEDIA_TAG_RE = re.compile(
    r"`?MEDIA:[ \t]*(?:`([^`\n]+)`|\"([^\"\n]+)\"|'([^'\n]+)'|(/[^\s`\"'<>]+))`?"
)
_TRAILING_PUNCTUATION = ".,;:!?)]}。，；：！？）」』、"
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})", re.MULTILINE)

_VIDEO_STYLE = "max-width:100%;max-height:70vh;border-radius:12px;background:#000"
_AUDIO_STYLE = "width:100%;max-width:520px"


def media_kind(content_type: str, name: str = "") -> str:
    """image / video / audio / html / file."""
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(name or "")[0] or ""
    if content_type.startswith("image/") and content_type != "image/svg+xml":
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type == "text/html":
        return "html"
    return "file"


def _label(name: str) -> str:
    return re.sub(r"[\[\]\n]", " ", name or "").strip() or "文件"


def media_markdown(name: str, url: str, content_type: str) -> str:
    """How a stored file shows in a reply. Players and previews are HTML blocks wrapped in
    a div (a lone ``<video>`` line is not an HTML block to Markdown) set off by blank lines."""
    label = _label(name)
    kind = media_kind(content_type, name)
    if kind == "image":
        return f"![{label}]({url})"
    if kind == "video":
        return (
            f'\n\n<div><video src="{url}" controls preload="metadata" playsinline '
            f'style="{_VIDEO_STYLE}"></video></div>\n\n[{label}]({url})'
        )
    if kind == "audio":
        return (
            f'\n\n<div><audio src="{url}" controls preload="metadata" '
            f'style="{_AUDIO_STYLE}"></audio></div>\n\n[{label}]({url})'
        )
    if kind == "html" and url.endswith("/content"):
        return f'\n\n<iframe src="{url}/html"></iframe>\n\n[{label}]({url})'
    return f"[{label}]({url})"


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """Fenced code blocks: a MEDIA tag inside one is an example, not a file."""
    spans, start, fence = [], None, ""
    for match in _FENCE_RE.finditer(text):
        marker = match.group(1)
        if start is None:
            start, fence = match.start(), marker
        elif marker[0] == fence[0] and len(marker) >= len(fence):
            spans.append((start, match.end()))
            start = None
    if start is not None:
        spans.append((start, len(text)))
    return spans


def media_tag_paths(text: str) -> list[str]:
    """Absolute paths of the MEDIA tags outside code blocks, in order, once each."""
    return list(dict.fromkeys(path for _, _, path in _media_tags(text)))


def _media_tags(text: str):
    spans = _fenced_spans(text)
    for match in _MEDIA_TAG_RE.finditer(text or ""):
        if any(start <= match.start() < end for start, end in spans):
            continue
        path = next(group for group in match.groups() if group is not None).strip()
        end = match.end()
        if match.group(4) is not None:
            stripped = path.rstrip(_TRAILING_PUNCTUATION)
            wrapped = match.group(0).startswith("`") and match.group(0).endswith("`")
            if not wrapped:  # "MEDIA:/x.mp4。" keeps its full stop
                end = match.start(4) + len(stripped)
            path = stripped
        if path.startswith("/"):
            yield match.start(), end, path


Store = Callable[[str, object, str], str]


async def localize_media_tags(
    text: str,
    media_url: str,
    headers: dict,
    store: Store,
    fetch: Optional[Callable[[str], Awaitable[Optional[tuple]]]] = None,
) -> str:
    """Swap each MEDIA tag of *text* for the stored file (:func:`media_markdown`).

    *media_url* is Hermes' ``…/v1/media``; *store(name, fileobj, content_type)* saves the
    bytes and returns the file's URL. A file Hermes will not hand out (gone, too big,
    refused) stays named: ``path``（没能取回：reason）. *fetch* replaces the HTTP fetch in tests."""
    if not text or "MEDIA:" not in text:
        return text
    tags = list(_media_tags(text))
    if not tags:
        return text
    shown: dict[str, str] = {}

    async def _fetch(path: str):
        if fetch is not None:
            return await fetch(path)
        return await _fetch_from_hermes(media_url, headers, path)

    for path in dict.fromkeys(path for _, _, path in tags):
        name = os.path.basename(path) or "file"
        if len(shown) >= MEDIA_TAGS_MAX:
            shown[path] = f"`{path}`"
            continue
        try:
            fetched = await _fetch(path)
        except Exception as e:  # never lose the reply over a file
            log.warning(f"hermes media fetch failed for {name}: {e}")
            fetched = (None, None, "取回出错")
        handle, content_type, problem = fetched
        if handle is None:
            shown[path] = f"`{path}`（没能取回：{problem}）"
            continue
        try:
            content_type = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
            url = store(name, handle, content_type)
            shown[path] = media_markdown(name, url, content_type)
        except Exception as e:
            log.warning(f"hermes media store failed for {name}: {e}")
            shown[path] = f"`{path}`（没能保存）"
        finally:
            handle.close()

    parts, last = [], 0
    for start, end, path in tags:
        parts.append(text[last:start])
        parts.append(shown[path])
        last = end
    parts.append(text[last:])
    return re.sub(r"\n{3,}", "\n\n", "".join(parts))


async def _fetch_from_hermes(media_url: str, headers: dict, path: str):
    """(file object at offset 0, content type, None) or (None, None, why)."""
    timeout = aiohttp.ClientTimeout(total=MEDIA_FETCH_TIMEOUT_SECONDS)
    url = f"{media_url}?path={quote(path, safe='/')}"
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        async with session.get(
            url, headers=headers, ssl=AIOHTTP_CLIENT_SESSION_SSL
        ) as response:
            if response.status == 404:
                return None, None, "文件不存在或不允许读取"
            if response.status == 413:
                return None, None, "文件超过 200MB"
            if response.status != 200:
                return None, None, f"Hermes 返回 HTTP {response.status}"
            handle = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
            size = 0
            async for chunk in response.content.iter_chunked(1024 * 1024):
                size += len(chunk)
                if size > MEDIA_FETCH_MAX_BYTES:
                    handle.close()
                    return None, None, "文件超过 200MB"
                handle.write(chunk)
            handle.seek(0)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
            return handle, content_type, None


def hermes_media_url(base_url: str) -> str:
    """``…/v1/media`` for a Hermes connection base URL (normalized to end in /v1)."""
    base = (base_url or "").rstrip("/")
    return f"{base}/media" if base.endswith("/v1") else f"{base}/v1/media"


_PLAYER_RE = re.compile(
    r'\n*<div><(video|audio) src="[^"]*"[^>]*></\1></div>\n*'
    r'|\n*<iframe src="/api/v1/files/[^"]+/content/html"></iframe>\n*'
)


def strip_media_players(text: str) -> str:
    """*text* without the players and previews of :func:`media_markdown` (each keeps its
    link line): for a push, and for the HTML card's designer — its sandboxed frame cannot
    load the file, the chat shows the player next to the card."""
    if not text or "<" not in text:
        return text
    return _PLAYER_RE.sub("\n\n", text)


_SHOWN_FILE_RE = re.compile(
    r'(?:<(?:video|audio) src="|!\[[^\]\n]*\]\()/api/v1/files/([A-Za-z0-9-]{8,64})/content'
)
PUSH_MEDIA_MAX = 4


def push_media(content: str, user_id: str) -> list[dict]:
    """The pictures, videos and audio Hermes made that *content* shows, as the away push
    attaches them (``{"path", "name", "content_type"}``): only the user's own files that
    came from Hermes, at most :data:`PUSH_MEDIA_MAX`."""
    file_ids = list(dict.fromkeys(_SHOWN_FILE_RE.findall(content or "")))
    if not file_ids:
        return []
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage

    media = []
    for file_id in file_ids:
        if len(media) >= PUSH_MEDIA_MAX:
            break
        try:
            record = Files.get_file_by_id(file_id)
            meta = (record.meta or {}) if record else {}
            if not record or record.user_id != user_id:
                continue
            if (meta.get("data") or {}).get("source") != "hermes-agent":
                continue
            media.append(
                {
                    "path": Storage.get_file(record.path),
                    "name": meta.get("name") or record.filename,
                    "content_type": meta.get("content_type") or "",
                }
            )
        except Exception as e:
            log.warning(f"push media lookup failed for {file_id}: {e}")
    return media
