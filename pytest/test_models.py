"""
test_models.py — Comprehensive tests for zabbig_client/models.py.
"""
import time

import pytest

from zabbig_client.models import (
    DELIVERY_BATCH,
    DELIVERY_IMMEDIATE,
    ERROR_POLICY_FALLBACK,
    ERROR_POLICY_MARK_FAILED,
    ERROR_POLICY_SKIP,
    RESULT_FAILED,
    RESULT_FALLBACK,
    RESULT_OK,
    RESULT_SKIPPED,
    RESULT_TIMEOUT,
    VALID_COLLECTORS,
    VALID_DELIVERY,
    VALID_ERROR_POLICY,
    VALID_IMPORTANCE,
    VALID_VALUE_TYPES,
    BatchingConfig,
    ClientConfig,
    CollectorDefaults,
    FeaturesConfig,
    LogFileConfig,
    LoggingConfig,
    MetricDef,
    MetricResult,
    MetricsConfig,
    RunSummary,
    RuntimeConfig,
    StateConfig,
    ZabbixConfig,
)
from conftest import make_metric, make_result


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_valid_collectors_contains_all(self):
        assert VALID_COLLECTORS == {"cpu", "memory", "disk", "service", "network", "log", "probe", "database"}

    def test_valid_delivery(self):
        assert VALID_DELIVERY == {"batch", "immediate"}

    def test_valid_error_policy(self):
        assert VALID_ERROR_POLICY == {"skip", "fallback", "mark_failed"}

    def test_valid_value_types(self):
        assert "float" in VALID_VALUE_TYPES
        assert "int" in VALID_VALUE_TYPES
        assert "string" in VALID_VALUE_TYPES

    def test_valid_importance(self):
        assert VALID_IMPORTANCE == {"low", "normal", "high", "critical"}

    def test_result_constants(self):
        assert RESULT_OK == "ok"
        assert RESULT_FAILED == "failed"
        assert RESULT_TIMEOUT == "timeout"
        assert RESULT_SKIPPED == "skipped"
        assert RESULT_FALLBACK == "fallback"


# ---------------------------------------------------------------------------
# Config dataclasses — defaults
# ---------------------------------------------------------------------------

class TestZabbixConfig:
    def test_defaults(self):
        cfg = ZabbixConfig()
        assert cfg.server_hosts == ["127.0.0.1"]
        assert cfg.server_port == 10051
        assert cfg.host_name == ""
        assert cfg.host_group == "zabbig Clients"
        assert cfg.connect_timeout_seconds == 10.0
        assert cfg.send_timeout_seconds == 30.0

    def test_custom_values(self):
        cfg = ZabbixConfig(server_hosts=["zabbix.example.com"], server_port=10052, host_name="myhost")
        assert cfg.server_hosts == ["zabbix.example.com"]
        assert cfg.server_port == 10052
        assert cfg.host_name == "myhost"

    def test_multiple_hosts(self):
        cfg = ZabbixConfig(server_hosts=["proxy-a", "proxy-b", "proxy-c"])
        assert cfg.server_hosts == ["proxy-a", "proxy-b", "proxy-c"]


class TestRuntimeConfig:
    def test_defaults(self):
        cfg = RuntimeConfig()
        assert cfg.overall_timeout_seconds == 240.0
        assert cfg.max_concurrency == 8
        assert cfg.lock_file == "state/zabbig_client.lock"
        assert cfg.dry_run is False
        assert cfg.fail_fast is False
        assert cfg.proc_root == "/proc"

    def test_dry_run_flag(self):
        cfg = RuntimeConfig(dry_run=True)
        assert cfg.dry_run is True


class TestBatchingConfig:
    def test_defaults(self):
        cfg = BatchingConfig()
        assert cfg.batch_collection_window_seconds == 60.0
        assert cfg.batch_send_max_size == 250
        assert cfg.flush_immediate_separately is True
        assert cfg.immediate_micro_batch_window_ms == 200


