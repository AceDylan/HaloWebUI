import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import open_webui.routers.images as images  # noqa: E402
from open_webui.routers.images import (  # noqa: E402
    _apply_capability_overrides,
    _capability_override_match_score,
    _engine_from_generation_mode,
    _gemini_image_size_fallback_steps,
    _is_image_size_param_error,
    _learn_unsupported_image_sizes,
    _normalize_capability_overrides,
    _resolve_gemini_image_size_to_send,
    _validate_capability_overrides_payload,
)


def _fake_request(overrides=None):
    cfg = SimpleNamespace(
        IMAGES_MODEL_CAPABILITY_OVERRIDES=({} if overrides is None else overrides)
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=cfg)))


def _entry(model_id="gpt-image-3", generation_mode="openai_images", **caps):
    base = {
        "id": model_id,
        "model_id": model_id,
        "generation_mode": generation_mode,
        "supports_background": False,
        "supports_batch": True,
        "supports_image_size": False,
        "supports_resolution": False,
        "size_mode": "exact",
        "text_output_supported": False,
    }
    base.update(caps)
    return base


# --------------------------------------------------------------------------
# _engine_from_generation_mode
# --------------------------------------------------------------------------


def test_engine_from_generation_mode():
    assert _engine_from_generation_mode("openai_images") == "openai"
    assert _engine_from_generation_mode("openai_chat_image") == "openai"
    assert _engine_from_generation_mode("gemini_generate_content_image") == "gemini"
    assert _engine_from_generation_mode("gemini_predict") == "gemini"
    assert _engine_from_generation_mode("xai_images") == "grok"
    assert _engine_from_generation_mode("") == ""
    assert _engine_from_generation_mode(None) == ""


# --------------------------------------------------------------------------
# _normalize_capability_overrides
# --------------------------------------------------------------------------


def test_normalize_drops_non_dict_and_lowercases_keys():
    raw = {
        "OpenAI:GPT-Image-3": {"supports_image_size": True},
        "  ": {"supports_image_size": True},  # blank key dropped
        "bad": "not-a-dict",  # non-dict value dropped
    }
    norm = _normalize_capability_overrides(raw)
    assert norm == {"openai:gpt-image-3": {"supports_image_size": True}}


def test_normalize_non_dict_input_returns_empty():
    assert _normalize_capability_overrides(None) == {}
    assert _normalize_capability_overrides("x") == {}
    assert _normalize_capability_overrides([]) == {}


# --------------------------------------------------------------------------
# _capability_override_match_score
# --------------------------------------------------------------------------


def test_match_score_exact_engine_qualified_beats_agnostic_and_prefix():
    engine, base = "openai", "gpt-image-3"
    exact_qualified = _capability_override_match_score(
        "openai:gpt-image-3", engine, base
    )
    exact_agnostic = _capability_override_match_score("gpt-image-3", engine, base)
    prefix = _capability_override_match_score("gpt-image*", engine, base)
    assert exact_qualified > exact_agnostic > prefix > 0


def test_match_score_engine_mismatch_returns_zero():
    assert _capability_override_match_score("gemini:gpt-image-3", "openai", "gpt-image-3") == 0


def test_match_score_prefix_longer_is_more_specific():
    short = _capability_override_match_score("gemini-3*", "gemini", "gemini-3-flash-image")
    long = _capability_override_match_score(
        "gemini-3-flash*", "gemini", "gemini-3-flash-image"
    )
    assert long > short > 0


def test_match_score_non_matching_prefix_is_zero():
    assert _capability_override_match_score("dall-e*", "openai", "gpt-image-3") == 0


# --------------------------------------------------------------------------
# _apply_capability_overrides
# --------------------------------------------------------------------------


def test_apply_no_overrides_returns_entry_unchanged():
    entry = _entry()
    assert _apply_capability_overrides(entry, {}) is entry


