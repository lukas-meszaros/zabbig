"""
test_config_loader.py — Unit tests for config loading and validation.

No external dependencies. Uses unittest and temporary YAML files.
"""
import os
import sys
import tempfile
import unittest

# Ensure src/ is on path
_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from zabbig_client.config_loader import ConfigError, load_client_config, load_metrics_config


def _write_yaml(content: str) -> str:
    """Write a YAML string to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    return path


class TestLoadClientConfig(unittest.TestCase):

    def test_defaults_when_empty(self):
        path = _write_yaml("{}")
        try:
            cfg = load_client_config(path)
            self.assertEqual(cfg.zabbix.server_port, 10051)
            self.assertEqual(cfg.runtime.max_concurrency, 8)
            self.assertFalse(cfg.runtime.dry_run)
        finally:
            os.unlink(path)

    def test_overrides_applied(self):
        yaml_content = """
zabbix:
  server_host: "10.0.0.1"
  server_port: 10052
  host_name: "my-host"
runtime:
  dry_run: true
  max_concurrency: 4
"""
        path = _write_yaml(yaml_content)
        try:
            cfg = load_client_config(path)
            self.assertEqual(cfg.zabbix.server_host, "10.0.0.1")
            self.assertEqual(cfg.zabbix.server_port, 10052)
            self.assertEqual(cfg.zabbix.host_name, "my-host")
            self.assertTrue(cfg.runtime.dry_run)
            self.assertEqual(cfg.runtime.max_concurrency, 4)
        finally:
            os.unlink(path)

    def test_invalid_port_raises(self):
        path = _write_yaml("zabbix:\n  server_port: 99999\n  host_name: test\n")
        try:
            with self.assertRaises(ConfigError):
                load_client_config(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_client_config("/nonexistent/path/client.yaml")

    def test_invalid_log_level_raises(self):
        path = _write_yaml("zabbix:\n  host_name: test\nlogging:\n  level: SUPERVERBOSE\n")
        try:
            with self.assertRaises(ConfigError):
                load_client_config(path)
        finally:
            os.unlink(path)


class TestLoadMetricsConfig(unittest.TestCase):

    VALID_METRICS = """
version: 1
defaults:
  enabled: true
  delivery: batch
  timeout_seconds: 10
  error_policy: skip
metrics:
  - id: cpu_test
    name: CPU test
    enabled: true
    collector: cpu
    key: host.cpu.util
    value_type: float
    params:
      mode: percent
"""

    def test_valid_metrics_parsed(self):
        path = _write_yaml(self.VALID_METRICS)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(len(cfg.metrics), 1)
            m = cfg.metrics[0]
            self.assertEqual(m.id, "cpu_test")
            self.assertEqual(m.collector, "cpu")
            self.assertEqual(m.key, "host.cpu.util")
            self.assertTrue(m.enabled)
        finally:
            os.unlink(path)

    def test_duplicate_id_raises(self):
        yaml_content = self.VALID_METRICS + """
  - id: cpu_test
    name: Duplicate
    enabled: true
    collector: cpu
    key: host.cpu.util2
    params:
      mode: load1
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_duplicate_key_raises(self):
        yaml_content = self.VALID_METRICS + """
  - id: cpu_test2
    name: Unique ID duplicate key
    enabled: true
    collector: cpu
    key: host.cpu.util
    params:
      mode: load1
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_invalid_collector_raises(self):
        yaml_content = """
version: 1
defaults:
  enabled: true
  delivery: batch
  timeout_seconds: 10
  error_policy: skip
metrics:
  - id: bad
    name: Bad collector
    enabled: true
    collector: nonexistent
    key: host.bad
    params: {}
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_invalid_delivery_raises(self):
        yaml_content = """
version: 1
defaults: {}
metrics:
  - id: bad_delivery
    name: Bad delivery
    enabled: true
    collector: cpu
    key: host.test
    delivery: realtime
    params:
      mode: percent
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_service_missing_service_name_raises(self):
        yaml_content = """
version: 1
defaults: {}
metrics:
  - id: bad_service
    name: Bad service
    enabled: true
    collector: service
    key: host.svc.test
    params:
      check_mode: systemd
      # service_name missing on purpose
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_disk_missing_mount_raises(self):
        yaml_content = """
version: 1
defaults: {}
metrics:
  - id: bad_disk
    name: Bad disk
    enabled: true
    collector: disk
    key: host.disk.test
    params:
      mode: used_percent
      # mount missing on purpose
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_enabled_must_be_bool_strict(self):
        yaml_content = """
version: 1
defaults: {}
metrics:
  - id: maybe
    name: Maybe
    enabled: "yes"
    collector: cpu
    key: host.maybe
    params:
      mode: percent
"""
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(ConfigError):
                load_metrics_config(path, strict=True)
        finally:
            os.unlink(path)

    def test_disabled_metric_included_in_list(self):
        """Disabled metrics are parsed and included; filtering happens in main.py."""
        yaml_content = """
version: 1
defaults:
  enabled: true
  delivery: batch
  timeout_seconds: 10
  error_policy: skip
metrics:
  - id: disabled_metric
    name: Disabled
    enabled: false
    collector: cpu
    key: host.disabled
    params:
      mode: percent
"""
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(len(cfg.metrics), 1)
            self.assertFalse(cfg.metrics[0].enabled)
        finally:
            os.unlink(path)

    def test_collector_defaults_override_global(self):
        yaml_content = """
