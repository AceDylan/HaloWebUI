"""结论配图: a picture for the team's result, drawn by gpt-image in the style of one of the owner's
HaloWebUI image templates (else Hermes' own hand-drawn infographic template), placed under the
result's title.

The lead first condenses the result into what fits on one picture (a title, a subtitle, 3–6 short
points); then Hermes' ``image_generate`` (gpt-image through the configured provider) draws template
+ content. The image and its prompt are kept in the workspace like a member's
(``images/result-<n>.png`` + ``.prompt.md``) and the conclusion gets the picture between
``<!-- halo:illustration -->`` marks — a rewritten conclusion gets it back. Runs in a background
thread; ``conclusion.illustration`` in the team record says where it stands.

A conclusion the lead has just written gets its picture on its own (``auto``), in the template
HaloWebUI handed over when the team started (the owner's 「手绘万能图 · 自动选画风与画幅」); the
hand-over of the result to its chat waits for it (``WAIT``). HALO_TEAMS_AUTO_ILLUSTRATE=0 leaves it
to the button.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .common import logger, now, read_team, redact, update_team

MARK = "<!-- halo:illustration -->"
MARK_END = "<!-- /halo:illustration -->"
STALE = 900
WAIT = 360  # the result's hand-over to its chat waits this long for a picture being drawn
CONDENSE_SYSTEM = """你要把一份结果提炼成一张图上放的内容。只输出这些内容本身，不要解释、不要代码块：
标题：不超过 16 个字
副标题：一句话（可省略）
要点：3 到 6 条，每条不超过 14 个字，可在前面加一个贴切的 emoji
用和结果相同的语言，只用结果里有的信息，数字和专有名词照抄。"""
FALLBACK_TEMPLATE = ("请把下面的内容画成一张手绘风格的信息图：一个醒目的标题，3–6 个要点配简单的图标和箭头，"
                     "选择合适的不透明底色，确保文字和插图有足够对比度；中文清晰可读、不要错别字、不要拼凑的假文字。\n\n内容：")
_PLACEHOLDER = "{{USER_INPUT}}"
_jobs: dict[str, threading.Thread] = {}
_lock = threading.Lock()


def _hermes_template() -> Optional[str]:
    """Hermes' hand-drawn infographic template (the one 「把结论生成图片」 uses in chats)."""
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    path = home / "skills" / "creative" / "conclusion-infographic" / "templates" / "hand-drawn-infographic.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.count(_PLACEHOLDER) == 1 and len(text) < 40000 else None


def aspect_of(template: Optional[dict]) -> str:
    """image_generate's aspect from a template's canvas ("3:2" landscape, "2:3" portrait, "1:1" square)."""
    value = str((template or {}).get("aspect") or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[:x×]\s*(\d+(?:\.\d+)?)$", value)
    if not m:
        size = re.match(r"^(\d+)\s*[x×]\s*(\d+)$", str((template or {}).get("size") or ""))
        m = size
    if not m:
        return "landscape"
    w, h = float(m.group(1)), float(m.group(2))
    if abs(w - h) < 0.05 * max(w, h):
        return "square"
    return "landscape" if w > h else "portrait"


def build_prompt(template: Optional[dict], content: str) -> tuple[str, str]:
    """(prompt, the template's name) — the user's template, else Hermes' own, else a plain one."""
    content = content.strip()
    if template and str(template.get("prompt") or "").strip():
        return str(template["prompt"]).rstrip() + "\n" + content, str(template.get("name") or "模板")
    hermes = _hermes_template()
    if hermes:
        return "Create a new image from scratch.\n\n" + hermes.replace(_PLACEHOLDER, content, 1), "手绘信息图（Hermes）"
    return FALLBACK_TEMPLATE + "\n" + content, "手绘信息图"


def generate_image(args: dict) -> Any:
    """Hermes' image tool, the same one members call (gpt-image through image_gen's provider)."""
    from tools.image_generation_tool import _handle_image_generate

    return _handle_image_generate(args)


def strip(markdown: str) -> str:
    """The conclusion without its illustration block."""
    return re.sub(re.escape(MARK) + r".*?" + re.escape(MARK_END) + r"\n*", "", markdown, flags=re.S)


def place(markdown: str, block: str) -> str:
    """*block* under the result's # title and its one-line > summary (top when there is no title)."""
    lines = strip(markdown).split("\n")
    at = 0
    fence = None
    for i, line in enumerate(lines):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            fence = marker.group(1)[0] if fence is None else (None if marker.group(1)[0] == fence else fence)
            continue
        if fence is None and line.startswith("# "):
            at = i + 1
            j = at
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].startswith(">"):
                while j < len(lines) and lines[j].startswith(">"):
                    j += 1
                at = j
            break
    head, tail = lines[:at], lines[at:]
    while tail and not tail[0].strip():
        tail = tail[1:]
    return "\n".join(head + ([""] if head else []) + [block, ""] + tail)


