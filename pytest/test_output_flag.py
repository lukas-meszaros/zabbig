"""
test_output_flag.py — Tests for the --output / _write_output functionality in main.py.
"""
import csv
import json
import os
import textwrap

import pytest

from zabbig_client.main import _write_output
from zabbig_client.models import MetricResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(key="host.test", value="42", status="ok", collector="cpu"):
    return MetricResult(
        metric_id=key.replace(".", "_"),
        key=key,
        value=value,
        value_type="float",
        timestamp=1000000,
        collector=collector,
        delivery="batch",
        status=status,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWriteOutputJson:
    def test_creates_json_file(self, tmp_path):
        out = str(tmp_path / "out.json")
        results = [_make_result("host.cpu.util", "75.3")]
        _write_output(results, out, "json")
        assert os.path.isfile(out)
        data = json.loads(open(out).read())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["key"] == "host.cpu.util"
        assert data[0]["value"] == "75.3"

    def test_only_sendable_results_included(self, tmp_path):
        out = str(tmp_path / "out.json")
        results = [
            _make_result("host.ok", "1", status="ok"),
            _make_result("host.failed", None, status="failed"),
            _make_result("host.timeout", None, status="timeout"),
            _make_result("host.fallback", "0", status="fallback"),
        ]
        _write_output(results, out, "json")
        data = json.loads(open(out).read())
        keys = {r["key"] for r in data}
        # ok and fallback are sendable; failed and timeout are not
        assert "host.ok" in keys
        assert "host.fallback" in keys
        assert "host.failed" not in keys
        assert "host.timeout" not in keys

    def test_empty_results_writes_empty_array(self, tmp_path):
        out = str(tmp_path / "out.json")
        _write_output([], out, "json")
        data = json.loads(open(out).read())
        assert data == []


class TestWriteOutputCsv:
    def test_creates_csv_file(self, tmp_path):
        out = str(tmp_path / "out.csv")
        results = [
            _make_result("host.cpu.util", "75"),
            _make_result("host.mem.used", "60"),
        ]
        _write_output(results, out, "csv")
        assert os.path.isfile(out)
        with open(out, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 2
        keys = {r["key"] for r in rows}
        assert "host.cpu.util" in keys
        assert "host.mem.used" in keys

    def test_empty_results_writes_empty_file(self, tmp_path):
        out = str(tmp_path / "out.csv")
        _write_output([], out, "csv")
        assert os.path.isfile(out)
        assert open(out).read() == ""


class TestWriteOutputTable:
    def test_creates_table_file(self, tmp_path):
        out = str(tmp_path / "out.txt")
        results = [_make_result("host.cpu.util", "75.3")]
        _write_output(results, out, "table")
        assert os.path.isfile(out)
        content = open(out).read()
        assert "host.cpu.util" in content
        assert "75.3" in content

    def test_empty_results_writes_no_results(self, tmp_path):
        out = str(tmp_path / "out.txt")
        _write_output([], out, "table")
        assert "no results" in open(out).read()

    def test_table_has_header_and_separator(self, tmp_path):
        out = str(tmp_path / "out.txt")
        results = [_make_result()]
        _write_output(results, out, "table")
        lines = open(out).readlines()
        assert len(lines) >= 3  # header, separator, at least one data row
        assert "key" in lines[0]
        assert "---" in lines[1]


class TestWriteOutputIOError:
    def test_bad_path_logs_error_not_raised(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            _write_output([_make_result()], "/nonexistent/dir/out.json", "json")
        assert any("Could not write output" in r.message for r in caplog.records)
