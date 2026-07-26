"""HaloWebUI-only HTML visual artifact prompt overlay.

This module intentionally lives in HaloWebUI rather than Hermes Agent so web chat
requests can opt into rich HTML Artifact previews without changing Hermes's
Telegram/default reply policy.
"""

from __future__ import annotations

import html
import re
from typing import Any

HTML_VISUAL_FEATURE_KEY = "html_visual_artifacts"
HTML_VISUAL_SURFACE_KEY = "html_visual_surface"
HTML_VISUAL_PROMPT_MARKER = "HALOWEBUI_HTML_VISUAL_ARTIFACT_MODE"
HTML_VISUAL_FORCE_PROMPT_MARKER = "HALOWEBUI_HTML_VISUAL_FORCE_REQUIRED"
HTML_VISUAL_FALLBACK_MARKER = "HALOWEBUI_HTML_VISUAL_SAFE_FALLBACK"
HTML_VISUAL_WEB_SURFACE = "halowebui-web"

HTML_VISUAL_PROMPT = f"""[{HTML_VISUAL_PROMPT_MARKER}]
当前输出 surface 是 HaloWebUI Web Chat，支持消息卡片内嵌 Artifact iframe，并可打开完整预览；本规则只适用于当前 Web 会话，不代表 Telegram/纯文本平台也支持 HTML。

当回答包含复杂结构、横向对比、流程/架构/状态关系、信息卡片、参数矩阵、表格、数据图表、密集多字段归纳，或纯 Markdown 会显得冗长割裂时，优先提供一个 fenced `html` Artifact：
````html
<div style="max-width:920px;margin:0 auto;padding:22px 20px;background:#fff;color:#171717;font-family:Inter,Arial,'Noto Sans SC',sans-serif;">
  <div style="font-size:24px;font-weight:750;line-height:1.3;">清晰标题</div>
  <div style="margin-top:16px;padding:16px;background:#f7f7f5;border-left:3px solid #1f2937;">一个主重点或核心结论</div>
  <div style="display:flex;flex-wrap:wrap;gap:12px;margin-top:16px;">
    <div style="flex:1 1 360px;min-width:0;padding:14px 0;border-top:1px solid #e5e7eb;">次重点</div>
    <div style="flex:1 1 360px;min-width:0;padding:14px 0;border-top:1px solid #e5e7eb;">次重点</div>
  </div>
</div>
````

生成规则：
- 使用简体中文；Markdown 标题从 ## 起，子层级使用 ###，禁用单个 #。
- HTML 只输出局部片段，禁止 !DOCTYPE/html/head/body 全量页面框架。
- 根容器保持扁平：不要添加外层边框、圆角或阴影，HaloWebUI 已提供消息卡片边界；禁止卡片套卡片，视觉嵌套最多一层。
- 先建立“标题/结论 → 一个主重点 → 2–4 个次重点 → 紧凑详情”的层级；不要把所有条目做成等权卡片。新闻等长列表采用“1 条头条 + 3 条重点 + 其余紧凑列表/折叠详情”。
- 默认最多两列，使用 `display:flex;flex-wrap:wrap` 与 `flex:1 1 360px;min-width:0`，让窄屏自动单列；禁止三列窄卡和固定宽度桌面长图缩放。
- 长文本不要塞进多列表格。四列以上或单元格文字较长时，改为纵向对比卡/列表；确需表格时外包 `overflow-x:auto`，并降低网格线对比度。
- 默认使用黑白灰克制视觉，只保留一个强调色；红/橙只用于风险，绿色只用于完成状态。不要同时堆叠黑色横幅、多色分类、重阴影和粗边框。
- 优先用字号、字重、留白和细分隔线建立层级；同一画面最多一种圆角尺度、一种边框强度，阴影仅用于真正需要悬浮的元素。
- 正文建议 14–16px、行高 1.6–1.75；长哈希、URL、命令用 `overflow-wrap:anywhere` 或紧凑代码区，避免孤字断行。
- HTML 片段优先使用纯内联 style；避免 class、伪类/伪元素、外链资源、可解析 URL、远程图片、远程字体。
- 可使用 Flexbox、基础盒模型、table、details/summary、内联 SVG/纯 CSS 条形图；不要为装饰而过度设计。
- 不要把整段回复都塞进一个巨大 HTML 块；先给必要结论，再用 Artifact 承载复杂可视化。
- 如果用户明确要求 Telegram、短信、纯文本、Markdown-only 或不支持 Artifact 的输出，禁止输出 HTML Artifact，改用紧凑 Markdown。
""".strip()

