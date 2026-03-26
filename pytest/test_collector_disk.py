"""
test_collector_disk.py — Tests for the disk collector.
"""
import os
from unittest.mock import patch, MagicMock

import pytest

from conftest import make_metric
from zabbig_client.collectors.disk import DiskCollector, _disk_stat
from zabbig_client.models import RESULT_OK


def mock_statvfs(
    f_blocks=1000000,
    f_bavail=400000,
    f_frsize=4096,
    f_files=200000,
    f_ffree=100000,
):
    sv = MagicMock()
    sv.f_blocks = f_blocks
    sv.f_bavail = f_bavail
    sv.f_frsize = f_frsize
    sv.f_files = f_files
    sv.f_ffree = f_ffree
    return sv


class TestDiskStatHelper:
    def test_used_percent(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            val = _disk_stat("/", "used_percent")
        # total=1M*4096, free=400k*4096, used=600k*4096
        # used_pct = 600/1000 * 100 = 60%
        assert val == pytest.approx(60.0)

    def test_free_bytes(self):
        with patch("os.statvfs", return_value=mock_statvfs(f_bavail=500000, f_frsize=4096)):
            val = _disk_stat("/", "free_bytes")
        assert val == 500000 * 4096

    def test_used_bytes(self):
        sv = mock_statvfs(f_blocks=1000, f_bavail=600, f_frsize=512)
        with patch("os.statvfs", return_value=sv):
            val = _disk_stat("/", "used_bytes")
        assert val == (1000 - 600) * 512

    def test_inodes_total(self):
        with patch("os.statvfs", return_value=mock_statvfs(f_files=200000)):
            val = _disk_stat("/", "inodes_total")
        assert val == 200000

    def test_inodes_free(self):
        with patch("os.statvfs", return_value=mock_statvfs(f_ffree=80000)):
            val = _disk_stat("/", "inodes_free")
        assert val == 80000

    def test_inodes_used(self):
        sv = mock_statvfs(f_files=200000, f_ffree=150000)
        with patch("os.statvfs", return_value=sv):
            val = _disk_stat("/", "inodes_used")
        assert val == 50000

    def test_inodes_used_percent(self):
        sv = mock_statvfs(f_files=100, f_ffree=25)
        with patch("os.statvfs", return_value=sv):
            val = _disk_stat("/data", "inodes_used_percent")
        assert val == pytest.approx(75.0)

    def test_inodes_used_percent_dynamic_inodes(self):
        """Filesystems with dynamic inode allocation (f_files=0) return 0.0."""
        sv = mock_statvfs(f_files=0, f_ffree=0)
        with patch("os.statvfs", return_value=sv):
            val = _disk_stat("/", "inodes_used_percent")
        assert val == 0.0

    def test_unknown_mode_raises(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            with pytest.raises(ValueError, match="Unknown disk collector mode"):
                _disk_stat("/", "unknown_mode")

    def test_used_percent_empty_fs(self):
        sv = mock_statvfs(f_blocks=0, f_bavail=0, f_frsize=4096)
        with patch("os.statvfs", return_value=sv):
            val = _disk_stat("/empty", "used_percent")
        assert val == 0.0


class TestDiskCollector:
    async def test_mode_used_percent(self):
        sv = mock_statvfs()
        with patch("os.statvfs", return_value=sv):
            metric = make_metric(
                collector="disk", key="host.disk.used",
                params={"mount": "/", "mode": "used_percent"},
            )
            result = await DiskCollector().collect(metric)
        assert result.status == RESULT_OK
        assert 0.0 <= float(result.value) <= 100.0

    async def test_mode_free_bytes(self):
        sv = mock_statvfs(f_bavail=300000, f_frsize=4096)
        with patch("os.statvfs", return_value=sv):
            metric = make_metric(
                collector="disk", key="host.disk.free",
                params={"mount": "/data", "mode": "free_bytes"},
            )
            result = await DiskCollector().collect(metric)
        assert result.status == RESULT_OK
        assert int(result.value) == 300000 * 4096

    async def test_mode_used_bytes(self):
        sv = mock_statvfs(f_blocks=1000, f_bavail=400, f_frsize=1024)
        with patch("os.statvfs", return_value=sv):
            metric = make_metric(
                collector="disk", key="host.disk.used.bytes",
                params={"mount": "/", "mode": "used_bytes"},
            )
            result = await DiskCollector().collect(metric)
        assert int(result.value) == 600 * 1024

    @pytest.mark.parametrize("mode", [
        "used_percent", "used_bytes", "free_bytes",
        "inodes_used_percent", "inodes_used", "inodes_free", "inodes_total"
    ])
    async def test_all_modes_return_result(self, mode):
        with patch("os.statvfs", return_value=mock_statvfs()):
            metric = make_metric(
                collector="disk", key="host.disk",
                params={"mount": "/", "mode": mode},
            )
            result = await DiskCollector().collect(metric)
        assert result.status == RESULT_OK

    async def test_default_mode_is_used_percent(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            metric = make_metric(
                collector="disk", key="host.disk",
                params={"mount": "/"},  # no mode
            )
            result = await DiskCollector().collect(metric)
        assert result.status == RESULT_OK

    async def test_source_field_contains_mount(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            metric = make_metric(
                collector="disk", key="host.disk",
                params={"mount": "/mydata", "mode": "used_percent"},
            )
            result = await DiskCollector().collect(metric)
        assert "/mydata" in result.source

    async def test_metric_host_name_on_result(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            metric = make_metric(
                collector="disk", key="host.disk",
                params={"mount": "/", "mode": "used_percent"},
                host_name="disk-override",
            )
            result = await DiskCollector().collect(metric)
        assert result.host_name == "disk-override"

    async def test_no_host_name_override_is_none(self):
        with patch("os.statvfs", return_value=mock_statvfs()):
            metric = make_metric(
                collector="disk", key="host.disk",
                params={"mount": "/", "mode": "used_percent"},
            )
            result = await DiskCollector().collect(metric)
        assert result.host_name is None
