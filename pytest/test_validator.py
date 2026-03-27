"""
test_validator.py — Tests for validate_metrics_file() in config_loader.py.
"""
import textwrap

import pytest

from zabbig_client.config_loader import validate_metrics_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, content: str) -> str:
    p = tmp_path / "metrics.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


VALID_SINGLE = """
    version: 1
    metrics:
      - id: cpu_util
        collector: cpu
        key: host.cpu.util
        value_type: float
        unit: "%"
        params:
          mode: percent
"""

VALID_MULTI = """
    version: 1
    metrics:
      - id: cpu_util
        collector: cpu
        key: host.cpu.util
        params:
          mode: percent
      - id: mem_used
        collector: memory
        key: host.memory.used_percent
        params:
          mode: used_percent
      - id: disk_root
        collector: disk
        key: host.disk.root.used_percent
        params:
          mount: "/"
          mode: used_percent
"""


# ---------------------------------------------------------------------------
# File-level errors
# ---------------------------------------------------------------------------

class TestFileErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            validate_metrics_file(str(tmp_path / "nonexistent.yaml"))

    def test_yaml_syntax_error(self, tmp_path):
        p = tmp_path / "metrics.yaml"
        p.write_text("metrics:\n  - id: [unclosed\n")
        issues, metrics = validate_metrics_file(str(p))
        assert len(issues) >= 1
        assert any("YAML" in i or "syntax" in i.lower() for i in issues)
        assert metrics == []

    def test_empty_file_returns_no_metrics(self, tmp_path):
        p = tmp_path / "metrics.yaml"
        p.write_text("")
        issues, metrics = validate_metrics_file(str(p))
        assert metrics == []


# ---------------------------------------------------------------------------
# Valid files — no issues
# ---------------------------------------------------------------------------

class TestValidFiles:
    def test_single_valid_metric(self, tmp_path):
        path = write_yaml(tmp_path, VALID_SINGLE)
        issues, metrics = validate_metrics_file(path)
        assert issues == []
        assert len(metrics) == 1
        assert metrics[0].id == "cpu_util"

    def test_multiple_valid_metrics(self, tmp_path):
        path = write_yaml(tmp_path, VALID_MULTI)
        issues, metrics = validate_metrics_file(path)
        assert issues == []
        assert len(metrics) == 3
        ids = [m.id for m in metrics]
        assert "cpu_util" in ids
        assert "mem_used" in ids
        assert "disk_root" in ids

    def test_all_schedule_fields_valid(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: cpu_sched
                collector: cpu
                key: host.cpu.sched
                time_window_from: "0800"
                time_window_till: "1800"
                max_executions_per_day: 10
                run_frequency: 2
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert issues == []
        assert len(metrics) == 1
        m = metrics[0]
        assert m.time_window_from == "0800"
        assert m.time_window_till == "1800"
        assert m.max_executions_per_day == 10
        assert m.run_frequency == 2


# ---------------------------------------------------------------------------
# Invalid files — issues collected without stopping
# ---------------------------------------------------------------------------

class TestIssuesCollected:
    def test_invalid_collector_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: bad
                collector: nonexistent
                key: host.bad
                params: {}
        """)
        issues, metrics = validate_metrics_file(path)
        assert len(issues) >= 1
        assert any("nonexistent" in i or "collector" in i.lower() for i in issues)

    def test_invalid_delivery_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu.test
                delivery: realtime
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("delivery" in i.lower() or "realtime" in i for i in issues)

    def test_invalid_schedule_field_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: cpu_sched
                collector: cpu
                key: host.cpu.sched
                time_window_from: "2500"
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert len(issues) >= 1
        assert any("time_window_from" in i or "2500" in i or "hours" in i for i in issues)

    def test_multiple_errors_all_reported(self, tmp_path):
        """All issues across multiple metrics are reported in one pass."""
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu.one
                time_window_from: "2500"
                params:
                  mode: percent
              - id: m2
                collector: cpu
                key: host.cpu.two
                run_frequency: -1
                params:
                  mode: percent
              - id: m3
                collector: cpu
                key: host.cpu.three
                max_executions_per_day: -5
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        # All three problematic fields must each produce an issue entry
        assert len(issues) >= 3

    def test_valid_and_invalid_mixed(self, tmp_path):
        """Valid metrics are still returned when other metrics have issues."""
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: good
                collector: cpu
                key: host.cpu.good
                params:
                  mode: percent
              - id: bad
                collector: cpu
                key: host.cpu.bad
                time_window_from: "9999"
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert len(issues) >= 1
        # The valid metric is still present
        metric_ids = [m.id for m in metrics]
        assert "good" in metric_ids

    def test_duplicate_id_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: dup
                collector: cpu
                key: host.cpu.one
                params:
                  mode: percent
              - id: dup
                collector: cpu
                key: host.cpu.two
                params:
                  mode: load1
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("dup" in i or "Duplicate" in i for i in issues)

    def test_duplicate_key_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu.same
                params:
                  mode: percent
              - id: m2
                collector: cpu
                key: host.cpu.same
                params:
                  mode: load1
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("host.cpu.same" in i or "Duplicate" in i for i in issues)

    def test_missing_required_collector_params(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: disk_no_mount
                collector: disk
                key: host.disk.test
                params:
                  mode: used_percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("mount" in i for i in issues)

    def test_invalid_run_frequency_string_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu.test
                run_frequency: "weekly"
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("run_frequency" in i or "weekly" in i for i in issues)

    def test_negative_max_executions_reported(self, tmp_path):
        path = write_yaml(tmp_path, """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu.test
                max_executions_per_day: -3
                params:
                  mode: percent
        """)
        issues, metrics = validate_metrics_file(path)
        assert any("max_executions_per_day" in i or "-3" in i for i in issues)


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

class TestReturnTypes:
    def test_issues_is_list_of_strings(self, tmp_path):
        path = write_yaml(tmp_path, VALID_SINGLE)
        issues, metrics = validate_metrics_file(path)
        assert isinstance(issues, list)
        for item in issues:
            assert isinstance(item, str)

    def test_metrics_is_list_of_metricdefs(self, tmp_path):
        from zabbig_client.models import MetricDef
        path = write_yaml(tmp_path, VALID_SINGLE)
        issues, metrics = validate_metrics_file(path)
        assert isinstance(metrics, list)
        for m in metrics:
            assert isinstance(m, MetricDef)

    def test_always_returns_two_tuple(self, tmp_path):
        path = write_yaml(tmp_path, VALID_SINGLE)
        result = validate_metrics_file(path)
        assert len(result) == 2
