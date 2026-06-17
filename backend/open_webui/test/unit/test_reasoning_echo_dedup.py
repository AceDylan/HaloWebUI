import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.middleware import (  # noqa: E402
    _is_duplicated_reasoning_echo,
)


def test_echo_detected_for_identical_content_and_reasoning():
    assert _is_duplicated_reasoning_echo("用户问了我", "用户问了我") is True


def test_echo_detected_ignoring_surrounding_whitespace():
    assert _is_duplicated_reasoning_echo("  thinking  ", "thinking") is True


def test_real_answer_content_is_not_treated_as_echo():
    # The visible answer differs from the reasoning -> must be kept.
    assert _is_duplicated_reasoning_echo("I am a model.", "Let me introduce myself") is False


def test_empty_content_is_not_an_echo():
    assert _is_duplicated_reasoning_echo("", "anything") is False
    assert _is_duplicated_reasoning_echo("   ", "anything") is False


def test_non_string_inputs_are_safe():
    assert _is_duplicated_reasoning_echo(None, "x") is False
    assert _is_duplicated_reasoning_echo("x", None) is False
    assert _is_duplicated_reasoning_echo(123, 123) is False
