"""
disk.py — Disk/filesystem metrics collector.

Uses os.statvfs().
params:
  mount  — filesystem path to inspect (e.g. "/", "/data")
  mode   — "used_percent"        | "used_bytes"         | "free_bytes"
           "inodes_used_percent" | "inodes_used"         | "inodes_free"
           "inodes_total"

Note: filesystems with dynamic inode allocation (e.g. btrfs, some tmpfs)
      report f_files=0.  inodes_used_percent returns 0.0 in that case.
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
            host_name=metric.host_name,
        )


# ---------------------------------------------------------------------------
# Blocking helpers
# ---------------------------------------------------------------------------

def _disk_stat(mount: str, mode: str) -> float | int:
    st = os.statvfs(mount)

    # --- block (byte) metrics ---
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

    # --- inode metrics ---
    # f_files=0 means the filesystem uses dynamic inode allocation (e.g. btrfs)
    total_inodes = st.f_files
    free_inodes = st.f_ffree
    used_inodes = total_inodes - free_inodes

    if mode == "inodes_total":
        return total_inodes
    elif mode == "inodes_free":
        return free_inodes
    elif mode == "inodes_used":
        return used_inodes
    elif mode == "inodes_used_percent":
        if total_inodes == 0:
            return 0.0  # dynamic inode allocation — treat as unlimited
        return round(used_inodes / total_inodes * 100.0, 2)
    else:
        raise ValueError(f"Unknown disk collector mode: '{mode}'")
