"""讨论台 / 精答 web notes: the part of each page about the question."""

import pathlib
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import mode_chats  # noqa: E402

PAGE = (
    "# 遮天\n## 简介：遮天动画，每周三10:00腾讯视频播出。\n"
    + "冰冷与黑暗并存的宇宙深处，九具庞大的龙尸拉着一口青铜古棺。" * 60
    + "\n截至目前，遮天动画已更新到第179集，对应小说约第1100章。\n"
    + "其他无关内容。" * 200
)


def test_terms_cover_english_words_and_chinese_pairs():
    terms = mode_chats.search_terms("遮天动画更新到哪里了", "PostgreSQL 18 vs the MySQL")
    assert terms["postgresql"] == 2 and terms["18"] == 2 and terms["mysql"] == 2
    assert "the" not in terms and "vs" not in terms
    assert terms["遮天"] == 1 and terms["动画"] == 1 and "了" not in "".join(terms)


def test_excerpt_keeps_the_lead_and_the_passage_about_the_question():
    terms = mode_chats.search_terms("遮天动画更新到第几集 对应小说多少章")
    excerpt = mode_chats.relevant_excerpt(PAGE, terms, 600)
    assert len(excerpt) <= 602
    assert excerpt.startswith("# 遮天")
    assert "已更新到第179集，对应小说约第1100章" in excerpt
    assert " … " in excerpt
    # the old way, the head of the page, would have missed it
    assert "第179集" not in PAGE[:1600]


def test_short_pages_stay_whole_and_unrelated_ones_are_cut_from_the_top():
    assert mode_chats.relevant_excerpt("短短\n一页", {"遮天": 1}, 600) == "短短 一页"
    assert mode_chats.relevant_excerpt("无关。" * 400, {"遮天": 1}, 100) == ("无关。" * 400)[:100]


def test_sources_continue_after_existing_ones_and_skip_their_pages():
    found = {
        "queries": ["遮天 最新集数"],
        "docs": [
            {"url": "https://old.example", "title": "old", "content": "x" * 100},
            {"url": "https://new.example", "title": "new", "content": PAGE},
            {"url": "https://tiny.example", "title": "tiny", "content": "太短"},
        ],
    }
    existing = [{"n": 1, "url": "https://old.example", "title": "old", "excerpt": "x"}]
    sources = mode_chats.sources_from_docs(found, 5, 600, question="遮天动画更新到第几集", existing=existing)
    assert [(s["n"], s["url"]) for s in sources] == [(2, "https://new.example")]
    assert "第179集" in sources[0]["excerpt"]


def test_images_and_link_addresses_are_left_out():
    page = "![logo](//cdn.example/l.png) 登录 [遮天](https://qidian.example/a) 动画 " + "无关。" * 400
    excerpt = mode_chats.relevant_excerpt(page, {"遮天": 1}, 300)
    assert "cdn.example" not in excerpt and "qidian.example" not in excerpt and "遮天" in excerpt
