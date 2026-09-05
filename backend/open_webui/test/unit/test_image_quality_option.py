import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers.images import (  # noqa: E402
    _CAPABILITY_OVERRIDE_BOOL_FIELDS,
    GenerateImageForm,
    _classify_openai_image_model,
    _normalize_openai_image_quality,
)
from open_webui.utils.image_generation_options import (  # noqa: E402
    CHAT_IMAGE_GENERATION_OPTION_KEYS,
    sanitize_chat_image_generation_options,
)


def test_quality_normalizes_to_the_gpt_image_tiers_and_drops_auto():
    assert _normalize_openai_image_quality(" High ") == "high"
    assert _normalize_openai_image_quality("low") == "low"
    assert _normalize_openai_image_quality("medium") == "medium"
    # auto is the upstream default: omit the field rather than send it
    assert _normalize_openai_image_quality("auto") is None
    assert _normalize_openai_image_quality("ultra") is None
    assert _normalize_openai_image_quality(None) is None


def test_bare_gpt_image_relay_alias_advertises_quality_and_background():
    # The relay maps the bare "gpt-image" id onto gpt-image-1/2 dynamically;
    # the family, not the exact suffix, decides the capability.
    classified = _classify_openai_image_model(
        {"id": "gpt-image", "name": "gpt-image"},
        base_url="https://relay.example/v1",
        api_config={},
        source={"effective_source": "personal"},
    )

    assert classified is not None
    assert classified["generation_mode"] == "openai_images"
    assert classified["supports_quality"] is True
    assert classified["supports_background"] is True


def test_chat_image_models_do_not_advertise_quality():
    classified = _classify_openai_image_model(
        {"id": "gemini-2.5-flash-image-preview", "name": "nano banana"},
        base_url="https://relay.example/v1",
        api_config={},
        source={"effective_source": "personal"},
    )

    assert classified is None or classified["supports_quality"] is False


def test_quality_travels_through_chat_options_overrides_and_the_form():
    assert "quality" in CHAT_IMAGE_GENERATION_OPTION_KEYS
    assert sanitize_chat_image_generation_options(
        {"quality": "low", "background": "transparent", "junk": 1}
    ) == {"quality": "low", "background": "transparent"}
    assert GenerateImageForm(prompt="cat", quality="medium").quality == "medium"
    assert GenerateImageForm(prompt="cat").quality is None
    assert "supports_quality" in _CAPABILITY_OVERRIDE_BOOL_FIELDS