def block_for(entry: dict) -> str:
    alt = redact(entry.get("title") or "结果配图", 40)
    note = f"*配图：{entry.get('template') or '模板'} · gpt-image · [提示词]({entry.get('prompt_path')})*"
    return f"{MARK}\n![{alt}]({entry['path']})\n\n{note}\n{MARK_END}"


def reinsert(team: dict, markdown: str) -> str:
    """A conclusion written again keeps the picture made for the previous one."""
    entry = ((team.get("conclusion") or {}).get("illustration") or {})
    if entry.get("status") != "ready" or not entry.get("path"):
        return markdown
    workspace = team.get("workspace") or ""
    if not workspace or not (Path(workspace) / entry["path"]).is_file():
        return markdown
    return place(markdown, block_for(entry))


def _set(slug: str, **fields: Any) -> dict:
    def mutate(rec: dict) -> None:
        conclusion = dict(rec.get("conclusion") or {})
        current = dict(conclusion.get("illustration") or {})
        current.update(fields)
        conclusion["illustration"] = current
        rec["conclusion"] = conclusion

    return ((update_team(slug, mutate).get("conclusion") or {}).get("illustration") or {})


def _run(slug: str, template: Optional[dict]) -> None:
    from . import hooks
    from .conclusion import conclusion_path
    from .plan import call_model

    started = time.time()
    try:
        team = read_team(slug) or {}
        path = conclusion_path(team)
        markdown = path.read_text(encoding="utf-8") if path is not None and path.exists() else ""
        if not markdown.strip():
            _set(slug, status="failed", error="还没有结论，没法配图", at=now())
            return
        _set(slug, step="condense")
        lead = team.get("lead_model") if isinstance(team.get("lead_model"), dict) else {}
        content, reason, _used = call_model(
            [{"role": "system", "content": CONDENSE_SYSTEM}, {"role": "user", "content": strip(markdown)[:30000]}],
            timeout=120, max_tokens=800, temperature=0.2, preferred=lead.get("requested") or None)
        if not content or not content.strip():
            _set(slug, status="failed", error=redact(reason or "负责人没有给出图上的内容", 300), at=now())
            return
        prompt, template_name = build_prompt(template, content)
        args = {"prompt": prompt, "aspect_ratio": aspect_of(template), "workflow_action": "generate"}
        _set(slug, step="draw", template=template_name)
        raw = generate_image(args)
        data = hooks._as_dict(raw)
        rel = hooks.keep_image(team.get("workspace") or "", "result", args, data, who=f"结论配图（模板：{template_name}）")
        if not rel:
            error = data.get("error") or data.get("message") or "生图没有返回图片"
            _set(slug, status="failed", error=redact(f"生图失败：{error}", 300), at=now())
            return
        title = next((line[2:].strip() for line in markdown.split("\n") if line.startswith("# ")), "") or team.get("title")
        entry = _set(slug, status="ready", path=rel, prompt_path=rel.rsplit(".", 1)[0] + ".prompt.md",
                     template=template_name, title=redact(title, 60), seconds=round(time.time() - started, 1),
                     at=now(), error="", step="")
        fresh = path.read_text(encoding="utf-8") if path.exists() else markdown  # rewritten meanwhile?
        tmp = path.with_suffix(".tmp")
        tmp.write_text(place(fresh, block_for(entry)), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("halowebui-teams: illustration for %s failed", slug, exc_info=True)
        _set(slug, status="failed", error=f"配图出错：{type(exc).__name__}", at=now())
    finally:
        with _lock:
            _jobs.pop(slug, None)


def clean_template(template: Any) -> Optional[dict]:
    """A HaloWebUI image template as drawing needs it (name, prompt, canvas), or None."""
    if not isinstance(template, dict) or not str(template.get("prompt") or "").strip():
        return None
    return {"name": redact(template.get("name") or "模板", 60), "prompt": str(template["prompt"])[:6000],
            "aspect": str(template.get("aspect") or "")[:10], "size": str(template.get("size") or "")[:20]}


def start(slug: str, template: Optional[dict] = None, *, by: str = "user") -> dict:
    """Start drawing in the background (one at a time per team)."""
    team = read_team(slug) or {}
    current = ((team.get("conclusion") or {}).get("illustration") or {})
    if (team.get("conclusion") or {}).get("status") != "ready":
        raise ValueError("结论还没写好，写好后再配图")
    with _lock:
        if slug in _jobs and _jobs[slug].is_alive():
            return current
        clean = clean_template(template)
        entry = _set(slug, status="generating", started_at=now(), error="", step="condense", by=by,
                     template=(clean or {}).get("name") or "")
        if os.environ.get("HALO_TEAMS_CONCLUSION_SYNC") == "1":  # tests
            _jobs[slug] = threading.current_thread()
        else:
            thread = threading.Thread(target=_run, args=(slug, clean), name=f"halo-illustrate-{slug}", daemon=True)
            _jobs[slug] = thread
            thread.start()
            return entry
    _run(slug, clean)
    return ((read_team(slug) or {}).get("conclusion") or {}).get("illustration") or entry


def auto(slug: str) -> Optional[dict]:
    """The lead has just written the conclusion: draw its picture unless it has one (a rewrite keeps
    the picture of the version before) or one is being drawn. In the template the team was handed
    at the start (the owner's 「手绘万能图」), else Hermes' hand-drawn infographic."""
    if os.environ.get("HALO_TEAMS_AUTO_ILLUSTRATE", "1") == "0":
        return None
    team = read_team(slug) or {}
    current = public((team.get("conclusion") or {}).get("illustration")) or {}
    if current.get("status") == "generating":
        return None
    if current.get("status") == "ready" and current.get("path") and team.get("workspace") \
            and (Path(team["workspace"]) / current["path"]).is_file():
        return None
    return start(slug, team.get("illustrate_template"), by="auto")


def drawing(entry: Any) -> bool:
    """A picture for this conclusion entry is being drawn (and not given up on)."""
    ill = public((entry or {}).get("illustration") if isinstance(entry, dict) else None) or {}
    return ill.get("status") == "generating" and now() - int(ill.get("started_at") or 0) < WAIT


def public(entry: Any) -> Optional[dict]:
    """What HaloWebUI shows of it (a stale 'generating' after a gateway restart reads as failed)."""
    if not isinstance(entry, dict) or not entry.get("status"):
        return None
    out = {k: entry.get(k) for k in ("status", "path", "prompt_path", "template", "started_at", "at", "seconds",
                                     "error", "step", "by") if entry.get(k) not in (None, "")}
    if out.get("status") == "generating" and now() - int(entry.get("started_at") or 0) > STALE:
        out.update(status="failed", error="配图被中断（网关重启），可以重新配图")
    return out

