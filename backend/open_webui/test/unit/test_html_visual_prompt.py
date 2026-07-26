import pytest

from open_webui.utils.hermes_agent import _build_run_payload
from open_webui.utils.html_visual_prompt import (
    HTML_VISUAL_FALLBACK_MARKER,
    HTML_VISUAL_FORCE_PROMPT_MARKER,
    HTML_VISUAL_PROMPT_MARKER,
    apply_html_visual_prompt_overlay,
    append_html_visual_fallback,
    has_fenced_html_artifact,
    normalize_html_visual_mode,
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "force"),
        (False, "off"),
        ("force", "force"),
        ("auto", "auto"),
        ("off", "off"),
        (" TRUE ", "force"),
        (None, "off"),
        ("unexpected", "off"),
    ],
)
def test_html_visual_mode_normalizes_legacy_and_explicit_values(value, expected):
    assert normalize_html_visual_mode(value) == expected


def test_force_and_auto_modes_receive_different_prompt_instructions():
    auto_form = apply_html_visual_prompt_overlay(
        _form_data(),
        {
            "features": {
                "html_visual_artifacts": "auto",
                "html_visual_surface": "halowebui-web",
            }
        },
    )
    force_form = apply_html_visual_prompt_overlay(
        _form_data(),
        {
            "features": {
                "html_visual_artifacts": "force",
                "html_visual_surface": "halowebui-web",
            }
        },
    )

    auto_prompt = auto_form["messages"][1]["content"]
    force_prompt = force_form["messages"][1]["content"]
    assert HTML_VISUAL_PROMPT_MARKER in auto_prompt
    assert HTML_VISUAL_PROMPT_MARKER in force_prompt
    assert HTML_VISUAL_FORCE_PROMPT_MARKER not in auto_prompt
    assert HTML_VISUAL_FORCE_PROMPT_MARKER in force_prompt
    assert auto_prompt != force_prompt


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
    metadata = {"features": {"html_visual_surface": "halowebui-web"}}
    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

    assert len(form_data["messages"]) == 2


def test_html_visual_prompt_and_force_fallback_require_explicit_web_surface():
    metadata = {"features": {"html_visual_artifacts": "force"}}
    form_data = apply_html_visual_prompt_overlay(_form_data(), metadata)

    assert len(form_data["messages"]) == 2
    assert not should_apply_html_visual_prompt(metadata)
    assert append_html_visual_fallback("Plain response", metadata) == "Plain response"


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


def _metadata(mode="force", surface="halowebui-web"):
    return {
        "features": {
            "html_visual_artifacts": mode,
            "html_visual_surface": surface,
        }
    }


def test_force_fallback_preserves_original_and_escapes_copied_content():
    original = (
        'Answer **first** <script>alert("x")</script> & https://evil.test/a\n'
        '<details type="tool_calls" result="<unsafe>">tool result</details>\n'
        "```text\nkept code\n```"
    )

    content = append_html_visual_fallback(original, _metadata())

    assert content.startswith(f"{original}\n\n")
    assert content.count(HTML_VISUAL_FALLBACK_MARKER) == 1
    assert content.count("```html\n") == 1
    fallback = content.split("```html\n", 1)[1]
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in fallback
    assert "tool_calls" not in fallback
    assert "tool result" not in fallback
    assert "&#96;&#96;&#96;text" in fallback
    assert "https://" not in fallback
    assert "<script" not in fallback.lower()
    assert "<style" not in fallback.lower()
    assert " class=" not in fallback.lower()
    assert " style=" in fallback.lower()


def test_force_fallback_is_idempotent_and_respects_existing_html_artifact():
    original = "Plain response"
    once = append_html_visual_fallback(original, _metadata())
    twice = append_html_visual_fallback(once, _metadata())
    existing = 'Before\n```HTML\n<div style="color:red">Ready</div>\n```\nAfter'
    longer_closer = "````html\n<div>Ready</div>\n`````"
    nested_in_text = "```text\n```html\n<div>Example only</div>\n```\n```"

    assert twice == once
    assert twice.count(HTML_VISUAL_FALLBACK_MARKER) == 1
    assert has_fenced_html_artifact(once)
    assert has_fenced_html_artifact(existing)
    assert has_fenced_html_artifact(longer_closer)
    assert not has_fenced_html_artifact(nested_in_text)
    assert append_html_visual_fallback(existing, _metadata()) == existing


def test_force_fallback_accepts_full_html_document_but_not_bare_fragment():
    document = "<!doctype html><html><body><main>ready</main></body></html>"
    fragment = '<div style="color:#111">ready</div>'
    document_as_text = (
        "```text\n<!doctype html><html><body>example only</body></html>\n```"
    )

    assert append_html_visual_fallback(document, _metadata()) == document
    assert HTML_VISUAL_FALLBACK_MARKER in append_html_visual_fallback(
        fragment, _metadata()
    )
    assert HTML_VISUAL_FALLBACK_MARKER in append_html_visual_fallback(
        document_as_text, _metadata()
    )


def test_force_fallback_ignores_html_hidden_in_tool_and_reasoning_details():
    hidden = (
        '<details type="tool_calls">```html\n<div>tool only</div>\n```</details>\n'
        '<details type="reasoning">```html\n<div>reasoning only</div>\n```</details>\n'
        "Visible answer"
    )

    assert HTML_VISUAL_FALLBACK_MARKER in append_html_visual_fallback(
        hidden, _metadata()
    )


def test_force_fallback_closes_unterminated_source_fence_before_artifact():
    original = "```text\nunfinished example"

    content = append_html_visual_fallback(original, _metadata())

    assert "\n```\n\n```html\n" in content
    assert HTML_VISUAL_FALLBACK_MARKER in content


@pytest.mark.parametrize("mode", ["off", "auto"])
def test_non_force_modes_never_append_fallback(mode):
    assert (
        append_html_visual_fallback("Plain response", _metadata(mode))
        == "Plain response"
    )


@pytest.mark.parametrize(
    "surface", ["telegram", "telegram:webhook", "web/telegram", "tg-bot", "sms"]
)
def test_force_fallback_is_fail_closed_for_plain_text_surfaces(surface):
    assert (
        append_html_visual_fallback("Plain response", _metadata(surface=surface))
        == "Plain response"
    )


def test_force_fallback_does_not_create_an_empty_artifact():
    assert append_html_visual_fallback("", _metadata()) == ""
