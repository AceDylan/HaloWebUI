"""结论卡片 for 精答 / 讨论台 / 协作台: where the card goes in what the chat keeps, what it is designed
from, and that it survives the trip back into a chat whole."""

import asyncio
import pathlib
import sys
from types import SimpleNamespace

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import answer_desk as desk  # noqa: E402
from open_webui.utils import discussion_room as room  # noqa: E402
from open_webui.utils import html_visual_prompt as hv  # noqa: E402
from open_webui.utils import mode_card  # noqa: E402

HTML = '<section class="hv" data-theme="ink"><h1 class="hv-title">结论</h1></section>'
CARD = {"status": "ready", "html": HTML}
FENCE = f"````html\n{HTML}\n````"
PICTURE = {"status": "ready", "url": "/api/v1/files/p/content"}
LONG = "## 结论\n\n" + "\n".join(f"- 第 {i} 条要点，写得足够长，不是一句话的简短回答。" for i in range(8))


def test_the_card_goes_after_the_text_only_when_it_is_ready():
    assert mode_card.with_card("正文", CARD) == f"正文\n\n{FENCE}"
    assert mode_card.with_card("正文\n\n", CARD) == f"正文\n\n{FENCE}"
    for card in (None, {"status": "designing"}, {"status": "failed"}, {"status": "ready", "html": " "}):
        assert mode_card.with_card("正文", card) == "正文"
    assert mode_card.with_card("", CARD) == ""


def test_the_answer_keeps_picture_text_sources_then_card():
    run = {
        "answer": {"content": "用 Postgres。"},
        "research": {"sources": [{"n": 1, "title": "文档", "url": "https://e.com"}]},
        "illustration": PICTURE,
        "card": CARD,
    }
    content = desk.stored_content(run)
    assert content.startswith("![配图](/api/v1/files/p/content)\n\n用 Postgres。")
    assert content.endswith(f"1. [文档](https://e.com)\n\n{FENCE}")
    # designed from the answer and its sources, without the picture or an earlier card
    source = desk.card_source(run)
    assert source.startswith("用 Postgres。") and source.endswith("1. [文档](https://e.com)")
    assert "![" not in source and "````" not in source


def test_the_conclusion_keeps_its_tail_before_the_card():
    ask = {"conclusion": {"content": "## 结论\n用 Postgres"}, "illustration": None, "card": CARD}
    assert room.stored_content(ask) == f"## 结论\n用 Postgres\n\n{FENCE}"
    assert room.stored_content(ask, tail="\n\n---\n**资料来源**") == f"## 结论\n用 Postgres\n\n---\n**资料来源**\n\n{FENCE}"
    assert room.stored_content({**ask, "card": None}) == "## 结论\n用 Postgres"


def test_design_hands_back_the_card_or_why_not(monkeypatch):
    seen = []

    async def designed(content, metadata):
        seen.append((content, hv.should_apply_html_visual_prompt(metadata), hv.get_html_visual_mode(metadata)))
        metadata[hv.HTML_VISUAL_AGY_HTML_METADATA_KEY] = {"status": "success", "html": HTML}
        return content

    monkeypatch.setattr(hv, "design_html_visual_artifact_with_agy", designed)
    text = f"<!-- halo:illustration -->\n![结论配图](images/result-1.png)\n<!-- /halo:illustration -->\n\n{LONG}"
    out = asyncio.run(mode_card.design(text))
    assert out["status"] == "ready" and out["html"] == HTML
    # the team's picture block is not text to design; the web surface's force mode is what designs
    assert seen == [(LONG, True, "force")]

    async def timed_out(content, metadata):
        metadata[hv.HTML_VISUAL_AGY_HTML_METADATA_KEY] = {"status": "timeout"}
        return content

    monkeypatch.setattr(hv, "design_html_visual_artifact_with_agy", timed_out)
    assert asyncio.run(mode_card.design(LONG))["status"] == "failed"
    assert asyncio.run(mode_card.design(LONG))["reason"] == "timeout"

    async def broken(content, metadata):
        raise RuntimeError("boom")

    monkeypatch.setattr(hv, "design_html_visual_artifact_with_agy", broken)
    assert asyncio.run(mode_card.design(LONG))["status"] == "failed"
    # a few plain words need no card
    assert asyncio.run(mode_card.design("好的，用 Postgres。")) == {"status": "skipped"}


def test_make_tells_where_the_card_stands_and_can_be_turned_off(monkeypatch):
    async def design(text):
        return {"status": "ready", "html": HTML}

    monkeypatch.setattr(mode_card, "design", design)
    entries = []

    async def on_change(entry):
        entries.append(entry["status"])

    assert asyncio.run(mode_card.make(LONG, on_change))["status"] == "ready"
    assert entries == ["designing", "ready"]
    monkeypatch.setenv(mode_card.AUTO_ENV, "0")
    assert asyncio.run(mode_card.make(LONG, on_change)) is None and entries == ["designing", "ready"]


def test_a_report_back_keeps_the_card_whole_after_a_cut(monkeypatch):
    from open_webui.utils import mode_dispatch

    run = {
        "id": "r1",
        "question": "问题",
        "assistant": {"name": "助手"},
        "answer": {"content": LONG},
        "card": CARD,
    }
    _, content, _ = mode_dispatch.report_of("answer", "c1", run)
    assert content == f"{LONG}\n\n{FENCE}"
    monkeypatch.setattr(mode_dispatch, "REPORT_CONTENT_MAX_CHARS", 40)
    monkeypatch.setattr(mode_dispatch, "REPORT_POST_MAX_CHARS", 40 + 400)
    _, cut, _ = mode_dispatch.report_of("answer", "c1", run)
    assert "太长了" in cut and cut.endswith(FENCE)
    # a card that would not fit is left out, the text goes on its own
    _, alone, _ = mode_dispatch.report_of("answer", "c1", {**run, "card": {"status": "ready", "html": HTML * 20}})
    assert "````" not in alone


def test_the_teams_card_sits_before_the_line_the_page_turns_into_buttons():
    from open_webui.utils import agent_team_outputs as outputs

    team = SimpleNamespace(id="t1", meta={outputs.CARD_META_KEY: {**CARD, "generated_at": 7}})
    conclusion = {"status": "ready", "markdown": "# 结果\n\n正文", "entry": {"generated_at": 7}, "workspace": "", "files": []}
    content = outputs.chat_content(team, conclusion, CARD)
    assert content.startswith(f"# 结果\n\n正文\n\n{FENCE}\n\n---\n")
    assert content.splitlines()[-1].startswith("在协作台看：[结果页](/teams/t1/conclusion)")
    assert "````" not in outputs.chat_content(team, conclusion)
    # the page reads the card of the version it shows, not an older one
    assert outputs.conclusion_with_card(team, conclusion)["card"]["html"] == HTML
    assert "card" not in outputs.conclusion_with_card(team, {**conclusion, "entry": {"generated_at": 8}})


def test_a_push_reads_the_text_not_the_card():
    assert hv.html_cards_as_text(f"{LONG}\n\n{FENCE}") == LONG
    # a card that is nearly all there is: its visible words
    assert hv.html_cards_as_text(f"好\n\n{FENCE}").split() == ["好", "结论"]