class TestLogFileConfig:
    def test_defaults(self):
        cfg = LogFileConfig(path="/var/log/test.log")
        assert cfg.path == "/var/log/test.log"
        assert cfg.max_size_mb == 10
        assert cfg.max_backups == 5
        assert cfg.compress is True

    def test_custom_values(self):
        cfg = LogFileConfig(path="/tmp/x.log", max_size_mb=50, max_backups=3, compress=False)
        assert cfg.max_size_mb == 50
        assert cfg.max_backups == 3
        assert cfg.compress is False


class TestLoggingConfig:
    def test_defaults(self):
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.format == "text"
        assert cfg.file is None
        assert cfg.console is True

    def test_json_format(self):
        cfg = LoggingConfig(format="json")
        assert cfg.format == "json"


class TestFeaturesConfig:
    def test_defaults(self):
        cfg = FeaturesConfig()
        assert cfg.self_monitoring_metrics is True
        assert cfg.strict_config_validation is True
        assert cfg.skip_disabled_metrics is True

    def test_custom(self):
        cfg = FeaturesConfig(strict_config_validation=False)
        assert cfg.strict_config_validation is False


class TestClientConfig:
    def test_default_sub_configs(self):
        cfg = ClientConfig()
        assert isinstance(cfg.zabbix, ZabbixConfig)
        assert isinstance(cfg.runtime, RuntimeConfig)
        assert isinstance(cfg.batching, BatchingConfig)
        assert isinstance(cfg.logging, LoggingConfig)
        assert isinstance(cfg.state, StateConfig)
        assert isinstance(cfg.features, FeaturesConfig)


# ---------------------------------------------------------------------------
# MetricDef
# ---------------------------------------------------------------------------

class TestMetricDef:
    def test_basic_fields(self):
        m = make_metric(id="my_metric", collector="cpu", key="host.cpu")
        assert m.id == "my_metric"
        assert m.collector == "cpu"
        assert m.key == "host.cpu"

    def test_defaults(self):
        m = MetricDef(
            id="m",
            name="m",
            enabled=True,
            collector="cpu",
            key="k",
            delivery=DELIVERY_BATCH,
            timeout_seconds=10.0,
            error_policy=ERROR_POLICY_SKIP,
        )
        assert m.description == ""
        assert m.value_type == "float"
        assert m.unit == ""
        assert m.importance == "normal"
        assert m.fallback_value is None
        assert m.tags == []
        assert m.params == {}

    def test_params_stored(self):
        m = make_metric(params={"mode": "percent", "proc_root": "/proc"})
        assert m.params["mode"] == "percent"

    def test_enabled_false(self):
        m = make_metric(enabled=False)
        assert m.enabled is False

    def test_host_name_default_is_none(self):
        m = make_metric()
        assert m.host_name is None

    def test_host_name_stored(self):
        m = make_metric(host_name="override-host")
        assert m.host_name == "override-host"


# ---------------------------------------------------------------------------
# MetricResult
# ---------------------------------------------------------------------------

