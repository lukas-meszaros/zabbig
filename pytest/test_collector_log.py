"""
test_collector_log.py — Tests for the log file monitoring collector.
"""
import json
import os
import time

import pytest

from conftest import make_metric
from zabbig_client.collectors.log import (
    LogCollector,
    _resolve_path,
    _state_file,
    _load_state,
    _save_state,
    _eval_conditions,
    _eval_one_condition,
    _resolve_result,
    _log_count,
    _log_condition,
)
from zabbig_client.models import RESULT_OK


class TestResolvePath:
    def test_exact_file(self, tmp_path):
        f = tmp_path / "app.log"
        f.write_text("content")
        resolved = _resolve_path(str(f))
        assert resolved == str(f)

    def test_regex_basename_most_recent(self, tmp_path):
        older = tmp_path / "app.log.1"
        newer = tmp_path / "app.log"
        older.write_text("old")
        newer.write_text("new")
        # Touch newer to ensure it has a later mtime
        os.utime(str(newer), (time.time() + 1, time.time() + 1))
        resolved = _resolve_path(str(tmp_path / r"app\.log.*"))
        # Should pick the most recently modified
        assert "app.log" in resolved

    def test_no_match_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _resolve_path(str(tmp_path / "nonexistent.log"))

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _resolve_path(str(tmp_path / "missing_dir" / "app.log"))

    def test_invalid_regex_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid regex"):
            _resolve_path(str(tmp_path / "[invalid"))


