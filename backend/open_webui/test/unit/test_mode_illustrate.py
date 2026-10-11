"""结论配图 for 精答 / 讨论台: where the picture goes, which template draws it, and when none is drawn."""

import asyncio
import pathlib
import sys
from types import SimpleNamespace

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import answer_desk as desk  # noqa: E402
from open_webui.utils import mode_illustrate as mi  # noqa: E402

READY = {"status": "ready", "url": "/api/v1/files/p/content"}


def test_the_picture_goes_under_the_title_or_on_top():
    assert mi.with_picture("# 标题\n\n正文", READY, "标题") == "# 标题\n\n![标题](/api/v1/files/p/content)\n\n正文"
    assert mi.with_picture("正文\n第二行", READY) == "![配图](/api/v1/files/p/content)\n\n正文\n第二行"
    # not ready, or nothing to put it on: the text as it is
    assert mi.with_picture("正文", {"status": "generating"}) == "正文"
    assert mi.with_picture("正文", None) == "正文"
    assert mi.with_picture("", READY) == ""


def test_the_answer_as_the_chat_keeps_it_has_its_picture_before_its_sources():
    run = {
        "answer": {"content": "用 Postgres。"},
        "research": {"sources": [{"n": 1, "title": "文档", "url": "https://e.com"}]},
        "illustration": READY,
    }
    content = desk.stored_content(run)
    assert content.startswith("![配图](/api/v1/files/p/content)\n\n用 Postgres。")
    assert content.endswith("1. [文档](https://e.com)")


def test_the_template_is_the_users_hand_drawn_one(monkeypatch):
    from open_webui.models import image_studio

    items = [
        SimpleNamespace(id="other", data={"name": "海报", "config": {"prompt": "海报："}}),
        SimpleNamespace(id="mine", data={"name": "手绘万能图（改）", "config": {"prompt": "按名字：", "model": "m2"}}),
        SimpleNamespace(
            id="halo_hand_v1_auto_style",
            data={"name": "手绘万能图 · 自动选画风与画幅", "config": {"prompt": "画：", "model": "modelref::x::gpt-image", "size": "1536x1024", "aspectRatio": "3:2"}},
        ),
    ]
    monkeypatch.setattr(image_studio.ImageStudioItems, "get_items_by_user_id", lambda user_id, kind=None, limit=None: items)
    assert mi.picture_template("u1") == {
        "name": "手绘万能图 · 自动选画风与画幅",
        "prompt": "画：",
        "model": "modelref::x::gpt-image",
        "size": "1536x1024",
        "aspect": "3:2",
    }
    monkeypatch.setattr(image_studio.ImageStudioItems, "get_items_by_user_id", lambda user_id, kind=None, limit=None: items[:2])
    assert mi.picture_template("u1")["prompt"] == "按名字："
    monkeypatch.setattr(image_studio.ImageStudioItems, "get_items_by_user_id", lambda user_id, kind=None, limit=None: items[:1])
    assert mi.picture_template("u1") is None


def test_drawing_uses_the_templates_model_and_canvas(monkeypatch):
    from open_webui.routers import images

    forms = []

    async def fake_generations(request, form, user=None):
        forms.append(form)
        return [{"url": "/api/v1/files/new/content"}]

    monkeypatch.setattr(images, "image_generations", fake_generations)
    template = {"name": "手绘万能图", "prompt": "画：", "model": "modelref::openai::personal::id:c1::gpt-image", "size": "1536x1024", "aspect": "3:2"}
    picture = asyncio.run(mi.draw(None, SimpleNamespace(id="u1"), template, "标题：X"))
    assert forms[0].prompt == "画：\n标题：X" and forms[0].model == template["model"]
    assert forms[0].size == "1536x1024" and forms[0].aspect_ratio == "3:2" and forms[0].background is None
    assert picture == {"url": "/api/v1/files/new/content", "model": "gpt-image", "template": "手绘万能图", "prompt": "画：\n标题：X", "size": "1536x1024"}
    # without a template: the default image model and the plain hand-drawn prompt
    asyncio.run(mi.draw(None, SimpleNamespace(id="u1"), None, "标题：Y"))
    assert forms[1].model is None and forms[1].prompt.startswith(mi.FALLBACK_PROMPT.rstrip())


def test_it_is_off_by_switch_or_without_image_generation(monkeypatch):
    from open_webui.routers import images

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_IMAGE_GENERATION=True))))
    monkeypatch.setattr(images, "_can_use_image_generation", lambda request, user: True)
    assert mi.may_illustrate(request, SimpleNamespace(id="u1")) is True
    monkeypatch.setenv(mi.AUTO_ENV, "0")
    assert mi.may_illustrate(request, SimpleNamespace(id="u1")) is False
    monkeypatch.delenv(mi.AUTO_ENV)
    monkeypatch.setattr(images, "_can_use_image_generation", lambda request, user: False)
    assert mi.may_illustrate(request, SimpleNamespace(id="u1")) is False
    request.app.state.config.ENABLE_IMAGE_GENERATION = False
    monkeypatch.setattr(images, "_can_use_image_generation", lambda request, user: True)
    assert mi.may_illustrate(request, SimpleNamespace(id="u1")) is False


def test_a_condensed_reply_drops_its_thinking(monkeypatch):
    from open_webui.utils import chat as chat_utils

    async def fake(request, payload, user):
        assert payload["stream"] is False and payload["messages"][0]["content"] == mi.CONDENSE_SYSTEM
        return {"choices": [{"message": {"content": "<think>嗯</think>标题：X"}}]}

    monkeypatch.setattr(chat_utils, "generate_chat_completion", fake)
    assert asyncio.run(mi.condense(None, None, "m", "长文", {})) == "标题：X"
