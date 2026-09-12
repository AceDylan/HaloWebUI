import asyncio
import pathlib
import sys
from types import SimpleNamespace

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.chat_image_prompt import (  # noqa: E402
    compose_chat_image_prompt,
    get_preset_system_prompt,
    is_preset_model,
    resolve_chat_image_model_selection,
)

BASE_SELECTION = "modelref::openai::personal::id:c153e2d2::gpt-image"


def _preset_model(**overrides):
    """Shape produced by utils/models.py for a workspace preset ("助手")."""
    model = {
        "id": "hand-drawn-infographic",
        "selection_id": "hand-drawn-infographic",
        "name": "手绘信息图助手",
        "owned_by": "openai",
        "preset": True,
        "model_ref": {
            "provider": "openai",
            "source": "personal",
            "connection_id": "c153e2d2",
        },
        "info": {
            "id": "hand-drawn-infographic",
            "base_model_id": BASE_SELECTION,
            "params": {"system": "Hand-drawn infographic. Content: {{USER_INPUT}}"},
            "meta": {
                "base_model_ref": {
                    "provider": "openai",
                    "source": "personal",
                    "connection_id": "c153e2d2",
                },
                "base_selection_id": BASE_SELECTION,
            },
        },
    }
    model.update(overrides)
    return model


def test_preset_resolves_to_base_image_model_not_preset_id():
    selected, model_ref = resolve_chat_image_model_selection(_preset_model())

    assert selected == "gpt-image"
    assert model_ref["provider"] == "openai"
    assert model_ref["connection_id"] == "c153e2d2"


def test_preset_with_plain_base_model_id_keeps_the_base_name():
    model = _preset_model()
    model["info"]["base_model_id"] = "gpt-image-2"
    model["info"]["meta"].pop("base_selection_id")

    selected, model_ref = resolve_chat_image_model_selection(model)

    assert selected == "gpt-image-2"
    assert model_ref == {}


def test_preset_with_legacy_prefixed_base_unwraps_connection_id():
    model = _preset_model()
    model["info"]["base_model_id"] = "d7f188cd.gpt-image-2"
    model["info"]["meta"].pop("base_selection_id")

    selected, model_ref = resolve_chat_image_model_selection(model)

    assert selected == "gpt-image-2"
    assert model_ref == {"connection_id": "d7f188cd"}


def test_regular_model_keeps_previous_priority_order():
    model = {
        "id": BASE_SELECTION,
        "model_id": "gpt-image",
        "original_id": "gpt-image",
        "info": {"base_model_id": None},
    }

    selected, model_ref = resolve_chat_image_model_selection(model)

    assert selected == "gpt-image"
    assert model_ref == {}


def test_regular_model_with_selection_id_only_is_unwrapped():
    selected, model_ref = resolve_chat_image_model_selection({"id": BASE_SELECTION})

    assert selected == "gpt-image"
    assert model_ref["connection_id"] == "c153e2d2"


def test_regular_model_with_generic_base_model_id_is_not_treated_as_preset():
    # Legacy rows carry owned_by-like strings in base_model_id; without the
    # preset marker they must not turn into the upstream model name.
    model = {"id": "gpt-image-2", "info": {"base_model_id": "openai"}}

    assert not is_preset_model(model)
    assert resolve_chat_image_model_selection(model)[0] == "gpt-image-2"


def test_fallback_model_id_used_when_model_is_empty():
    assert resolve_chat_image_model_selection(None, "gpt-image-2") == (
        "gpt-image-2",
        {},
    )


def test_preset_system_prompt_only_for_presets():
    assert (
        get_preset_system_prompt(_preset_model())
        == "Hand-drawn infographic. Content: {{USER_INPUT}}"
    )
    assert (
        get_preset_system_prompt(
            {"id": "gpt-image", "info": {"params": {"system": "x"}}}
        )
        == ""
    )


