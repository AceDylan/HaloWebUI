"""Obsidian 笔记 in the composer (# in the input): search the note vault — the one the Hub's
笔记 tab shows, mounted read-only into the container — and read one note, so a chat takes it
along as context (an inline document, like a web page) and hermes is told where it lives on
the host (HUB_VAULT_ROOT).

HALO_VAULT_DIR is the container path of that mount (default /opt/vault); without it the
feature is off and the composer lists no notes.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

VAULT_DIR_ENV = "HALO_VAULT_DIR"
DEFAULT_VAULT_DIR = "/opt/vault"
MAX_NOTE_CHARS = 60_000
MAX_NOTES = 5_000
SEARCH_LIMIT = 12
SNIPPET_CHARS = 90
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)


class VaultError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def vault_dir() -> Optional[Path]:
    value = os.environ.get(VAULT_DIR_ENV, DEFAULT_VAULT_DIR).strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def _notes(root: Path) -> list[tuple[str, Path, float]]:
    """(vault-relative path, file, mtime) of every note; hidden folders (.obsidian, .trash,
    .git) are not notes."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if not name.endswith(".md") or name.startswith("."):
                continue
            path = Path(folder) / name
            try:
                if path.is_symlink():
                    continue
                found.append((path.relative_to(root).as_posix(), path, path.stat().st_mtime))
            except OSError:
                continue
            if len(found) >= MAX_NOTES:
                return found
    return found


def _title(rel: str) -> str:
    return rel.rsplit("/", 1)[-1][: -len(".md")]


def _snippet(text: str, at: int, length: int) -> str:
    start = max(0, at - SNIPPET_CHARS // 3)
    end = min(len(text), at + length + SNIPPET_CHARS)
    piece = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start else "") + piece + ("…" if end < len(text) else "")


def search_notes(query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    """Notes for the composer's list: the newest ones for an empty query, else those whose
    name, folder or text contains it (name first), each with an excerpt around the match."""
    root = vault_dir()
    if root is None:
        return []
    q = (query or "").strip().lower()
    scored = []
    for rel, path, mtime in _notes(root):
        if not q:
            scored.append((0, mtime, rel, ""))
            continue
        title = _title(rel).lower()
        if q in title:
            scored.append((3, mtime, rel, ""))
        elif q in rel.lower():
            scored.append((2, mtime, rel, ""))
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            at = text.lower().find(q)
            if at >= 0:
                scored.append((1, mtime, rel, _snippet(text, at, len(q))))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [
        {
            "path": rel,
            "title": _title(rel),
            "folder": rel.rsplit("/", 1)[0] if "/" in rel else "",
            "snippet": snippet,
            "updated_at": int(mtime),
        }
        for _score, mtime, rel, snippet in scored[: max(1, min(limit, 50))]
    ]


def resolve_note(rel: str) -> tuple[Path, Path]:
    """(vault root, note file) for a vault-relative note path; refuses anything outside the
    vault (.., absolute, hidden folders, symlinks) or that is not a Markdown note."""
    root = vault_dir()
    if root is None:
        raise VaultError(503, "笔记库没有接入（HALO_VAULT_DIR）")
    text = (rel or "").strip()
    parts = text.split("/")
    if (
        not text.endswith(".md")
        or text.startswith("/")
        or "\\" in text
        or "\x00" in text
        or any(not part or part in (".", "..") or part.startswith(".") for part in parts)
        or len(text) > 1024
    ):
        raise VaultError(400, "不是笔记库里的笔记路径")
    path = root / text
    try:
        real_root = root.resolve()
        real = path.resolve()
    except OSError:
        raise VaultError(404, "没有这篇笔记")
    if path.is_symlink() or real_root not in real.parents or not real.is_file():
        raise VaultError(404, "没有这篇笔记")
    return root, path


def read_note(rel: str) -> dict:
    _root, path = resolve_note(rel)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise VaultError(404, f"读不出这篇笔记：{e}")
    body = _FRONTMATTER_RE.sub("", text, count=1)
    from open_webui.utils.hub_embed import vault_root

    host_root = vault_root()
    return {
        "path": rel,
        "title": _title(rel),
        "content": body[:MAX_NOTE_CHARS],
        "truncated": len(body) > MAX_NOTE_CHARS,
        "size": len(text.encode("utf-8")),
        # where hermes (on the host) finds it; None without the Hub's vault setting
        "host_path": f"{host_root}/{rel}" if host_root else None,
    }
