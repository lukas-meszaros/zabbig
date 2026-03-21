"""
test_collector_memory.py — Tests for the memory collector.
"""
import pytest

from conftest import make_metric
from zabbig_client.collectors.memory import (
    MemoryCollector,
    _mem_used_percent,
    _read_meminfo,
    _swap_used_percent,
)
from zabbig_client.models import RESULT_OK

MEMINFO_SAMPLE = """\
MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:    4096000 kB
Buffers:          512000 kB
Cached:          2048000 kB
SwapTotal:       8192000 kB
SwapFree:        4096000 kB
"""


def write_meminfo(tmp_path, content=MEMINFO_SAMPLE):
    (tmp_path / "meminfo").write_text(content)


class TestMemoryHelpers:
    def test_read_meminfo_total(self, tmp_path):
        write_meminfo(tmp_path)
        info = _read_meminfo(str(tmp_path))
        assert info["MemTotal"] == 16384000

    def test_read_meminfo_available(self, tmp_path):
        write_meminfo(tmp_path)
        info = _read_meminfo(str(tmp_path))
        assert info["MemAvailable"] == 4096000

    def test_read_meminfo_swap(self, tmp_path):
        write_meminfo(tmp_path)
        info = _read_meminfo(str(tmp_path))
        assert info["SwapTotal"] == 8192000
        assert info["SwapFree"] == 4096000

    def test_mem_used_percent(self):
        info = {"MemTotal": 16000, "MemAvailable": 4000}
        pct = _mem_used_percent(info)
        assert pct == pytest.approx(75.0)

    def test_mem_used_percent_zero_total(self):
        info = {"MemTotal": 0, "MemAvailable": 0}
        assert _mem_used_percent(info) == 0.0

    def test_swap_used_percent(self):
        info = {"SwapTotal": 8000, "SwapFree": 2000}
        pct = _swap_used_percent(info)
        assert pct == pytest.approx(75.0)

    def test_swap_used_percent_no_swap(self):
        info = {"SwapTotal": 0, "SwapFree": 0}
        assert _swap_used_percent(info) == 0.0

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            _read_meminfo(str(tmp_path))


class TestMemoryCollector:
    async def test_mode_used_percent(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            collector="memory", key="host.mem.used",
            params={"mode": "used_percent", "proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert result.status == RESULT_OK
        assert 0.0 <= float(result.value) <= 100.0

    async def test_mode_available_bytes(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            collector="memory", key="host.mem.avail",
            params={"mode": "available_bytes", "proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert result.status == RESULT_OK
        # MemAvailable=4096000 kB → 4096000 * 1024 bytes
        assert float(result.value) == pytest.approx(4096000 * 1024)

    async def test_mode_swap_used_percent(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            collector="memory", key="host.mem.swap",
            params={"mode": "swap_used_percent", "proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert result.status == RESULT_OK
        assert float(result.value) == pytest.approx(50.0)

    async def test_unknown_mode_raises(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            collector="memory", key="host.mem",
            params={"mode": "bogus", "proc_root": str(tmp_path)},
        )
        with pytest.raises(ValueError, match="Unknown memory collector mode"):
            await MemoryCollector().collect(metric)

    async def test_default_mode_used_percent(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            collector="memory", key="host.mem",
            params={"proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert result.status == RESULT_OK

    async def test_result_collector_field(self, tmp_path):
        write_meminfo(tmp_path)
        metric = make_metric(
            id="mem1",
            collector="memory", key="host.mem",
            params={"mode": "used_percent", "proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert result.collector == "memory"
        assert result.metric_id == "mem1"

    async def test_no_swap_returns_zero(self, tmp_path):
        no_swap = "MemTotal: 8000 kB\nMemAvailable: 2000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
        write_meminfo(tmp_path, content=no_swap)
        metric = make_metric(
            collector="memory", key="host.swap",
            params={"mode": "swap_used_percent", "proc_root": str(tmp_path)},
        )
        result = await MemoryCollector().collect(metric)
        assert float(result.value) == 0.0
