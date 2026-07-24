import pathlib
import sys

import pytest
from fastapi import HTTPException

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import terminal as terminal_router  # noqa: E402


def test_resolve_safe_path_rejects_workspace_prefix_sibling(monkeypatch, tmp_path):
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    sibling = tmp_path / "workspace-private"
    sibling.mkdir()

    monkeypatch.setattr(terminal_router, "_get_workspace_root", lambda: workspace)

    with pytest.raises(HTTPException) as exc_info:
        terminal_router._resolve_safe_path("../workspace-private/secret.html")

    assert exc_info.value.status_code == 403


def test_resolve_safe_path_allows_workspace_root_and_descendants(monkeypatch, tmp_path):
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    monkeypatch.setattr(terminal_router, "_get_workspace_root", lambda: workspace)

    assert terminal_router._resolve_safe_path("") == workspace
    assert (
        terminal_router._resolve_safe_path("pages/index.html")
        == workspace / "pages/index.html"
    )


def test_resolve_safe_path_rejects_symlinks_that_escape_workspace(
    monkeypatch, tmp_path
):
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(terminal_router, "_get_workspace_root", lambda: workspace)

    with pytest.raises(HTTPException) as exc_info:
        terminal_router._resolve_safe_path("escape/secret.html")

    assert exc_info.value.status_code == 403
