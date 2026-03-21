"""
test_runner.py — Tests for runner.py (async collector runner and error policy).
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import make_metric
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
    ClientConfig,
    MetricResult,
    RunSummary,
)
from zabbig_client.runner import _apply_error_policy, run_all_collectors, update_summary


# ---------------------------------------------------------------------------
# _apply_error_policy
# ---------------------------------------------------------------------------

class TestApplyErrorPolicy:
    def _make_failed_result(self, metric):
        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=None,
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector=metric.collector,
            delivery=metric.delivery,
            status=RESULT_FAILED,
        )

    def test_skip_policy_makes_skipped(self):
        metric = make_metric(error_policy=ERROR_POLICY_SKIP)
        raw = self._make_failed_result(metric)
        result = _apply_error_policy(raw, metric)
        assert result.status == RESULT_SKIPPED
        assert result.value is None

    def test_mark_failed_policy_keeps_failed(self):
        metric = make_metric(error_policy=ERROR_POLICY_MARK_FAILED)
        raw = self._make_failed_result(metric)
        result = _apply_error_policy(raw, metric)
        assert result.status == RESULT_FAILED

    def test_fallback_with_value(self):
        metric = make_metric(error_policy=ERROR_POLICY_FALLBACK, fallback_value="0")
        raw = self._make_failed_result(metric)
        result = _apply_error_policy(raw, metric)
        assert result.status == RESULT_FALLBACK
        assert result.value == "0"

    def test_fallback_no_value_degrades_to_skip(self):
        metric = make_metric(error_policy=ERROR_POLICY_FALLBACK, fallback_value=None)
        raw = self._make_failed_result(metric)
        result = _apply_error_policy(raw, metric)
        assert result.status == RESULT_SKIPPED

    def test_timeout_with_skip(self):
        metric = make_metric(error_policy=ERROR_POLICY_SKIP)
        raw = MetricResult.make_timeout(metric)
        result = _apply_error_policy(raw, metric)
        assert result.status == RESULT_SKIPPED

    def test_ok_result_not_modified(self):
        metric = make_metric(error_policy=ERROR_POLICY_SKIP)
        ok_result = MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value="42",
            value_type="float",
            timestamp=int(time.time()),
            collector=metric.collector,
            delivery=metric.delivery,
            status=RESULT_OK,
        )
        result = _apply_error_policy(ok_result, metric)
        assert result.status == RESULT_OK
        assert result.value == "42"


# ---------------------------------------------------------------------------
# update_summary
# ---------------------------------------------------------------------------

class TestUpdateSummary:
    def test_counts_ok(self):
        from conftest import make_result
        summary = RunSummary()
        results = [make_result(status=RESULT_OK)] * 3
        update_summary(summary, results, [])
        assert summary.collected_ok == 3

    def test_counts_failed(self):
        from conftest import make_result
        summary = RunSummary()
        results = [make_result(status=RESULT_FAILED, value=None)] * 2
        update_summary(summary, results, [])
        assert summary.collected_failed == 2

    def test_counts_timeout(self):
        from conftest import make_result
        summary = RunSummary()
        results = [make_result(status=RESULT_TIMEOUT, value=None)]
        update_summary(summary, [], results)
        assert summary.collected_timeout == 1

    def test_counts_skipped(self):
        from conftest import make_result
        summary = RunSummary()
        results = [make_result(status=RESULT_SKIPPED, value=None)] * 4
        update_summary(summary, results, [])
        assert summary.skipped == 4

    def test_mixed_counts(self):
        from conftest import make_result
        summary = RunSummary()
        immediate = [
            make_result(key="k1", status=RESULT_OK, value="1"),
            make_result(key="k2", status=RESULT_FAILED, value=None),
        ]
        batch = [
            make_result(key="k3", status=RESULT_TIMEOUT, value=None),
            make_result(key="k4", status=RESULT_SKIPPED, value=None),
            make_result(key="k5", status=RESULT_OK, value="5"),
        ]
        update_summary(summary, immediate, batch)
        assert summary.collected_ok == 2
        assert summary.collected_failed == 1
        assert summary.collected_timeout == 1
        assert summary.skipped == 1


# ---------------------------------------------------------------------------
# run_all_collectors (integration with mock collectors)
# ---------------------------------------------------------------------------

class TestRunAllCollectors:
    def _make_config(self, max_concurrency=8, window=60.0, proc_root="/tmp"):
        cfg = ClientConfig()
        cfg.runtime.max_concurrency = max_concurrency
        cfg.runtime.proc_root = proc_root
        cfg.batching.batch_collection_window_seconds = window
        cfg.state.directory = "/tmp/state"
        return cfg

    async def test_single_batch_metric(self):
        """A batch collector returns its result in batch_results."""
        metric = make_metric(
            id="cpu1", collector="cpu", key="host.cpu",
            delivery=DELIVERY_BATCH,
            params={"mode": "uptime"},  # uptime doesn't need real /proc
        )
        cfg = self._make_config()
        # Run with real uptime — needs /proc/uptime (available on Linux/macOS via /proc in Docker)
        # On macOS /proc/uptime doesn't exist, so let's just test with a mock
        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = AsyncMock(return_value=MetricResult(
                metric_id="cpu1", key="host.cpu", value="99.0",
                value_type="float", timestamp=int(time.time()),
                collector="cpu", delivery=DELIVERY_BATCH, status=RESULT_OK,
            ))
            mock_get.return_value = mock_cls
            immediate, batch = await run_all_collectors([metric], cfg)
        assert len(batch) == 1
        assert batch[0].value == "99.0"

    async def test_single_immediate_metric(self):
        metric = make_metric(
            id="svc1", collector="service", key="svc.nginx",
            delivery=DELIVERY_IMMEDIATE,
        )
        cfg = self._make_config()
        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = AsyncMock(return_value=MetricResult(
                metric_id="svc1", key="svc.nginx", value="1",
                value_type="int", timestamp=int(time.time()),
                collector="service", delivery=DELIVERY_IMMEDIATE, status=RESULT_OK,
            ))
            mock_get.return_value = mock_cls
            immediate, batch = await run_all_collectors([metric], cfg)
        assert len(immediate) == 1
        assert batch == []

    async def test_collector_exception_skipped(self):
        metric = make_metric(
            id="bad", collector="cpu", key="host.broken",
            error_policy=ERROR_POLICY_SKIP,
        )
        cfg = self._make_config()
        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = AsyncMock(side_effect=RuntimeError("disk fail"))
            mock_get.return_value = mock_cls
            _, batch = await run_all_collectors([metric], cfg)
        assert len(batch) == 1
        assert batch[0].status == RESULT_SKIPPED

    async def test_collector_timeout_applied(self):
        metric = make_metric(
            id="slow", collector="cpu", key="host.slow",
            timeout_seconds=0.05,
            error_policy=ERROR_POLICY_SKIP,
        )
        cfg = self._make_config()

        async def slow_collect(m):
            await asyncio.sleep(10)

        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = slow_collect
            mock_get.return_value = mock_cls
            _, batch = await run_all_collectors([metric], cfg)
        assert batch[0].status == RESULT_SKIPPED

    async def test_probe_list_result_flattened(self):
        """Probe returns list[MetricResult] — runner must flatten it."""
        metric = make_metric(
            id="probe1", collector="probe", key="probe.test",
            delivery=DELIVERY_IMMEDIATE,
        )
        cfg = self._make_config()
        sub_results = [
            MetricResult(
                metric_id="probe1", key="probe.test",
                value="1", value_type="int", timestamp=int(time.time()),
                collector="probe", delivery=DELIVERY_IMMEDIATE, status=RESULT_OK,
            ),
            MetricResult(
                metric_id="probe1", key="probe.test.response_time_ms",
                value="42", value_type="float", timestamp=int(time.time()),
                collector="probe", delivery=DELIVERY_IMMEDIATE, status=RESULT_OK,
            ),
        ]
        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = AsyncMock(return_value=sub_results)
            mock_get.return_value = mock_cls
            immediate, _ = await run_all_collectors([metric], cfg)
        assert len(immediate) == 2

    async def test_empty_metrics_list(self):
        cfg = self._make_config()
        immediate, batch = await run_all_collectors([], cfg)
        assert immediate == []
        assert batch == []

    async def test_concurrency_limit_respected(self):
        """With max_concurrency=1 all tasks still complete."""
        metrics = [
            make_metric(id=f"m{i}", key=f"k{i}", delivery=DELIVERY_BATCH)
            for i in range(5)
        ]
        cfg = self._make_config(max_concurrency=1)
        call_order = []

        async def ordered_collect(m):
            call_order.append(m.id)
            return MetricResult(
                metric_id=m.id, key=m.key, value="1",
                value_type="float", timestamp=int(time.time()),
                collector="cpu", delivery=DELIVERY_BATCH, status=RESULT_OK,
            )

        with patch("zabbig_client.runner.get_collector") as mock_get:
            mock_cls = MagicMock()  # class instantiation is sync
            mock_cls.return_value.collect = ordered_collect
            mock_get.return_value = mock_cls
            _, batch = await run_all_collectors(metrics, cfg)
        assert len(batch) == 5
