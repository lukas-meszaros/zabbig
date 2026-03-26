"""
memory.py — Memory/swap metrics collector.

Reads from /proc/meminfo (Linux).
params.mode:
  used_percent      — RAM used percentage
  available_bytes   — MemAvailable in bytes
  swap_used_percent — swap used percentage (0.0 if no swap)
"""
from __future__ import annotations

import asyncio
import time

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector


@register_collector("memory")
class MemoryCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        mode = metric.params.get("mode", "used_percent")
        proc_root = metric.params.get("proc_root", "/proc")
        t0 = time.monotonic()

        info = await asyncio.to_thread(_read_meminfo, proc_root)

        if mode == "used_percent":
            value = _mem_used_percent(info)
        elif mode == "available_bytes":
            value = info["MemAvailable"] * 1024
        elif mode == "swap_used_percent":
            value = _swap_used_percent(info)
        else:
            raise ValueError(f"Unknown memory collector mode: '{mode}'")

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="memory",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=f"{proc_root}/meminfo (mode={mode})",
            duration_ms=(time.monotonic() - t0) * 1000,
            host_name=metric.host_name,
        )


# ---------------------------------------------------------------------------
# Blocking helpers
# ---------------------------------------------------------------------------

def _read_meminfo(proc_root: str) -> dict[str, int]:
    """Parse {proc_root}/meminfo and return a dict of key → kibibytes."""
    result: dict[str, int] = {}
    with open(f"{proc_root}/meminfo", "r") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                try:
                    result[key] = int(parts[1])
                except ValueError:
                    pass
    return result


def _mem_used_percent(info: dict[str, int]) -> float:
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    if total == 0:
        return 0.0
    used = total - available
    return round(used / total * 100.0, 2)


def _swap_used_percent(info: dict[str, int]) -> float:
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    if swap_total == 0:
        return 0.0
    swap_used = swap_total - swap_free
    return round(swap_used / swap_total * 100.0, 2)