HTML_VISUAL_FORCE_PROMPT = f"""{HTML_VISUAL_PROMPT}

[{HTML_VISUAL_FORCE_PROMPT_MARKER}]
当前模式是 force。最终回复必须包含一个非空的 fenced `html` Artifact；即使答案主要是纯文本，也要在保留原始结论后提供安全、自包含的 HTML 可视化。
""".strip()

_PLAIN_TEXT_SURFACES = {
    "telegram",
    "tg",
    "sms",
    "signal",
    "whatsapp",
    "discord",
    "slack",
    "plain",
    "text",
    "markdown-only",
}

_TOOL_CALL_DETAILS_RE = re.compile(
    r"<details\b(?=[^>]*\btype\s*=\s*(?P<quote>[\"'])tool_calls(?P=quote))"
    r"[^>]*>.*?</details\s*>",
    re.IGNORECASE | re.DOTALL,
)
_NON_ARTIFACT_DETAILS_RE = re.compile(
    r"<details\b(?=[^>]*\btype\s*=\s*(?P<quote>[\"'])(?:tool_calls|reasoning)(?P=quote))"
    r"[^>]*>.*?</details\s*>",
    re.IGNORECASE | re.DOTALL,
)
_THINKING_BLOCK_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_FULL_HTML_DOCUMENT_RE = re.compile(
    r"^[\t ]*(?:<!doctype\s+html\b|<html\b)",
    re.IGNORECASE | re.MULTILINE,
)


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_html_visual_mode(value: Any) -> str:
    """Normalize client feature values to off/auto/force."""
    if isinstance(value, bool):
        return "force" if value else "off"
    if value is None:
        return "off"

    normalized = str(value).strip().lower()
    if normalized == "auto":
        return "auto"
    if normalized in {"1", "true", "yes", "on", "force", "always"}:
        return "force"
    return "off"


def get_html_visual_mode(metadata: dict[str, Any] | None) -> str:
    metadata = _as_mapping(metadata)
    features = _as_mapping(metadata.get("features"))
    return normalize_html_visual_mode(features.get(HTML_VISUAL_FEATURE_KEY))


def get_html_visual_surface(metadata: dict[str, Any] | None) -> str:
    metadata = _as_mapping(metadata)
    features = _as_mapping(metadata.get("features"))
    return (
        str(
            metadata.get("surface")
            or metadata.get("source")
            or features.get(HTML_VISUAL_SURFACE_KEY)
            or ""
        )
        .strip()
        .lower()
    )


def _is_plain_text_surface(surface: str) -> bool:
    normalized = surface.strip().lower()
    if normalized in _PLAIN_TEXT_SURFACES:
        return True
    tokens = {token for token in re.split(r"[:/_-]+", normalized) if token}
    return bool(tokens & _PLAIN_TEXT_SURFACES)


def should_apply_html_visual_prompt(metadata: dict[str, Any] | None) -> bool:
    metadata = _as_mapping(metadata)
    features = _as_mapping(metadata.get("features"))
    mode = get_html_visual_mode(metadata)
    if mode == "off":
        return False

    client_surface = str(features.get(HTML_VISUAL_SURFACE_KEY) or "").strip().lower()
    if client_surface != HTML_VISUAL_WEB_SURFACE:
        return False

    explicit_surfaces = (
        metadata.get("surface"),
        metadata.get("source"),
        features.get(HTML_VISUAL_SURFACE_KEY),
    )
    if any(
        _is_plain_text_surface(str(surface))
        for surface in explicit_surfaces
        if surface is not None
    ):
        return False

    surface = get_html_visual_surface(metadata)
    return not _is_plain_text_surface(surface)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return ""


def _already_has_html_visual_prompt(messages: list[Any]) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if HTML_VISUAL_PROMPT_MARKER in _content_text(message.get("content")):
            return True
    return False


