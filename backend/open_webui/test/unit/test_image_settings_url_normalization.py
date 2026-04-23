import pathlib
import sys
import asyncio
from types import SimpleNamespace


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import images as images_router  # noqa: E402
from open_webui.routers.images import _normalize_image_provider_base_url  # noqa: E402
from open_webui.routers.images import _generate_via_xai_images  # noqa: E402
from open_webui.routers.images import _resolve_image_provider_source  # noqa: E402
from open_webui.routers.images import _select_runtime_image_provider_source  # noqa: E402
from open_webui.routers.images import _sync_image_provider_config_state  # noqa: E402


def test_openai_image_settings_auto_append_v1():
    normalized, force_mode = _normalize_image_provider_base_url(
        "https://api.example.com",
        "/v1",
    )

    assert normalized == "https://api.example.com/v1"
    assert force_mode is False


def test_openai_image_settings_preserve_irregular_version_path():
    normalized, force_mode = _normalize_image_provider_base_url(
        "https://relay.example.com/api/v3",
        "/v1",
    )

    assert normalized == "https://relay.example.com/api/v3"
    assert force_mode is False


def test_openai_image_settings_strip_known_endpoint_suffixes():
    normalized, force_mode = _normalize_image_provider_base_url(
        "https://api.example.com/v1/chat/completions",
        "/v1",
    )

    assert normalized == "https://api.example.com/v1"
    assert force_mode is False


def test_openai_image_settings_hash_enables_exact_mode():
    normalized, force_mode = _normalize_image_provider_base_url(
        "https://relay.example.com/custom/path#",
        "/v1",
    )

    assert normalized == "https://relay.example.com/custom/path"
    assert force_mode is True


def test_gemini_image_settings_force_mode_is_preserved_from_payload():
    normalized, force_mode = _normalize_image_provider_base_url(
        "https://generativelanguage.googleapis.com/custom",
        "/v1beta",
        force_mode=True,
    )

    assert normalized == "https://generativelanguage.googleapis.com/custom"
    assert force_mode is True


def test_image_settings_source_does_not_inherit_global_openai_auth_config_when_key_is_explicit():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com/v1",
        IMAGES_OPENAI_API_KEY="image-key",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=["https://api.example.com/v1"],
        OPENAI_API_KEYS=["global-key"],
        OPENAI_API_CONFIGS={"0": {"auth_type": "api-key", "force_mode": True}},
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="openai",
        context="settings",
    )

    assert source is not None
    assert source["key"] == "image-key"
    assert source["api_config"] == {}


def test_image_runtime_shared_source_keeps_image_force_mode_while_merging_global_config():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com/v1",
        IMAGES_OPENAI_API_KEY="image-key",
        IMAGES_OPENAI_API_FORCE_MODE=True,
        OPENAI_API_BASE_URLS=["https://api.example.com/v1"],
        OPENAI_API_KEYS=["global-key"],
        OPENAI_API_CONFIGS={"0": {"auth_type": "bearer"}},
        ENABLE_IMAGE_GENERATION_SHARED_KEY=True,
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="openai",
        context="runtime",
        credential_source="shared",
    )

    assert source is not None
    assert source["api_config"]["auth_type"] == "bearer"
    assert source["api_config"]["force_mode"] is True


def test_image_runtime_explicit_shared_source_uses_shared_config_even_when_toggle_is_disabled():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com/v1",
        IMAGES_OPENAI_API_KEY="image-key",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=["https://api.example.com/v1"],
        OPENAI_API_KEYS=["global-key"],
        OPENAI_API_CONFIGS={},
        ENABLE_IMAGE_GENERATION_SHARED_KEY=False,
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="openai",
        context="runtime",
        credential_source="shared",
    )

    assert source is not None
    assert source["effective_source"] == "shared"
    assert source["key"] == "image-key"


def test_image_runtime_explicit_shared_source_can_fallback_to_global_key():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com/v1",
        IMAGES_OPENAI_API_KEY="",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=["https://api.example.com/v1"],
        OPENAI_API_KEYS=["global-key"],
        OPENAI_API_CONFIGS={"0": {"auth_type": "bearer"}},
        ENABLE_IMAGE_GENERATION_SHARED_KEY=False,
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="openai",
        context="runtime",
        credential_source="shared",
    )

    assert source is not None
    assert source["effective_source"] == "shared"
    assert source["key"] == "global-key"
    assert source["api_config"]["auth_type"] == "bearer"


def test_image_settings_source_normalizes_legacy_openai_base_url_without_v1():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com",
        IMAGES_OPENAI_API_KEY="image-key",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=[],
        OPENAI_API_KEYS=[],
        OPENAI_API_CONFIGS={},
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="openai",
        context="settings",
    )

    assert source is not None
    assert source["base_url"] == "https://api.example.com/v1"
    assert source["api_config"] == {}


