from unittest.mock import patch

from open_webui.utils import hermes_agent
from open_webui.utils.hermes_agent import _build_run_payload


def test_run_payload_omits_raw_images_from_conversation_history():
    historical_image = "data:image/png;base64," + ("A" * 100_000)
    form_data = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Make this image sharper"},
                    {
                        "type": "image_url",
                        "image_url": {"url": historical_image},
                    },
                ],
            },
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Now change the clothes"},
        ]
    }

    payload = _build_run_payload(form_data, {"chat_id": "chat-1"}, "hermes-agent")

    assert payload["input"] == "Now change the clothes"
    assert payload["conversation_history"][0] == {
        "role": "user",
        "content": "Make this image sharper\n[Image attachment omitted from prior turn]",
    }
    assert historical_image not in str(payload["conversation_history"])


def test_only_current_run_input_is_materialized():
    payload = {
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Edit this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "/api/v1/files/current/content"},
                    },
                ],
            }
        ],
        "conversation_history": [
            {
                "role": "user",
                "content": "Earlier image\n[Image attachment omitted from prior turn]",
            }
        ],
    }
    seen_messages = []

    def fake_materialize(form_data, **_kwargs):
        seen_messages.extend(form_data["messages"])
        materialized = {
            **form_data["messages"][0],
            "content": [
                {"type": "text", "text": "Edit this"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        }
        return {"messages": [materialized]}

    with patch.object(
        hermes_agent,
        "materialize_openai_image_message_refs",
        side_effect=fake_materialize,
    ):
        result = hermes_agent._materialize_run_input_image_refs(
            payload,
            user_id="user-1",
            is_admin=False,
        )

    assert seen_messages == payload["input"]
    assert result["input"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert result["conversation_history"] == payload["conversation_history"]