def apply_html_visual_prompt_overlay(
    form_data: dict[str, Any], metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """Inject a web-surface-only system prompt into an OpenAI-style chat payload.

    The function mutates and returns ``form_data`` for compatibility with the
    existing chat pipeline. It is intentionally a no-op unless the web client
    explicitly sends ``features.html_visual_artifacts``.
    """
    if not should_apply_html_visual_prompt(metadata):
        return form_data

    messages = form_data.get("messages")
    if not isinstance(messages, list) or _already_has_html_visual_prompt(messages):
        return form_data

    insertion_index = 0
    while insertion_index < len(messages):
        message = messages[insertion_index]
        if not isinstance(message, dict) or message.get("role") not in {
            "system",
            "developer",
        }:
            break
        insertion_index += 1

    mode = get_html_visual_mode(metadata)
    prompt_message = {
        "role": "system",
        "content": (
            HTML_VISUAL_FORCE_PROMPT if mode == "force" else HTML_VISUAL_PROMPT
        ),
    }
    form_data["messages"] = [
        *messages[:insertion_index],
        prompt_message,
        *messages[insertion_index:],
    ]

    if isinstance(metadata, dict):
        metadata["html_visual_artifacts"] = {
            "enabled": True,
            "surface": get_html_visual_surface(metadata),
            "mode": mode,
        }
    return form_data


def _parse_markdown_fence_line(line: str) -> tuple[str, int, str] | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    candidate = line[indent:]
    if not candidate or candidate[0] not in {"`", "~"}:
        return None
    marker = candidate[0]
    length = len(candidate) - len(candidate.lstrip(marker))
    if length < 3:
        return None
    return marker, length, candidate[length:]


def _scan_top_level_markdown_fences(
    content: str,
) -> tuple[list[tuple[str, str]], str, str | None]:
    blocks: list[tuple[str, str]] = []
    outside: list[str] = []
    active: tuple[str, int, str, list[str]] | None = None

    for line in content.splitlines():
        fence = _parse_markdown_fence_line(line)
        if active is None:
            if fence is None:
                outside.append(line)
                continue
            marker, length, info = fence
            if marker == "`" and "`" in info:
                outside.append(line)
                continue
            active = (marker, length, info.strip(), [])
            continue

        marker, length, info, body = active
        if (
            fence is not None
            and fence[0] == marker
            and fence[1] >= length
            and not fence[2].strip()
        ):
            blocks.append((info, "\n".join(body)))
            active = None
        else:
            body.append(line)

    unclosed_fence = active[0] * active[1] if active is not None else None
    return blocks, "\n".join(outside), unclosed_fence


def has_fenced_html_artifact(content: Any) -> bool:
    """Return whether content contains a top-level non-empty fenced HTML block."""
    if not isinstance(content, str):
        return False
    blocks, _, _ = _scan_top_level_markdown_fences(content)
    return any(
        info.strip().lower().split(None, 1)[0] == "html" and body.strip()
        for info, body in blocks
        if info.strip()
    )


def has_html_visual_artifact(content: Any) -> bool:
    """Mirror the frontend's previewable HTML shapes while ignoring hidden details."""
    if not isinstance(content, str) or not content.strip():
        return False
    candidate = _THINKING_BLOCK_RE.sub("", content)
    candidate = _NON_ARTIFACT_DETAILS_RE.sub("", candidate)
    blocks, outside, _ = _scan_top_level_markdown_fences(candidate)
    has_html_fence = any(
        info.strip().lower().split(None, 1)[0] == "html" and body.strip()
        for info, body in blocks
        if info.strip()
    )
    return has_html_fence or bool(_FULL_HTML_DOCUMENT_RE.search(outside))


def _escape_fallback_content(content: str) -> str:
    # Escaping markup preserves the response as inert text. Encoding fence and
    # URL punctuation also prevents copied Markdown from closing the generated
    # fence or becoming a URL-like token in the Artifact source.
    return html.escape(content, quote=True).replace("`", "&#96;").replace(":", "&#58;")


def append_html_visual_fallback(content: Any, metadata: dict[str, Any] | None) -> Any:
    """Append one safe local Artifact for a successful force-mode response.

    Callers are responsible for invoking this only for successful terminal
    responses. The helper additionally fails closed for disabled/advisory modes,
    pure-text surfaces, empty content, and replies that already have an Artifact.
    """
    if (
        not isinstance(content, str)
        or not content.strip()
        or get_html_visual_mode(metadata) != "force"
        or not should_apply_html_visual_prompt(metadata)
        or has_html_visual_artifact(content)
    ):
        return content

    display_content = _TOOL_CALL_DETAILS_RE.sub("", content).strip()
    if not display_content:
        display_content = "任务已完成，详细过程请查看原回复中的工具调用记录。"
    escaped_content = _escape_fallback_content(display_content)
    artifact = f"""```html
<!-- {HTML_VISUAL_FALLBACK_MARKER} -->
<section style="max-width:920px;margin:0 auto;padding:22px 20px;background:#ffffff;color:#171717;font-family:Inter,Arial,'Noto Sans SC',sans-serif;">
  <div style="margin:0;font-size:12px;font-weight:700;letter-spacing:0.08em;color:#6b7280;">回复摘要</div>
  <div style="margin-top:12px;padding-top:14px;border-top:1px solid #e5e7eb;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px;line-height:1.7;color:#1f2937;">{escaped_content}</div>
</section>
```"""
    _, _, unclosed_fence = _scan_top_level_markdown_fences(content)
    if unclosed_fence:
        leading_newline = "" if content.endswith("\n") else "\n"
        separator = f"{leading_newline}{unclosed_fence}\n\n"
    else:
        separator = "\n\n" if not content.endswith("\n") else "\n"
    return f"{content}{separator}{artifact}"
