#!/usr/bin/env python3
"""
test_log_writer.py — Generate realistic log entries for testing the log collector.

Designed to run inside the zabbig-client Docker container (or locally).
Log paths match the metrics.yaml example definitions:
  App log  (severity / error monitoring): /var/log/myapp/app.log
  Access log (API call count + response time): /var/log/myapp/access.log

Usage:
  python3 tests/test_log_writer.py [options] <command>

  Inside the container:
    docker exec -it zabbig-client python3 tests/test_log_writer.py demo
    docker exec -it zabbig-client python3 tests/test_log_writer.py write-api
    docker exec -it zabbig-client python3 tests/test_log_writer.py show-state

Commands:
  write-ok          Append 5 normal INFO lines to --app-log (no severity match)
  write-warn        Append 1 WARN line to --app-log
  write-error       Append 1 ERROR line to --app-log
  write-fatal       Append 1 FATAL line to --app-log
  write-api         Append 10 API call lines to --access-log
  write-flood       Append 50 mixed lines to both logs (stress test)
  rotate-app        Rename --app-log to <path>.1 (simulate rotation)
  rotate-access     Rename --access-log to <path>.1 (simulate rotation)
  truncate-app      Truncate --app-log to 0 bytes (simulate copytruncate)
  truncate-access   Truncate --access-log to 0 bytes (simulate copytruncate)
  show-state        Pretty-print all state files found in ./state/
  reset-state       Delete all log_*.json state files in ./state/
  demo              Run a full end-to-end demo exercising all three log metrics

Default paths (match metrics.yaml examples):
  --app-log     /var/log/myapp/app.log
  --access-log  /var/log/myapp/access.log

Examples:
  python3 tests/test_log_writer.py write-api
  python3 tests/test_log_writer.py write-fatal
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


def cmd_write_ok(app_log: str) -> None:
    print("[write-ok] Writing 5 normal INFO lines …")
    lines = [
        f"{_ts()} [INFO ] Service running normally (iteration {i})"
        for i in range(1, 6)
    ]
    _write(app_log, lines)


def cmd_write_warn(app_log: str) -> None:
    print("[write-warn] Writing 1 WARN line …")
    _write(app_log, [f"{_ts()} [WARN ] Cache miss rate elevated: 45%"])


def cmd_write_error(app_log: str) -> None:
    print("[write-error] Writing 1 ERROR line …")
    _write(app_log, [f"{_ts()} [ERROR] Database connection failed: timeout after 30s"])


def cmd_write_fatal(app_log: str) -> None:
    print("[write-fatal] Writing 1 FATAL line …")
    _write(app_log, [f"{_ts()} [FATAL] OutOfMemory: unable to allocate 512 MB"])


def cmd_write_api(access_log: str, count: int = 10) -> None:
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
    _write(access_log, lines)


def cmd_write_flood(app_log: str, access_log: str) -> None:
    """Append a large burst of mixed lines to both logs."""
    print("[write-flood] Writing 50 lines to app log …")
    app_lines: list[str] = []
    for i in range(50):
        level = random.choices(
            ["INFO ", "WARN ", "ERROR", "DEBUG"],
            weights=[70, 15, 10, 5],
        )[0]
        msg = random.choice([
            f"Processed request #{i}",
            "Cache eviction triggered",
            "Heap usage: 78%",
            "WARN Cache miss rate elevated",
            "ERROR Failed to connect to upstream",
        ])
        app_lines.append(f"{_ts()} [{level}] {msg}")
    _write(app_log, app_lines)
    print("[write-flood] Writing 50 API lines to access log …")
    cmd_write_api(access_log, count=50)


def cmd_rotate(log_path: str, label: str) -> None:
    """Rename a log file to simulate log rotation."""
    rotated = log_path + ".1"
    if os.path.exists(log_path):
        os.rename(log_path, rotated)
        print(f"[rotate-{label}] Renamed {log_path} → {rotated}")
        print("  The collector will detect the new inode and reset offset to 0.")
    else:
        print(f"[rotate-{label}] Log file not found: {log_path}")


def cmd_truncate(log_path: str, label: str) -> None:
    """Truncate a log to 0 bytes (simulates logrotate copytruncate)."""
    if os.path.exists(log_path):
        with open(log_path, "w") as fh:
            pass  # truncate
        print(f"[truncate-{label}] Truncated {log_path} to 0 bytes")
        print("  The collector detects size < stored offset and resets to 0.")
    else:
        print(f"[truncate-{label}] Log file not found: {log_path}")


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

def cmd_demo(app_log: str, access_log: str) -> None:
    """
    Full demonstration exercising all three metrics.yaml log metrics:
      log_app_severity          → app_log   (condition, WARN/ERROR/FATAL)
      log_api_response_time_max → access_log (condition, response_time extraction)
      log_payment_api_calls_total → access_log (count, cumulative)
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
            id="log_app_severity",
            name="Application log severity",
            enabled=True,
            collector="log",
            key="app.log.severity",
            delivery="immediate",
            timeout_seconds=30.0,
            error_policy="skip",
            params={
                "path": app_log,
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
            id="log_payment_api_calls_total",
            name="Payment API calls total (log)",
            enabled=True,
            collector="log",
            key="app.log.payment.calls.total",
            delivery="batch",
            timeout_seconds=60.0,
            error_policy="skip",
            params={
                "path": access_log,
                "match": "POST /api/v1/payment",
                "mode": "count",
            },
        )

    def _make_response_time_metric() -> MetricDef:
        return MetricDef(
            id="log_api_response_time_max",
            name="API max response time (log)",
            enabled=True,
            collector="log",
            key="app.log.api.response_time_max_ms",
            delivery="batch",
            timeout_seconds=30.0,
            error_policy="skip",
            params={
                "path": access_log,
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
        try:
            cnt = _log_count(_make_count_metric())
            rt  = _log_condition(_make_response_time_metric())
        except FileNotFoundError:
            cnt = 0
            rt  = 0
        print(f"    → app.log.severity={sev}  payment.calls.total={cnt}  response_time_max={rt}ms")

    # Clean up from any previous demo run
    for p in (app_log, access_log):
        if os.path.exists(p):
            os.unlink(p)
    cmd_reset_state(state_dir)

    print("\n=== DEMO START ===")
    print(f"  app log    : {app_log}")
    print(f"  access log : {access_log}")
    print()

    print("Step 1: Write 5 normal INFO lines to app log, then collect")
    cmd_write_ok(app_log)
    collect_all()

    print("\nStep 2: Write WARN + ERROR to app log, then collect")
    cmd_write_warn(app_log)
    cmd_write_error(app_log)
    collect_all()

    print("\nStep 3: Write another OK batch, then collect (severity resets to 0)")
    cmd_write_ok(app_log)
    collect_all()

    print("\nStep 4: Write FATAL to app log, then collect")
    cmd_write_fatal(app_log)
    collect_all()

    print("\nStep 5: Write 15 API lines to access log, then collect")
    cmd_write_api(access_log, count=15)
    collect_all()

    print("\nStep 6: Simulate app log rotation, then collect (offset resets)")
    cmd_rotate(app_log, "app")
    cmd_write_warn(app_log)   # first line in fresh file
    collect_all()

    print("\nStep 7: Simulate access log truncation, then collect (offset resets)")
    cmd_write_api(access_log, count=10)
    cmd_truncate(access_log, "access")
    cmd_write_api(access_log, count=5)
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
        "--app-log",
        default="/var/log/myapp/app.log",
        metavar="PATH",
        help="Path to the application log  (default: /var/log/myapp/app.log)",
    )
    parser.add_argument(
        "--access-log",
        default="/var/log/myapp/access.log",
        metavar="PATH",
        help="Path to the access/API log    (default: /var/log/myapp/access.log)",
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
            "rotate-app", "rotate-access",
            "truncate-app", "truncate-access",
            "show-state", "reset-state",
            "demo",
        ],
    )
    args = parser.parse_args()

    dispatch = {
        "write-ok":       lambda: cmd_write_ok(args.app_log),
        "write-warn":     lambda: cmd_write_warn(args.app_log),
        "write-error":    lambda: cmd_write_error(args.app_log),
        "write-fatal":    lambda: cmd_write_fatal(args.app_log),
        "write-api":      lambda: cmd_write_api(args.access_log),
        "write-flood":    lambda: cmd_write_flood(args.app_log, args.access_log),
        "rotate-app":     lambda: cmd_rotate(args.app_log, "app"),
        "rotate-access":  lambda: cmd_rotate(args.access_log, "access"),
        "truncate-app":   lambda: cmd_truncate(args.app_log, "app"),
        "truncate-access":lambda: cmd_truncate(args.access_log, "access"),
        "show-state":     lambda: cmd_show_state(args.state_dir),
        "reset-state":    lambda: cmd_reset_state(args.state_dir),
        "demo":           lambda: cmd_demo(args.app_log, args.access_log),
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()
