"""
test_collectors.py — Unit tests for individual collector helpers.

Tests the pure blocking functions (_cpu_percent, _read_meminfo, etc.) directly
rather than the async wrappers, to stay dependency-free and fast.

CPU and memory tests require Linux (/proc). They are skipped automatically
on non-Linux platforms.
"""
import os
import platform
import sys
import time
import unittest

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

IS_LINUX = platform.system() == "Linux"


@unittest.skipUnless(IS_LINUX, "CPU collector requires /proc/stat (Linux only)")
class TestCpuHelpers(unittest.TestCase):

    def test_cpu_percent_in_range(self):
        from zabbig_client.collectors.cpu import _cpu_percent
        value = _cpu_percent()
        self.assertIsInstance(value, float)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 100.0)

    def test_load_avg_values(self):
        from zabbig_client.collectors.cpu import _load_avg
        for mode in ("load1", "load5", "load15"):
            v = _load_avg(mode)
            self.assertIsInstance(v, float)
            self.assertGreaterEqual(v, 0.0)

    def test_uptime_seconds_positive(self):
        from zabbig_client.collectors.cpu import _uptime_seconds
        v = _uptime_seconds()
        self.assertIsInstance(v, float)
        self.assertGreater(v, 0.0)


@unittest.skipUnless(IS_LINUX, "Memory collector requires /proc/meminfo (Linux only)")
class TestMemoryHelpers(unittest.TestCase):

    def test_meminfo_has_expected_keys(self):
        from zabbig_client.collectors.memory import _read_meminfo
        info = _read_meminfo()
        self.assertIn("MemTotal", info)
        self.assertIn("MemFree", info)
        self.assertGreater(info["MemTotal"], 0)

    def test_used_percent_in_range(self):
        from zabbig_client.collectors.memory import _read_meminfo, _mem_used_percent
        info = _read_meminfo()
        pct = _mem_used_percent(info)
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 100.0)

    def test_swap_percent_non_negative(self):
        from zabbig_client.collectors.memory import _read_meminfo, _swap_used_percent
        info = _read_meminfo()
        pct = _swap_used_percent(info)
        self.assertGreaterEqual(pct, 0.0)


class TestDiskHelpers(unittest.TestCase):
    """os.statvfs disk metrics."""

    def test_root_used_percent(self):
        from zabbig_client.collectors.disk import _disk_stat
        pct = _disk_stat("/", "used_percent")
        self.assertIsInstance(pct, float)
        self.assertGreater(pct, 0.0)
        self.assertLess(pct, 100.0)

    def test_root_free_bytes(self):
        from zabbig_client.collectors.disk import _disk_stat
        free = _disk_stat("/", "free_bytes")
        self.assertIsInstance(free, int)
        self.assertGreater(free, 0)

    def test_invalid_mode_raises(self):
        from zabbig_client.collectors.disk import _disk_stat
        with self.assertRaises(ValueError):
            _disk_stat("/", "invalid_mode")

    def test_nonexistent_mount_raises(self):
        from zabbig_client.collectors.disk import _disk_stat
        with self.assertRaises(FileNotFoundError):
            _disk_stat("/this/does/not/exist", "used_percent")


@unittest.skipUnless(IS_LINUX, "Process check requires /proc (Linux only)")
class TestServiceHelpers(unittest.TestCase):

    def test_process_check_finds_itself(self):
        """The current Python process should always be found."""
        from zabbig_client.collectors.service import _process_check
        result = _process_check(r"python")
        self.assertEqual(result, 1)

    def test_process_check_no_match(self):
        from zabbig_client.collectors.service import _process_check
        result = _process_check(r"__zabbig_nonexistent_process_12345__")
        self.assertEqual(result, 0)

    def test_process_check_returns_int(self):
        from zabbig_client.collectors.service import _process_check
        result = _process_check(r"init|systemd")
        self.assertIn(result, (0, 1))


class TestCollectorRegistryImports(unittest.TestCase):
    """Verify all collectors register themselves at import time."""

    def test_all_collectors_registered(self):
        from zabbig_client.collector_registry import registered_names
        names = registered_names()
        for expected in ("cpu", "memory", "disk", "service"):
            self.assertIn(expected, names, f"Collector '{expected}' not registered")

    def test_get_nonexistent_raises(self):
        from zabbig_client.collector_registry import get_collector
        with self.assertRaises(KeyError):
            get_collector("nonexistent_collector")


if __name__ == "__main__":
    unittest.main()
