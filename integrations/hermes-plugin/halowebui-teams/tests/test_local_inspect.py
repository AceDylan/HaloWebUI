"""Unit tests for read-only local evidence inspection (POST /v1/halo-teams/inspect)."""

from __future__ import annotations

import pytest

from halowebui_teams import local_inspect


@pytest.mark.parametrize("cmd", [
    "ls -la /etc/nginx/sites-enabled",
    "cat /etc/nginx/nginx.conf | grep -n proxy_pass",
    "git -C /root/HaloWebUI log -n 5 --oneline",
    "git status && git diff --stat",
    "docker ps --format '{{.Names}} {{.Status}}'",
    "docker logs --tail 50 halowebui 2>&1 | grep -i error",
    "docker compose -f /root/halowebui/docker-compose.yaml ps",
    "systemctl status hindsight-hermes --no-pager",
    "rg -n 'normalize_selection' /root/HaloWebUI/backend/open_webui/utils/auto_routing.py",
    "ss -tlnp 2>/dev/null | head -n 20",
    "nginx -t",
    "df -h && free -m",
])
def test_readonly_commands_allowed(cmd):
    ok, reason = local_inspect.is_readonly_command(cmd)
    assert ok, f"expected allowed, got blocked: {reason}"


@pytest.mark.parametrize("cmd", [
    "rm -rf /tmp/foo",
    "echo hacked > /tmp/x",
    "cat /etc/nginx/nginx.conf | tee /tmp/out",
    "sed -i 's/a/b/g' /tmp/a.txt",
    "git commit -m 'x'",
    "git branch -D main",
    "docker restart halowebui",
    "docker compose up -d",
    "systemctl restart nginx",
    "nginx -s reload",
    "cat /root/halowebui/.env",
    "cat /root/.ssh/id_rsa",
    "printenv",
    "env",
    "python3 -c 'import os; os.remove(\"/tmp/x\")'",
    "ls $(whoami)",
    "find /tmp -delete",
])
def test_mutating_or_sensitive_commands_blocked(cmd):
    ok, _reason = local_inspect.is_readonly_command(cmd)
    assert not ok, f"expected blocked: {cmd}"


@pytest.mark.parametrize("path,blocked", [
    ("/root/halowebui/.env", True),
    ("/root/.hermes/.env.prod", True),
    ("/root/HaloWebUI/.env.example", False),
    ("/root/.ssh/id_ed25519", True),
    ("/etc/ssl/private/server.key", True),
    ("/root/.gemini/antigravity-cli/antigravity-oauth-token", True),
    ("/root/.claude-thirdparty/settings-cch.json", True),
    ("/etc/nginx/sites-enabled/halowebui.conf", False),
    ("/root/HaloWebUI/backend/open_webui/utils/auto_routing.py", False),
])
def test_sensitive_path_detection(path, blocked):
    assert local_inspect.is_sensitive_path(path) is blocked


def test_redact_evidence_masks_secrets_and_keeps_placeholders():
    raw = (
        "OPENAI_API_KEY=sk-1234567890abcdefghijklmnop\n"
        "HERMES_API_KEY=${HERMES_API_KEY}\n"
        "token: supersecretvalue123\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abcdef123456\n"
        "url=https://admin:mySecretPass@example.com/api\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
    )
    redacted = local_inspect.redact_evidence(raw)
    assert "sk-1234567890abcdefghijklmnop" not in redacted
    assert "supersecretvalue123" not in redacted
    assert "mySecretPass" not in redacted
    assert "MIIEowIBAAKCAQEA" not in redacted
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert "${HERMES_API_KEY}" in redacted
    assert "[REDACTED]" in redacted


def test_pre_tool_call_only_guards_active_inspect_sessions():
    # Non-inspect session is untouched
    assert local_inspect.on_pre_tool_call("write_file", {"path": "/tmp/a"}, session_id="normal-1") is None
    sid = "halo-inspect-test123"
    with local_inspect._sessions_lock:
        local_inspect._active_sessions.add(sid)
    try:
        assert local_inspect.on_pre_tool_call("write_file", {"path": "/tmp/a"}, session_id=sid)["action"] == "block"
        assert local_inspect.on_pre_tool_call("read_file", {"path": "/root/halowebui/.env"}, session_id=sid)["action"] == "block"
        assert local_inspect.on_pre_tool_call("read_file", {"path": "/etc/nginx/nginx.conf"}, session_id=sid) is None
        assert local_inspect.on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}, session_id=sid)["action"] == "block"
        assert local_inspect.on_pre_tool_call("terminal", {"command": "docker ps"}, session_id=sid) is None
    finally:
        with local_inspect._sessions_lock:
            local_inspect._active_sessions.discard(sid)


def test_collect_records_sources_redacts_and_cleans_session(monkeypatch):
    class FakeAgent:
        model = "gpt-chat"

        def __init__(self, on_tool):
            self._on_tool = on_tool

        def run_conversation(self, user_message, task_id=None):
            assert task_id in local_inspect._active_sessions
            self._on_tool("c1", "read_file", {"path": "/etc/nginx/nginx.conf"})
            self._on_tool("c2", "read_file", {"path": "/root/halowebui/.env"})  # filtered out
            self._on_tool("c3", "terminal", {"command": "docker ps"})
            return {"final_response": "nginx 监听 3001，API_KEY=sk-abcdefghijklmnopqrstuvwxyz"}

    monkeypatch.setattr(local_inspect, "_build_agent", lambda sid, cb: FakeAgent(cb))
    out = local_inspect.collect("检查 nginx 配置", mode="discuss")
    assert out["ok"] is True
    assert out["model"] == "gpt-chat"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out["summary"]
    assert ("***" in out["summary"] or "[REDACTED]" in out["summary"])
    assert out["sources"] == [
        {"kind": "file", "path": "/etc/nginx/nginx.conf"},
        {"kind": "command", "path": "docker ps"},
    ]
    assert not local_inspect._active_sessions
