"""Zip and tar archives as text a model can read: what is inside, and the text files in it.

Nothing is extracted to disk. Reads are capped per member and in total, and a tar stops being
walked once the sizes it declares get too large to skip through (compression bombs)."""

import os
import tarfile
import zipfile

from langchain_core.documents import Document

from open_webui.utils.file_upload_diagnostics import (
    FileUploadDiagnosticError,
    make_archive_diagnostic,
)

MAX_ENTRIES = 1000
MAX_MEMBER_CHARS = 50_000
MAX_TOTAL_CHARS = 200_000
MAX_TAR_SKIP_BYTES = 512 * 1024 * 1024

TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "rst", "csv", "tsv", "json", "jsonl", "yaml", "yml", "toml", "ini",
    "cfg", "conf", "env", "xml", "html", "htm", "css", "scss", "less", "svg", "srt", "vtt", "log",
    "sql", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "vue", "svelte", "java", "kt", "kts",
    "go", "rs", "c", "h", "cc", "cpp", "hpp", "cs", "rb", "php", "swift", "m", "mm", "scala",
    "dart", "lua", "pl", "pm", "r", "sh", "bash", "zsh", "ps1", "bat", "cmd", "gradle", "groovy",
    "tex", "properties", "gitignore", "dockerfile", "makefile",
}  # fmt: skip


def _is_text_name(name: str) -> bool:
    base = os.path.basename(name).lower()
    ext = base.rsplit(".", 1)[-1] if "." in base else base
    return ext in TEXT_EXTENSIONS


def _decode(data: bytes) -> str | None:
    if b"\x00" in data[:4096]:
        return None
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _zip_name(info: zipfile.ZipInfo) -> str:
    # Zips made on Chinese Windows store GBK names without the UTF-8 flag; Python reads them as cp437.
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


class ArchiveLoader:
    def __init__(self, file_path: str, filename: str):
        self.file_path = file_path
        self.filename = os.path.basename(filename)

    def load(self) -> list[Document]:
        if zipfile.is_zipfile(self.file_path):
            entries, texts, truncated = self._read_zip()
        elif tarfile.is_tarfile(self.file_path):
            entries, texts, truncated = self._read_tar()
        else:  # 7z, rar, a lone .gz …: no reader here; the upload keeps the original file
            raise FileUploadDiagnosticError(make_archive_diagnostic(self.filename))

        lines = [f"Archive «{self.filename}» contains {len(entries)} entries:"]
        lines += [f"- {name} ({_human_size(size)})" for name, size in entries]
        if truncated:
            lines.append("- … (listing stopped here)")
        parts = ["\n".join(lines)]
        parts += [f"=== {name} ===\n{text}" for name, text in texts]
        return [Document(page_content="\n\n".join(parts), metadata={"source": self.filename})]

    def _collect(self, entries, texts, budget, name, size, read) -> int:
        entries.append((name, size))
        if budget <= 0 or not _is_text_name(name):
            return budget
        limit = min(MAX_MEMBER_CHARS, budget)
        text = _decode(read(limit * 4 + 1))
        if text is None:
            return budget
        if len(text) > limit:
            text = text[:limit] + "\n…[truncated]"
        texts.append((name, text))
        return budget - len(text)

    def _read_zip(self):
        entries, texts, budget = [], [], MAX_TOTAL_CHARS
        with zipfile.ZipFile(self.file_path) as archive:
            infos = [i for i in archive.infolist() if not i.is_dir()]
            for info in infos[:MAX_ENTRIES]:
                def read(n, info=info):
                    with archive.open(info) as stream:
                        return stream.read(n)

                budget = self._collect(entries, texts, budget, _zip_name(info), info.file_size, read)
        return entries, texts, len(infos) > MAX_ENTRIES

    def _read_tar(self):
        entries, texts, budget, skipped = [], [], MAX_TOTAL_CHARS, 0
        with tarfile.open(self.file_path, "r:*") as archive:
            while True:
                if len(entries) >= MAX_ENTRIES or skipped > MAX_TAR_SKIP_BYTES:
                    return entries, texts, True
                member = archive.next()
                if member is None:
                    return entries, texts, False
                if not member.isfile():
                    continue
                skipped += member.size

                def read(n, member=member):
                    stream = archive.extractfile(member)
                    return stream.read(n) if stream else b""

                budget = self._collect(entries, texts, budget, member.name, member.size, read)
