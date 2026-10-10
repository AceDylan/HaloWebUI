import asyncio
from types import SimpleNamespace

from open_webui.routers import files as files_router


def test_list_files_without_content_tolerates_files_without_text(monkeypatch):
    stored = [
        SimpleNamespace(id="a", data={"content": "text", "status": "completed"}),
        SimpleNamespace(id="b", data={"status": "completed"}),
        SimpleNamespace(id="c", data=None),
    ]
    monkeypatch.setattr(files_router.Files, "get_files", lambda: stored)

    result = asyncio.run(
        files_router.list_files(user=SimpleNamespace(role="admin", id="u"), content=False)
    )

    assert [f.id for f in result] == ["a", "b", "c"]
    assert result[0].data == {"status": "completed"}
    assert result[1].data == {"status": "completed"}
    assert result[2].data is None
