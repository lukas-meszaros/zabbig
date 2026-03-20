"""
test_result_router.py — Unit tests for result routing and error policy.
"""
import os
import sys
import time
import unittest

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from zabbig_client.models import (
    DELIVERY_BATCH,
    DELIVERY_IMMEDIATE,
    RESULT_FAILED,
    RESULT_OK,
    RESULT_SKIPPED,
    RESULT_TIMEOUT,
    MetricDef,
    MetricResult,
)
from zabbig_client.result_router import route
from zabbig_client.runner import _apply_error_policy


def _result(*, delivery=DELIVERY_BATCH, status=RESULT_OK, value="1.0") -> MetricResult:
    return MetricResult(
        metric_id="test", key="host.test", value=value, value_type="float",
        timestamp=int(time.time()), collector="cpu", delivery=delivery,
        status=status,
    )


def _metric(**kwargs) -> MetricDef:
    defaults = dict(
        id="test", name="Test", enabled=True, collector="cpu",
        key="host.test", delivery=DELIVERY_BATCH,
        timeout_seconds=10.0, error_policy="skip", fallback_value=None,
    )
    defaults.update(kwargs)
    return MetricDef(**defaults)


class TestRoute(unittest.TestCase):

    def test_ok_batch_goes_to_batch(self):
        results = [_result(delivery=DELIVERY_BATCH, status=RESULT_OK)]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 1)
        self.assertEqual(len(immediate), 0)

    def test_ok_immediate_goes_to_immediate(self):
        results = [_result(delivery=DELIVERY_IMMEDIATE, status=RESULT_OK)]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 0)
        self.assertEqual(len(immediate), 1)

    def test_failed_result_dropped(self):
        results = [_result(status=RESULT_FAILED, value=None)]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 0)
        self.assertEqual(len(immediate), 0)

    def test_timeout_result_dropped(self):
        results = [_result(status=RESULT_TIMEOUT, value=None)]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 0)

    def test_skipped_result_dropped(self):
        results = [_result(status=RESULT_SKIPPED, value=None)]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 0)

    def test_mixed_results(self):
        results = [
            _result(delivery=DELIVERY_BATCH, status=RESULT_OK),
            _result(delivery=DELIVERY_IMMEDIATE, status=RESULT_OK),
            _result(status=RESULT_FAILED, value=None),
        ]
        batch, immediate = route(results)
        self.assertEqual(len(batch), 1)
        self.assertEqual(len(immediate), 1)


class TestApplyErrorPolicy(unittest.TestCase):

    def test_skip_policy_makes_skipped(self):
        m = _metric(error_policy="skip")
        raw = MetricResult.make_error(m, RuntimeError("err"))
        result = _apply_error_policy(raw, m)
        self.assertEqual(result.status, RESULT_SKIPPED)
        self.assertIsNone(result.value)

    def test_fallback_policy_with_value(self):
        m = _metric(error_policy="fallback", fallback_value="0")
        raw = MetricResult.make_error(m, RuntimeError("err"))
        result = _apply_error_policy(raw, m)
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.value, "0")
        self.assertTrue(result.is_sendable)

    def test_fallback_policy_without_value_degrades_to_skip(self):
        m = _metric(error_policy="fallback", fallback_value=None)
        raw = MetricResult.make_error(m, RuntimeError("err"))
        result = _apply_error_policy(raw, m)
        self.assertEqual(result.status, RESULT_SKIPPED)

    def test_mark_failed_policy_keeps_failed(self):
        m = _metric(error_policy="mark_failed")
        raw = MetricResult.make_error(m, RuntimeError("err"))
        result = _apply_error_policy(raw, m)
        self.assertEqual(result.status, RESULT_FAILED)
        self.assertFalse(result.is_sendable)

    def test_ok_result_passes_through_unchanged(self):
        m = _metric(error_policy="skip")
        ok = _result(status=RESULT_OK)
        result = _apply_error_policy(ok, m)
        self.assertEqual(result.status, RESULT_OK)

    def test_timeout_also_applies_policy(self):
        m = _metric(error_policy="fallback", fallback_value="-1")
        raw = MetricResult.make_timeout(m)
        result = _apply_error_policy(raw, m)
        self.assertEqual(result.value, "-1")


if __name__ == "__main__":
    unittest.main()
