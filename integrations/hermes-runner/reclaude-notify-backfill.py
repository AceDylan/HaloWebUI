#!/usr/bin/env python3
"""reclaude-notify-backfill.py — annotate past runs whose completion notice was skipped.

Before the runner started recording the launching hermes session at launch
(2026-09-15, see reclaude-notify.py), the notifier had to reconstruct that session
from tool-call provenance in state.db, and it ran within a second of the run
finishing — often before the launching turn had been persisted.  Those runs ended
with `notify.json: {"skipped": "origin session not found"}` even though state.db
later did contain the evidence.

This tool re-runs that same read-only lookup *now*, with a wide lookback, and writes
what it found into `<run-dir>/origin-backfill.json`.  It is a record, not a redelivery:

  * it never sends a notification and imports no HTTP client of its own;
  * it never rewrites notify.json, meta.json, result.md or anything else;
  * state.db is opened read-only, exactly as the notifier opens it;
  * without --apply it prints the report and writes nothing at all.

Runs whose provenance is genuinely gone are recorded as `resolved: false` with the
reason, so the unrecoverable set is explicit instead of being quietly forgotten.

Usage:
  reclaude-notify-backfill.py                      # dry run, both runs roots
  reclaude-notify-backfill.py --apply              # write origin-backfill.json
  reclaude-notify-backfill.py --runs-root DIR ...  # non-default roots
  reclaude-notify-backfill.py --json               # machine-readable report

Stdlib only.  Exit code is 0 unless the arguments are wrong.
"""
import argparse
import datetime
import importlib.util
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_PY = os.path.join(SCRIPT_DIR, "reclaude-notify.py")
DEFAULT_ROOTS = (
    ("/root/.hermes/reclaude-runs", "reclaude-run.sh"),
    ("/root/.hermes/codex-runs", "codex-run.sh"),
)
# Everything the notifier could not deliver for want of an origin.  A run that was
# correctly skipped (telegram/qqbot) or delivered is left alone.
BACKFILLABLE = ("origin session not found",)
REPORT_NAME = "origin-backfill.json"


def load_notify(path=NOTIFY_PY):
    """Import reclaude-notify.py for its read-only lookup helpers."""
    spec = importlib.util.spec_from_file_location("reclaude_notify", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def classify(run_dir):
    """Why this run is (or is not) a backfill candidate."""
    record = read_json(os.path.join(run_dir, "notify.json"))
    if not os.path.exists(os.path.join(run_dir, "meta.json")):
        return "not-a-run", record
    if not os.path.exists(os.path.join(run_dir, "notify.json")):
        return "no-notify-record", record
    skipped = record.get("skipped") or ""
    if skipped in BACKFILLABLE:
        return "candidate", record
    if record.get("delivered_at"):
        return "delivered", record
    if record.get("failed"):
        return "delivery-failed", record
    return "skipped-by-design" if skipped else "unknown", record


def examine(notify, run_dir, run_id, tool_marker, db_path, lookback_days):
    """Read-only: what the legacy provenance lookup can still recover for this run."""
    meta = notify.read_meta(run_dir)
    recorded = (meta.get("origin_session_id") or "").strip()
    if recorded:
        source = notify.session_source(recorded, db_path)
        return {
            "resolved": True,
            "method": "runner-meta",
            "origin_session": recorded,
            "origin_source": source or (meta.get("origin_platform") or ""),
        }
    previous = notify.LOOKBACK_SECONDS
    notify.LOOKBACK_SECONDS = int(lookback_days * 24 * 3600)
    try:
        found = notify.find_origin(
            run_id,
            "",
            meta.get("parent_run", "") or "",
            tool_marker=tool_marker,
            db_path=db_path,
        )
    finally:
        notify.LOOKBACK_SECONDS = previous
    if not found:
        return {
            "resolved": False,
            "method": "state.db-provenance",
            "reason": "no launching tool call for this run id is left in state.db",
        }
    session_id, source = found
    return {
        "resolved": True,
        "method": "state.db-provenance",
        "origin_session": session_id,
        "origin_source": source,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs-root",
        action="append",
        default=[],
        metavar="DIR[:TOOL_MARKER]",
        help="runs directory to scan; repeatable. Defaults to the reclaude and codex roots.",
    )
    parser.add_argument("--state-db", default=None, help="hermes state DB (read-only)")
    parser.add_argument(
        "--lookback-days",
        type=float,
        default=400.0,
        help="how far back the provenance lookup may search (default: 400)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=f"write {REPORT_NAME} into each candidate run dir (default: report only)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--notify-script", default=NOTIFY_PY)
    args = parser.parse_args()

    notify = load_notify(args.notify_script)
    db_path = args.state_db or notify.STATE_DB
    roots = []
    for entry in args.runs_root:
        path, _, marker = entry.partition(":")
        roots.append((path, marker or "reclaude-run.sh"))
    roots = roots or list(DEFAULT_ROOTS)

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    report = {"generated_at": stamp, "state_db": db_path, "applied": args.apply, "runs": []}
    for root, tool_marker in roots:
        if not os.path.isdir(root):
            continue
        for run_id in sorted(os.listdir(root)):
            run_dir = os.path.join(root, run_id)
            if not os.path.isdir(run_dir):
                continue
            state, _record = classify(run_dir)
            if state != "candidate":
                continue
            finding = examine(
                notify, run_dir, run_id, tool_marker, db_path, args.lookback_days
            )
            entry = {
                "run_id": run_id,
                "run_dir": run_dir,
                "runner": tool_marker,
                "backfilled_at": stamp,
                "note": (
                    "Recovered provenance only. No notification was sent and no chat "
                    "turn was created; notify.json is left exactly as the run wrote it."
                ),
                **finding,
            }
            report["runs"].append(entry)
            if args.apply:
                with open(
                    os.path.join(run_dir, REPORT_NAME), "w", encoding="utf-8"
                ) as handle:
                    json.dump(entry, handle, ensure_ascii=False, indent=2)

    resolved = [r for r in report["runs"] if r["resolved"]]
    report["summary"] = {
        "candidates": len(report["runs"]),
        "resolved": len(resolved),
        "unrecoverable": len(report["runs"]) - len(resolved),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(
        f"{report['summary']['candidates']} run(s) whose notice was skipped for a missing "
        f"origin; {report['summary']['resolved']} recoverable, "
        f"{report['summary']['unrecoverable']} unrecoverable "
        f"({'written' if args.apply else 'dry run, nothing written'})"
    )
    for entry in report["runs"]:
        if entry["resolved"]:
            print(
                f"  [recovered] {entry['run_id']:32} {entry['origin_session']} "
                f"(source={entry['origin_source'] or '?'}, via {entry['method']})"
            )
        else:
            print(f"  [lost]      {entry['run_id']:32} {entry['reason']}")
    if report["runs"] and not args.apply:
        print(f"\nRe-run with --apply to write {REPORT_NAME} into each run dir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
