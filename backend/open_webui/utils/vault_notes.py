"""Obsidian 笔记 in the composer (# in the input): search the note vault — the one the Hub's
笔记 tab shows, mounted read-only into the container — and read one note, so a chat takes it
along as context (an inline document, like a web page) and hermes is told where it lives on
the host (HUB_VAULT_ROOT).

HALO_VAULT_DIR is the container path of that mount (default /opt/vault); without it the
feature is off and the composer lists no notes.
"""

import logging
import math
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


# --- 精答 / 讨论 / 协作: the notes that bear on a question -----------------------------------
# The vault is the owner's knowledge base (projects, servers, earlier decisions): a mode run by
# an admin looks there first, the way it looks on the web, and gets the related notes as material.

MODES_ENV = "HALO_MODES_VAULT_NOTES"  # "0" turns it off
RELATED_LIMIT = 4
RELATED_NOTE_CHARS = 1500
RELATED_MIN_COVERAGE = 0.34  # share of the question's (weighted) words a note must contain
_PARAGRAPH_CHARS = 600
_ASCII_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*[a-z0-9]|[a-z0-9]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
# particles that sit between words: a pair across one ("流有", "间吗") is not a word
_PARTICLES_RE = re.compile(r"[的了吗呢吧啊和与及或把被是有在]")
# question words that say nothing about the subject
_STOP = {
    "什么", "怎么", "为什", "如何", "可以", "一下", "这个", "那个", "我的", "是否", "有没", "没有", "能否",
    "当前", "现在", "帮我", "请问", "需要", "问题", "一些", "哪些", "哪个", "以及", "还是", "或者",
    "the", "and", "for", "how", "what", "why", "is", "are", "my", "to", "of", "in", "a", "an",
}
_text_cache: dict[str, tuple[float, str]] = {}


def _modes_enabled() -> bool:
    return os.environ.get(MODES_ENV, "1").strip() != "0"


def _terms(question: str) -> set[str]:
    """The question's words: ASCII words, and each pair of adjacent Chinese characters (the vault
    is mostly Chinese, written without spaces)."""
    text = (question or "").lower()[:2000]
    terms = {w for w in _ASCII_RE.findall(text) if len(w) >= 2}
    for run in _CJK_RE.findall(text):
        for part in _PARTICLES_RE.split(run):
            terms.update(part[i : i + 2] for i in range(len(part) - 1))
    return terms - _STOP


def _note_text(rel: str, path: Path, mtime: float) -> str:
    cached = _text_cache.get(rel)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        text = _FRONTMATTER_RE.sub("", path.read_text(encoding="utf-8", errors="replace"), count=1)
    except OSError:
        text = ""
    _text_cache[rel] = (mtime, text)
    return text


def _excerpt(text: str, weights: dict[str, float]) -> str:
    """The note's paragraphs that carry most of the question's words, in their order."""
    paragraphs = [p.strip()[:_PARAGRAPH_CHARS] for p in re.split(r"\n\s*\n", text) if p.strip()]
    ranked = sorted(
        range(len(paragraphs)),
        key=lambda i: -sum(w for t, w in weights.items() if t in paragraphs[i].lower()),
    )
    picked, used = [], 0
    for i in ranked:
        if used + len(paragraphs[i]) > RELATED_NOTE_CHARS and picked:
            continue
        picked.append(i)
        used += len(paragraphs[i])
        if used >= RELATED_NOTE_CHARS:
            break
    return "\n…\n".join(paragraphs[i] for i in sorted(picked))[:RELATED_NOTE_CHARS]


