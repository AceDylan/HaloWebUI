import io
import tarfile
import zipfile

import pytest

from open_webui.retrieval.loaders.archive import MAX_MEMBER_CHARS, ArchiveLoader
from open_webui.retrieval.loaders.main import Loader
from open_webui.utils.file_upload_diagnostics import FileUploadDiagnosticError
from open_webui.utils.middleware import (
    _build_current_chat_resources_context,
    _get_current_chat_resource_access,
)


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return str(path)


def test_zip_lists_entries_and_reads_text_members(tmp_path):
    path = _zip(
        tmp_path / "bundle.zip",
        {
            "src/app.py": "print('hi')\n",
            "notes/说明.md": "# 标题\n内容".encode("utf-8"),
            "legacy.txt": "旧编码".encode("gb18030"),
            "clip.mp4": b"\x00\x00\x00\x18ftypmp42",
            "fake.txt": b"bin\x00ary",
        },
    )
    [doc] = ArchiveLoader(path, "bundle.zip").load()
    text = doc.page_content
    assert "contains 5 entries" in text
    assert "- clip.mp4 (" in text
    assert "=== src/app.py ===\nprint('hi')" in text
    assert "=== notes/说明.md ===\n# 标题\n内容" in text
    assert "=== legacy.txt ===\n旧编码" in text
    assert "=== clip.mp4 ===" not in text and "=== fake.txt ===" not in text


def test_zip_names_from_chinese_windows_are_decoded(tmp_path):
    # Same byte length as the GBK name, swapped in afterwards: zipfile itself would write UTF-8.
    path = tmp_path / "win.zip"
    _zip(path, {"abcd.txt": "ok"})
    path.write_bytes(path.read_bytes().replace(b"abcd.txt", "报告.txt".encode("gbk")))
    [doc] = ArchiveLoader(str(path), "win.zip").load()
    assert "=== 报告.txt ===\nok" in doc.page_content


def test_large_members_are_truncated(tmp_path):
    path = _zip(tmp_path / "big.zip", {"big.log": "x" * (MAX_MEMBER_CHARS * 3)})
    [doc] = ArchiveLoader(path, "big.zip").load()
    assert "…[truncated]" in doc.page_content
    assert len(doc.page_content) < MAX_MEMBER_CHARS + 500


def test_tar_gz_is_read(tmp_path):
    path = tmp_path / "bundle.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        data = b"key: value\n"
        info = tarfile.TarInfo("conf/app.yaml")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    [doc] = Loader().load("bundle.tar.gz", "application/gzip", str(path))
    assert "=== conf/app.yaml ===\nkey: value" in doc.page_content


def test_unreadable_archive_keeps_the_archive_diagnostic(tmp_path):
    path = tmp_path / "bundle.7z"
    path.write_bytes(b"7z\xbc\xaf\x27\x1c rest")
    with pytest.raises(FileUploadDiagnosticError) as error:
        Loader().load("bundle.7z", "application/x-7z-compressed", str(path))
    assert error.value.diagnostic["code"] == "unsupported_archive"


def test_raw_attachment_is_named_but_not_read():
    item = {
        "type": "file",
        "id": "f1",
        "name": "clip.mp4",
        "processing_mode": "full_context",
        "file": {"meta": {"content_type": "video/mp4", "size": 10, "raw_attachment": True}},
    }
    assert _get_current_chat_resource_access(item, "clip.mp4", "video/mp4") == "metadata_only"
    context = _build_current_chat_resources_context([item], "看看这个视频")
    assert '"access": "metadata_only"' in context
    assert "attached as original files" in context


def test_unreadable_attachment_does_not_stop_the_others(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from open_webui.models.files import FileModel
    from open_webui.utils import middleware
    from open_webui.utils.file_upload_diagnostics import make_unsupported_binary_diagnostic

    records = {
        file_id: FileModel(
            id=file_id, user_id="u", filename=name, path=f"/data/{name}",
            meta={"name": name, "content_type": kind}, data={}, created_at=1, updated_at=1,
        )
        for file_id, name, kind in [("v", "clip.mp4", "video/mp4"), ("d", "report.pdf", "application/pdf")]
    }  # fmt: skip
    processed = []

    def process(request, form, user):
        if form.file_id == "v":
            raise FileUploadDiagnosticError(make_unsupported_binary_diagnostic("clip.mp4"))
        processed.append(form.file_id)
        records["d"] = records["d"].model_copy(update={"data": {"content": "text"}})

    def update_meta(file_id, meta):
        records[file_id] = records[file_id].model_copy(update={"meta": {**records[file_id].meta, **meta}})
        return records[file_id]

    monkeypatch.setattr(middleware.Files, "get_file_by_id", records.get)
    monkeypatch.setattr(middleware.Files, "update_file_metadata_by_id", update_meta)
    monkeypatch.setattr(middleware, "process_file", process)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        config=SimpleNamespace(FILE_PROCESSING_DEFAULT_MODE="full_context"))))  # fmt: skip
    metadata = {"files": [{"type": "file", "id": "v"}, {"type": "file", "id": "d"}]}

    asyncio.run(middleware._ensure_requested_chat_file_modes(request, metadata, None, {}, None))
    assert processed == ["d"]
    assert records["v"].meta["raw_attachment"] is True
    assert metadata["files"][0]["file"]["meta"]["raw_attachment"] is True
    # The next turn does not try the video again.
    asyncio.run(middleware._ensure_requested_chat_file_modes(request, metadata, None, {}, None))
    assert processed == ["d"]
