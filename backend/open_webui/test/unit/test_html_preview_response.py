import pathlib
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers.files import _build_html_preview_response  # noqa: E402


def test_html_preview_response_uses_inline_html_and_security_headers(tmp_path):
    preview_file = tmp_path / "preview page.html"
    preview_file.write_text("<h1>Preview</h1>", encoding="utf-8")

    response = _build_html_preview_response(preview_file, preview_file.name)

    assert response.media_type == "text/html"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "preview%20page.html" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "camera=()" in response.headers["permissions-policy"]
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "connect-src 'none'" in response.headers["content-security-policy"]
    assert "form-action 'none'" in response.headers["content-security-policy"]
