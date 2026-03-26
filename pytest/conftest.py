"""
conftest.py — Shared fixtures and sys.path setup for the pytest test suite.

Adds both zabbig_client/src/ (for zabbig_client, zabbix_utils, yaml, requests)
and zabbix_update/ (for _common, create_* scripts) to sys.path so all modules
can be imported directly.
"""
import os
import sys
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT_SRC = os.path.join(_ROOT, "zabbig_client", "src")
_CLIENT_DIR = os.path.join(_ROOT, "zabbig_client")
_ZABBIX_UPDATE = os.path.join(_ROOT, "zabbix_update")

for _p in [_CLIENT_SRC, _CLIENT_DIR, _ZABBIX_UPDATE]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Shared helpers for building minimal MetricDef / MetricResult instances
# ---------------------------------------------------------------------------

from zabbig_client.models import (
    MetricDef,
    MetricResult,
    RESULT_OK,
    DELIVERY_IMMEDIATE,
    DELIVERY_BATCH,
)


def make_metric(
    id="test_metric",
    collector="cpu",
    key="test.key",
    delivery=DELIVERY_BATCH,
    timeout_seconds=10.0,
    error_policy="skip",
    value_type="float",
    params=None,
    fallback_value=None,
    enabled=True,
    host_name=None,
):
    return MetricDef(
        id=id,
        name=id,
        enabled=enabled,
        collector=collector,
        key=key,
        delivery=delivery,
        timeout_seconds=timeout_seconds,
        error_policy=error_policy,
        value_type=value_type,
        params=params or {},
        fallback_value=fallback_value,
        host_name=host_name,
    )


def make_result(
    metric_id="test_metric",
    key="test.key",
    value="42",
    status=RESULT_OK,
    delivery=DELIVERY_BATCH,
    value_type="float",
    collector="cpu",
    error=None,
    host_name=None,
):
    return MetricResult(
        metric_id=metric_id,
        key=key,
        value=value,
        value_type=value_type,
        timestamp=int(time.time()),
        collector=collector,
        delivery=delivery,
        status=status,
        error=error,
        host_name=host_name,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_metric():
    return make_metric()


@pytest.fixture
def minimal_result():
    return make_result()
