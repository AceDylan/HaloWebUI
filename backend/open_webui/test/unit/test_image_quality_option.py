import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers.images import (  # noqa: E402
    _CAPABILITY_OVERRIDE_BOOL_FIELDS,
    GenerateImageForm,
    _classify_openai_image_model,
    _normalize_openai_image_background,
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


def test_background_is_opaque_unless_transparent_is_chosen():
    # Left at auto, the relay's gpt-image returned fully transparent PNGs.
    assert _normalize_openai_image_background(" Transparent ") == "transparent"
    for value in (None, "", "auto", "opaque", "white", "black"):
        assert _normalize_openai_image_background(value) == "opaque"


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


def test_a_rejected_default_background_is_dropped_and_sent_once_more():
    import asyncio

    from open_webui.routers.images import _send_dropping_default_background

    def run(payload, statuses):
        sent = []

        async def send(body):
            sent.append(dict(body))
            return {"status": statuses[len(sent) - 1]}, {}

        result, _ = asyncio.run(_send_dropping_default_background(send, payload))
        return result["status"], sent

    # The relay's sunburst model: "background is only supported for GPT image models".
    status, sent = run({"prompt": "p", "background": "opaque"}, [400, 200])
    assert status == 200
    assert sent == [{"prompt": "p", "background": "opaque"}, {"prompt": "p"}]

    # A transparent background the person asked for is not silently dropped.
    status, sent = run({"prompt": "p", "background": "transparent"}, [400])
    assert (status, len(sent)) == (400, 1)

    # Other failures and successes are left alone.
    assert run({"prompt": "p", "background": "opaque"}, [500])[0] == 500
    assert len(run({"prompt": "p", "background": "opaque"}, [200])[1]) == 1


def test_a_refused_default_background_is_not_sent_again_for_a_while(monkeypatch):
    import asyncio

    from open_webui.routers import images

    clock = [1000.0]
    monkeypatch.setattr(images.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(images, "_background_refused_until", {})
    sent = []

    def run(payload, statuses, route="https://relay/v1/images/generations"):
        start = len(sent)

        async def send(body):
            sent.append(dict(body))
            return {"status": statuses[len(sent) - start - 1]}, {}

        result, _ = asyncio.run(images._send_dropping_default_background(send, payload, route=route))
        return result["status"], sent[start:]

    opaque = {"model": "gpt-image", "prompt": "p", "background": "opaque"}
    # The first image finds out (400, then 200 without the field) ...
    assert run(opaque, [400, 200]) == (200, [opaque, {"model": "gpt-image", "prompt": "p"}])
    # ... the next ones go out without it straight away, no failed request first.
    assert run(opaque, [200]) == (200, [{"model": "gpt-image", "prompt": "p"}])
    # Another endpoint (edits) or model is asked as before; an explicit transparent is always sent.
    assert run(opaque, [200], route="https://relay/v1/images/edits")[1] == [opaque]
    assert run({**opaque, "model": "gpt-image-2"}, [200])[1][0]["background"] == "opaque"
    transparent = {**opaque, "background": "transparent"}
    assert run(transparent, [200])[1] == [transparent]
    # After a few hours the field is tried again (the relay may route to a model that takes it).
    clock[0] += images.BACKGROUND_REFUSAL_TTL_SECONDS + 1
    assert run(opaque, [200])[1] == [opaque]

    # A retry that fails too says nothing about the field: nothing is remembered.
    monkeypatch.setattr(images, "_background_refused_until", {})
    assert run(opaque, [400, 400])[0] == 400
    assert run(opaque, [200])[1] == [opaque]
