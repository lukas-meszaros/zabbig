"""
test_proc_cache.py — Tests for /proc scan deduplication in the service collector.
"""
import os
import textwrap

import pytest

from zabbig_client.collectors.service import _proc_cmdlines_cache, _process_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_proc(tmp_path, pids_cmdlines: dict[int, str]) -> str:
    """
    Build a fake /proc directory with numbered subdirs, each having a cmdline file.
    Returns the path to the fake proc root.
    """
    proc_root = str(tmp_path / "proc")
    os.makedirs(proc_root)
    # Add a non-numeric entry to test that those are skipped
    non_num = tmp_path / "proc" / "cpuinfo"
    non_num.write_text("notaprocess")
    for pid, cmdline in pids_cmdlines.items():
        pid_dir = tmp_path / "proc" / str(pid)
        pid_dir.mkdir()
        (pid_dir / "cmdline").write_bytes(
            cmdline.replace(" ", "\x00").encode("utf-8") + b"\x00"
        )
    return proc_root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProcessCheck:
    def setup_method(self):
        # Always start with a clean cache for each test
        _proc_cmdlines_cache.clear()

    def teardown_method(self):
        _proc_cmdlines_cache.clear()

    def test_match_found(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {100: "python3 myapp.py", 200: "nginx master"})
        assert _process_check("nginx", proc_root) == 1

    def test_no_match(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {100: "python3 myapp.py"})
        assert _process_check("nginx", proc_root) == 0

    def test_cache_populated_after_first_call(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {100: "python3 myapp.py"})
        assert proc_root not in _proc_cmdlines_cache
        _process_check("python3", proc_root)
        assert proc_root in _proc_cmdlines_cache
        assert len(_proc_cmdlines_cache[proc_root]) == 1

    def test_cache_reused_not_rescanned(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {100: "python3 myapp.py"})
        # First call populates the cache
        _process_check("python3", proc_root)

        # Corrupt the on-disk proc so that a re-scan would return nothing
        import shutil
        shutil.rmtree(proc_root)
        os.makedirs(proc_root)  # empty now

        # Second call should still find the process from the cache
        result = _process_check("python3", proc_root)
        assert result == 1  # cached result

    def test_different_proc_roots_cached_separately(self, tmp_path):
        proc_a = _make_fake_proc(tmp_path / "a", {100: "nginx master"})
        proc_b = _make_fake_proc(tmp_path / "b", {100: "apache2"})
        _process_check("nginx", proc_a)
        _process_check("apache2", proc_b)
        assert proc_a in _proc_cmdlines_cache
        assert proc_b in _proc_cmdlines_cache
        assert _proc_cmdlines_cache[proc_a] != _proc_cmdlines_cache[proc_b]

    def test_multiple_patterns_same_proc_root_one_scan(self, tmp_path):
        """Two calls with different patterns on the same proc_root must only scan once."""
        scan_count = [0]
        original_scandir = os.scandir

        def counting_scandir(path):
            if path == proc_root:
                scan_count[0] += 1
            return original_scandir(path)

        proc_root = _make_fake_proc(tmp_path, {100: "nginx master", 200: "redis-server"})

        import unittest.mock as mock
        with mock.patch("os.scandir", side_effect=counting_scandir):
            _process_check("nginx", proc_root)
            _process_check("redis", proc_root)

        assert scan_count[0] == 1

    def test_permission_error_raises(self, tmp_path):
        proc_root = str(tmp_path / "noperm")
        os.makedirs(proc_root, mode=0o000)
        try:
            with pytest.raises(RuntimeError, match="Cannot scan"):
                _process_check("anything", proc_root)
        finally:
            os.chmod(proc_root, 0o755)
