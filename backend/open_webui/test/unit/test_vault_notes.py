"""Obsidian 笔记 in the composer: search, read, path safety, and the host paths hermes gets."""

import os
from types import SimpleNamespace

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


# --- 精答 / 讨论 / 协作: related notes --------------------------------------------------------


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "项目" / "HaloWebUI").mkdir(parents=True)
    (root / "运维").mkdir()
    (root / "项目" / "HaloWebUI" / "自动分流与共享标题.md").write_text(
        "---\nkind: fix\n---\n# 自动分流\n\n## 结论\n\n自动分流按哪种方式提升结果选择精答、讨论或协作。\n\n"
        "## 回滚\n\n部署上一镜像。\n"
    )
    (root / "项目" / "HaloWebUI" / "讨论台.md").write_text("讨论台多个模型讨论，主持人写结论。HaloWebUI 的模式之一。")
    (root / "运维" / "多 VPS 管理清单.md").write_text("hk vps 的 ssh 端口 61234。\n\n其它机器同样。")
    for i in range(6):
        (root / f"杂项{i}.md").write_text(f"第 {i} 篇无关的记录：今天天气不错，HaloWebUI 照常运行。")
    monkeypatch.setenv(vault_notes.VAULT_DIR_ENV, str(root))
    monkeypatch.setenv("HUB_VAULT_ROOT", "/host/vault")
    monkeypatch.delenv(vault_notes.MODES_ENV, raising=False)
    vault_notes._text_cache.clear()
    return root


def test_related_notes_find_the_subject_not_stray_words(kb):
    hits = vault_notes.related_notes("当前 HaloWebUI 自动分流有优化空间吗")
    assert hits[0]["path"] == "项目/HaloWebUI/自动分流与共享标题.md"
    assert hits[0]["n"] == 1 and hits[0]["title"] == "自动分流与共享标题"
    assert "精答、讨论或协作" in hits[0]["excerpt"] and "kind: fix" not in hits[0]["excerpt"]
    assert hits[0]["hostPath"] == "/host/vault/项目/HaloWebUI/自动分流与共享标题.md"
    assert [h["path"] for h in vault_notes.related_notes("hk vps 的 ssh 端口是多少")] == ["运维/多 VPS 管理清单.md"]
    # pairs across two words (「选精」「么规」) are not words the vault lacks
    asked = vault_notes.related_notes("HaloWebUI 的自动分流现在按什么规则选精答、讨论还是协作？")
    assert asked and asked[0]["path"] == "项目/HaloWebUI/自动分流与共享标题.md"
    # general questions share a stray pair of characters with some note at most
    assert vault_notes.related_notes("人为什么需要吃饭") == []
    assert vault_notes.related_notes("帮我写一首关于秋天的诗") == []
    assert vault_notes.related_notes("") == []


def test_notes_are_for_admins_and_can_be_turned_off(kb, monkeypatch):
    admin, member = SimpleNamespace(role="admin"), SimpleNamespace(role="user")
    assert vault_notes.notes_for(admin, "自动分流怎么选")
    assert vault_notes.notes_for(member, "自动分流怎么选") == []
    monkeypatch.setenv(vault_notes.MODES_ENV, "0")
    assert vault_notes.notes_for(admin, "自动分流怎么选") == []
    monkeypatch.setenv(vault_notes.VAULT_DIR_ENV, str(kb / "nope"))
    monkeypatch.delenv(vault_notes.MODES_ENV)
    assert vault_notes.notes_for(admin, "自动分流怎么选") == []


def test_notes_reach_the_answer_the_discussion_and_the_team(kb):
    from open_webui.utils import answer_desk as desk
    from open_webui.utils import discussion_room as room

    notes = vault_notes.related_notes("自动分流怎么选")
    run = {"question": "自动分流怎么选", "assistant": {"saved": True}, "notes": notes,
           "answer": {"content": "按结果选。"}}
    prompt = desk.answer_messages(run)[-1]["content"]
    assert "user's own knowledge base" in prompt and "《自动分流与共享标题》" in prompt
    stored = desk.stored_content(run)
    assert "**笔记库参考**" in stored and "`项目/HaloWebUI/自动分流与共享标题.md`" in stored
    assert "笔记库参考" not in desk.stored_content({**run, "notes": []})

    ask = {"question": "q", "notes": notes, "conclusion": {"content": "结论"}}
    assert "笔记库参考" in room.stored_content(ask)
    assert room.stored_content({**ask, "conclusion": {"content": ""}}) == ""

    admin = SimpleNamespace(role="admin")
    goal = vault_notes.with_goal_notes("优化自动分流", admin, "自动分流怎么选", 8000)
    assert goal.startswith("优化自动分流\n\n笔记库里可能相关的笔记")
    assert "/host/vault/项目/HaloWebUI/自动分流与共享标题.md" in goal
    assert vault_notes.with_goal_notes("优化自动分流", admin, "自动分流怎么选", 20) == "优化自动分流"
