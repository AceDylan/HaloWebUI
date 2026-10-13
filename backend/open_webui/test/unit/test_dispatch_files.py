import asyncio
from types import SimpleNamespace

import pytest

from open_webui.utils.dispatch_files import conversation_file_ids


def test_current_documents_and_user_images_from_active_history_are_deduplicated():
    messages = [
        {"role": "user", "files": [{"id": "removed", "type": "file"}], "content": [
            {"type": "image_url", "image_url": {"url": "openwebui-file://photo"}},
        ]},
        {"role": "assistant", "content": [
            {"type": "image_url", "image_url": {"url": "/api/v1/files/generated/content"}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": "分析之前的附件"},
            {"type": "image_url", "image_url": {"url": "/api/v1/files/photo/content"}},
            {"type": "image_url", "image_url": {"url": "https://example.org/photo.png"}},
        ]},
    ]
    metadata = {"files": [{"file": {"id": "doc"}}, {"id": "doc"}]}
    assert conversation_file_ids(metadata, messages) == ["doc", "photo"]
    assert conversation_file_ids({"files": []}, messages) == ["photo"]


def test_team_dispatch_receives_historical_images_as_owned_host_files(monkeypatch):
    from open_webui import tasks
    from open_webui.models.files import Files
    from open_webui.utils import agent_team_dispatch as dispatch, hermes_agent

    user = SimpleNamespace(id="u1", role="user")
    record = SimpleNamespace(id="photo", user_id="u1", filename="photo.png",
                             path=f"{hermes_agent.DATA_DIR}/uploads/photo.png")
    monkeypatch.setattr(Files, "get_file_by_id", lambda id: record if id == "photo" else None)
    monkeypatch.setattr(hermes_agent, "_host_data_dir", lambda: "/host/data")
    captured = []
    original = dispatch.attachments

    def attachments(metadata, user):
        captured.extend(original(metadata, user))
        return captured

    monkeypatch.setattr(dispatch, "attachments", attachments)
    monkeypatch.setattr("open_webui.socket.main.get_event_emitter", lambda _: None)

    def close_task(coro, **kwargs):
        coro.close()
        return "task", None

    monkeypatch.setattr(tasks, "create_task", close_task)
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {
        "url": "/api/v1/files/photo/content"}}]}, {"role": "user", "content": "分析附件"}]
    metadata = {"chat_id": "chat", "message_id": "reply", "files": []}
    asyncio.run(dispatch.run_team_dispatch(None, {"messages": messages}, user, metadata, "hermes-agent"))
    assert captured == [{"name": "photo.png", "path": "/host/data/uploads/photo.png"}]
    record.user_id = "other"
    captured.clear()
    asyncio.run(dispatch.run_team_dispatch(None, {"messages": messages}, user, metadata, "hermes-agent"))
    assert captured == []


def test_raw_document_text_limits_and_unreadable_files(tmp_path, monkeypatch):
    from open_webui.models.files import Files
    from open_webui.routers.discussions import _load_files
    from open_webui.utils.discussion_room import FILE_TEXT_CHARS, _files_block

    path = tmp_path / "notes.txt"
    path.write_text("已验证的附件正文" * FILE_TEXT_CHARS, encoding="utf-8")
    record = SimpleNamespace(id="doc", user_id="u1", filename=path.name, path=str(path),
                             meta={"content_type": "text/plain"}, data={})
    monkeypatch.setattr(Files, "get_file_by_id", lambda _: record)
    user = SimpleNamespace(id="u1", role="user")
    loaded = _load_files(["doc", "doc"], user)
    assert len(loaded) == 1 and len(loaded[0]["text"]) == FILE_TEXT_CHARS
    assert loaded[0]["text"].startswith("已验证的附件正文")
    record.data = {"content": "已有提取文本"}
    path.unlink()
    assert _load_files(["doc"], user)[0]["text"] == "已有提取文本"
    record.data = {}
    loaded = _load_files(["doc"], user)
    assert "could not be read" in _files_block({"files": loaded}, sees_images=False, gets_images=False)
    record.user_id = "other"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _load_files(["doc"], user)
    assert exc.value.status_code == 404
