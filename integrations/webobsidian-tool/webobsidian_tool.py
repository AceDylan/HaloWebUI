"""
title: WebObsidian Vault (read-only)
author: HaloWebUI
version: 1.0.0
license: MIT
description: Search and read notes in a WebObsidian vault through its Agent API.
requirements:
"""

# Paste this file into Workspace -> Tools -> "+" and fill the valves in.
# See README.md next to this file for the key, the scopes and the reverse-proxy hop.
#
# Read-only on purpose. The key this tool holds needs `read` and `search` and
# nothing else, so a prompt-injected model that finds the tool can quote the
# vault back but never edit it. Writing into the vault is the Bookmark Hub's
# job (it holds a separate `write` key that can only touch one folder).
#
# Every helper here is a module-level function rather than a method: HaloWebUI
# turns *every* non-dunder attribute of the Tools instance into a function the
# model can call (utils/tools.py, get_functions_from_tool), so a method named
# `_get` would be offered to the model as a tool.

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field

# Vault-relative, as the Agent API wants it: no leading slash, no backslashes,
# no traversal, no dot-directories (`.trash`, `.git`, `.obsidian`).
_PATH_MAX = 400
_SEGMENT_BAD = frozenset({"", ".", ".."})
_TIMEOUT_RANGE = (1.0, 30.0)
_RESULT_CEILING = 50
_NOTE_CHARS_RANGE = (500, 100_000)


def _clean_path(raw: Any) -> str:
    """A vault-relative path, or '' when the model handed us something else.

    WebObsidian refuses traversal on its side too; this keeps a bad path from
    ever being sent, so the answer is a clear sentence instead of a 400.
    """
    path = str(raw or "").strip().replace("\\", "/").lstrip("/")
    if not path or len(path) > _PATH_MAX:
        return ""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        return ""
    if any(s in _SEGMENT_BAD or s.startswith(".") for s in path.split("/")):
        return ""
    return path


def _clean_folder(raw: Any) -> str:
    """A folder prefix for filtering; '' means the whole vault."""
    folder = str(raw or "").strip().replace("\\", "/").strip("/")
    return _clean_path(folder) if folder else ""


def _base_url(valves: Any) -> str:
    return str(getattr(valves, "base_url", "") or "").strip().rstrip("/")


def _timeout(valves: Any) -> float:
    low, high = _TIMEOUT_RANGE
    try:
        return max(low, min(float(valves.timeout_seconds), high))
    except (AttributeError, TypeError, ValueError):
        return 8.0


def _result_limit(valves: Any, asked: Any, default: int) -> int:
    try:
        ceiling = max(1, min(int(valves.max_results), _RESULT_CEILING))
    except (AttributeError, TypeError, ValueError):
        ceiling = 10
    try:
        wanted = int(asked)
    except (TypeError, ValueError):
        wanted = default
    return max(1, min(wanted, ceiling))


def _note_chars(valves: Any) -> int:
    low, high = _NOTE_CHARS_RANGE
    try:
        return max(low, min(int(valves.max_note_chars), high))
    except (AttributeError, TypeError, ValueError):
        return 8000


