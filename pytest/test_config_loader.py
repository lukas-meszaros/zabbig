"""
test_config_loader.py — Tests for config_loader.py (client.yaml + metrics.yaml loading).
"""
import os
import textwrap

import pytest

from zabbig_client.config_loader import ConfigError, load_client_config, load_metrics_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content))
    return str(p)


# ---------------------------------------------------------------------------
# load_client_config
# ---------------------------------------------------------------------------

class TestLoadClientConfig:
    def test_minimal_valid(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              server_host: ["127.0.0.1"]
              host_name: "testhost"
        """)
        cfg = load_client_config(path)
        assert cfg.zabbix.server_hosts == ["127.0.0.1"]
        assert cfg.zabbix.host_name == "testhost"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_client_config("/nonexistent/path/client.yaml")

    def test_defaults_applied(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "myhost"
        """)
        cfg = load_client_config(path)
        assert cfg.zabbix.server_port == 10051
        assert cfg.runtime.max_concurrency == 8
        assert cfg.batching.batch_send_max_size == 250
        assert cfg.logging.level == "INFO"
        assert cfg.state.enabled is False
        assert cfg.features.self_monitoring_metrics is True

    def test_all_sections(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              server_host: ["10.0.0.1"]
              server_port: 10052
              host_name: "srv01"
              host_group: "My Group"
              connect_timeout_seconds: 5
              send_timeout_seconds: 15

            runtime:
              overall_timeout_seconds: 120
              max_concurrency: 4
              lock_file: /tmp/test.lock
              dry_run: true
              fail_fast: true
              proc_root: /host/proc

            batching:
              batch_collection_window_seconds: 30
              batch_send_max_size: 100
              flush_immediate_separately: false
              immediate_micro_batch_window_ms: 100

            logging:
              level: DEBUG
              format: json
              console: false

            state:
              enabled: true
              directory: /tmp/state

            features:
              self_monitoring_metrics: false
              strict_config_validation: false
              skip_disabled_metrics: false
        """)
        cfg = load_client_config(path)
        assert cfg.zabbix.server_hosts == ["10.0.0.1"]
        assert cfg.zabbix.server_port == 10052
        assert cfg.zabbix.host_name == "srv01"
        assert cfg.zabbix.host_group == "My Group"
        assert cfg.runtime.overall_timeout_seconds == 120.0
        assert cfg.runtime.max_concurrency == 4
        assert cfg.runtime.dry_run is True
        assert cfg.runtime.fail_fast is True
        assert cfg.runtime.proc_root == "/host/proc"
        assert cfg.batching.batch_collection_window_seconds == 30.0
        assert cfg.batching.flush_immediate_separately is False
        assert cfg.logging.level == "DEBUG"
        assert cfg.logging.format == "json"
        assert cfg.logging.console is False
        assert cfg.state.enabled is True
        assert cfg.features.self_monitoring_metrics is False
        assert cfg.features.strict_config_validation is False

    def test_invalid_port_too_low(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
              server_port: 0
        """)
        with pytest.raises(ConfigError, match="server_port"):
            load_client_config(path)

    def test_invalid_port_too_high(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
              server_port: 70000
        """)
        with pytest.raises(ConfigError, match="server_port"):
            load_client_config(path)

    def test_invalid_log_level(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            logging:
              level: VERBOSE
        """)
        with pytest.raises(ConfigError, match="logging.level"):
            load_client_config(path)

    def test_overall_timeout_zero(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            runtime:
              overall_timeout_seconds: 0
        """)
        with pytest.raises(ConfigError, match="overall_timeout_seconds"):
            load_client_config(path)

    def test_level_uppercased(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            logging:
              level: debug
        """)
        cfg = load_client_config(path)
        assert cfg.logging.level == "DEBUG"

    def test_empty_yaml_uses_defaults(self, tmp_path):
        path = tmp_path / "client.yaml"
        path.write_text("")
        # Empty YAML won't have host_name so load_client_config will populate from socket
        import socket
        cfg = load_client_config(str(path))
        assert cfg.zabbix.server_hosts == ["127.0.0.1"]
        assert cfg.zabbix.host_name == socket.gethostname()

    def test_server_host_bare_string_raises(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              server_host: "10.0.0.1"
              host_name: "h"
        """)
        with pytest.raises(ConfigError, match="must be a list"):
            load_client_config(path)

    def test_server_host_multiple_entries(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              server_host: ["proxy-a", "proxy-b", "proxy-c"]
              host_name: "h"
        """)
        cfg = load_client_config(path)
        assert cfg.zabbix.server_hosts == ["proxy-a", "proxy-b", "proxy-c"]

    def test_logging_file_plain_string(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", f"""
            zabbix:
              host_name: "h"
            logging:
              file: "/var/log/zabbig/client.log"
        """)
        cfg = load_client_config(path)
        assert cfg.logging.file is not None
        assert cfg.logging.file.path == "/var/log/zabbig/client.log"
        assert cfg.logging.file.max_size_mb == 10
        assert cfg.logging.file.max_backups == 5
        assert cfg.logging.file.compress is True

    def test_logging_file_mapping_full(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            logging:
              file:
                path: "/var/log/zabbig/client.log"
                max_size_mb: 25
                max_backups: 3
                compress: false
        """)
        cfg = load_client_config(path)
        fc = cfg.logging.file
        assert fc.path == "/var/log/zabbig/client.log"
        assert fc.max_size_mb == 25
        assert fc.max_backups == 3
        assert fc.compress is False

    def test_logging_file_mapping_defaults(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            logging:
              file:
                path: "/var/log/zabbig/client.log"
        """)
        cfg = load_client_config(path)
        fc = cfg.logging.file
        assert fc.max_size_mb == 10
        assert fc.max_backups == 5
        assert fc.compress is True

    def test_logging_file_mapping_missing_path_raises(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
            logging:
              file:
                max_size_mb: 10
        """)
        with pytest.raises(ConfigError, match="logging.file.path"):
            load_client_config(path)

    def test_logging_file_none_when_absent(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "h"
        """)
        cfg = load_client_config(path)
        assert cfg.logging.file is None


# ---------------------------------------------------------------------------
# load_metrics_config
# ---------------------------------------------------------------------------

class TestLoadMetricsConfig:
    def test_minimal_cpu_metric(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                value_type: float
                params:
                  mode: percent
        """)
        mc = load_metrics_config(path)
        assert len(mc.metrics) == 1
        assert mc.metrics[0].id == "cpu_util"
        assert mc.metrics[0].collector == "cpu"
        assert mc.metrics[0].key == "host.cpu.util"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_metrics_config("/nonexistent/metrics.yaml")

    def test_defaults_inherited(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            defaults:
              timeout_seconds: 30
              delivery: immediate
              error_policy: mark_failed
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                params:
                  mode: percent
        """)
        mc = load_metrics_config(path)
        m = mc.metrics[0]
        assert m.timeout_seconds == 30.0
        assert m.delivery == "immediate"
        assert m.error_policy == "mark_failed"

    def test_collector_defaults_override(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            defaults:
              timeout_seconds: 5
            collector_defaults:
              memory:
                timeout_seconds: 20
                delivery: immediate
            metrics:
              - id: mem
                collector: memory
                key: host.mem
                params:
                  mode: used_percent
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].timeout_seconds == 20.0
        assert mc.metrics[0].delivery == "immediate"

    def test_metric_level_override_wins(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            defaults:
              timeout_seconds: 5
            collector_defaults:
              cpu:
                timeout_seconds: 10
            metrics:
              - id: cpu1
                collector: cpu
                key: host.cpu
                timeout_seconds: 99
                params:
                  mode: percent
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].timeout_seconds == 99.0

    def test_duplicate_id_raises(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: dup
                collector: cpu
                key: host.cpu1
                params: {mode: percent}
              - id: dup
                collector: cpu
                key: host.cpu2
                params: {mode: percent}
        """)
        with pytest.raises(ConfigError, match="Duplicate metric id"):
            load_metrics_config(path)

    def test_duplicate_key_raises(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                params: {mode: percent}
              - id: m2
                collector: cpu
                key: host.cpu
                params: {mode: percent}
        """)
        with pytest.raises(ConfigError, match="Duplicate Zabbix key"):
            load_metrics_config(path)

    def test_unknown_collector_raises_strict(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: bogus_collector
                key: test.key
        """)
        with pytest.raises(ConfigError, match="unknown collector"):
            load_metrics_config(path, strict=True)

    def test_unknown_collector_warns_not_strict(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: bogus_collector
                key: test.key
        """)
        mc = load_metrics_config(path, strict=False)
        assert len(mc.metrics) == 0

    def test_disabled_metric_included(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                enabled: false
                collector: cpu
                key: host.cpu
                params: {mode: percent}
        """)
        mc = load_metrics_config(path)
        assert len(mc.metrics) == 1
        assert mc.metrics[0].enabled is False

    def test_fallback_value_stored(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                error_policy: fallback
                fallback_value: "0"
                params: {mode: percent}
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].fallback_value == "0"

    def test_host_name_parsed(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                host_name: override-host
                params: {mode: percent}
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].host_name == "override-host"

    def test_host_name_defaults_to_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                params: {mode: percent}
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].host_name is None

    def test_invalid_delivery_strict(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: m1
                collector: cpu
                key: host.cpu
                delivery: instant
                params: {mode: percent}
        """)
        with pytest.raises(ConfigError, match="delivery"):
            load_metrics_config(path, strict=True)

    def test_disk_requires_mount(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: d1
                collector: disk
                key: host.disk
                params:
                  mode: used_percent
        """)
        with pytest.raises(ConfigError, match="mount"):
            load_metrics_config(path, strict=True)

    def test_service_systemd_requires_service_name(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: s1
                collector: service
                key: svc.state
                params:
                  check_mode: systemd
        """)
        with pytest.raises(ConfigError, match="service_name"):
            load_metrics_config(path, strict=True)

    def test_network_requires_mode(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: n1
                collector: network
                key: net.rx
                params:
                  interface: eth0
        """)
        with pytest.raises(ConfigError, match="mode"):
            load_metrics_config(path, strict=True)

    def test_network_sockstat_no_interface_required(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: n1
                collector: network
                key: net.tcp
                params:
                  mode: tcp_inuse
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].params["mode"] == "tcp_inuse"

    def test_log_requires_path(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: l1
                collector: log
                key: app.log
                params:
                  match: "ERROR"
        """)
        with pytest.raises(ConfigError, match="path"):
            load_metrics_config(path, strict=True)

    def test_log_requires_match(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: l1
                collector: log
                key: app.log
                params:
                  path: /var/log/app.log
        """)
        with pytest.raises(ConfigError, match="match"):
            load_metrics_config(path, strict=True)

    def test_probe_params_stored(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: p1
                collector: probe
                key: probe.google.dns
                value_type: int
                params:
                  host: 8.8.8.8
                  port: 53
                  mode: tcp
        """)
        mc = load_metrics_config(path)
        assert mc.metrics[0].collector == "probe"
        assert mc.metrics[0].params["host"] == "8.8.8.8"

    def test_version_one_accepted(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics: []
        """)
        mc = load_metrics_config(path)
        assert mc.version == 1

    def test_unsupported_version_raises(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 99
            metrics: []
        """)
        with pytest.raises(ConfigError, match="version"):
            load_metrics_config(path)

    @pytest.mark.parametrize("collector,params", [
        ("cpu", {"mode": "percent"}),
        ("cpu", {"mode": "load1"}),
        ("cpu", {"mode": "load5"}),
        ("cpu", {"mode": "load15"}),
        ("cpu", {"mode": "uptime"}),
        ("memory", {"mode": "used_percent"}),
        ("memory", {"mode": "available_bytes"}),
        ("memory", {"mode": "swap_used_percent"}),
        ("disk", {"mount": "/", "mode": "used_percent"}),
        ("disk", {"mount": "/", "mode": "free_bytes"}),
        ("disk", {"mount": "/", "mode": "used_bytes"}),
        ("disk", {"mount": "/", "mode": "inodes_used_percent"}),
    ])
    def test_valid_collector_params(self, tmp_path, collector, params):
        params_yaml = "\n".join(f"                  {k}: {repr(v)}" for k, v in params.items())
        path = write_yaml(tmp_path, "metrics.yaml", f"""
            version: 1
            metrics:
              - id: m1
                collector: {collector}
                key: test.key
                params:
{params_yaml}
        """)
        mc = load_metrics_config(path)
        assert len(mc.metrics) == 1


# ---------------------------------------------------------------------------
# Schedule field validation
# ---------------------------------------------------------------------------

class TestScheduleFieldValidation:
    """Tests for parsing of time_window_from/till, max_executions_per_day,
    and run_frequency in metrics.yaml."""

    BASE = textwrap.dedent("""
        version: 1
        defaults:
          enabled: true
          delivery: batch
          timeout_seconds: 10
          error_policy: skip
        metrics:
          - id: cpu_sched
            collector: cpu
            key: host.cpu.sched
            params:
              mode: percent
    """)

    def _with_field(self, tmp_path, field_yaml: str) -> str:
        content = self.BASE.rstrip() + "\n    " + field_yaml + "\n"
        return write_yaml(tmp_path, "metrics.yaml", content)

    # --- time_window_from ---

    def test_time_window_from_quoted_string(self, tmp_path):
        path = self._with_field(tmp_path, 'time_window_from: "0800"')
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].time_window_from == "0800"

    def test_time_window_from_integer(self, tmp_path):
        # Unquoted integer: 800 → normalised to "0800"
        path = self._with_field(tmp_path, "time_window_from: 800")
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].time_window_from == "0800"

    def test_time_window_from_absent_is_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", self.BASE)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].time_window_from is None

    def test_time_window_from_invalid_hours_raises(self, tmp_path):
        path = self._with_field(tmp_path, 'time_window_from: "2500"')
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    def test_time_window_from_invalid_minutes_raises(self, tmp_path):
        path = self._with_field(tmp_path, 'time_window_from: "0860"')
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    # --- time_window_till ---

    def test_time_window_till_valid(self, tmp_path):
        path = self._with_field(tmp_path, 'time_window_till: "1800"')
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].time_window_till == "1800"

    def test_time_window_till_invalid_raises(self, tmp_path):
        path = self._with_field(tmp_path, 'time_window_till: "2500"')
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    def test_time_window_till_absent_is_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", self.BASE)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].time_window_till is None

    # --- max_executions_per_day ---

    def test_max_executions_valid(self, tmp_path):
        path = self._with_field(tmp_path, "max_executions_per_day: 5")
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].max_executions_per_day == 5

    def test_max_executions_zero_allowed(self, tmp_path):
        path = self._with_field(tmp_path, "max_executions_per_day: 0")
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].max_executions_per_day == 0

    def test_max_executions_negative_raises(self, tmp_path):
        path = self._with_field(tmp_path, "max_executions_per_day: -1")
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    def test_max_executions_absent_is_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", self.BASE)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].max_executions_per_day is None

    # --- run_frequency ---

    def test_run_frequency_integer(self, tmp_path):
        path = self._with_field(tmp_path, "run_frequency: 5")
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].run_frequency == 5

    def test_run_frequency_zero_allowed(self, tmp_path):
        path = self._with_field(tmp_path, "run_frequency: 0")
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].run_frequency == 0

    def test_run_frequency_even(self, tmp_path):
        path = self._with_field(tmp_path, 'run_frequency: "even"')
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].run_frequency == "even"

    def test_run_frequency_odd(self, tmp_path):
        path = self._with_field(tmp_path, 'run_frequency: "odd"')
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].run_frequency == "odd"

    def test_run_frequency_invalid_string_raises(self, tmp_path):
        path = self._with_field(tmp_path, 'run_frequency: "weekly"')
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    def test_run_frequency_negative_raises(self, tmp_path):
        path = self._with_field(tmp_path, "run_frequency: -3")
        with pytest.raises(ConfigError):
            load_metrics_config(path)

    def test_run_frequency_absent_is_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", self.BASE)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].run_frequency is None

    def test_all_four_schedule_fields_together(self, tmp_path):
        content = (
            self.BASE.rstrip()
            + "\n    time_window_from: \"0800\""
            + "\n    time_window_till: \"2000\""
            + "\n    max_executions_per_day: 10"
            + "\n    run_frequency: 2\n"
        )
        path = write_yaml(tmp_path, "metrics.yaml", content)
        cfg = load_metrics_config(path)
        m = cfg.metrics[0]
        assert m.time_window_from == "0800"
        assert m.time_window_till == "2000"
        assert m.max_executions_per_day == 10
        assert m.run_frequency == 2
