import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(
    __file__
).resolve().parents[4] / "integrations" / "hermes-runner" / "runner-progress.py"
spec = importlib.util.spec_from_file_location("runner_progress", SCRIPT)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)


def _run_dir(tmp_path, status="running", lines=()):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"status": status, "started_at": "2026-09-26 17:43:54 +0800"})
    )
    (run_dir / "progress.log").write_text("\n".join(lines) + "\n")
    return run_dir


def test_progress_line_reads_the_step_and_the_last_activity(tmp_path):
    run_dir = _run_dir(
        tmp_path,
        lines=[
            "17:44:01 [tool#197] Read: /root/a.py",
            "17:44:05 [tool#198] Bash: curl -H 'Authorization: Bearer abcdefghijklmnop' x API_TOKEN=s3cret",
            "17:44:06 [tool-result] ok: done",
        ],
    )
    step, last = progress.read_progress(str(run_dir))
    assert step == 198
    assert last.startswith("Bash: curl")
    assert "abcdefghijklmnop" not in last and "s3cret" not in last


def test_reporter_posts_at_start_on_interval_and_once_at_the_end(tmp_path):
    run_dir = _run_dir(tmp_path, lines=["17:44:01 [tool#1] Read: a"])
    config = tmp_path / "runner.env"
    config.write_text("HALOWEBUI_NOTIFY_URL=http://halo.test/n\nHALOWEBUI_NOTIFY_TOKEN=t\n")
    sent = []
    now = [0.0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds
        if now[0] >= 400:
            meta = json.loads((run_dir / "meta.json").read_text())
            meta["status"] = "success"
            (run_dir / "meta.json").write_text(json.dumps(meta))

    args = SimpleNamespace(
        agent="reclaude",
        runs_root=str(tmp_path / "runs"),
        run_id="r1",
        chat_id="chat-1",
        interval=180,
        config_file=[str(config)],
    )
    assert progress.run(args, sleep=sleep, clock=clock, send=lambda u, t, p: sent.append(p)) == 0
    statuses = [payload["status"] for payload in sent]
    assert statuses == ["running", "running", "running", "finished"]
    assert sent[0]["chat_id"] == "chat-1" and sent[0]["mode"] == "progress"
    assert sent[0]["step"] == 1
    assert sent[0]["started_at"] == progress.parse_started_at("2026-09-26 17:43:54 +0800")
    assert sent[-1]["runner_status"] == "success"


def test_reporter_does_nothing_without_config(tmp_path, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    args = SimpleNamespace(
        agent="codex", runs_root=str(tmp_path), run_id="r1", chat_id="c",
        interval=180, config_file=[str(tmp_path / "missing.env")],
    )
    sent = []
    assert progress.run(args, sleep=lambda s: None, send=lambda *a: sent.append(a)) == 0
    assert sent == []