def test_apply_enables_capability_for_unknown_new_model():
    # 核心用例：新模型 gpt-image-3 名字匹配不上启发式，靠覆盖打开 background
    entry = _entry(model_id="gpt-image-3", supports_background=False)
    overrides = _normalize_capability_overrides(
        {"openai:gpt-image-3": {"supports_background": True}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_background"] is True
    assert result["capability_override_applied"] is True
    # 原 entry 不被原地修改
    assert entry["supports_background"] is False


def test_apply_override_wins_over_metadata_heuristic():
    # provider 元数据/启发式给的是 False，覆盖强制 True（解析优先级的关键）
    entry = _entry(
        model_id="gemini-4-flash-image",
        generation_mode="gemini_generate_content_image",
        supports_image_size=False,
        size_mode="aspect_ratio",
    )
    overrides = _normalize_capability_overrides(
        {"gemini:gemini-4-flash-image": {"supports_image_size": True}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_image_size"] is True


def test_apply_engine_agnostic_key_matches():
    entry = _entry(model_id="provider/gpt-image-3")  # basename 提取
    overrides = _normalize_capability_overrides(
        {"gpt-image-3": {"supports_image_size": True}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_image_size"] is True


def test_apply_prefix_key_matches():
    entry = _entry(
        model_id="gemini-3-pro-image",
        generation_mode="gemini_generate_content_image",
    )
    overrides = _normalize_capability_overrides(
        {"gemini:gemini-3*": {"supports_image_size": True}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_image_size"] is True


def test_apply_more_specific_key_wins_on_conflict():
    entry = _entry(model_id="gpt-image-3")
    overrides = _normalize_capability_overrides(
        {
            "gpt-image*": {"supports_background": False},  # 低特异度
            "openai:gpt-image-3": {"supports_background": True},  # 高特异度，胜出
        }
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_background"] is True


def test_apply_size_mode_only_accepts_valid_values():
    entry = _entry(size_mode="exact")
    valid = _apply_capability_overrides(
        entry, _normalize_capability_overrides({"gpt-image-3": {"size_mode": "aspect_ratio"}})
    )
    assert valid["size_mode"] == "aspect_ratio"

    invalid = _apply_capability_overrides(
        entry, _normalize_capability_overrides({"gpt-image-3": {"size_mode": "garbage"}})
    )
    assert invalid["size_mode"] == "exact"  # 非法值被忽略，保留原值


def test_apply_learned_unsupported_aggregated_and_sorted():
    entry = _entry()
    overrides = _normalize_capability_overrides(
        {"gpt-image-3": {"_learned_unsupported": ["size:4096x4096", "size:2048x2048", ""]}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["learned_unsupported"] == ["size:2048x2048", "size:4096x4096"]


def test_apply_engine_mismatch_does_not_change_entry():
    entry = _entry(model_id="gpt-image-3", generation_mode="openai_images")
    overrides = _normalize_capability_overrides(
        {"gemini:gpt-image-3": {"supports_image_size": True}}
    )
    result = _apply_capability_overrides(entry, overrides)
    assert result["supports_image_size"] is False
    assert "capability_override_applied" not in result


def test_apply_handles_none_and_idless_entry():
    overrides = _normalize_capability_overrides(
        {"gpt-image-3": {"supports_image_size": True}}
    )
    assert _apply_capability_overrides(None, overrides) is None
    idless = {"generation_mode": "openai_images"}
    assert _apply_capability_overrides(idless, overrides) is idless


# --------------------------------------------------------------------------
# _validate_capability_overrides_payload (admin save 校验)
# --------------------------------------------------------------------------


def test_validate_accepts_dict_of_dicts_and_drops_blank_keys():
    payload = {
        "openai:gpt-image-3": {"supports_background": True},
        "  ": {"supports_image_size": True},  # 空 key 丢弃
    }
    cleaned = _validate_capability_overrides_payload(payload)
    assert cleaned == {"openai:gpt-image-3": {"supports_background": True}}


def test_validate_rejects_non_dict_top_level():
    for bad in (None, "x", [1, 2], 5):
        with pytest.raises(HTTPException) as exc:
            _validate_capability_overrides_payload(bad)
        assert exc.value.status_code == 400


def test_validate_rejects_non_dict_value():
    with pytest.raises(HTTPException) as exc:
        _validate_capability_overrides_payload({"openai:gpt-image-3": "nope"})
    assert exc.value.status_code == 400


def test_validate_preserves_extension_fields():
    payload = {"gpt-image-3": {"_learned_unsupported": ["size:4096x4096"]}}
    cleaned = _validate_capability_overrides_payload(payload)
    assert cleaned == payload


# --------------------------------------------------------------------------
# 阶段 C: _is_image_size_param_error（参数错误白名单 + 负面拦截）
# --------------------------------------------------------------------------


def test_param_error_true_for_size_keyword_4xx():
    assert _is_image_size_param_error(400, "Unsupported image size: 4K") is True
    assert _is_image_size_param_error(422, "invalid imageConfig") is True


def test_param_error_false_for_non_4xx_status():
    assert _is_image_size_param_error(500, "unsupported size") is False
    assert _is_image_size_param_error(429, "size too large") is False
    assert _is_image_size_param_error(401, "unsupported size") is False


def test_param_error_false_when_negative_keyword_present():
    # 即便含 "invalid"，但属鉴权/额度/限流 → 不降级（避免重复计费）
    assert _is_image_size_param_error(400, "invalid api key") is False
    assert _is_image_size_param_error(400, "insufficient balance") is False
    assert _is_image_size_param_error(429, "too many requests") is False


def test_param_error_false_for_unrelated_400():
    assert _is_image_size_param_error(400, "prompt was flagged by safety") is False


# --------------------------------------------------------------------------
# 阶段 C: _gemini_image_size_fallback_steps（降级阶梯，最多 2 步）
# --------------------------------------------------------------------------


def test_fallback_steps_one_lower_then_omit():
    assert _gemini_image_size_fallback_steps("4K") == ["2K", None]
    assert _gemini_image_size_fallback_steps("2K") == ["1K", None]
    assert _gemini_image_size_fallback_steps("1K") == ["512", None]
    assert _gemini_image_size_fallback_steps("512") == [None]


def test_fallback_steps_unrecognized_size_just_omits():
    assert _gemini_image_size_fallback_steps("garbage") == [None]
    assert _gemini_image_size_fallback_steps(None) == [None]


# --------------------------------------------------------------------------
# 阶段 C: _resolve_gemini_image_size_to_send（首次发送决策）
# --------------------------------------------------------------------------


def test_resolve_sends_when_confirmed_supported():
    meta = {"supports_image_size": True, "detection_method": "metadata"}
    assert _resolve_gemini_image_size_to_send(meta, "4K") == "4K"


def test_resolve_optimistic_for_search_candidate():
    meta = {"supports_image_size": False, "detection_method": "search"}
    assert _resolve_gemini_image_size_to_send(meta, "4K") == "4K"


def test_resolve_blocks_learned_unsupported_even_for_search():
    meta = {
        "supports_image_size": False,
        "detection_method": "search",
        "learned_unsupported": ["image_size:4K"],
    }
    assert _resolve_gemini_image_size_to_send(meta, "4K") is None


def test_resolve_no_optimism_for_discovered_unsupported():
    meta = {"supports_image_size": False, "detection_method": "metadata"}
    assert _resolve_gemini_image_size_to_send(meta, "4K") is None


def test_resolve_none_when_no_size_requested():
    assert _resolve_gemini_image_size_to_send({"supports_image_size": True}, None) is None


# --------------------------------------------------------------------------
# 阶段 C: _learn_unsupported_image_sizes（学习写回 + 合并）
# --------------------------------------------------------------------------


def test_learn_writes_back_with_engine_basename_key():
    req = _fake_request({})
    _learn_unsupported_image_sizes(req, "gemini", "models/gemini-4-flash-image", ["4K"])
    assert req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES == {
        "gemini:gemini-4-flash-image": {"_learned_unsupported": ["image_size:4K"]}
    }


def test_learn_merges_with_existing_overrides():
    req = _fake_request(
        {
            "gemini:gemini-4-flash-image": {
                "supports_image_size": True,
                "_learned_unsupported": ["image_size:4K"],
            }
        }
    )
    _learn_unsupported_image_sizes(
        req, "gemini", "gemini-4-flash-image", ["2K", "4K"]
    )
    entry = req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES[
        "gemini:gemini-4-flash-image"
    ]
    assert entry["supports_image_size"] is True  # 既有字段保留
    assert entry["_learned_unsupported"] == ["image_size:2K", "image_size:4K"]


def test_learn_noop_for_empty():
    req = _fake_request({})
    _learn_unsupported_image_sizes(req, "gemini", "m", [None])
    assert req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES == {}


# --------------------------------------------------------------------------
# 阶段 C: _generate_gemini_image_with_size_fallback（降级 + 学习 端到端）
# --------------------------------------------------------------------------


def test_wrapper_degrades_on_param_error_and_learns(monkeypatch):
    calls = []

    async def fake_gen(request, user, *, model_id, prompt, image_size, **kwargs):
        calls.append(image_size)
        if image_size == "4K":
            raise HTTPException(status_code=400, detail="Unsupported image size: 4K")
        return [{"url": "ok"}]

    monkeypatch.setattr(images, "_generate_via_gemini_generate_content", fake_gen)
    req = _fake_request({})
    result = asyncio.run(
        images._generate_gemini_image_with_size_fallback(
            req,
            None,
            model_id="models/gemini-4-flash-image",
            prompt="x",
            image_size="4K",
            aspect_ratio=None,
            source={},
            engine="gemini",
        )
    )
    assert result == [{"url": "ok"}]
    assert calls == ["4K", "2K"]  # 降一档即成功
    learned = req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES[
        "gemini:gemini-4-flash-image"
    ]["_learned_unsupported"]
    assert learned == ["image_size:4K"]


def test_wrapper_does_not_degrade_on_auth_error(monkeypatch):
    calls = []

    async def fake_gen(request, user, *, model_id, prompt, image_size, **kwargs):
        calls.append(image_size)
        raise HTTPException(status_code=401, detail="invalid api key")

    monkeypatch.setattr(images, "_generate_via_gemini_generate_content", fake_gen)
    req = _fake_request({})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            images._generate_gemini_image_with_size_fallback(
                req,
                None,
                model_id="gemini-x",
                prompt="x",
                image_size="4K",
                aspect_ratio=None,
                source={},
                engine="gemini",
            )
        )
    assert exc.value.status_code == 401
    assert calls == ["4K"]  # 未降级，仅一次调用
    assert req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES == {}


def test_wrapper_no_learning_when_all_attempts_fail(monkeypatch):
    calls = []

    async def fake_gen(request, user, *, model_id, prompt, image_size, **kwargs):
        calls.append(image_size)
        raise HTTPException(status_code=400, detail="invalid size value")

    monkeypatch.setattr(images, "_generate_via_gemini_generate_content", fake_gen)
    req = _fake_request({})
    with pytest.raises(HTTPException):
        asyncio.run(
            images._generate_gemini_image_with_size_fallback(
                req,
                None,
                model_id="gemini-x",
                prompt="x",
                image_size="4K",
                aspect_ratio=None,
                source={},
                engine="gemini",
            )
        )
    assert calls == ["4K", "2K", None]  # 全部尝试，含最终省略
    # 从未成功 → 不学习（问题可能不在尺寸）
    assert req.app.state.config.IMAGES_MODEL_CAPABILITY_OVERRIDES == {}