def _note_url(valves: Any, path: str) -> str:
    base = _base_url(valves)
    if not base:
        return ""
    return f"{base}/note/" + "/".join(quote(part, safe="") for part in path.split("/"))


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fetch(valves: Any, path: str, params: Optional[dict] = None) -> tuple[Optional[Any], str]:
    """``(payload, error)``; exactly one of the two is meaningful."""
    base = _base_url(valves)
    if not base:
        return None, "The WebObsidian tool is not configured yet (base_url valve is empty)."
    key = str(getattr(valves, "api_key", "") or "").strip()
    if not key:
        return None, "The WebObsidian tool is not configured yet (api_key valve is empty)."
    seconds = _timeout(valves)
    try:
        response = requests.get(
            f"{base}/api/v1{path}",
            params=params or {},
            # X-API-Key rather than Authorization: a reverse proxy in front of
            # WebObsidian may clear Authorization for its own basic auth.
            headers={"X-API-Key": key, "Accept": "application/json"},
            timeout=seconds,
            verify=bool(getattr(valves, "verify_tls", True)),
        )
    except requests.Timeout:
        return None, f"WebObsidian did not answer within {seconds:.0f}s."
    except requests.RequestException as exc:
        return None, f"Could not reach WebObsidian ({type(exc).__name__})."

    status = response.status_code
    if status == 401:
        return None, "WebObsidian refused the API key (401). Check the api_key valve."
    if status == 403:
        return None, "The API key is missing a scope (403). It needs read and search."
    if status == 404:
        return None, "Not found in the vault."
    if status == 429:
        return None, "WebObsidian is rate-limiting this key (429). Try again in a minute."
    if status >= 400:
        return None, f"WebObsidian answered HTTP {status}."
    try:
        return response.json(), ""
    except ValueError:
        return None, "WebObsidian answered something that is not JSON."


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default="",
            description=(
                "Origin of the WebObsidian deployment, e.g. "
                "https://notes.example.com:3003 . Empty disables the tool."
            ),
        )
        api_key: str = Field(
            default="",
            description="WebObsidian API key (Settings -> API Keys) with the read and search scopes only.",
        )
        timeout_seconds: float = Field(
            default=8.0,
            description="Per-request timeout. Kept short: a chat must not hang on the vault.",
        )
        max_results: int = Field(
            default=10, description="Upper bound on hits returned by a search or a listing."
        )
        max_note_chars: int = Field(
            default=8000,
            description="Longest note body handed back to the model; longer notes are truncated.",
        )
        verify_tls: bool = Field(
            default=True,
            description="Verify the TLS certificate. Turn off only for a self-signed lab instance.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.citation = True

    def search_notes(self, query: str, limit: int = 5) -> str:
        """
        Search the user's personal Obsidian vault and return the notes that match, each
        with a snippet. Use this before answering anything the user may have written
        down themselves. Fielded queries work: tag:idea, path:Projects/, title:weekly.

        :param query: What to look for. Plain words, or a fielded query.
        :param limit: How many notes to return (1..10).
        :return: JSON with the hits: path, title, tags, snippet and a link that opens the note.
        """
        text = str(query or "").strip()
        if not text:
            return "Give me something to search for."
        payload, error = _fetch(
            self.valves, "/search", {"q": text[:500], "limit": _result_limit(self.valves, limit, 5)}
        )
        if error:
            return error
        hits = payload.get("hits") if isinstance(payload, dict) else None
        results = []
        for hit in hits if isinstance(hits, list) else []:
            if not isinstance(hit, dict):
                continue
            path = _clean_path(hit.get("path"))
            if not path:
                continue
            results.append(
                {
                    "path": path,
                    "title": str(hit.get("title") or path)[:200],
                    "tags": [str(t)[:60] for t in (hit.get("tags") or [])][:12],
                    "snippet": re.sub(r"\s+", " ", str(hit.get("snippet") or ""))[:400],
                    "open": _note_url(self.valves, path),
                }
            )
        if not results:
            return f"No note in the vault matches {text!r}."
        return _dump({"query": text, "hits": results})

    def read_note(self, path: str) -> str:
        """
        Read one note from the user's personal Obsidian vault in full. Call this after
        search_notes when the snippet is not enough to answer.

        :param path: Vault-relative path of the note, exactly as search_notes reported it.
        :return: JSON with the note's title, tags, body and a link that opens it.
        """
        clean = _clean_path(path)
        if not clean:
            return "That is not a valid vault path. Use the path search_notes reported."
        payload, error = _fetch(self.valves, f"/notes/{clean}")
        if error:
            return error
        if not isinstance(payload, dict):
            return "WebObsidian answered something unexpected."
        ceiling = _note_chars(self.valves)
        body = str(payload.get("content") or "")
        return _dump(
            {
                "path": clean,
                "title": str(payload.get("title") or clean)[:200],
                "tags": [str(t)[:60] for t in (payload.get("tags") or [])][:32],
                "content": body[:ceiling],
                "truncated": len(body) > ceiling,
                "open": _note_url(self.valves, clean),
            }
        )

    def list_notes(self, folder: str = "", limit: int = 20) -> str:
        """
        List the notes in the user's personal Obsidian vault, optionally only those under
        one folder. Use it to learn how the vault is organised before searching.

        :param folder: Folder to list, e.g. Projects or Knowledge/Tools. Empty lists the whole vault.
        :param limit: How many paths to return (1..50).
        :return: JSON with the paths, the number of notes and the top-level folders seen.
        """
        payload, error = _fetch(self.valves, "/notes", {"limit": 500})
        if error:
            return error
        notes = payload.get("notes") if isinstance(payload, dict) else None
        if not isinstance(notes, list):
            return "WebObsidian answered something unexpected."
        prefix = _clean_folder(folder)
        paths = [p for p in (_clean_path(n) for n in notes) if p]
        if prefix:
            paths = [p for p in paths if p.startswith(prefix + "/")]
        folders = sorted({p.split("/")[0] for p in paths if "/" in p})
        return _dump(
            {
                "folder": prefix or "(vault root)",
                "total": len(paths),
                "folders": folders[:40],
                "notes": sorted(paths)[: _result_limit(self.valves, limit, 20)],
            }
        )

    def find_backlinks(self, path: str) -> str:
        """
        List the notes that link to a given note in the user's personal Obsidian vault.
        Use it to see the context around a note the user asked about.

        :param path: Vault-relative path of the note, exactly as search_notes reported it.
        :return: JSON with the paths of the notes that link to it.
        """
        clean = _clean_path(path)
        if not clean:
            return "That is not a valid vault path. Use the path search_notes reported."
        payload, error = _fetch(self.valves, "/backlinks", {"path": clean})
        if error:
            return error
        links = payload.get("backlinks") if isinstance(payload, dict) else None
        if not isinstance(links, list):
            return "WebObsidian answered something unexpected."
        clean_links = sorted({p for p in (_clean_path(link) for link in links) if p})
        if not clean_links:
            return f"Nothing links to {clean}."
        return _dump({"path": clean, "backlinks": clean_links[:100]})