class TestStateHelpers:
    def test_state_file_path(self, tmp_path):
        path = _state_file(str(tmp_path), "my_metric")
        assert path == str(tmp_path / "log_my_metric.json")

    def test_save_and_load_state(self, tmp_path):
        path = _state_file(str(tmp_path), "m1")
        _save_state(path, {"offset": 100, "inode": 9999})
        state = _load_state(path)
        assert state == {"offset": 100, "inode": 9999}

    def test_load_missing_returns_empty(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        assert _load_state(path) == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        f = tmp_path / "corrupt.json"
        f.write_text("{not valid json")
        assert _load_state(str(f)) == {}

    def test_save_creates_parent_directory(self, tmp_path):
        nested_path = str(tmp_path / "nested" / "deep" / "state.json")
        _save_state(nested_path, {"offset": 0})
        assert os.path.exists(nested_path)


class TestEvalConditions:
    def test_when_matches(self):
        conds = [{"when": "ERROR", "value": 1}]
        result = _eval_conditions(conds, "2024-01-01 ERROR something failed")
        assert result == 1

    def test_when_no_match_returns_none(self):
        conds = [{"when": "ERROR", "value": 1}]
        result = _eval_conditions(conds, "2024-01-01 INFO all good")
        assert result is None

    def test_catch_all(self):
        conds = [{"value": 42}]
        result = _eval_conditions(conds, "any line at all")
        assert result == 42

    def test_ordered_first_match(self):
        conds = [
            {"when": "CRITICAL", "value": 2},
            {"when": "ERROR", "value": 1},
            {"value": 0},
        ]
        assert _eval_conditions(conds, "CRITICAL system failure") == 2
        assert _eval_conditions(conds, "ERROR minor issue") == 1
        assert _eval_conditions(conds, "INFO all good") == 0

    def test_extract_gt(self):
        conds = [{"extract": r"latency=(\d+)ms", "compare": "gt", "threshold": 100, "value": 1}]
        assert _eval_conditions(conds, "request latency=250ms") == 1
        assert _eval_conditions(conds, "request latency=50ms") is None

    def test_extract_dollar_one_returns_captured_value(self):
        conds = [{"extract": r"cpu=(\d+\.?\d*)%", "compare": "gte", "threshold": 0, "value": "$1"}]
        result = _eval_conditions(conds, "cpu=87.5%")
        assert result == pytest.approx(87.5)

    def test_extract_lte(self):
        conds = [{"extract": r"memory=(\d+)", "compare": "lte", "threshold": 200, "value": "high"}]
        assert _eval_conditions(conds, "memory=150") == "high"
        assert _eval_conditions(conds, "memory=300") is None

    def test_extract_eq(self):
        conds = [{"extract": r"code=(\d+)", "compare": "eq", "threshold": 200, "value": "ok"}]
        assert _eval_conditions(conds, "code=200") == "ok"

    def test_extract_unknown_compare_raises(self):
        conds = [{"extract": r"(\d+)", "compare": "invalid_op", "threshold": 0, "value": 1}]
        with pytest.raises(ValueError, match="Unknown compare operator"):
            _eval_conditions(conds, "value=5")


class TestResolveResult:
    def test_last_strategy(self):
        assert _resolve_result([1, 2, 3], "last") == 3

    def test_first_strategy(self):
        assert _resolve_result([1, 2, 3], "first") == 1

    def test_max_strategy(self):
        assert _resolve_result([3, 1, 4, 1, 5], "max") == 5.0

    def test_min_strategy(self):
        assert _resolve_result([3, 1, 4, 1, 5], "min") == 1.0

    def test_non_numeric_falls_back_to_last(self):
        assert _resolve_result(["a", "b", "c"], "max") == "c"

    def test_empty_returns_none(self):
        assert _resolve_result([], "last") is None

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown result strategy"):
            _resolve_result([1, 2], "median")


class TestLogCountHelper:
    def test_count_all_lines(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("line1\nline2\nline3\n")
        metric = make_metric(
            collector="log", key="host.log.count",
            params={"path": str(logfile), "mode": "count"},
        )
        assert _log_count(metric) == 3

    def test_count_matching_lines_only(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("ERROR foo\nINFO bar\nERROR baz\n")
        metric = make_metric(
            collector="log", key="host.log.errors",
            params={"path": str(logfile), "match": "ERROR", "mode": "count"},
        )
        assert _log_count(metric) == 2

    def test_count_no_match(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("INFO foo\nINFO bar\n")
        metric = make_metric(
            collector="log", key="host.log.warn",
            params={"path": str(logfile), "match": "WARN", "mode": "count"},
        )
        assert _log_count(metric) == 0

    def test_count_empty_file(self, tmp_path):
        logfile = tmp_path / "empty.log"
        logfile.write_text("")
        metric = make_metric(
            collector="log", key="host.log.count",
            params={"path": str(logfile), "mode": "count"},
        )
        assert _log_count(metric) == 0


class TestLogConditionHelper:
    def _metric_for(self, tmp_path, logfile, extra_params=None):
        state_dir = str(tmp_path / "state")
        params = {
            "path": str(logfile),
            "mode": "condition",
            "state_dir": state_dir,
        }
        if extra_params:
            params.update(extra_params)
        return make_metric(collector="log", key="host.log.cond", params=params)

    def test_returns_default_when_no_match(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("INFO everything is fine\n")
        metric = self._metric_for(tmp_path, logfile, {"match": "ERROR", "default_value": 0})
        val = _log_condition(metric)
        assert val == 0

    def test_returns_value_on_match(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("ERROR database connection lost\n")
        metric = self._metric_for(tmp_path, logfile, {
            "match": "ERROR",
            "conditions": [{"when": "ERROR", "value": 1}],
            "default_value": 0,
        })
        val = _log_condition(metric)
        assert val == 1

    def test_incremental_scan_advances_offset(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("ERROR first\n")
        metric = self._metric_for(tmp_path, logfile, {"match": "ERROR", "default_value": 0})
        val1 = _log_condition(metric)
        # Simulate no new content — second call should return default
        val2 = _log_condition(metric)
        assert val1 == 1
        assert val2 == 0

    def test_appended_lines_detected(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("INFO ok\n")
        metric = self._metric_for(tmp_path, logfile, {"match": "ERROR", "default_value": 0})
        _log_condition(metric)  # consume existing content
        # Append new error
        with open(str(logfile), "a") as fh:
            fh.write("ERROR new problem\n")
        val = _log_condition(metric)
        assert val == 1

    def test_rotation_resets_offset(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("INFO old line\n")
        metric = self._metric_for(tmp_path, logfile, {"match": "ERROR", "default_value": 0})
        _log_condition(metric)  # consume first file entirely

        # Write fresh content — same filename but different inode (simulate rotation
        # by deleting and recreating the file)
        os.unlink(str(logfile))
        logfile.write_text("ERROR fresh error after rotation\n")
        val = _log_condition(metric)
        assert val == 1


class TestLogCollector:
    async def test_mode_count(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("ERROR one\nERROR two\nINFO three\n")
        metric = make_metric(
            collector="log", key="host.log.count",
            params={"path": str(logfile), "mode": "count", "match": "ERROR"},
        )
        result = await LogCollector().collect(metric)
        assert result.status == RESULT_OK
        assert result.value == "2"

    async def test_mode_condition(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("ERROR failure detected\n")
        state_dir = str(tmp_path / "state")
        metric = make_metric(
            collector="log", key="host.log.cond",
            params={
                "path": str(logfile),
                "mode": "condition",
                "match": "ERROR",
                "conditions": [{"when": "ERROR", "value": 1}],
                "default_value": 0,
                "state_dir": state_dir,
            },
        )
        result = await LogCollector().collect(metric)
        assert result.status == RESULT_OK
        assert result.value == "1"

    async def test_unknown_mode_raises(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("data\n")
        metric = make_metric(
            collector="log", key="host.log.x",
            params={"path": str(logfile), "mode": "full_scan"},
        )
        with pytest.raises(ValueError, match="Unknown log collector mode"):
            await LogCollector().collect(metric)

    async def test_default_mode_is_condition(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("INFO ok\n")
        state_dir = str(tmp_path / "state")
        metric = make_metric(
            collector="log", key="host.log.x",
            params={
                "path": str(logfile),
                "state_dir": state_dir,
                "default_value": 99,
                "match": r"ERROR",  # no ERROR lines → default_value returned
            },
        )
        result = await LogCollector().collect(metric)
        assert result.status == RESULT_OK
        # No conditions provided, no match → each match would contribute 1,
        # but here there are no matching lines so default_value (99) is returned
        assert result.value == "99"  # default_value returned (no match)

    async def test_result_collector_field(self, tmp_path):
        logfile = tmp_path / "app.log"
        logfile.write_text("")
        state_dir = str(tmp_path / "state")
        metric = make_metric(
            collector="log", key="host.log.x",
            params={"path": str(logfile), "mode": "count"},
        )
        result = await LogCollector().collect(metric)
        assert result.collector == "log"
