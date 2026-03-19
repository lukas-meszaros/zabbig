"""
disk.py — Disk/filesystem metrics collector.

Uses os.statvfs() — works on Linux and macOS.
params:
  mount  — filesystem path to inspect (e.g. "/", "/data")
  mode   — "used_percent" | "used_bytes" | "free_bytes"
"""
from __future__ import annotations

import asyncio
import os
import time

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector


@register_collector("disk")
class DiskCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        mount = metric.params.get("mount", "/")
        mode = metric.params.get("mode", "used_percent")
        t0 = time.monotonic()

        value = await asyncio.to_thread(_disk_stat, mount, mode)

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="disk",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=f"statvfs({mount}) mode={mode}",
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Blocking helpers
# ---------------------------------------------------------------------------

def _disk_stat(mount: str, mode: str) -> float | int:
    st = os.statvfs(mount)
    total_bytes = st.f_blocks * st.f_frsize
    free_bytes = st.f_bavail * st.f_frsize  # f_bavail = available to non-root
    used_bytes = total_bytes - free_bytes

    if mode == "free_bytes":
        return free_bytes
    elif mode == "used_bytes":
        return used_bytes
    elif mode == "used_percent":
        if total_bytes == 0:
            return 0.0
        return round(used_bytes / total_bytes * 100.0, 2)
    else:
        raise ValueError(f"Unknown disk collector mode: '{mode}'")
