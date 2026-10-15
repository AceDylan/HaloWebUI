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
