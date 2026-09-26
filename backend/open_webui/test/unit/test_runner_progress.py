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


def _reporter(tmp_path, run_dir, events, end_at):
    """Run the reporter on a fake clock; ``events`` maps a time to progress.log lines
    written then; the run ends at ``end_at``. Returns [(time, payload)]."""
    config = tmp_path / "runner.env"
    config.write_text("HALOWEBUI_NOTIFY_URL=http://halo.test/n\nHALOWEBUI_NOTIFY_TOKEN=t\n")
    sent = []
    now = [0.0]
    pending = dict(events)

    def sleep(seconds):
        now[0] += seconds
        for at in sorted(pending):
            if at <= now[0]:
                with (run_dir / "progress.log").open("a") as handle:
                    handle.write("\n".join(pending.pop(at)) + "\n")
        if now[0] >= end_at:
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
    send = lambda u, t, p: sent.append((now[0], p))
    assert progress.run(args, sleep=sleep, clock=lambda: now[0], send=send) == 0
    return sent


def test_reporter_posts_at_start_early_on_interval_and_once_at_the_end(tmp_path):
    run_dir = _run_dir(tmp_path, lines=["17:44:01 [tool#1] Read: a"])
    sent = _reporter(tmp_path, run_dir, {}, end_at=400)
    # Started; an early update a little after 40 s; then nothing moves, so every 180 s.
    assert [at for at, _ in sent] == [0, 45, 225, 405]
    statuses = [payload["status"] for _, payload in sent]
    assert statuses == ["running", "running", "running", "finished"]
    first = sent[0][1]
    assert first["chat_id"] == "chat-1" and first["mode"] == "progress"
    assert first["step"] == 1
    assert first["started_at"] == progress.parse_started_at("2026-09-26 17:43:54 +0800")
    assert sent[-1][1]["runner_status"] == "success"


def test_reporter_follows_the_steps_at_most_once_a_minute(tmp_path):
    run_dir = _run_dir(tmp_path, lines=["17:44:01 [tool#1] Read: a"])
    events = {at: [f"17:45:{at % 60:02d} [tool#{at}] Bash: step {at}"] for at in range(20, 300, 20)}
    sent = _reporter(tmp_path, run_dir, events, end_at=300)
    times = [at for at, _ in sent]
    # Steps move every 20 s; the chat hears of it once a minute, and of the end at once.
    assert times == [0, 45, 105, 165, 225, 285, 300]
    assert sent[2][1]["step"] > sent[1][1]["step"]
    assert sent[2][1]["last_activity"].startswith("Bash: step")


def test_reporter_does_nothing_without_config(tmp_path, monkeypatch):
    monkeypatch.delenv("RECLAUDE_NOTIFY_CONFIG", raising=False)
    args = SimpleNamespace(
        agent="codex", runs_root=str(tmp_path), run_id="r1", chat_id="c",
        interval=180, config_file=[str(tmp_path / "missing.env")],
    )
    sent = []
    assert progress.run(args, sleep=lambda s: None, send=lambda *a: sent.append(a)) == 0
    assert sent == []
