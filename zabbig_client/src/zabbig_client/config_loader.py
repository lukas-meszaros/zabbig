"""
config_loader.py — Load and validate client.yaml and metrics.yaml.

Uses the vendored pure-Python yaml package from src/yaml/.
Validation raises ConfigError for structural problems.
When strict_config_validation=False, validation errors are logged as warnings.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

import yaml  # vendored pure-Python PyYAML in src/yaml/

from .models import (
    BatchingConfig,
    ClientConfig,
    CollectorDefaults,
    FeaturesConfig,
    LoggingConfig,
    MetricDef,
    MetricsConfig,
    RuntimeConfig,
    StateConfig,
    ZabbixConfig,
    VALID_COLLECTORS,
    VALID_DELIVERY,
    VALID_ERROR_POLICY,
    VALID_IMPORTANCE,
    VALID_VALUE_TYPES,
)

log = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when a config file contains an invalid value."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_client_config(path: str) -> ClientConfig:
    """Load and validate client.yaml. Returns a fully-populated ClientConfig."""
    raw = _read_yaml(path)
    cfg = ClientConfig()

    z = raw.get("zabbix", {})
    cfg.zabbix = ZabbixConfig(
        server_host=str(z.get("server_host", "127.0.0.1")),
        server_port=int(z.get("server_port", 10051)),
        host_name=str(z.get("host_name", socket.gethostname())),
        host_group=str(z.get("host_group", "zabbig Clients")),
        connect_timeout_seconds=float(z.get("connect_timeout_seconds", 10.0)),
        send_timeout_seconds=float(z.get("send_timeout_seconds", 30.0)),
    )

    r = raw.get("runtime", {})
    cfg.runtime = RuntimeConfig(
        overall_timeout_seconds=float(r.get("overall_timeout_seconds", 240.0)),
        max_concurrency=int(r.get("max_concurrency", 8)),
        lock_file=str(r.get("lock_file", "/tmp/zabbig_client.lock")),
        dry_run=bool(r.get("dry_run", False)),
        fail_fast=bool(r.get("fail_fast", False)),
        proc_root=str(r.get("proc_root", "/proc")),
    )

    b = raw.get("batching", {})
    cfg.batching = BatchingConfig(
        batch_collection_window_seconds=float(b.get("batch_collection_window_seconds", 60.0)),
        batch_send_max_size=int(b.get("batch_send_max_size", 250)),
        flush_immediate_separately=bool(b.get("flush_immediate_separately", True)),
        immediate_micro_batch_window_ms=int(b.get("immediate_micro_batch_window_ms", 200)),
    )

    lg = raw.get("logging", {})
    cfg.logging = LoggingConfig(
        level=str(lg.get("level", "INFO")).upper(),
        format=str(lg.get("format", "text")),
        file=lg.get("file") or None,
        console=bool(lg.get("console", True)),
    )

    st = raw.get("state", {})
    cfg.state = StateConfig(
        enabled=bool(st.get("enabled", False)),
        directory=str(st.get("directory", "state")),
    )

    ft = raw.get("features", {})
    cfg.features = FeaturesConfig(
        self_monitoring_metrics=bool(ft.get("self_monitoring_metrics", True)),
        emit_partial_failure_metrics=bool(ft.get("emit_partial_failure_metrics", False)),
        strict_config_validation=bool(ft.get("strict_config_validation", True)),
        skip_disabled_metrics=bool(ft.get("skip_disabled_metrics", True)),
    )

    _validate_client_config(cfg)
    return cfg


def load_metrics_config(path: str, strict: bool = True) -> MetricsConfig:
    """Load and validate metrics.yaml. Returns MetricsConfig with a list of MetricDef."""
    raw = _read_yaml(path)

    if raw.get("version", 1) != 1:
        _config_error(f"Unsupported metrics.yaml version: {raw.get('version')}", strict)

    defaults = raw.get("defaults", {})
    collector_defs_raw = raw.get("collector_defaults", {})

    collector_defaults: dict[str, CollectorDefaults] = {}
    for cname, craw in collector_defs_raw.items():
        collector_defaults[cname] = CollectorDefaults(
            timeout_seconds=float(craw.get("timeout_seconds", defaults.get("timeout_seconds", 10.0))),
            delivery=str(craw.get("delivery", defaults.get("delivery", "batch"))),
        )

    metrics: list[MetricDef] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()

    for raw_metric in raw.get("metrics", []):
        m = _parse_metric(raw_metric, defaults, collector_defaults, strict)
        if m is None:
            continue

        if m.id in seen_ids:
            _config_error(f"Duplicate metric id: '{m.id}'", strict)
        seen_ids.add(m.id)

        if m.key in seen_keys:
            _config_error(f"Duplicate Zabbix key: '{m.key}' (metric id={m.id})", strict)
        seen_keys.add(m.key)

        metrics.append(m)

    return MetricsConfig(
        version=int(raw.get("version", 1)),
        defaults=defaults,
        collector_defaults=collector_defs_raw,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must be a YAML mapping, got {type(data).__name__}: {path}")
    return data


def _parse_metric(
    raw: dict,
    defaults: dict,
    collector_defaults: dict[str, CollectorDefaults],
    strict: bool,
) -> MetricDef | None:
    """Parse one metric entry from metrics.yaml."""

    def get(key: str, fallback: Any = None) -> Any:
        if key in raw:
            return raw[key]
        if key in defaults:
            return defaults[key]
        return fallback

    metric_id = raw.get("id")
    if not metric_id:
        _config_error("Metric entry missing required field 'id'", strict)
        return None

    collector = raw.get("collector")
    if not collector:
        _config_error(f"Metric '{metric_id}' missing required field 'collector'", strict)
        return None
    if collector not in VALID_COLLECTORS:
        _config_error(
            f"Metric '{metric_id}' has unknown collector '{collector}'. "
            f"Valid: {sorted(VALID_COLLECTORS)}", strict
        )
        return None

    key = raw.get("key")
    if not key:
        _config_error(f"Metric '{metric_id}' missing required field 'key'", strict)
        return None

    enabled = get("enabled", True)
    if not isinstance(enabled, bool):
        _config_error(f"Metric '{metric_id}': 'enabled' must be a boolean", strict)
        enabled = bool(enabled)

    # Resolve timeout: metric → collector_default → global default
    cd = collector_defaults.get(collector)
    default_timeout = cd.timeout_seconds if cd else float(defaults.get("timeout_seconds", 10.0))
    timeout = float(raw.get("timeout_seconds", default_timeout))
    if timeout <= 0:
        _config_error(f"Metric '{metric_id}': timeout_seconds must be > 0", strict)
        timeout = 10.0

    # Resolve delivery
    default_delivery = (cd.delivery if cd else None) or defaults.get("delivery", "batch")
    delivery = str(raw.get("delivery", default_delivery))
    if delivery not in VALID_DELIVERY:
        _config_error(
            f"Metric '{metric_id}': invalid delivery '{delivery}'. Valid: {sorted(VALID_DELIVERY)}", strict
        )
        delivery = "batch"

    error_policy = str(get("error_policy", "skip"))
    if error_policy not in VALID_ERROR_POLICY:
        _config_error(
            f"Metric '{metric_id}': invalid error_policy '{error_policy}'. Valid: {sorted(VALID_ERROR_POLICY)}", strict
        )
        error_policy = "skip"

    value_type = str(get("value_type", "float"))
    if value_type not in VALID_VALUE_TYPES:
        _config_error(
            f"Metric '{metric_id}': invalid value_type '{value_type}'. Valid: {sorted(VALID_VALUE_TYPES)}", strict
        )
        value_type = "float"

    importance = str(get("importance", "normal"))
    if importance not in VALID_IMPORTANCE:
        _config_error(
            f"Metric '{metric_id}': invalid importance '{importance}'. Valid: {sorted(VALID_IMPORTANCE)}", strict
        )
        importance = "normal"

    fallback_value = raw.get("fallback_value")
    if fallback_value is not None:
        fallback_value = str(fallback_value)

    tags = list(get("tags", []))
    params = dict(raw.get("params", {}))

    # Validate required params per collector
    _validate_collector_params(metric_id, collector, params, strict)

    return MetricDef(
        id=metric_id,
        name=str(raw.get("name", metric_id)),
        enabled=enabled,
        collector=collector,
        key=key,
        delivery=delivery,
        timeout_seconds=timeout,
        error_policy=error_policy,
        description=str(raw.get("description", "")),
        value_type=value_type,
        unit=str(raw.get("unit", "")),
        importance=importance,
        fallback_value=fallback_value,
        tags=tags,
        params=params,
    )


def _validate_collector_params(metric_id: str, collector: str, params: dict, strict: bool) -> None:
    """Validate that required params for each collector type are present."""
    if collector == "cpu":
        mode = params.get("mode", "percent")
        valid_modes = {"percent", "load1", "load5", "load15", "uptime"}
        if mode not in valid_modes:
            _config_error(
                f"Metric '{metric_id}': cpu collector params.mode='{mode}' not in {valid_modes}", strict
            )
    elif collector == "memory":
        mode = params.get("mode", "used_percent")
        valid_modes = {"used_percent", "available_bytes", "swap_used_percent"}
        if mode not in valid_modes:
            _config_error(
                f"Metric '{metric_id}': memory collector params.mode='{mode}' not in {valid_modes}", strict
            )
    elif collector == "disk":
        if "mount" not in params:
            _config_error(
                f"Metric '{metric_id}': disk collector requires params.mount (e.g. '/')", strict
            )
        mode = params.get("mode", "used_percent")
        valid_modes = {
            "used_percent", "used_bytes", "free_bytes",
            "inodes_used_percent", "inodes_used", "inodes_free", "inodes_total",
        }
        if mode not in valid_modes:
            _config_error(
                f"Metric '{metric_id}': disk collector params.mode='{mode}' not in {valid_modes}", strict
            )
    elif collector == "service":
        check_mode = params.get("check_mode", "systemd")
        valid_check_modes = {"systemd", "process"}
        if check_mode not in valid_check_modes:
            _config_error(
                f"Metric '{metric_id}': service collector params.check_mode='{check_mode}' not in {valid_check_modes}", strict
            )
        if check_mode == "systemd" and "service_name" not in params:
            _config_error(
                f"Metric '{metric_id}': service collector with check_mode=systemd requires params.service_name", strict
            )
        if check_mode == "process" and "process_pattern" not in params:
            _config_error(
                f"Metric '{metric_id}': service collector with check_mode=process requires params.process_pattern", strict
            )
    elif collector == "network":
        mode = params.get("mode")
        valid_modes = {
            "rx_bytes_per_sec", "tx_bytes_per_sec",
            "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
            "rx_errors", "tx_errors", "rx_dropped", "tx_dropped",
            "tcp_inuse", "tcp_timewait", "tcp_orphans", "udp_inuse",
        }
        if not mode:
            _config_error(
                f"Metric '{metric_id}': network collector requires params.mode", strict
            )
        elif mode not in valid_modes:
            _config_error(
                f"Metric '{metric_id}': network collector params.mode='{mode}' not in {valid_modes}", strict
            )
        # interface is required for all non-sockstat modes
        sockstat_modes = {"tcp_inuse", "tcp_timewait", "tcp_orphans", "udp_inuse"}
        if mode not in sockstat_modes and "interface" not in params:
            _config_error(
                f"Metric '{metric_id}': network collector mode='{mode}' requires params.interface", strict
            )


def _validate_client_config(cfg: ClientConfig) -> None:
    if cfg.zabbix.server_port < 1 or cfg.zabbix.server_port > 65535:
        raise ConfigError(f"zabbix.server_port out of range: {cfg.zabbix.server_port}")
    if not cfg.zabbix.host_name:
        raise ConfigError("zabbix.host_name must not be empty")
    if cfg.runtime.overall_timeout_seconds <= 0:
        raise ConfigError("runtime.overall_timeout_seconds must be > 0")
    if cfg.runtime.max_concurrency < 1:
        raise ConfigError("runtime.max_concurrency must be >= 1")
    if cfg.batching.batch_collection_window_seconds <= 0:
        raise ConfigError("batching.batch_collection_window_seconds must be > 0")
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if cfg.logging.level not in valid_log_levels:
        raise ConfigError(f"logging.level '{cfg.logging.level}' not in {valid_log_levels}")


def _config_error(message: str, strict: bool) -> None:
    if strict:
        raise ConfigError(message)
    log.warning("Config warning (strict=False): %s", message)