version: 1
defaults:
  timeout_seconds: 30
  delivery: batch
  error_policy: skip
collector_defaults:
  service:
    timeout_seconds: 5
    delivery: immediate
metrics:
  - id: svc_test
    name: Service test
    enabled: true
    collector: service
    key: host.svc.test
    params:
      check_mode: systemd
      service_name: sshd
"""
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            m = cfg.metrics[0]
            self.assertEqual(m.timeout_seconds, 5.0)
            self.assertEqual(m.delivery, "immediate")
        finally:
            os.unlink(path)


class TestScheduleFieldValidation(unittest.TestCase):
    """Tests for config_loader validation of the four scheduling fields."""

    BASE = """
version: 1
defaults:
  enabled: true
  delivery: batch
  timeout_seconds: 10
  error_policy: skip
metrics:
  - id: cpu_sched
    name: CPU sched test
    enabled: true
    collector: cpu
    key: host.cpu.sched
    params:
      mode: percent
"""

    def _yaml_with(self, extra_fields: str) -> str:
        """Insert extra top-level fields into the metric entry."""
        return self.BASE.replace(
            "      mode: percent",
            f"      mode: percent\n{extra_fields}",
        )

    # --- time_window_from ---

    def test_time_window_from_valid_string(self):
        yaml_content = self._yaml_with('    time_window_from: "0800"')
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].time_window_from, "0800")
        finally:
            os.unlink(path)

    def test_time_window_from_valid_int(self):
        # YAML without quotes: 800 → int 800 → normalised to "0800"
        yaml_content = self._yaml_with("    time_window_from: 800")
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].time_window_from, "0800")
        finally:
            os.unlink(path)

    def test_time_window_from_invalid_hours_raises(self):
        yaml_content = self._yaml_with('    time_window_from: "2500"')
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_time_window_from_invalid_minutes_raises(self):
        yaml_content = self._yaml_with('    time_window_from: "0860"')
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_time_window_from_absent_is_none(self):
        path = _write_yaml(self.BASE)
        try:
            cfg = load_metrics_config(path)
            self.assertIsNone(cfg.metrics[0].time_window_from)
        finally:
            os.unlink(path)

    # --- time_window_till ---

    def test_time_window_till_valid(self):
        yaml_content = self._yaml_with('    time_window_till: "1800"')
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].time_window_till, "1800")
        finally:
            os.unlink(path)

    def test_time_window_till_invalid_raises(self):
        yaml_content = self._yaml_with('    time_window_till: "2500"')
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    # --- max_executions_per_day ---

    def test_max_executions_valid(self):
        yaml_content = self._yaml_with("    max_executions_per_day: 5")
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].max_executions_per_day, 5)
        finally:
            os.unlink(path)

    def test_max_executions_zero_allowed(self):
        yaml_content = self._yaml_with("    max_executions_per_day: 0")
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].max_executions_per_day, 0)
        finally:
            os.unlink(path)

    def test_max_executions_negative_raises(self):
        yaml_content = self._yaml_with("    max_executions_per_day: -1")
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_max_executions_absent_is_none(self):
        path = _write_yaml(self.BASE)
        try:
            cfg = load_metrics_config(path)
            self.assertIsNone(cfg.metrics[0].max_executions_per_day)
        finally:
            os.unlink(path)

    # --- run_frequency ---

    def test_run_frequency_integer(self):
        yaml_content = self._yaml_with("    run_frequency: 5")
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].run_frequency, 5)
        finally:
            os.unlink(path)

    def test_run_frequency_zero_allowed(self):
        yaml_content = self._yaml_with("    run_frequency: 0")
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].run_frequency, 0)
        finally:
            os.unlink(path)

    def test_run_frequency_even(self):
        yaml_content = self._yaml_with('    run_frequency: "even"')
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].run_frequency, "even")
        finally:
            os.unlink(path)

    def test_run_frequency_odd(self):
        yaml_content = self._yaml_with('    run_frequency: "odd"')
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            self.assertEqual(cfg.metrics[0].run_frequency, "odd")
        finally:
            os.unlink(path)

    def test_run_frequency_invalid_string_raises(self):
        yaml_content = self._yaml_with('    run_frequency: "weekly"')
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_run_frequency_negative_raises(self):
        yaml_content = self._yaml_with("    run_frequency: -3")
        path = _write_yaml(yaml_content)
        try:
            with self.assertRaises(Exception):
                load_metrics_config(path)
        finally:
            os.unlink(path)

    def test_run_frequency_absent_is_none(self):
        path = _write_yaml(self.BASE)
        try:
            cfg = load_metrics_config(path)
            self.assertIsNone(cfg.metrics[0].run_frequency)
        finally:
            os.unlink(path)

    def test_all_schedule_fields_together(self):
        yaml_content = self._yaml_with(
            '    time_window_from: "0800"\n'
            '    time_window_till: "2000"\n'
            "    max_executions_per_day: 10\n"
            "    run_frequency: 2\n"
        )
        path = _write_yaml(yaml_content)
        try:
            cfg = load_metrics_config(path)
            m = cfg.metrics[0]
            self.assertEqual(m.time_window_from, "0800")
            self.assertEqual(m.time_window_till, "2000")
            self.assertEqual(m.max_executions_per_day, 10)
            self.assertEqual(m.run_frequency, 2)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
