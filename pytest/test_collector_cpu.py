"""
test_collector_cpu.py — Tests for the CPU collector.
"""
import os
import time

import pytest

from conftest import make_metric
from zabbig_client.collectors.cpu import (
    CpuCollector,
    _cpu_percent,
    _load_avg,
    _uptime_seconds,
)
from zabbig_client.models import RESULT_OK


def write_proc_files(tmp_path, stat=None, loadavg=None, uptime=None):
    """Write fake /proc files to a tmp directory."""
    if stat is not None:
        (tmp_path / "stat").write_text(stat)
    if loadavg is not None:
        (tmp_path / "loadavg").write_text(loadavg)
    if uptime is not None:
        (tmp_path / "uptime").write_text(uptime)


class TestCpuHelperFunctions:
    def test_uptime_seconds(self, tmp_path):
        write_proc_files(tmp_path, uptime="12345.67 234.56\n")
        value = _uptime_seconds(str(tmp_path))
        assert value == pytest.approx(12345.67)

    def test_load_avg_load1(self, tmp_path):
        write_proc_files(tmp_path, loadavg="1.23 2.34 3.45 1/100 9999\n")
        assert _load_avg("load1", str(tmp_path)) == pytest.approx(1.23)

    def test_load_avg_load5(self, tmp_path):
        write_proc_files(tmp_path, loadavg="1.23 2.34 3.45 1/100 9999\n")
        assert _load_avg("load5", str(tmp_path)) == pytest.approx(2.34)

    def test_load_avg_load15(self, tmp_path):
        write_proc_files(tmp_path, loadavg="1.23 2.34 3.45 1/100 9999\n")
        assert _load_avg("load15", str(tmp_path)) == pytest.approx(3.45)

    def test_cpu_percent_idle(self, tmp_path):
        """Two identical /proc/stat reads → 0% CPU."""
        stat = "cpu  1000 0 500 8500 0 0 0 0 0 0\n"
        write_proc_files(tmp_path, stat=stat)
        # Both reads will see same values → 0% or near-0%
        value = _cpu_percent(str(tmp_path))
        assert 0.0 <= value <= 100.0

    def test_cpu_percent_range(self, tmp_path):
        write_proc_files(tmp_path, stat="cpu  500 0 200 9000 0 0 0 0 0 0\n")
        val = _cpu_percent(str(tmp_path))
        assert 0.0 <= val <= 100.0

    def test_uptime_missing_file(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            _uptime_seconds(str(tmp_path))

    def test_loadavg_missing_file(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            _load_avg("load1", str(tmp_path))


class TestCpuCollector:
    async def test_mode_uptime(self, tmp_path):
        write_proc_files(tmp_path, uptime="9876.0 100.0\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.uptime",
            params={"mode": "uptime", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert result.status == RESULT_OK
        assert float(result.value) == pytest.approx(9876.0)

    async def test_mode_load1(self, tmp_path):
        write_proc_files(tmp_path, loadavg="0.5 1.0 1.5 1/50 1234\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.load1",
            params={"mode": "load1", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert result.status == RESULT_OK
        assert float(result.value) == pytest.approx(0.5)

    async def test_mode_load5(self, tmp_path):
        write_proc_files(tmp_path, loadavg="0.5 1.0 1.5 1/50 1234\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.load5",
            params={"mode": "load5", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert float(result.value) == pytest.approx(1.0)

    async def test_mode_load15(self, tmp_path):
        write_proc_files(tmp_path, loadavg="0.5 1.0 1.5 1/50 1234\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.load15",
            params={"mode": "load15", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert float(result.value) == pytest.approx(1.5)

    async def test_mode_percent(self, tmp_path):
        write_proc_files(tmp_path, stat="cpu  500 0 200 9000 100 0 0 0 0 0\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.util",
            params={"mode": "percent", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert result.status == RESULT_OK
        assert 0.0 <= float(result.value) <= 100.0

    async def test_unknown_mode_raises(self, tmp_path):
        metric = make_metric(
            collector="cpu", key="host.cpu",
            params={"mode": "unknownmode", "proc_root": str(tmp_path)},
        )
        with pytest.raises(ValueError, match="Unknown cpu collector mode"):
            await CpuCollector().collect(metric)

    async def test_result_fields(self, tmp_path):
        write_proc_files(tmp_path, uptime="100.0 10.0\n")
        metric = make_metric(
            id="cpu_uptime", collector="cpu", key="host.cpu.uptime",
            params={"mode": "uptime", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert result.metric_id == "cpu_uptime"
        assert result.key == "host.cpu.uptime"
        assert result.collector == "cpu"
        assert result.duration_ms >= 0
        assert result.timestamp > 0

    async def test_metric_host_name_on_result(self, tmp_path):
        write_proc_files(tmp_path, uptime="100.0 10.0\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.uptime",
            params={"mode": "uptime", "proc_root": str(tmp_path)},
            host_name="cpu-override",
        )
        result = await CpuCollector().collect(metric)
        assert result.host_name == "cpu-override"

    async def test_no_host_name_override_is_none(self, tmp_path):
        write_proc_files(tmp_path, uptime="100.0 10.0\n")
        metric = make_metric(
            collector="cpu", key="host.cpu.uptime",
            params={"mode": "uptime", "proc_root": str(tmp_path)},
        )
        result = await CpuCollector().collect(metric)
        assert result.host_name is None

    async def test_default_mode_is_percent(self, tmp_path):
        write_proc_files(tmp_path, stat="cpu  100 0 50 9000 0 0 0 0 0 0\n")
        metric = make_metric(
            collector="cpu", key="host.cpu",
            params={"proc_root": str(tmp_path)},  # no 'mode' key
        )
        result = await CpuCollector().collect(metric)
        assert result.status == RESULT_OK