def test_sync_image_provider_config_state_persists_normalized_legacy_urls():
    class DummyConfig(SimpleNamespace):
        def __setattr__(self, key, value):
            super().__setattr__(key, value)

    cfg = DummyConfig(
        IMAGES_OPENAI_API_BASE_URL="https://api.example.com",
        IMAGES_OPENAI_API_KEY="image-key",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        IMAGES_GEMINI_API_BASE_URL="https://generativelanguage.googleapis.com",
        IMAGES_GEMINI_API_KEY="gemini-key",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        IMAGES_GROK_API_BASE_URL="https://api.x.ai",
        IMAGES_GROK_API_KEY="grok-key",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    _sync_image_provider_config_state(request)

    assert cfg.IMAGES_OPENAI_API_BASE_URL == "https://api.example.com/v1"
    assert cfg.IMAGES_OPENAI_API_FORCE_MODE is False
    assert cfg.IMAGES_GEMINI_API_BASE_URL == "https://generativelanguage.googleapis.com/v1beta"
    assert cfg.IMAGES_GEMINI_API_FORCE_MODE is False
    assert cfg.IMAGES_GROK_API_BASE_URL == "https://api.x.ai/v1"


def test_auto_runtime_source_matches_selected_model_across_personal_connections(monkeypatch):
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="https://shared.example.com/v1",
        IMAGES_OPENAI_API_KEY="shared-key",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=["https://shared.example.com/v1"],
        OPENAI_API_KEYS=["shared-key"],
        OPENAI_API_CONFIGS={},
        ENABLE_IMAGE_GENERATION_SHARED_KEY=True,
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))
    user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(
        images_router.openai_router,
        "_get_openai_user_config",
        lambda _user: (
            [
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "https://ark.cn-beijing.volces.com/api/v3",
            ],
            ["aliyun-key", "volc-key"],
            {},
        ),
    )

    async def fake_discover(_request, _user, engine, source):
        assert engine == "openai"
        if "volces.com" in source.get("base_url", ""):
            return [{"id": "doubao-seedream-4-5-251128"}]
        return [{"id": "wanx2.1-t2i-turbo"}]

    monkeypatch.setattr(images_router, "_discover_image_models_for_source", fake_discover)

    source, discovered_models = asyncio.run(
        _select_runtime_image_provider_source(
            request,
            user,
            "openai",
            selected_model="doubao-seedream-4-5-251128",
        )
    )

    assert source is not None
    assert source["effective_source"] == "personal"
    assert source["connection_index"] == 1
    assert discovered_models == [{"id": "doubao-seedream-4-5-251128"}]


def test_grok_settings_source_uses_grok_shared_config():
    cfg = SimpleNamespace(
        IMAGES_OPENAI_API_BASE_URL="",
        IMAGES_OPENAI_API_KEY="",
        IMAGES_OPENAI_API_FORCE_MODE=False,
        OPENAI_API_BASE_URLS=[],
        OPENAI_API_KEYS=[],
        OPENAI_API_CONFIGS={},
        IMAGES_GEMINI_API_BASE_URL="",
        IMAGES_GEMINI_API_KEY="",
        IMAGES_GEMINI_API_FORCE_MODE=False,
        GEMINI_API_BASE_URLS=[],
        GEMINI_API_KEYS=[],
        GEMINI_API_CONFIGS={},
        IMAGES_GROK_API_BASE_URL="https://api.x.ai/v1",
        IMAGES_GROK_API_KEY="grok-key",
        GROK_API_BASE_URLS=["https://api.x.ai/v1"],
        GROK_API_KEYS=["grok-key"],
        GROK_API_CONFIGS={"0": {"auth_type": "bearer"}},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))

    source = _resolve_image_provider_source(
        request,
        user=None,
        provider="grok",
        context="settings",
    )

    assert source is not None
    assert source["base_url"] == "https://api.x.ai/v1"
    assert source["key"] == "grok-key"


def test_volcengine_chat_image_falls_back_to_images_endpoint(monkeypatch):
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(images_router, "_build_openai_image_headers", lambda *_args, **_kwargs: {})

    class FakeResponse:
        status_code = 429

    monkeypatch.setattr(images_router.requests, "post", lambda *args, **kwargs: FakeResponse())

    async def fake_images_endpoint(_request, _user, **kwargs):
        assert kwargs["model_id"] == "doubao-seedream-4-5-251128"
        assert kwargs["size"] == "1024x1024"
        return [{"url": "/api/v1/files/fallback-image"}]

    monkeypatch.setattr(
        images_router,
        "_generate_via_openai_images_endpoint",
        fake_images_endpoint,
    )

    result = asyncio.run(
        images_router._generate_via_openai_chat_image(
            request,
            user,
            model_id="doubao-seedream-4-5-251128",
            prompt="draw a dog",
            n=1,
            size="1024x1024",
            background=None,
            source={
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "key": "volc-key",
                "api_config": {},
            },
            model_meta={"text_output_supported": True},
        )
    )

    assert result == [{"url": "/api/v1/files/fallback-image"}]


def test_xai_generation_payload_only_uses_supported_fields(monkeypatch):
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")
    captured_payloads = []

    monkeypatch.setattr(images_router, "_build_openai_image_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(images_router, "upload_image", lambda *_args, **_kwargs: "/api/v1/files/generated")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"b64_json": "YWJj"}]}

    def fake_post(_url, json=None, headers=None, timeout=None, verify=None):
        captured_payloads.append(dict(json or {}))
        return FakeResponse()

    monkeypatch.setattr(images_router.requests, "post", fake_post)

    result = asyncio.run(
        _generate_via_xai_images(
            request,
            user,
            model_id="grok-imagine-image",
            prompt="health check",
            n=1,
            source={
                "base_url": "https://api.x.ai/v1",
                "key": "grok-key",
                "api_config": {},
            },
            aspect_ratio="16:9",
            resolution="2k",
            fallback_size="1024x1024",
        )
    )

    assert result == [{"url": "/api/v1/files/generated"}]
    assert captured_payloads == [
        {
            "model": "grok-imagine-image",
            "prompt": "health check",
            "n": 1,
            "response_format": "b64_json",
            "aspect_ratio": "16:9",
            "resolution": "2k",
        }
    ]
