"""
models.py — All dataclasses and enums used across the client.
No external dependencies. stdlib only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Delivery / policy constants (plain strings keep YAML config readable)
# ---------------------------------------------------------------------------
DELIVERY_BATCH = "batch"
DELIVERY_IMMEDIATE = "immediate"

ERROR_POLICY_SKIP = "skip"
ERROR_POLICY_FALLBACK = "fallback"
ERROR_POLICY_MARK_FAILED = "mark_failed"

RESULT_OK = "ok"
RESULT_FAILED = "failed"
RESULT_TIMEOUT = "timeout"
RESULT_SKIPPED = "skipped"
RESULT_FALLBACK = "fallback"

VALID_DELIVERY = {DELIVERY_BATCH, DELIVERY_IMMEDIATE}
VALID_ERROR_POLICY = {ERROR_POLICY_SKIP, ERROR_POLICY_FALLBACK, ERROR_POLICY_MARK_FAILED}
VALID_VALUE_TYPES = {"int", "float", "string", "text"}
VALID_IMPORTANCE = {"low", "normal", "high", "critical"}
VALID_COLLECTORS = {"cpu", "memory", "disk", "service", "network", "log", "probe"}


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

@dataclass
class ZabbixConfig:
    server_host: str = "127.0.0.1"
    server_port: int = 10051
    host_name: str = ""
    host_group: str = "zabbig Clients"
    connect_timeout_seconds: float = 10.0
    send_timeout_seconds: float = 30.0


@dataclass
class RuntimeConfig:
    overall_timeout_seconds: float = 240.0
    max_concurrency: int = 8
    lock_file: str = "state/zabbig_client.lock"
    dry_run: bool = False
    fail_fast: bool = False
    proc_root: str = "/proc"


@dataclass
class BatchingConfig:
    batch_collection_window_seconds: float = 60.0
    batch_send_max_size: int = 250
    flush_immediate_separately: bool = True
    immediate_micro_batch_window_ms: int = 200


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "text"
    file: Optional[str] = None
    console: bool = True


@dataclass
class StateConfig:
    enabled: bool = False
    directory: str = "state"


@dataclass
class FeaturesConfig:
    self_monitoring_metrics: bool = True
    emit_partial_failure_metrics: bool = False
    strict_config_validation: bool = True
    skip_disabled_metrics: bool = True


@dataclass
class ClientConfig:
    zabbix: ZabbixConfig = field(default_factory=ZabbixConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    batching: BatchingConfig = field(default_factory=BatchingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    state: StateConfig = field(default_factory=StateConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)


# ---------------------------------------------------------------------------
# Metric definition (parsed from metrics.yaml)
# ---------------------------------------------------------------------------

@dataclass
class MetricDef:
    id: str
    name: str
    enabled: bool
    collector: str
    key: str
    delivery: str
    timeout_seconds: float
    error_policy: str
    description: str = ""
    value_type: str = "float"
    unit: str = ""
    importance: str = "normal"
    fallback_value: Optional[str] = None
    tags: list = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class CollectorDefaults:
    timeout_seconds: float = 10.0
    delivery: str = DELIVERY_BATCH


@dataclass
class MetricsConfig:
    version: int = 1
    defaults: dict = field(default_factory=dict)
    collector_defaults: dict = field(default_factory=dict)
    metrics: list = field(default_factory=list)  # List[MetricDef]


# ---------------------------------------------------------------------------
# Normalized result produced by each collector
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    metric_id: str
    key: str
    value: Optional[str]
    value_type: str
    timestamp: int
    collector: str
    delivery: str
    status: str
    unit: str = ""
    tags: list = field(default_factory=list)
    error: Optional[str] = None
    source: str = ""
    duration_ms: float = 0.0

    @property
    def is_sendable(self) -> bool:
        """True when status indicates a value that should be sent to Zabbix."""
        return self.status in (RESULT_OK, RESULT_FALLBACK) and self.value is not None

    @classmethod
    def make_timeout(cls, metric: MetricDef, duration_ms: float = 0.0) -> "MetricResult":
        return cls(
            metric_id=metric.id,
            key=metric.key,
            value=None,
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector=metric.collector,
            delivery=metric.delivery,
            status=RESULT_TIMEOUT,
            unit=metric.unit,
            tags=metric.tags,
            error="Collector timed out",
            duration_ms=duration_ms,
        )

    @classmethod
    def make_error(cls, metric: MetricDef, exc: Exception, duration_ms: float = 0.0) -> "MetricResult":
        return cls(
            metric_id=metric.id,
            key=metric.key,
            value=None,
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector=metric.collector,
            delivery=metric.delivery,
            status=RESULT_FAILED,
            unit=metric.unit,
            tags=metric.tags,
            error=str(exc),
            duration_ms=duration_ms,
        )

    @classmethod
    def make_fallback(cls, metric: MetricDef, duration_ms: float = 0.0) -> "MetricResult":
        return cls(
            metric_id=metric.id,
            key=metric.key,
            value=metric.fallback_value,
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector=metric.collector,
            delivery=metric.delivery,
            status=RESULT_FALLBACK,
            unit=metric.unit,
            tags=metric.tags,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Run-level summary
# ---------------------------------------------------------------------------

@dataclass
class RunSummary:
    total_configured: int = 0
    enabled: int = 0
    collected_ok: int = 0
    collected_failed: int = 0
    collected_timeout: int = 0
    skipped: int = 0
    sent_batch: int = 0
    sent_immediate: int = 0
    sender_failures: int = 0
    duration_ms: float = 0.0
    success: bool = True
