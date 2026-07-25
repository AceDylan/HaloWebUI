"""HaloWebUI-only HTML visual artifact prompt overlay.

This module intentionally lives in HaloWebUI rather than Hermes Agent so web chat
requests can opt into rich HTML Artifact previews without changing Hermes's
Telegram/default reply policy.
"""

from __future__ import annotations

import re
from typing import Any

HTML_VISUAL_FEATURE_KEY = "html_visual_artifacts"
HTML_VISUAL_SURFACE_KEY = "html_visual_surface"
HTML_VISUAL_PROMPT_MARKER = "HALOWEBUI_HTML_VISUAL_ARTIFACT_MODE"

HTML_VISUAL_PROMPT = f"""[{HTML_VISUAL_PROMPT_MARKER}]
当前输出 surface 是 HaloWebUI Web Chat，支持右侧 Artifact iframe 预览；本规则只适用于当前 Web 会话，不代表 Telegram/纯文本平台也支持 HTML。

当回答包含复杂结构、横向对比、流程/架构/状态关系、信息卡片、参数矩阵、表格、数据图表、密集多字段归纳，或纯 Markdown 会显得冗长割裂时，优先提供一个 fenced `html` Artifact：
````html
<div style="max-width:980px;margin:0 auto;padding:28px;background:#fff;color:#111;font-family:Inter,Arial,'Noto Sans SC',sans-serif;">
  <!-- 自包含 HTML 片段 -->
</div>
````

生成规则：
- 使用简体中文；Markdown 标题从 ## 起，子层级使用 ###，禁用单个 #。
- HTML 只输出局部片段，禁止 !DOCTYPE/html/head/body 全量页面框架。
- 默认使用黑白灰克制视觉：线条、留白、边框、阴影建立层级；重点信息可少量使用高级强调色。
- HTML 片段优先使用纯内联 style；避免 class、伪类/伪元素、外链资源、可解析 URL、远程图片、远程字体。
- 可使用 Flexbox、基础盒模型、table、details/summary、内联 SVG/纯 CSS 条形图；不要为装饰而过度设计。
- 不要把整段回复都塞进一个巨大 HTML 块；先给必要结论，再用 Artifact 承载复杂可视化。
- 如果用户明确要求 Telegram、短信、纯文本、Markdown-only 或不支持 Artifact 的输出，禁止输出 HTML Artifact，改用紧凑 Markdown。
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


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_html_visual_mode(value: Any) -> str:
    """Normalize client feature values to off/auto/force."""
    if isinstance(value, bool):
        return "auto" if value else "off"
    if value is None:
        return "off"

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "auto"}:
        return "auto"
    if normalized in {"force", "always"}:
        return "force"
    return "off"


def get_html_visual_surface(metadata: dict[str, Any] | None) -> str:
    metadata = _as_mapping(metadata)
    features = _as_mapping(metadata.get("features"))
    return (
        str(
            metadata.get("surface")
            or metadata.get("source")
            or features.get(HTML_VISUAL_SURFACE_KEY)
            or "halowebui-web"
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
    mode = normalize_html_visual_mode(features.get(HTML_VISUAL_FEATURE_KEY))
    if mode == "off":
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

    prompt_message = {"role": "system", "content": HTML_VISUAL_PROMPT}
    form_data["messages"] = [
        *messages[:insertion_index],
        prompt_message,
        *messages[insertion_index:],
    ]

    if isinstance(metadata, dict):
        metadata["html_visual_artifacts"] = {
            "enabled": True,
            "surface": get_html_visual_surface(metadata),
            "mode": normalize_html_visual_mode(
                _as_mapping(metadata.get("features")).get(HTML_VISUAL_FEATURE_KEY)
            ),
        }
    return form_data
