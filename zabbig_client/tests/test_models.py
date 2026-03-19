"""
test_models.py — Unit tests for MetricResult factory methods and properties.
"""
import os
import sys
import time
import unittest

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from zabbig_client.models import (
    RESULT_FALLBACK,
    RESULT_FAILED,
    RESULT_OK,
    RESULT_SKIPPED,
    RESULT_TIMEOUT,
    MetricDef,
    MetricResult,
)


def _make_metric(**kwargs) -> MetricDef:
    defaults = dict(
        id="test_metric",
        name="Test metric",
        enabled=True,
        collector="cpu",
        key="host.test",
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
        fallback_value=None,
    )
    defaults.update(kwargs)
    return MetricDef(**defaults)


class TestMetricResultIsProperty(unittest.TestCase):

    def test_ok_is_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value="1.0", value_type="float",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_OK,
        )
        self.assertTrue(r.is_sendable)

    def test_fallback_with_value_is_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value="0", value_type="int",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_FALLBACK,
        )
        self.assertTrue(r.is_sendable)

    def test_failed_not_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value=None, value_type="float",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_FAILED,
        )
        self.assertFalse(r.is_sendable)

    def test_timeout_not_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value=None, value_type="float",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_TIMEOUT,
        )
        self.assertFalse(r.is_sendable)

    def test_skipped_not_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value=None, value_type="float",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_SKIPPED,
        )
        self.assertFalse(r.is_sendable)

    def test_ok_with_none_value_not_sendable(self):
        r = MetricResult(
            metric_id="x", key="host.k", value=None, value_type="float",
            timestamp=int(time.time()), collector="cpu", delivery="batch",
            status=RESULT_OK,
        )
        self.assertFalse(r.is_sendable)


class TestMetricResultFactories(unittest.TestCase):

    def test_make_timeout(self):
        m = _make_metric()
        r = MetricResult.make_timeout(m, duration_ms=5000.0)
        self.assertEqual(r.status, RESULT_TIMEOUT)
        self.assertIsNone(r.value)
        self.assertFalse(r.is_sendable)
        self.assertEqual(r.duration_ms, 5000.0)
        self.assertEqual(r.metric_id, "test_metric")

    def test_make_error(self):
        m = _make_metric()
        r = MetricResult.make_error(m, RuntimeError("boom"), duration_ms=100.0)
        self.assertEqual(r.status, RESULT_FAILED)
        self.assertIsNone(r.value)
        self.assertIn("boom", r.error)

    def test_make_fallback(self):
        m = _make_metric(fallback_value="0")
        r = MetricResult.make_fallback(m, duration_ms=50.0)
        self.assertEqual(r.status, RESULT_FALLBACK)
        self.assertEqual(r.value, "0")
        self.assertTrue(r.is_sendable)


if __name__ == "__main__":
    unittest.main()
