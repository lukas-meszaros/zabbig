"""
network.py — Network interface metrics collector.

Reads from {proc_root}/net/dev and {proc_root}/net/sockstat (Linux only).

params:
  interface   — Network interface name (e.g. "eth0", "ens3").
                Use "total" to sum all non-loopback interfaces.
                Required for all traffic and error modes.
                Not required for socket modes (tcp_inuse, tcp_timewait,
                tcp_orphans, udp_inuse).

  mode        — One of:
                Traffic rates (two /proc/net/dev reads, 1 s apart):
                  rx_bytes_per_sec  — Receive throughput in bytes/second.
                  tx_bytes_per_sec  — Transmit throughput in bytes/second.

                Cumulative counters (single /proc/net/dev read):
                  rx_bytes          — Total bytes received since boot.
                  tx_bytes          — Total bytes transmitted since boot.
                  rx_packets        — Total packets received since boot.
                  tx_packets        — Total packets transmitted since boot.
                  rx_errors         — Total receive errors since boot.
                  tx_errors         — Total transmit errors since boot.
                  rx_dropped        — Total receive drops since boot.
                  tx_dropped        — Total transmit drops since boot.

                Socket counters (from /proc/net/sockstat, no interface needed):
                  tcp_inuse         — Currently open TCP sockets.
                  tcp_timewait      — Sockets in TIME_WAIT state.
                  tcp_orphans       — Orphaned TCP sockets (no fd attached).
                  udp_inuse         — Currently open UDP sockets.

  proc_root   — Optional. Override the proc filesystem root.
                Default: runtime.proc_root (which defaults to "/proc").
"""
from __future__ import annotations

import asyncio
import time

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector

# Modes that require a rate measurement (two reads with a sleep in between)
_RATE_MODES = {"rx_bytes_per_sec", "tx_bytes_per_sec"}

# Modes that read from /proc/net/dev (counters or rates)
_DEV_MODES = {
    "rx_bytes_per_sec", "tx_bytes_per_sec",
    "rx_bytes", "tx_bytes",
    "rx_packets", "tx_packets",
    "rx_errors", "tx_errors",
    "rx_dropped", "tx_dropped",
}

# Modes that read from /proc/net/sockstat
_SOCKSTAT_MODES = {"tcp_inuse", "tcp_timewait", "tcp_orphans", "udp_inuse"}


@register_collector("network")
class NetworkCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> MetricResult:
        mode = metric.params.get("mode")
        interface = metric.params.get("interface", "total")
        proc_root = metric.params.get("proc_root", "/proc")
        t0 = time.monotonic()

        if mode in _RATE_MODES:
            value = await asyncio.to_thread(_net_rate, interface, mode, proc_root)
            source = f"{proc_root}/net/dev iface={interface} mode={mode} (rate)"
        elif mode in _DEV_MODES:
            value = await asyncio.to_thread(_net_counter, interface, mode, proc_root)
            source = f"{proc_root}/net/dev iface={interface} mode={mode}"
        elif mode in _SOCKSTAT_MODES:
            value = await asyncio.to_thread(_sockstat, mode, proc_root)
            source = f"{proc_root}/net/sockstat mode={mode}"
        else:
            raise ValueError(f"Unknown network collector mode: '{mode}'")

        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="network",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit=metric.unit,
            tags=metric.tags,
            source=source,
            duration_ms=(time.monotonic() - t0) * 1000,
        )


# ---------------------------------------------------------------------------
# Blocking helpers (run in thread pool)
# ---------------------------------------------------------------------------

# Column indices inside /proc/net/dev (after stripping "iface:" prefix)
# Format: rx_bytes rx_packets rx_errs rx_drop rx_fifo rx_frame rx_compressed
#         rx_multicast tx_bytes tx_packets tx_errs tx_drop tx_fifo tx_colls
#         tx_carrier tx_compressed
_COL = {
    "rx_bytes":   0,
    "rx_packets": 1,
    "rx_errors":  2,
    "rx_dropped": 3,
    "tx_bytes":   8,
    "tx_packets": 9,
    "tx_errors":  10,
    "tx_dropped": 11,
}


def _parse_net_dev(proc_root: str) -> dict[str, list[int]]:
    """
    Parse {proc_root}/net/dev.
    Returns a dict mapping interface name → list of 16 integer counters.
    """
    path = f"{proc_root}/net/dev"
    result: dict[str, list[int]] = {}
    with open(path, "r") as fh:
        lines = fh.readlines()
    # First two lines are headers
    for line in lines[2:]:
        iface, _, data = line.partition(":")
        iface = iface.strip()
        counters = [int(x) for x in data.split()]
        result[iface] = counters
    return result


def _get_counters(
    iface_data: dict[str, list[int]], interface: str, col: int
) -> int:
    """
    Return the counter value for `col` on `interface`.
    If interface == "total", sum all non-loopback interfaces.
    """
    if interface == "total":
        return sum(
            counters[col]
            for name, counters in iface_data.items()
            if name != "lo"
        )
    if interface not in iface_data:
        raise ValueError(
            f"Network interface '{interface}' not found in /proc/net/dev. "
            f"Available: {sorted(iface_data.keys())}"
        )
    return iface_data[interface][col]


def _net_counter(interface: str, mode: str, proc_root: str) -> int:
    """Return a single cumulative counter from /proc/net/dev."""
    col = _COL[mode]
    iface_data = _parse_net_dev(proc_root)
    return _get_counters(iface_data, interface, col)


def _net_rate(interface: str, mode: str, proc_root: str) -> float:
    """
    Compute bytes/second by reading /proc/net/dev twice with a 1-second gap.
    """
    col = _COL[mode.replace("_per_sec", "")]  # "rx_bytes_per_sec" → "rx_bytes"

    data1 = _parse_net_dev(proc_root)
    time.sleep(1.0)
    data2 = _parse_net_dev(proc_root)

    v1 = _get_counters(data1, interface, col)
    v2 = _get_counters(data2, interface, col)
    return round(max(0, v2 - v1) / 1.0, 2)  # bytes per second over 1s window


def _sockstat(mode: str, proc_root: str) -> int:
    """
    Parse {proc_root}/net/sockstat for socket usage counters.

    Example lines:
        TCP: inuse 12 orphan 0 tw 3 alloc 15 mem 3
        UDP: inuse 4 mem 1
    """
    path = f"{proc_root}/net/sockstat"
    with open(path, "r") as fh:
        content = fh.read()

    mapping = {
        "tcp_inuse":    ("TCP",  "inuse"),
        "tcp_timewait": ("TCP",  "tw"),
        "tcp_orphans":  ("TCP",  "orphan"),
        "udp_inuse":    ("UDP",  "inuse"),
    }
    proto, field = mapping[mode]

    for line in content.splitlines():
        if not line.startswith(f"{proto}:"):
            continue
        parts = line.split()
        # parts[0] = "TCP:" or "UDP:", then key value pairs follow
        for i in range(1, len(parts) - 1, 2):
            if parts[i] == field:
                return int(parts[i + 1])

    raise RuntimeError(
        f"Field '{field}' for proto '{proto}' not found in {path}"
    )
