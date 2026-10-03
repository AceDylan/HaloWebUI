import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.image_generation_options import (  # noqa: E402
    sanitize_chat_image_generation_options,
)
from open_webui.utils.middleware import (  # noqa: E402
    _find_chat_image_generation_source_urls,
)


def _image(url):
    return {"type": "image_url", "image_url": {"url": url}}


PREVIOUS = "/api/v1/files/previous-generated/content"
UPLOADED = "/api/v1/files/uploaded-photo/content"

# The request the page sends in image mode: the earlier generated image rides
# along on the assistant message, the new user message carries only text.
DISMISSED_REFERENCE = [
    {"role": "user", "content": "a red fox"},
    {"role": "assistant", "content": [_image(PREVIOUS)]},
    {"role": "user", "content": "a lighthouse at dusk"},
]


def test_a_dismissed_reference_is_not_used_as_the_source():
    assert (
        _find_chat_image_generation_source_urls(
            DISMISSED_REFERENCE, {"source_scope": "message"}
        )
        == []
    )


def test_a_kept_reference_or_an_upload_on_the_message_is_the_source():
    messages = DISMISSED_REFERENCE[:-1] + [
        {
            "role": "user",
            "content": [{"type": "text", "text": "make it blue"}, _image(PREVIOUS)],
        }
    ]
    assert _find_chat_image_generation_source_urls(
        messages, {"source_scope": "message"}
    ) == [PREVIOUS]

    messages = DISMISSED_REFERENCE[:-1] + [
        {
            "role": "user",
            "content": "in this style",
            "files": [{"type": "image", "url": UPLOADED}],
        }
    ]
    assert _find_chat_image_generation_source_urls(
        messages, {"source_scope": "message"}
    ) == [UPLOADED]


def test_messages_from_before_the_scope_still_look_back():
    # Older messages (and other clients) do not send a scope: the latest image
    # anywhere in the conversation is the source, as before.
    assert _find_chat_image_generation_source_urls(DISMISSED_REFERENCE, {}) == [
        PREVIOUS
    ]


def test_retrying_without_the_reference_uses_no_source():
    # The failed edit's "retry without the reference image": neither the
    # message's own upload nor an earlier image is sent.
    messages = DISMISSED_REFERENCE[:-1] + [
        {
            "role": "user",
            "content": [{"type": "text", "text": "make it blue"}, _image(PREVIOUS)],
            "files": [{"type": "image", "url": UPLOADED}],
        }
    ]
    assert _find_chat_image_generation_source_urls(messages, {"source_scope": "none"}) == []
    assert sanitize_chat_image_generation_options({"source_scope": "none"}) == {
        "source_scope": "none"
    }


def test_only_known_scopes_pass_the_sanitizer():
    assert sanitize_chat_image_generation_options(
        {"size": "1024x1024", "source_scope": "message"}
    ) == {"size": "1024x1024", "source_scope": "message"}
    assert sanitize_chat_image_generation_options(
        {"size": "1024x1024", "source_scope": "anything"}
    ) == {"size": "1024x1024"}
