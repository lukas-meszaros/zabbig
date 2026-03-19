"""
cpu.py — CPU metrics collector.

Reads from /proc/stat and /proc/loadavg (Linux).
Each metric is dispatched via params.mode:
  percent  — CPU utilization percentage (requires two /proc/stat reads, 0.2s apart)
  load1    — 1-minute load average
  load5    — 5-minute load average
  load15   — 15-minute load average
  uptime   — system uptime in seconds (/proc/uptime)

All blocking reads are dispatched to the thread pool via asyncio.to_thread
so they never block the event loop.
"""
from __future__ import annotations

import asyncio
import time

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector


@register_collector("cpu")
class CpuCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        mode = metric.params.get("mode", "percent")
        proc_root = metric.params.get("proc_root", "/proc")
        t0 = time.monotonic()

        if mode == "percent":
            value = await asyncio.to_thread(_cpu_percent, proc_root)
        elif mode in ("load1", "load5", "load15"):
            value = await asyncio.to_thread(_load_avg, mode, proc_root)
        elif mode == "uptime":
            value = await asyncio.to_thread(_uptime_seconds, proc_root)
        else:
            raise ValueError(f"Unknown cpu collector mode: '{mode}'")

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="cpu",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=f"{proc_root}/stat (mode={mode})",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Blocking helpers (run in thread pool)
# ---------------------------------------------------------------------------

def _read_proc_stat_cpu(proc_root: str) -> tuple[int, int]:
    """Return (total_jiffies, idle_jiffies) from the first line of {proc_root}/stat."""
    with open(f"{proc_root}/stat", "r") as fh:
        line = fh.readline()
    # cpu  user nice system idle iowait irq softirq steal guest guest_nice
    parts = line.split()
    if parts[0] != "cpu":
        raise RuntimeError("Unexpected /proc/stat format")
    values = [int(x) for x in parts[1:9]]
    total = sum(values)
    # idle + iowait
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _cpu_percent(proc_root: str) -> float:
    """
    Measure CPU utilization by reading {proc_root}/stat twice with a 0.2s gap.
    Returns a float in [0.0, 100.0].
    """
    t1, i1 = _read_proc_stat_cpu(proc_root)
    time.sleep(0.2)
    t2, i2 = _read_proc_stat_cpu(proc_root)

    delta_total = t2 - t1
    delta_idle = i2 - i1

    if delta_total <= 0:
        return 0.0
    return round((1.0 - delta_idle / delta_total) * 100.0, 2)


def _load_avg(mode: str, proc_root: str) -> float:
    """Read {proc_root}/loadavg and return the requested average."""
    with open(f"{proc_root}/loadavg", "r") as fh:
        parts = fh.read().split()
    mapping = {"load1": 0, "load5": 1, "load15": 2}
    return float(parts[mapping[mode]])


def _uptime_seconds(proc_root: str) -> float:
    """Read {proc_root}/uptime and return uptime in seconds."""
    with open(f"{proc_root}/uptime", "r") as fh:
        return float(fh.read().split()[0])
