"""
service.py — Service state collector.

Returns 1 (running/healthy) or 0 (not running/unhealthy).

params.check_mode:
  systemd  — calls `systemctl is-active <service_name>` (requires systemd)
             params.service_name must be set
  process  — scans /proc/*/cmdline for a regex process_pattern (Linux only)
             params.process_pattern must be set

For systemd check, exit code 0 = active, anything else = not active.
For process check, at least one matching cmdline = running.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector


@register_collector("service")
class ServiceCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        check_mode = metric.params.get("check_mode", "systemd")
        t0 = time.monotonic()

        if check_mode == "systemd":
            service_name = metric.params["service_name"]
            state = await asyncio.to_thread(_systemd_check, service_name)
            source = f"systemctl is-active {service_name}"
        elif check_mode == "process":
            pattern = metric.params["process_pattern"]
            proc_root = metric.params.get("proc_root", "/proc")
            state = await asyncio.to_thread(_process_check, pattern, proc_root)
            source = f"proc scan pattern={pattern} root={proc_root}"
        else:
            raise ValueError(f"Unknown service check_mode: '{check_mode}'")

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(state),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="service",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=source,
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Blocking helpers
# ---------------------------------------------------------------------------

def _systemd_check(service_name: str) -> int:
    """
    Returns 1 if the service is active, 0 otherwise.
    Uses `systemctl is-active --quiet` which exits 0 for active, non-0 otherwise.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            capture_output=True,
            timeout=5,
        )
        return 1 if result.returncode == 0 else 0
    except FileNotFoundError:
        raise RuntimeError(
            "systemctl not found. Use check_mode: process on non-systemd hosts."
        )
    except subprocess.TimeoutExpired:
        return 0


def _process_check(pattern: str, proc_root: str) -> int:
    """
    Scan {proc_root}/*/cmdline for any process matching the regex pattern.
    Returns 1 if at least one match found, 0 otherwise.
    Only works on Linux (/proc filesystem) or a mounted proc from another host.
    """
    compiled = re.compile(pattern)
    try:
        proc_entries = os.scandir(proc_root)
    except PermissionError as exc:
        raise RuntimeError(f"Cannot scan {proc_root}: {exc}") from exc

    with proc_entries as scanner:
        for entry in scanner:
            if not entry.name.isdigit():
                continue
            cmdline_path = f"{proc_root}/{entry.name}/cmdline"
            try:
                with open(cmdline_path, "rb") as fh:
                    # cmdline args separated by NUL bytes
                    cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
                if compiled.search(cmdline):
                    return 1
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue

    return 0
