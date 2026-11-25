"""On-demand read-only local evidence inspection for 精答 and 讨论台.

Admin-only (same gate as vault_notes): asks Hermes' ``POST /v1/halo-teams/inspect`` endpoint to
inspect relevant local files/configs/state read-only, without memory writes, and with mandatory
secret redaction on both sides before the resulting evidence pack is injected into prompts.

HALO_MODES_LOCAL_INSPECT=0 turns the feature off.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))

MODES_ENV = "HALO_MODES_LOCAL_INSPECT"  # "0" turns it off
INSPECT_TIMEOUT_SECONDS = 90
MAX_SUMMARY_CHARS = 4500
MAX_SOURCES = 20

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.I,
)
_URL_CREDS_RE = re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@", re.I)
_KV_SECRET_RE = re.compile(
    r"""(?ix)
    (
        (?:["']?[A-Za-z0-9_.-]*(?:
            api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret|
            auth[_-]?token|access[_-]?token|refresh[_-]?token|bearer[_-]?token|
            bot[_-]?token|notify[_-]?token|session[_-]?secret|jwt[_-]?secret|
            webhook[_-]?secret|private[_-]?key|password|passwd|secret|token
        )[A-Za-z0-9_.-]*["']?)
        \s*[:=]\s*
    )
    (["']?)(\$\{[^}\n]+\}|[^\s,"'}\]\n]{4,})(\2)
    """
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{12,}")
_VENDOR_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|AIza[0-9A-Za-z_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
_SAFE_PLACEHOLDER_RE = re.compile(
    r"^(?:\$\{[^}]+\}|\$[A-Z0-9_]+|\[REDACTED\]|<[^>]+>|true|false|null|none|off|on|\d+)$",
    re.I,
)


def enabled() -> bool:
    return os.environ.get(MODES_ENV, "1").strip().lower() not in {"0", "false", "off", "no"}


def may_inspect(user: Any) -> bool:
    """Only admins may trigger host read-only inspection (same trust boundary as vault_notes)."""
    return getattr(user, "role", None) == "admin" and enabled()


def redact_evidence(text: Any) -> str:
    """Defense-in-depth secret redaction on the HaloWebUI side before persisting or sending to models."""
    value = "" if text is None else str(text)
    if not value:
        return ""
    value = _PEM_BLOCK_RE.sub("[REDACTED PRIVATE KEY]", value)
    value = _URL_CREDS_RE.sub(r"\1[REDACTED]@", value)
    value = _BEARER_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", value)
    value = _VENDOR_TOKEN_RE.sub("[REDACTED]", value)

    def _mask_kv(match: re.Match) -> str:
        val = match.group(3)
        if _SAFE_PLACEHOLDER_RE.match(val):
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(4)}"

    return _KV_SECRET_RE.sub(_mask_kv, value)


def _clean_sources(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:MAX_SOURCES]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "file").strip()
        if kind not in {"file", "search", "command"}:
            kind = "file"
        path = redact_evidence(item.get("path") or "").replace("\n", " ").strip()[:180]
        if path:
            out.append({"kind": kind, "path": path})
    return out


async def inspect_host(
    request: Any,
    user: Any,
    question: str,
    *,
    context: str = "",
    mode: str = "answer",
    timeout: int = INSPECT_TIMEOUT_SECONDS,
) -> dict:
    """Ask Hermes' read-only inspect route for a redacted local evidence summary."""
    if not may_inspect(user):
        return {"skipped": True, "summary": "", "sources": []}
    from open_webui.utils.agent_teams import hermes_call, hermes_target

    target = await hermes_target(request, user)
    body = await hermes_call(
        target,
        "POST",
        "/inspect",
        json_body={
            "question": str(question or "").strip()[:4000],
            "context": str(context or "").strip()[:2000],
            "mode": "discuss" if mode == "discuss" else "answer",
        },
        timeout=timeout,
    )
    if not isinstance(body, dict) or not body.get("ok"):
        raise ValueError("Hermes 没有返回可用的本机取证结果")
    summary = redact_evidence(body.get("summary") or "").strip()[:MAX_SUMMARY_CHARS]
    sources = _clean_sources(body.get("sources"))
    return {
        "summary": summary,
        "sources": sources,
        "model": str(body.get("model") or "")[:120],
        "truncated": bool(body.get("truncated")),
    }


def inspect_block(inspect: Optional[dict]) -> str:
    """The local evidence pack as prompt material (精答 / 讨论)."""
    if not isinstance(inspect, dict) or inspect.get("status") != "done":
        return ""
    summary = str(inspect.get("summary") or "").strip()
    if not summary:
        return ""
    sources = inspect.get("sources") or []
    parts = [
        "Live read-only evidence collected from the user's server/workspace via Hermes right now "
        "(secrets redacted). Prefer these verified current facts over outdated notes or general "
        "assumptions. If a detail was not checked, state that explicitly instead of guessing:"
    ]
    if sources:
        listed = "\n".join(f"- [{s.get('kind') or 'file'}] {s.get('path')}" for s in sources if s.get("path"))
        if listed:
            parts.append(f"Checked paths/commands:\n{listed}")
    parts.append(summary)
    return "\n\n".join(parts)


def inspect_tail(inspect: Optional[dict]) -> str:
    """Checked local files/commands listed under the stored answer/conclusion (no raw secrets)."""
    if not isinstance(inspect, dict) or inspect.get("status") != "done":
        return ""
    sources = [s for s in (inspect.get("sources") or []) if isinstance(s, dict) and s.get("path")]
    if not sources:
        return ""
    kind_labels = {"file": "文件", "search": "检索", "command": "只读命令"}
    lines = [f"- {kind_labels.get(s.get('kind', ''), '核查')}：`{s['path']}`" for s in sources]
    return "\n\n---\n**本机取证（只读）**\n\n" + "\n".join(lines)
