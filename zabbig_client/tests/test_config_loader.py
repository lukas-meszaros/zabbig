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


if __name__ == "__main__":
    unittest.main()