def test_compose_prompt_fills_user_input_placeholder():
    prompt = compose_chat_image_prompt(
        "Style rules.\n\nContent:\n{{USER_INPUT}}\n\nEnd.", "三个要点：温暖、慵懒、阳光"
    )

    assert prompt == "Style rules.\n\nContent:\n三个要点：温暖、慵懒、阳光\n\nEnd."


def test_compose_prompt_placeholder_is_case_insensitive_and_repeated():
    prompt = compose_chat_image_prompt("A {{ prompt }} / B {{USER_INPUT}}", "cat")

    assert prompt == "A cat / B cat"


def test_compose_prompt_appends_when_no_placeholder():
    assert compose_chat_image_prompt("Hand-drawn style.", "a cat") == (
        "Hand-drawn style.\n\na cat"
    )


def test_compose_prompt_without_system_prompt_is_user_message():
    assert compose_chat_image_prompt("", "  a cat ") == "a cat"
    assert compose_chat_image_prompt(None, "a cat") == "a cat"


def test_compose_prompt_without_user_message_keeps_system_prompt():
    assert compose_chat_image_prompt("Hand-drawn style.", "") == "Hand-drawn style."


def test_compose_prompt_applies_prompt_variables():
    prompt = compose_chat_image_prompt(
        "For {{USER_NAME}}: {{USER_INPUT}}", "a cat", {"{{USER_NAME}}": "Ace"}
    )

    assert prompt == "For Ace: a cat"


def test_compose_prompt_user_text_with_backslashes_is_literal():
    assert compose_chat_image_prompt("{{USER_INPUT}}", r"C:\new\1") == r"C:\new\1"


def test_chat_image_generation_handler_sends_composed_prompt(monkeypatch):
    from open_webui.utils import middleware

    captured = {}

    async def fake_image_generations(request, form_data, user):
        captured["prompt"] = form_data.prompt
        captured["chat_generation"] = form_data.chat_generation
        return [{"url": "/api/v1/files/abc/content"}]

    monkeypatch.setattr(middleware, "image_generations", fake_image_generations)

    events = []

    async def emitter(event):
        events.append(event)

    form_data = {
        "model": "hand-drawn-infographic",
        "messages": [{"role": "user", "content": "三个要点：温暖、慵懒、阳光"}],
        "stream": False,
    }
    extra_params = {
        "__event_emitter__": emitter,
        "__metadata__": {"image_generation_options": {"n": 1}},
    }

    asyncio.run(
        middleware.chat_image_generation_handler(
            SimpleNamespace(state=SimpleNamespace()),
            form_data,
            extra_params,
            SimpleNamespace(id="user-1"),
            model=_preset_model(),
        )
    )

    assert (
        captured["prompt"]
        == "Hand-drawn infographic. Content: 三个要点：温暖、慵懒、阳光"
    )
    assert captured["chat_generation"] is True
    local_response = extra_params["__metadata__"]["local_response"]
    images = local_response["choices"][0]["message"]["images"]
    assert images[0]["status"] == "success"


def test_chat_image_generation_handler_ignores_prompt_of_text_model_presets(
    monkeypatch,
):
    from open_webui.utils import middleware

    captured = {}

    async def fake_image_generations(request, form_data, user):
        captured["prompt"] = form_data.prompt
        return [{"url": "/api/v1/files/abc/content"}]

    monkeypatch.setattr(middleware, "image_generations", fake_image_generations)

    async def emitter(event):
        pass

    text_preset = _preset_model()
    text_preset["info"][
        "base_model_id"
    ] = "modelref::openai::personal::id:13c104eb::gpt-chat"
    text_preset["info"]["meta"]["base_selection_id"] = text_preset["info"][
        "base_model_id"
    ]

    asyncio.run(
        middleware.chat_image_generation_handler(
            SimpleNamespace(state=SimpleNamespace()),
            {
                "model": "hand-drawn-infographic",
                "messages": [{"role": "user", "content": "a cat"}],
            },
            {"__event_emitter__": emitter, "__metadata__": {}},
            SimpleNamespace(id="user-1"),
            model=text_preset,
        )
    )

    assert captured["prompt"] == "a cat"
