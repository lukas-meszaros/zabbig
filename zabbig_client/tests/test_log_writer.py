#!/usr/bin/env python3
"""
test_log_writer.py — Generate realistic log entries for testing the log collector.

Designed to run inside the zabbig-client Docker container (or locally).

Usage:
  python3 tests/test_log_writer.py [--log <path>] <command>

  Inside the container:
    docker exec -it zabbig-client python3 tests/test_log_writer.py demo
    docker exec -it zabbig-client python3 tests/test_log_writer.py write-api
    docker exec -it zabbig-client python3 tests/test_log_writer.py show-state

Commands:
  write-ok          Append 5 normal INFO lines (no severity match, count adds 5)
  write-warn        Append 1 WARN line
  write-error       Append 1 ERROR line
  write-fatal       Append 1 FATAL line
  write-api         Append 10 API call lines with varied response times
  write-flood       Append 50 mixed lines (stress test for large-file scanning)
  rotate            Rename the current log to <path>.1 (simulate log rotation)
  truncate          Truncate the log to 0 bytes (simulate logrotate copytruncate)
  show-state        Pretty-print all state files found in ./state/
  reset-state       Delete all log_*.json state files in ./state/
  demo              Run a full end-to-end demo: write → collect → write more → collect

Default log path: /tmp/zabbig_test.log

Examples:
  python3 tests/test_log_writer.py write-api
  python3 tests/test_log_writer.py --log /tmp/myapp.log write-error
  python3 tests/test_log_writer.py demo
  python3 tests/test_log_writer.py show-state
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Path setup — ensure src/ is importable when running from any location.
# Works both inside the container (/app/tests/) and on the host (zabbig_client/tests/).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# ---------------------------------------------------------------------------
# Log line generators
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _write(log_path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    print(f"  Wrote {len(lines)} line(s) → {log_path}")


def cmd_write_ok(log_path: str) -> None:
    print("[write-ok] Writing 5 normal INFO lines …")
    lines = [
        f"{_ts()} [INFO ] Service running normally (iteration {i})"
        for i in range(1, 6)
    ]
    _write(log_path, lines)


def cmd_write_warn(log_path: str) -> None:
    print("[write-warn] Writing 1 WARN line …")
    _write(log_path, [f"{_ts()} [WARN ] Cache miss rate elevated: 45%"])


def cmd_write_error(log_path: str) -> None:
    print("[write-error] Writing 1 ERROR line …")
    _write(log_path, [f"{_ts()} [ERROR] Database connection failed: timeout after 30s"])


def cmd_write_fatal(log_path: str) -> None:
    print("[write-fatal] Writing 1 FATAL line …")
    _write(log_path, [f"{_ts()} [FATAL] OutOfMemory: unable to allocate 512 MB"])


def cmd_write_api(log_path: str, count: int = 10) -> None:
    print(f"[write-api] Writing {count} API call lines …")
    endpoints = [
        "POST /api/v1/payment",
        "GET  /api/v1/order",
        "POST /api/v1/refund",
    ]
    statuses = [200, 200, 200, 200, 201, 400, 500]
    lines = []
    for _ in range(count):
        ep = random.choice(endpoints)
        status = random.choice(statuses)
        if random.random() < 0.15:
            ms = random.randint(1500, 5000)
        elif random.random() < 0.25:
            ms = random.randint(501, 1499)
        else:
            ms = random.randint(10, 499)
        lines.append(
            f"{_ts()} [INFO ] {ep} response_time={ms}ms status={status}"
        )
    _write(log_path, lines)


def cmd_write_flood(log_path: str) -> None:
    """Append a large burst of mixed lines to stress-test the reader."""
    print("[write-flood] Writing 50 mixed lines …")
    lines: list[str] = []
    for i in range(50):
        level = random.choices(
            ["INFO ", "WARN ", "ERROR", "DEBUG"],
            weights=[70, 15, 10, 5],
        )[0]
        msg = random.choice([
            f"Processed request #{i}",
            "Cache eviction triggered",
            f"response_time={random.randint(5, 8000)}ms status=200",
            "Heap usage: 78%",
            "WARN Cache miss rate elevated",
            "ERROR Failed to connect to upstream",
        ])
        lines.append(f"{_ts()} [{level}] {msg}")
    _write(log_path, lines)


def cmd_rotate(log_path: str) -> None:
    """Rename the current log file to simulate log rotation."""
    rotated = log_path + ".1"
    if os.path.exists(log_path):
        os.rename(log_path, rotated)
        print(f"[rotate] Renamed {log_path} → {rotated}")
        print("  The collector will detect the new inode and reset offset to 0.")
    else:
        print(f"[rotate] Log file not found: {log_path}")


def cmd_truncate(log_path: str) -> None:
    """Truncate the log to 0 bytes (simulates logrotate copytruncate)."""
    if os.path.exists(log_path):
        with open(log_path, "w") as fh:
            pass  # truncate
        print(f"[truncate] Truncated {log_path} to 0 bytes")
        print("  The collector detects size < stored offset and resets to 0.")
    else:
        print(f"[truncate] Log file not found: {log_path}")


def cmd_show_state(state_dir: str = "state") -> None:
    """Pretty-print all log state files."""
    if not os.path.isdir(state_dir):
        print(f"[show-state] No state directory found at '{state_dir}'")
        return
    files = [f for f in os.listdir(state_dir) if f.startswith("log_") and f.endswith(".json")]
    if not files:
        print(f"[show-state] No log state files in '{state_dir}'")
        return
    print(f"[show-state] State files in '{state_dir}':")
    for fname in sorted(files):
        path = os.path.join(state_dir, fname)
        with open(path) as fh:
            data = json.load(fh)
        print(f"  {fname}")
        print(f"    inode:  {data.get('inode', 'N/A')}")
        print(f"    offset: {data.get('offset', 0):,} bytes")


def cmd_reset_state(state_dir: str = "state") -> None:
    """Delete all log_*.json state files."""
    if not os.path.isdir(state_dir):
        print(f"[reset-state] No state directory at '{state_dir}' — nothing to do")
        return
    files = [f for f in os.listdir(state_dir) if f.startswith("log_") and f.endswith(".json")]
    for fname in files:
        os.unlink(os.path.join(state_dir, fname))
    print(f"[reset-state] Deleted {len(files)} state file(s) from '{state_dir}'")


# ---------------------------------------------------------------------------
# End-to-end demo
# ---------------------------------------------------------------------------

def cmd_demo(log_path: str) -> None:
    """
    Full demonstration:
      1. Write normal OK lines → collect (expect severity=0, count grows)
      2. Write WARN + ERROR → collect (expect severity=2)
      3. Write FATAL → collect (expect severity=3)
      4. Simulate rotation → collect (expect reset, severity=0)
      5. Write API lines → collect response time extraction
    """
    try:
        from zabbig_client.collectors.log import _log_condition, _log_count
        from zabbig_client.models import MetricDef
    except ImportError as exc:
        print(f"Cannot import zabbig_client: {exc}")
        print("Ensure you are running from the /app directory (or zabbig_client/) "
              "with src/ on the path.")
        sys.exit(1)

    state_dir = "state"

    def _make_severity_metric() -> MetricDef:
        return MetricDef(
            id="demo_severity",
            name="Demo severity",
            enabled=True,
            collector="log",
            key="demo.log.severity",
            delivery="batch",
            timeout_seconds=30.0,
            error_policy="skip",
            params={
                "path": log_path,
                "match": "WARN|ERROR|FATAL|OutOfMemory",
                "mode": "condition",
                "result": "max",
                "default_value": 0,
                "state_dir": state_dir,
                "conditions": [
                    {"when": "FATAL|OutOfMemory", "value": 3},
                    {"when": "ERROR",              "value": 2},
                    {"when": "WARN",               "value": 1},
                    {"value": 0},
                ],
            },
        )

    def _make_count_metric() -> MetricDef:
        return MetricDef(
            id="demo_api_count",
            name="Demo API count",
            enabled=True,
            collector="log",
            key="demo.log.api.count",
            delivery="batch",
            timeout_seconds=30.0,
            error_policy="skip",
            params={
                "path": log_path,
                "match": "POST /api/v1/payment",
                "mode": "count",
            },
        )

    def _make_response_time_metric() -> MetricDef:
        return MetricDef(
            id="demo_response_time",
            name="Demo response time",
            enabled=True,
            collector="log",
            key="demo.log.api.response_time_max",
            delivery="batch",
            timeout_seconds=30.0,
            error_policy="skip",
            params={
                "path": log_path,
                "match": "response_time=",
                "mode": "condition",
                "result": "max",
                "default_value": 0,
                "state_dir": state_dir,
                "conditions": [
                    {"extract": r"response_time=(\d+(?:\.\d+)?)", "compare": "gt", "threshold": 2000, "value": "$1"},
                    {"extract": r"response_time=(\d+(?:\.\d+)?)", "compare": "gt", "threshold":  500, "value": "$1"},
                    {"value": 0},
                ],
            },
        )

    def collect_all() -> None:
        sev = _log_condition(_make_severity_metric())
        cnt = _log_count(_make_count_metric())
        rt  = _log_condition(_make_response_time_metric())
        print(f"    → severity={sev}  api_calls_total={cnt}  response_time_max={rt}ms")

    # Clean up from any previous demo run
    if os.path.exists(log_path):
        os.unlink(log_path)
    cmd_reset_state(state_dir)

    print("\n=== DEMO START ===\n")

    print("Step 1: Write 5 normal INFO lines, then collect")
    cmd_write_ok(log_path)
    collect_all()

    print("\nStep 2: Write WARN + ERROR lines, then collect")
    cmd_write_warn(log_path)
    cmd_write_error(log_path)
    collect_all()

    print("\nStep 3: Write another OK batch, then collect (severity resets to 0)")
    cmd_write_ok(log_path)
    collect_all()

    print("\nStep 4: Write FATAL line, then collect")
    cmd_write_fatal(log_path)
    collect_all()

    print("\nStep 5: Write 15 API lines, then collect (response times + count)")
    cmd_write_api(log_path, count=15)
    collect_all()

    print("\nStep 6: Simulate log rotation, then collect (offset resets)")
    cmd_rotate(log_path)
    cmd_write_api(log_path, count=5)
    collect_all()

    print("\nStep 7: Simulate truncation, then collect (offset resets)")
    cmd_write_api(log_path, count=10)
    cmd_truncate(log_path)
    cmd_write_ok(log_path)
    collect_all()

    print("\n=== DEMO END ===")
    print()
    cmd_show_state(state_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate test log entries for the zabbig log collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--log",
        default="/tmp/zabbig_test.log",
        metavar="PATH",
        help="Path to the log file  (default: /tmp/zabbig_test.log)",
    )
    parser.add_argument(
        "--state-dir",
        default="state",
        metavar="DIR",
        help="State directory for show-state / reset-state  (default: state)",
    )
    parser.add_argument(
        "command",
        choices=[
            "write-ok", "write-warn", "write-error", "write-fatal",
            "write-api", "write-flood",
            "rotate", "truncate",
            "show-state", "reset-state",
            "demo",
        ],
    )
    args = parser.parse_args()

    dispatch = {
        "write-ok":    lambda: cmd_write_ok(args.log),
        "write-warn":  lambda: cmd_write_warn(args.log),
        "write-error": lambda: cmd_write_error(args.log),
        "write-fatal": lambda: cmd_write_fatal(args.log),
        "write-api":   lambda: cmd_write_api(args.log),
        "write-flood": lambda: cmd_write_flood(args.log),
        "rotate":      lambda: cmd_rotate(args.log),
        "truncate":    lambda: cmd_truncate(args.log),
        "show-state":  lambda: cmd_show_state(args.state_dir),
        "reset-state": lambda: cmd_reset_state(args.state_dir),
        "demo":        lambda: cmd_demo(args.log),
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()