class TestMetricResult:
    def test_is_sendable_ok(self):
        r = make_result(status=RESULT_OK, value="42")
        assert r.is_sendable is True

    def test_is_sendable_fallback(self):
        r = make_result(status=RESULT_FALLBACK, value="0")
        assert r.is_sendable is True

    def test_is_sendable_failed(self):
        r = make_result(status=RESULT_FAILED, value=None)
        assert r.is_sendable is False

    def test_is_sendable_none_value(self):
        r = make_result(status=RESULT_OK, value=None)
        assert r.is_sendable is False

    def test_is_sendable_timeout(self):
        r = make_result(status=RESULT_TIMEOUT, value=None)
        assert r.is_sendable is False

    def test_is_sendable_skipped(self):
        r = make_result(status=RESULT_SKIPPED, value=None)
        assert r.is_sendable is False

    def test_make_timeout(self):
        metric = make_metric(id="t1", key="k1", value_type="float")
        r = MetricResult.make_timeout(metric, duration_ms=500.0)
        assert r.status == RESULT_TIMEOUT
        assert r.value is None
        assert r.metric_id == "t1"
        assert r.key == "k1"
        assert r.duration_ms == 500.0
        assert "timed out" in (r.error or "").lower()

    def test_make_error(self):
        metric = make_metric(id="e1", key="k2")
        exc = ValueError("something broke")
        r = MetricResult.make_error(metric, exc, duration_ms=100.0)
        assert r.status == RESULT_FAILED
        assert r.value is None
        assert "something broke" in r.error
        assert r.duration_ms == 100.0

    def test_make_fallback(self):
        metric = make_metric(id="f1", key="k3", fallback_value="0")
        r = MetricResult.make_fallback(metric, duration_ms=50.0)
        assert r.status == RESULT_FALLBACK
        assert r.value == "0"
        assert r.is_sendable is True

    def test_make_fallback_no_value(self):
        metric = make_metric(id="f2", key="k4", fallback_value=None)
        r = MetricResult.make_fallback(metric)
        assert r.value is None

    def test_timestamp_is_recent(self):
        metric = make_metric()
        r = MetricResult.make_timeout(metric)
        assert abs(r.timestamp - int(time.time())) <= 2

    def test_delivery_preserved(self):
        metric = make_metric(delivery=DELIVERY_IMMEDIATE)
        r = MetricResult.make_timeout(metric)
        assert r.delivery == DELIVERY_IMMEDIATE

    def test_host_name_default_is_none(self):
        r = make_result()
        assert r.host_name is None

    def test_host_name_stored(self):
        r = make_result(host_name="result-host")
        assert r.host_name == "result-host"

    def test_make_timeout_propagates_host_name(self):
        metric = make_metric(host_name="timeout-host")
        r = MetricResult.make_timeout(metric)
        assert r.host_name == "timeout-host"

    def test_make_timeout_no_host_name(self):
        metric = make_metric()
        r = MetricResult.make_timeout(metric)
        assert r.host_name is None

    def test_make_error_propagates_host_name(self):
        metric = make_metric(host_name="error-host")
        r = MetricResult.make_error(metric, ValueError("boom"))
        assert r.host_name == "error-host"

    def test_make_fallback_propagates_host_name(self):
        metric = make_metric(host_name="fallback-host", fallback_value="0")
        r = MetricResult.make_fallback(metric)
        assert r.host_name == "fallback-host"


# ---------------------------------------------------------------------------
# CollectorDefaults
# ---------------------------------------------------------------------------

class TestCollectorDefaults:
    def test_defaults(self):
        cd = CollectorDefaults()
        assert cd.timeout_seconds == 10.0
        assert cd.delivery == DELIVERY_BATCH

    def test_custom(self):
        cd = CollectorDefaults(timeout_seconds=30.0, delivery=DELIVERY_IMMEDIATE)
        assert cd.timeout_seconds == 30.0
        assert cd.delivery == DELIVERY_IMMEDIATE


# ---------------------------------------------------------------------------
# RunSummary
# ---------------------------------------------------------------------------

class TestRunSummary:
    def test_defaults(self):
        s = RunSummary()
        assert s.total_configured == 0
        assert s.collected_ok == 0
        assert s.collected_failed == 0
        assert s.collected_timeout == 0
        assert s.skipped == 0
        assert s.sent_batch == 0
        assert s.sent_immediate == 0
        assert s.sender_failures == 0
        assert s.duration_ms == 0.0
        assert s.success is True

    def test_mutation(self):
        s = RunSummary()
        s.collected_ok = 5
        s.collected_failed = 1
        s.success = False
        assert s.collected_ok == 5
        assert s.success is False


# ---------------------------------------------------------------------------
# MetricsConfig
# ---------------------------------------------------------------------------

class TestMetricsConfig:
    def test_defaults(self):
        mc = MetricsConfig()
        assert mc.version == 1
        assert mc.defaults == {}
        assert mc.collector_defaults == {}
        assert mc.metrics == []

    def test_with_metrics(self):
        m = make_metric()
        mc = MetricsConfig(metrics=[m])
        assert len(mc.metrics) == 1
