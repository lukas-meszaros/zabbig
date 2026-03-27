"""
scheduler.py — Per-metric scheduling guards.

Evaluates four optional constraints on every invocation to decide whether
a given metric should be collected in this run:

  1. time_window_from  — metric not yet in its active window
  2. time_window_till  — metric's active window has passed
  3. max_executions_per_day — today's quota is exhausted
  4. run_frequency — this run does not match the metric's cadence

All constraints are bypassed when dry_run=True, so --dry-run always
executes every enabled metric regardless of schedule settings.

The run counter is 1-based and resets to 1 at the start of each new day.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional, Tuple, Union

from .models import MetricDef

log = logging.getLogger(__name__)

VALID_FREQUENCY_STRINGS = frozenset({"even", "odd"})


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_hhmm(value: str) -> int:
    """Convert a normalised 4-digit HHMM string to minutes since midnight."""
    return int(value[:2]) * 60 + int(value[2:])


def normalise_hhmm(raw: object) -> str:
    """
    Accept an HHMM value that may arrive as an int (e.g. 800 → "0800") or a
    string and return a zero-padded 4-character string.  Assumes the value has
    already been validated by config_loader.
    """
    return str(raw).zfill(4)


def current_minutes() -> int:
    """Return the current local time as minutes since midnight."""
    now = datetime.datetime.now()
    return now.hour * 60 + now.minute


def today_str() -> str:
    """Return today's local date as an ISO-8601 string (YYYY-MM-DD)."""
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def should_execute(
    metric: MetricDef,
    run_counter: int,
    execution_count: int,
    dry_run: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Decide whether *metric* should be collected in the current invocation.

    Args:
        metric:          the metric definition (schedule fields may be None)
        run_counter:     1-based counter reset each calendar day
        execution_count: how many times this metric has already run today
        dry_run:         when True all scheduling constraints are bypassed

    Returns:
        (True, None)            — metric should execute
        (False, reason_string)  — metric is skipped; reason suitable for logging
    """
    if dry_run:
        return True, None

    # ------------------------------------------------------------------
    # 1. Time window
    # ------------------------------------------------------------------
    if metric.time_window_from is not None or metric.time_window_till is not None:
        now = current_minutes()

        if metric.time_window_from is not None:
            from_min = parse_hhmm(metric.time_window_from)
            if now < from_min:
                return False, f"time_window_from={metric.time_window_from} (current={now // 60:02d}{now % 60:02d})"

        if metric.time_window_till is not None:
            till_min = parse_hhmm(metric.time_window_till)
            if now >= till_min:
                return False, f"time_window_till={metric.time_window_till} (current={now // 60:02d}{now % 60:02d})"

    # ------------------------------------------------------------------
    # 2. Max executions per day
    # ------------------------------------------------------------------
    max_exec = metric.max_executions_per_day
    if max_exec is not None and max_exec > 0:
        if execution_count >= max_exec:
            return False, f"max_executions_per_day={max_exec} (today={execution_count})"

    # ------------------------------------------------------------------
    # 3. Run frequency
    # ------------------------------------------------------------------
    freq = metric.run_frequency
    if freq is not None:
        if isinstance(freq, str):
            if freq == "even" and run_counter % 2 != 0:
                return False, f"run_frequency=even (run={run_counter})"
            if freq == "odd" and run_counter % 2 != 1:
                return False, f"run_frequency=odd (run={run_counter})"
        elif isinstance(freq, int) and freq > 1:
            # Execute on run 1, 1+freq, 1+2*freq, …
            if (run_counter - 1) % freq != 0:
                return False, f"run_frequency={freq} (run={run_counter})"

    return True, None
