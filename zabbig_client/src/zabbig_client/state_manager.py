"""
state_manager.py — Optional lightweight run-state persistence.

Writes a small JSON file after each run so you can inspect:
  - last successful run timestamp
  - last run duration and counts
  - consecutive failure count (useful for alerting on broken cron)

If state.enabled=false (default), this module is a no-op.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict

from .models import ClientConfig, RunSummary

log = logging.getLogger(__name__)

STATE_FILE = "last_run.json"
SCHEDULE_FILE = "schedule.json"


def save_state(config: ClientConfig, summary: RunSummary) -> None:
    if not config.state.enabled:
        return

    state_dir = config.state.directory
    os.makedirs(state_dir, exist_ok=True)
    state_path = os.path.join(state_dir, STATE_FILE)

    # Load existing state to track consecutive failures
    existing = _load_raw(state_path)
    consecutive_failures = existing.get("consecutive_failures", 0)
    if summary.success:
        consecutive_failures = 0
    else:
        consecutive_failures += 1

    state = {
        "last_run_ts": int(time.time()),
        "success": summary.success,
        "duration_ms": round(summary.duration_ms, 1),
        "metrics_sent": summary.sent_batch + summary.sent_immediate,
        "collectors_failed": summary.collected_failed + summary.collected_timeout,
        "sender_failures": summary.sender_failures,
        "consecutive_failures": consecutive_failures,
    }

    tmp_path = state_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_path, state_path)
        log.debug("State saved to %s", state_path)
    except OSError as exc:
        log.warning("Could not save state to %s: %s", state_path, exc)


def load_state(config: ClientConfig) -> dict:
    """Load the last run state. Returns empty dict if disabled or not found."""
    if not config.state.enabled:
        return {}
    state_path = os.path.join(config.state.directory, STATE_FILE)
    return _load_raw(state_path)


def _load_raw(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Schedule state — always persisted (independent of state.enabled)
# ---------------------------------------------------------------------------

def load_schedule_state(config: ClientConfig) -> dict:
    """
    Load the scheduling state: run counter and per-metric execution counts.

    Unlike run state, this is always read regardless of state.enabled because
    the scheduling feature requires persistence to function correctly.
    Returns an empty dict when no state file exists yet.
    """
    state_path = os.path.join(config.state.directory, SCHEDULE_FILE)
    return _load_raw(state_path)


def save_schedule_state(config: ClientConfig, state: dict) -> None:
    """
    Save scheduling state (run counter + per-metric execution counts).

    Always writes regardless of state.enabled.  Creates the state directory
    if it does not yet exist.
    """
    state_dir = config.state.directory
    os.makedirs(state_dir, exist_ok=True)
    state_path = os.path.join(state_dir, SCHEDULE_FILE)
    tmp_path = state_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_path, state_path)
        log.debug("Schedule state saved to %s", state_path)
    except OSError as exc:
        log.warning("Could not save schedule state to %s: %s", state_path, exc)