def related_notes(question: str, limit: int = RELATED_LIMIT) -> list[dict]:
    """The notes most related to ``question`` — ``{"n", "path", "title", "excerpt", "hostPath"}``
    — or [] when the vault is off or nothing covers enough of the question. Words are weighted by
    how rare they are in the vault; a word in a note's name or folder counts three times."""
    root = vault_dir()
    terms = _terms(question)
    if root is None or not terms:
        return []
    notes = [(rel, _title(rel).lower() + " " + rel.lower(), _note_text(rel, path, mtime).lower())
             for rel, path, mtime in _notes(root)]
    df = {t: sum(1 for _, name, body in notes if t in name or t in body) for t in terms}
    total = len(notes)
    # a word no note has still counts in the question's whole: a question about something else
    # (「人为什么需要吃饭」) shares a stray pair with some note, not most of its words
    weights = {t: math.log((total + 1) / (n + 0.5)) for t, n in df.items() if n < total}
    whole = sum(weights.values())
    if not any(df[t] for t in weights):
        return []
    scored = []
    for rel, name, body in notes:
        found = [t for t in weights if df[t] and (t in name or t in body)]
        coverage = sum(weights[t] for t in found) / whole
        if coverage < RELATED_MIN_COVERAGE:
            continue
        score = sum(weights[t] * (3 if t in name else 1) * min(body.count(t), 9) ** 0.5 for t in found)
        scored.append((score, rel))
    scored.sort(reverse=True)
    if not scored:
        return []
    from open_webui.utils.hub_embed import vault_root

    host_root = vault_root()
    out = []
    for score, rel in scored[:limit]:
        if score < scored[0][0] * 0.3:
            break
        path = root / rel
        text = _note_text(rel, path, path.stat().st_mtime)
        out.append({
            "n": len(out) + 1,
            "path": rel,
            "title": _title(rel),
            "excerpt": _excerpt(text, weights),
            "hostPath": f"{host_root}/{rel}" if host_root else None,
        })
    return out


def notes_for(user, question: str) -> list[dict]:
    """``related_notes`` for a mode run: only for an admin (the vault is the owner's private
    notes, as in the composer) and unless HALO_MODES_VAULT_NOTES=0. Never raises."""
    if getattr(user, "role", None) != "admin" or not _modes_enabled():
        return []
    try:
        return related_notes(question)
    except Exception:  # noqa: BLE001 — the notes are extra material, never a reason to fail
        log.warning("vault: related notes failed", exc_info=True)
        return []


def notes_block(notes: list[dict]) -> str:
    """The notes as prompt material (精答 / 讨论)."""
    if not notes:
        return ""
    parts = [
        "Notes from the user's own knowledge base (their Obsidian vault: their projects, servers and earlier "
        "decisions) that look related to this question. They describe the user's own setup, so prefer them over "
        "general knowledge on those points, but they can be outdated or only partly relevant; ignore those that do "
        "not bear on the question. When you rely on one, name it as 《title》:"
    ]
    for note in notes:
        parts.append(f"《{note['title']}》 ({note['path']})\n{note.get('excerpt') or ''}")
    return "\n\n".join(parts)


def notes_tail(notes: list[dict]) -> str:
    """The notes a result used, listed under it like its web sources."""
    if not notes:
        return ""
    lines = [f"- 《{n['title']}》 `{n['path']}`" for n in notes]
    return "\n\n---\n**笔记库参考**\n\n" + "\n".join(lines)


def goal_notes(notes: list[dict]) -> str:
    """The notes for a team's goal: where they are on the host, for Hermes to read itself."""
    rows = [n for n in notes if n.get("hostPath")]
    if not rows:
        return ""
    return ("\n\n笔记库里可能相关的笔记（用户自己的知识库，宿主机只读路径，按需阅读；可能过时，以实际系统为准）：\n"
            + "\n".join(f"- {n['title']}：{n['hostPath']}" for n in rows))


def with_goal_notes(goal: str, user, question: str, max_chars: int) -> str:
    """A team's goal with the related notes' host paths after it, when they fit in ``max_chars``."""
    extra = goal_notes(notes_for(user, question))
    return goal + extra if extra and len(goal) + len(extra) <= max_chars else goal
