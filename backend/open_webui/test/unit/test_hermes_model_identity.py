"""is_hermes_agent_model must recognise every id shape this fork hands around:
the upstream id, the legacy "<connection>.<id>" prefix, the modelref:: selection
id the UI sends, and the decorated model dicts get_all_models returns."""

from open_webui.utils.hermes_agent import _model_upstream_id, is_hermes_agent_model

SELECTION = "modelref::openai::personal::id:ee5e02db::hermes-agent"
OTHER_SELECTION = "modelref::openai::personal::id:c153e2d2::gpt-chat"


def test_selection_id_strings_resolve_to_the_upstream_id():
    assert is_hermes_agent_model(SELECTION)
    assert not is_hermes_agent_model(OTHER_SELECTION)
    assert _model_upstream_id(OTHER_SELECTION) == "gpt-chat"


def test_legacy_forms_still_match():
    assert is_hermes_agent_model("hermes-agent")
    assert is_hermes_agent_model("ee5e02db.hermes-agent")
    assert not is_hermes_agent_model("gpt-chat")
    assert not is_hermes_agent_model("")
    assert not is_hermes_agent_model(None)


def test_model_dicts_match_by_decoration_or_by_selection_id():
    assert is_hermes_agent_model({"id": SELECTION})
    assert is_hermes_agent_model({"id": "anything", "original_id": "hermes-agent"})
    assert is_hermes_agent_model({"id": "anything", "model_id": "hermes-agent"})
    assert not is_hermes_agent_model({"id": OTHER_SELECTION, "original_id": "gpt-chat"})
    assert not is_hermes_agent_model({})
