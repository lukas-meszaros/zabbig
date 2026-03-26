"""
log.py — Application log file monitoring collector.

Scans log files for lines matching a regex and returns a derived value.
Two modes:

  condition — Incremental scan (last stored offset → EOF).
              Evaluates an ordered list of sub-conditions on each matching
              line, then collapses all results using `result` strategy.
              Returns `default_value` when no line matched this scan window.
              State (byte offset + inode number) is persisted between runs so
              each run resumes exactly where the previous one stopped.

  count     — Full-file scan (byte 0 → EOF every run).
              Counts all lines matching `match` and returns a cumulative
              integer. The value grows monotonically as the file grows,
              making it ideal for trend / rate-of-change graphs in Zabbix.

Large-file safety:
  Files are opened in binary mode and iterated line-by-line with readline()
  after seeking to the stored offset.  The full file is never loaded into
  memory.  For condition mode the cost is proportional to new bytes since the
  last run; for count mode the cost is proportional to the whole file.

File-rotation / truncation detection:
  On each run the inode number of the resolved file is compared against the
  stored value.  A mismatch (new file) or a file size smaller than the stored
  offset (truncation / logrotate in-place) resets the offset to 0.

Params reference — see metrics.yaml header for full documentation.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector


@register_collector("log")
class LogCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        t0 = time.monotonic()
        mode = metric.params.get("mode", "condition")

        if mode == "condition":
            value, cond_host_name = await asyncio.to_thread(_log_condition, metric)
        elif mode == "count":
            value = await asyncio.to_thread(_log_count, metric)
            cond_host_name = None
        else:
            raise ValueError(f"Unknown log collector mode: '{mode}'")

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="log",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=f"log mode={mode} path={metric.params.get('path', '')}",
            duration_ms=(time.monotonic() - t0) * 1000,
            host_name=cond_host_name or metric.host_name,
        )


# ---------------------------------------------------------------------------
# Blocking helpers (called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _resolve_path(raw_path: str) -> str:
    """
    Resolve raw_path to an absolute file path.

    The basename portion may be a Python regex; the directory must be literal.
    When multiple files match the regex, the most recently modified is used.
    Raises FileNotFoundError when no match exists.
    """
    dirpart = os.path.dirname(raw_path) or "."
    basepart = os.path.basename(raw_path)
    abs_dir = os.path.abspath(dirpart)

    # Fast path: exact filename (no regex metacharacters needed)
    exact = os.path.join(abs_dir, basepart)
    if os.path.isfile(exact):
        return exact

    if not os.path.isdir(abs_dir):
        raise FileNotFoundError(
            f"Log directory not found: '{abs_dir}' (from path='{raw_path}')"
        )

    try:
        entries = os.listdir(abs_dir)
    except OSError as exc:
        raise FileNotFoundError(
            f"Cannot list log directory '{abs_dir}': {exc}"
        ) from exc

    try:
        pattern = re.compile(f"^(?:{basepart})$")
    except re.error as exc:
        raise ValueError(
            f"Invalid regex in log path basename '{basepart}': {exc}"
        ) from exc

    matches = [
        e for e in entries
        if pattern.match(e) and os.path.isfile(os.path.join(abs_dir, e))
    ]
    if not matches:
        raise FileNotFoundError(
            f"No files matching '{raw_path}' found in '{abs_dir}'"
        )

    # Most recently modified file wins
    matches.sort(
        key=lambda name: os.path.getmtime(os.path.join(abs_dir, name)),
        reverse=True,
    )
    return os.path.join(abs_dir, matches[0])


def _state_file(state_dir: str, metric_id: str) -> str:
    return os.path.join(state_dir, f"log_{metric_id}.json")


def _load_state(path: str) -> dict:
    """Return state dict from disk. Returns empty dict if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(path: str, state: dict) -> None:
    """Atomically persist state via temp-file + rename."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _log_condition(metric: MetricDef) -> Any:
    """
    Incremental scan from the stored byte offset to EOF.
    Evaluates conditions on each matching line and returns one value
    according to the `result` strategy. Stores updated offset on exit.
    """
    params = metric.params
    raw_path: str = params["path"]
    match_pattern: str = params.get("match", "")
    encoding: str = params.get("encoding", "utf-8")
    result_strategy: str = params.get("result", "last")
    default_value: Any = params.get("default_value", 0)
    conditions: list[dict] = params.get("conditions", [])
    state_dir: str = params.get("state_dir", "state")

    resolved_path = _resolve_path(raw_path)
    sf = _state_file(state_dir, metric.id)
    state = _load_state(sf)

    stat_info = os.stat(resolved_path)
    current_inode: int = stat_info.st_ino
    current_size: int = stat_info.st_size

    stored_inode = state.get("inode")
    start_offset: int = state.get("offset", 0)

    # Reset on rotation (new inode) or truncation (file shrunk)
    if stored_inode != current_inode or current_size < start_offset:
        start_offset = 0

    match_re = re.compile(match_pattern) if match_pattern else None
    entries: list[tuple[Any, str | None]] = []
    new_offset = start_offset

    with open(resolved_path, "rb") as fh:
        fh.seek(start_offset)
        while True:
            line_start = fh.tell()
            raw_line = fh.readline()

            if not raw_line:
                # True EOF — all complete lines consumed
                break

            if not raw_line.endswith(b"\n"):
                # Partial line: app is still writing this line.
                # Leave offset at this line's start so we re-read it next run.
                new_offset = line_start
                break

            new_offset = fh.tell()
            line = raw_line.decode(encoding, errors="replace").rstrip("\r\n")

            if match_re and not match_re.search(line):
                continue

            # Line passed the top-level `match` filter — evaluate conditions
            if conditions:
                val, cond_host = _eval_conditions(conditions, line)
                if val is not None:
                    entries.append((val, cond_host))
            else:
                # No conditions defined — each match contributes 1
                entries.append((1, None))

    state["inode"] = current_inode
    state["offset"] = new_offset
    _save_state(sf, state)

    if not entries:
        return default_value, None
    return _resolve_result_with_host(entries, result_strategy)


def _log_count(metric: MetricDef) -> int:
    """
    Full-file scan from byte 0 each run. Counts lines matching `match`.
    Does not read or write offset state — the counter is always cumulative.
    """
    params = metric.params
    raw_path: str = params["path"]
    match_pattern: str = params.get("match", "")
    encoding: str = params.get("encoding", "utf-8")

    resolved_path = _resolve_path(raw_path)
    match_re = re.compile(match_pattern) if match_pattern else None

    count = 0
    with open(resolved_path, "rb") as fh:
        while True:
            raw_line = fh.readline()
            if not raw_line:
                break
            line = raw_line.decode(encoding, errors="replace").rstrip("\r\n")
            if match_re is None or match_re.search(line):
                count += 1
    return count


# ---------------------------------------------------------------------------
# Condition evaluation helpers
# ---------------------------------------------------------------------------

def _eval_conditions(conditions: list[dict], line: str) -> tuple[Any, str | None]:
    """
    Walk the ordered condition list. Return (value, host_name) of the first match.
    Returns (None, None) if no condition matches.
    """
    for cond in conditions:
        matched, value, host_name = _eval_one_condition(cond, line)
        if matched:
            return value, host_name
    return None, None


def _eval_one_condition(cond: dict, line: str) -> tuple[bool, Any, str | None]:
    """
    Evaluate a single condition entry against `line`.

    Entry types:
      { when: <regex>, value: X [, host_name: H] }
        — Pure regex match. Returns X (and optional host override H) when the
          regex matches the line.

      { extract: <regex with one capture group>,
        compare: gt|lt|gte|lte|eq,
        threshold: <number>,
        value: X | "$1" [, host_name: H] }
        — Extracts a number via capture group, compares against threshold.
          value="$1" returns the extracted number itself as the metric value.

      { value: X [, host_name: H] }
        — Catch-all. Always matches; place last in the list.

    Returns (matched: bool, value: Any, host_name: str | None).
    The host_name is taken from cond.get("host_name") and overrides the metric-
    level host_name when the condition matches. None means no override.
    """
    value_raw = cond.get("value")
    cond_host_name: str | None = cond.get("host_name") or None

    if "when" in cond:
        if re.search(cond["when"], line):
            return True, value_raw, cond_host_name
        return False, None, None

    if "extract" in cond:
        m = re.search(cond["extract"], line)
        if not m:
            return False, None, None
        try:
            captured = float(m.group(1))
        except (IndexError, ValueError):
            return False, None, None

        compare = cond.get("compare", "gt")
        threshold = float(cond.get("threshold", 0))

        _OPS = {
            "gt":  lambda a, b: a > b,
            "lt":  lambda a, b: a < b,
            "gte": lambda a, b: a >= b,
            "lte": lambda a, b: a <= b,
            "eq":  lambda a, b: a == b,
        }
        op = _OPS.get(compare)
        if op is None:
            raise ValueError(f"Unknown compare operator: '{compare}'")
        if not op(captured, threshold):
            return False, None, None

        # value="$1" → return the captured number as the metric value
        if value_raw == "$1":
            return True, captured, cond_host_name
        return True, value_raw, cond_host_name

    # Catch-all: no `when`, no `extract` — always matches
    return True, value_raw, cond_host_name


def _resolve_result(values: list[Any], strategy: str) -> Any:
    """
    Collapse a list of per-line values into one final value.

      last  — value from the last  matching line
      first — value from the first matching line
      max   — numerically highest; falls back to last if values are non-numeric
      min   — numerically lowest;  falls back to last if values are non-numeric
    """
    if not values:
        return None
    if strategy == "first":
        return values[0]
    if strategy == "last":
        return values[-1]

    numeric: list[float] = []
    for v in values:
        try:
            numeric.append(float(v))
        except (TypeError, ValueError):
            pass

    if not numeric:
        return values[-1]  # non-numeric values: fall back to last

    if strategy == "max":
        return max(numeric)
    if strategy == "min":
        return min(numeric)

    raise ValueError(f"Unknown result strategy: '{strategy}'")


def _resolve_result_with_host(
    entries: list[tuple[Any, str | None]], strategy: str
) -> tuple[Any, str | None]:
    """
    Like _resolve_result but preserves the host_name from the winning entry.

    Each entry is a (value, host_name) pair. The result strategy selects the
    winning entry; its host_name is returned alongside the value.

      last  — entry from the last  matching line
      first — entry from the first matching line
      max   — entry with numerically highest value; falls back to last
      min   — entry with numerically lowest  value; falls back to last
    """
    if not entries:
        return None, None
    if strategy == "first":
        return entries[0]
    if strategy == "last":
        return entries[-1]

    numeric: list[tuple[float, str | None]] = []
    for v, h in entries:
        try:
            numeric.append((float(v), h))
        except (TypeError, ValueError):
            pass

    if not numeric:
        return entries[-1]  # non-numeric values: fall back to last

    if strategy == "max":
        return max(numeric, key=lambda x: x[0])
    if strategy == "min":
        return min(numeric, key=lambda x: x[0])

    raise ValueError(f"Unknown result strategy: '{strategy}'")

