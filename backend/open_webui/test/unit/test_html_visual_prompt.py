from open_webui.utils.hermes_agent import _build_run_payload
from open_webui.utils.html_visual_prompt import (
    HTML_VISUAL_PROMPT_MARKER,
    apply_html_visual_prompt_overlay,
    should_apply_html_visual_prompt,
)


def _form_data():
    return {
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "做一个奖项体系对比"},
        ]
    }


def test_html_visual_prompt_injects_for_halowebui_web_surface():
    metadata = {
        "features": {
            "html_visual_artifacts": True,
            "html_visual_surface": "halowebui-web",
        }
    }

    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

    messages = form_data["messages"]
    assert [message["role"] for message in messages] == ["system", "system", "user"]
    assert HTML_VISUAL_PROMPT_MARKER in messages[1]["content"]
    assert "Telegram" in messages[1]["content"]
    assert metadata["html_visual_artifacts"]["enabled"] is True


def test_html_visual_prompt_is_not_injected_for_telegram_surface():
    for mode in (True, "force"):
        for surface in (
            "telegram",
            "telegram:webhook",
            "web/telegram",
            "halo-telegram",
            "tg-bot",
            "sms",
        ):
            metadata = {
                "features": {
                    "html_visual_artifacts": mode,
                    "html_visual_surface": surface,
                }
            }

            form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

            assert len(form_data["messages"]) == 2
            assert not should_apply_html_visual_prompt(metadata)


def test_trusted_plain_text_metadata_overrides_client_web_surface():
    for key in ("surface", "source"):
        metadata = {
            key: "telegram:webhook",
            "features": {
                "html_visual_artifacts": "force",
                "html_visual_surface": "halowebui-web",
            },
        }

        form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

        assert len(form_data["messages"]) == 2
        assert not should_apply_html_visual_prompt(metadata)


def test_html_visual_prompt_is_not_injected_without_explicit_feature():
    metadata = {"features": {}}

    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

    assert len(form_data["messages"]) == 2


def test_html_visual_prompt_flows_into_hermes_run_instructions():
    metadata = {
        "chat_id": "chat-1",
        "features": {
            "html_visual_artifacts": "auto",
            "html_visual_surface": "halowebui-web",
        },
    }
    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

    payload = _build_run_payload(form_data, metadata, "hermes-agent")

    assert payload["input"] == "做一个奖项体系对比"
    assert "You are concise." in payload["instructions"]
    assert HTML_VISUAL_PROMPT_MARKER in payload["instructions"]
    assert payload["session_id"] == "chat-1"


def test_html_visual_prompt_is_idempotent():
    metadata = {
        "features": {
            "html_visual_artifacts": True,
            "html_visual_surface": "halowebui-web",
        }
    }
    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)
    form_data = apply_html_visual_prompt_overlay(form_data, metadata)

    assert str(form_data["messages"]).count(HTML_VISUAL_PROMPT_MARKER) == 1
