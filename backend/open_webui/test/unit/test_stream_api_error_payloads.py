import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils.middleware import _build_api_error_payload  # noqa: E402


def test_build_api_error_payload_uses_http_status_override_for_rate_limit():
    payload = _build_api_error_payload(
        (
            '{"error":{"message":"Request was rejected due to rate limiting. '
            'Details: TPM limit reached.","type":"bad_response_status_code",'
            '"param":"","code":"bad_response_status_code"}}'
        ),
        "cherryin-490b.agent/deepseek-v3.2(free)",
        status_override=429,
    )

    assert payload["type"] == "api_error"
    assert payload["model_id"] == "cherryin-490b.agent/deepseek-v3.2(free)"
    assert "HTTP 429" in payload["content"]
    assert "TPM limit reached" in payload["content"]
    assert payload["reasons"] == ["api_rate_limit", "api_quota_exceeded"]
    assert payload["suggestion"] == "wait_retry"


def test_build_api_error_payload_handles_auth_failures_with_status_override():
    payload = _build_api_error_payload(
        '{"message":"invalid access token or token expired"}',
        "dashscope.qwen",
        status_override=401,
    )

    assert "HTTP 401" in payload["content"]
    assert "invalid access token or token expired" in payload["content"]
    assert payload["reasons"] == ["api_auth_error"]
    assert payload["suggestion"] == "check_api_key"
