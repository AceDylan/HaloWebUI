import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from open_webui.utils.discussion_profiles import planning_profile


@pytest.mark.parametrize("alias", ["grok-chat", "glm-chat", "kimi-chat", "gpt-chat"])
def test_an_alias_is_not_a_verified_version(alias):
    assert planning_profile({"id": alias}) == {"version": "unknown"}


def test_profiles_are_connection_scoped_and_only_expose_planning_fields():
    def model(version):
        return {"id": "glm-chat", "info": {"meta": {
            "description": "中文资料归纳", "private_value": "not-for-the-prompt",
            "discussion_profile": {"version": version, "family": "glm", "strengths": ["摘要"],
                                   "suggested_roles": ["资料归纳"], "limitations": ["未测试联网"],
                                   "version_source": "provider response.model", "verified_at": "2026-10-18",
                                   "context_window": 128000, "vision": True, "private_value": "secret"}}}}
    first, second = planning_profile(model("version-a")), planning_profile(model("version-b"))
    assert first["version"] == "version-a" and second["version"] == "version-b"
    assert first["description"] == "中文资料归纳" and first["strengths"] == ["摘要"]
    assert first["context_window"] == 128000 and first["verified_at"] == "2026-10-18"
    assert "private_value" not in first and "vision" not in first


@pytest.mark.parametrize("meta", [None, [], "bad", {"discussion_profile": []},
                                  {"discussion_profile": {"version": {}, "strengths": "bad", "context_window": True}}])
def test_invalid_metadata_does_not_break_planning(meta):
    assert planning_profile({"info": {"meta": meta}}) == {"version": "unknown"}


def test_profile_size_is_bounded():
    profile = planning_profile({"info": {"meta": {"description": "x" * 1000,
        "discussion_profile": {"version": "v" * 200, "strengths": ["s" * 200] * 20,
                               "limitations": [None, {}, "", "limit"]}}}})
    assert len(profile["description"]) == 600 and len(profile["version"]) == 120
    assert len(profile["strengths"]) == 6 and all(len(s) == 160 for s in profile["strengths"])
    assert profile["limitations"] == ["limit"]
