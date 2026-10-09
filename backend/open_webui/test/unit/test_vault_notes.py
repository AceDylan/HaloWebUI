"""Obsidian 笔记 in the composer: search, read, path safety, and the host paths hermes gets."""

import os

import pytest

from open_webui.utils import vault_notes
from open_webui.utils.vault_notes import VaultError, read_note, search_notes


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    (root / "项目").mkdir(parents=True)
    (root / ".obsidian").mkdir()
    (root / "运维SOP").mkdir()
    (root / "项目" / "HaloWebUI.md").write_text("---\ntags: [x]\n---\n# HaloWebUI\n部署用 deploy.sh\n")
    (root / "运维SOP" / "重启网关.md").write_text("先看 runs，再 hermes gateway restart。HaloWebUI 不受影响。")
    (root / ".obsidian" / "workspace.md").write_text("HaloWebUI hidden")
    (root / "收件箱.md").write_text("x" * (vault_notes.MAX_NOTE_CHARS + 10))
    os.utime(root / "收件箱.md", (2_000_000_000, 2_000_000_000))
    outside = tmp_path / "secret.md"
    outside.write_text("secret")
    (root / "link.md").symlink_to(outside)
    monkeypatch.setenv(vault_notes.VAULT_DIR_ENV, str(root))
    return root


def test_search_ranks_names_over_text_and_skips_hidden_and_links(vault):
    hits = search_notes("halowebui")
    assert [h["path"] for h in hits] == ["项目/HaloWebUI.md", "运维SOP/重启网关.md"]
    assert hits[0]["folder"] == "项目" and hits[0]["snippet"] == ""
    assert "HaloWebUI" in hits[1]["snippet"]
    newest = search_notes("")
    assert newest[0]["path"] == "收件箱.md"
    assert all(h["path"] != "link.md" for h in newest)


def test_read_strips_frontmatter_caps_size_and_names_host_path(vault, monkeypatch):
    monkeypatch.setenv("HUB_URL", "https://hub.example:5526")
    monkeypatch.setenv("HUB_VAULT_ROOT", "/root/Documents/Obsidian Vault")
    note = read_note("项目/HaloWebUI.md")
    assert note["content"].startswith("# HaloWebUI") and note["truncated"] is False
    assert note["host_path"] == "/root/Documents/Obsidian Vault/项目/HaloWebUI.md"
    big = read_note("收件箱.md")
    assert big["truncated"] is True and len(big["content"]) == vault_notes.MAX_NOTE_CHARS


@pytest.mark.parametrize(
    "bad",
    ["../secret.md", "/etc/passwd.md", "项目/../../secret.md", ".obsidian/workspace.md", "link.md", "项目", "a\\b.md", "missing.md"],
)
def test_read_refuses_paths_outside_the_vault(vault, bad):
    with pytest.raises(VaultError):
        read_note(bad)


def test_off_without_the_mount(monkeypatch, tmp_path):
    monkeypatch.setenv(vault_notes.VAULT_DIR_ENV, str(tmp_path / "nope"))
    assert search_notes("x") == []
    with pytest.raises(VaultError) as e:
        read_note("a.md")
    assert e.value.status_code == 503


def test_hermes_is_told_where_attached_notes_live(monkeypatch):
    from open_webui.utils.hermes_agent import _attachment_note, _vault_note_host_paths

    monkeypatch.setenv("HUB_URL", "https://hub.example:5526")
    monkeypatch.setenv("HUB_VAULT_ROOT", "/root/Documents/Obsidian Vault")
    metadata = {
        "files": [
            {"type": "vault_note", "name": "HaloWebUI", "path": "项目/HaloWebUI.md"},
            {"type": "vault_note", "name": "bad", "path": "../x.md"},
            {"type": "file", "id": "f1"},
        ]
    }
    notes = _vault_note_host_paths(metadata)
    assert notes == [("HaloWebUI", "/root/Documents/Obsidian Vault/项目/HaloWebUI.md")]
    text = _attachment_note([], notes)
    assert text.startswith("[Obsidian 笔记]") and "项目/HaloWebUI.md" in text
    both = _attachment_note([("a.pdf", "/data/a.pdf")], notes)
    assert both.index("[附件原文件]") < both.index("[Obsidian 笔记]")
    assert _attachment_note([], []) == ""
