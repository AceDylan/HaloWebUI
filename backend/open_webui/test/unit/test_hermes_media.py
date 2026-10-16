"""MEDIA:<path> files of a Hermes reply or runner report, shown in the chat."""

import asyncio
import io

from open_webui.utils import hermes_media


def _localize(text, files):
    stored, fetched = [], []

    async def fetch(path):
        fetched.append(path)
        if path in files:
            return io.BytesIO(files[path]), "", None
        return None, None, "文件不存在或不允许读取"

    def store(name, handle, content_type):
        stored.append((name, handle.read(), content_type))
        return f"/api/v1/files/f{len(stored)}/content"

    result = asyncio.run(
        hermes_media.localize_media_tags(text, "http://h/v1/media", {}, store, fetch=fetch)
    )
    return result, stored, fetched


def test_a_video_plays_where_the_report_named_it():
    text = (
        "做好了。\n\nMEDIA:/root/output/长征.mp4\n`MEDIA:/root/output/cover.png`\n"
        "再提一次 MEDIA:/root/output/长征.mp4。\nMEDIA:/root/gone.mp3\n\n"
        "```\nMEDIA:/root/example.mp4\n```"
    )
    result, stored, fetched = _localize(
        text, {"/root/output/长征.mp4": b"mp4", "/root/output/cover.png": b"png"}
    )
    assert fetched == ["/root/output/长征.mp4", "/root/output/cover.png", "/root/gone.mp3"]
    assert stored == [("长征.mp4", b"mp4", "video/mp4"), ("cover.png", b"png", "image/png")]
    assert '<div><video src="/api/v1/files/f1/content" controls preload="metadata" playsinline' in result
    assert "[长征.mp4](/api/v1/files/f1/content)" in result
    assert "![cover.png](/api/v1/files/f2/content)" in result
    assert result.count("<video") == 2  # named twice, stored once
    assert "/api/v1/files/f1/content)。" in result  # the full stop stays
    assert "`/root/gone.mp3`（没能取回：文件不存在或不允许读取）" in result
    assert "MEDIA:/root/example.mp4" in result  # an example in a code block is left alone
    assert "\n\n\n" not in result


def test_each_kind_shows_its_own_way():
    md = hermes_media.media_markdown
    assert md("a.png", "/u/content", "image/png") == "![a.png](/u/content)"
    assert "<audio src=\"/u/content\"" in md("a.mp3", "/u/content", "audio/mpeg")
    assert '<iframe src="/u/content/html"></iframe>' in md("p.html", "/u/content", "text/html")
    assert md("r.pdf", "/u/content", "application/pdf") == "[r.pdf](/u/content)"
    assert md("x[1].zip", "/u/content", "") == "[x 1 .zip](/u/content)"
    assert "<video" in md("clip.mov", "/u/content", "application/octet-stream")
    assert hermes_media.hermes_media_url("http://127.0.0.1:8642/v1") == "http://127.0.0.1:8642/v1/media"
    assert hermes_media.hermes_media_url("http://127.0.0.1:8642") == "http://127.0.0.1:8642/v1/media"


def test_a_push_and_the_card_designer_see_links_not_players():
    shown = "视频：" + hermes_media.media_markdown("v.mp4", "/api/v1/files/v1/content", "video/mp4")
    shown += "\n\n" + hermes_media.media_markdown("p.html", "/api/v1/files/h1/content", "text/html")
    stripped = hermes_media.strip_media_players(shown)
    assert "<video" not in stripped and "<iframe" not in stripped
    assert "[v.mp4](/api/v1/files/v1/content)" in stripped
    assert "[p.html](/api/v1/files/h1/content)" in stripped


def test_text_without_tags_is_left_as_is():
    for text in ("", "plain", "MEDIA: relative/x.mp4"):
        result, stored, _ = _localize(text, {})
        assert result == text and stored == []


def test_the_card_merge_keeps_the_players():
    # 2026-10-16 live: the design pass stripped the players as raw HTML, leaving the links.
    from open_webui.utils import html_visual_prompt as hvp

    md = hermes_media.media_markdown
    content = (
        "## 视频做好了\n\n- 91 秒\n"
        + md("v.mp4", "/api/v1/files/v1/content", "video/mp4")
        + "\n\n"
        + md("a.mp3", "/api/v1/files/a1/content", "audio/mpeg")
        + "\n\n"
        + md("p.html", "/api/v1/files/h1/content", "text/html")
    )
    merged = hvp._merge_agy_html_artifact(content, '<div class="hv"><h1>卡片</h1></div>')
    assert merged.count("<div><video src=") == 1
    assert merged.count("<div><audio src=") == 1
    assert '<iframe src="/api/v1/files/h1/content/html"></iframe>' in merged
    assert merged.rstrip().endswith("````")
    assert hvp.has_html_visual_artifact(merged)
    # A raw page outside a fence is still stripped.
    assert "<script" not in hvp._merge_agy_html_artifact("<script>x()</script>\n\n文字", "<div>c</div>")
    # A reply that is only a video is brief: no card around a player.
    assert hvp.is_brief_plain_reply("视频：" + md("v.mp4", "/api/v1/files/v1/content", "video/mp4"))
