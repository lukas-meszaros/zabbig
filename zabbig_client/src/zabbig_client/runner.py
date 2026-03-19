"""
runner.py — Async collector runner.

Design:
- All enabled metrics are split by delivery: immediate vs batch.
- Immediate collectors start first; results are available for early flushing.
- Batch collectors run concurrently, bounded by batch_collection_window_seconds.
- A semaphore limits simultaneous in-flight collectors to max_concurrency.
- Each collector has its own asyncio.wait_for timeout.
- Unfinished batch tasks at window expiry are cancelled and recorded as timed-out.
- error_policy (skip / fallback / mark_failed) is applied after collection.
- One failed collector never raises; it produces a failed MetricResult instead.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import List, Tuple

from .collector_registry import get_collector
from .models import (
    RESULT_FALLBACK,
    RESULT_FAILED,
    RESULT_SKIPPED,
    RESULT_TIMEOUT,
    ERROR_POLICY_FALLBACK,
    ERROR_POLICY_MARK_FAILED,
    ERROR_POLICY_SKIP,
    ClientConfig,
    MetricDef,
    MetricResult,
    RunSummary,
)

log = logging.getLogger(__name__)


async def run_all_collectors(
    metrics: List[MetricDef],
    config: ClientConfig,
) -> Tuple[List[MetricResult], List[MetricResult]]:
    """
    Run all collectors for the given metrics.

    Returns:
        (immediate_results, batch_results)
        Both lists contain fully resolved MetricResult objects (including
        error-policy application). Only sendable results need forwarding.
    """
    immediate_metrics = [m for m in metrics if m.delivery == "immediate"]
    batch_metrics = [m for m in metrics if m.delivery == "batch"]

    semaphore = asyncio.Semaphore(config.runtime.max_concurrency)

    proc_root = config.runtime.proc_root
    state_dir = config.state.directory

    async def run_one(metric: MetricDef) -> MetricResult:
        async with semaphore:
            # Inject the global proc_root into params if not overridden per-metric.
            if "proc_root" not in metric.params:
                metric = dataclasses.replace(
                    metric, params={**metric.params, "proc_root": proc_root}
                )
            # Inject state_dir for log collector from client.yaml state.directory.
            if metric.collector == "log" and "state_dir" not in metric.params:
                metric = dataclasses.replace(
                    metric, params={**metric.params, "state_dir": state_dir}
                )
            collector_cls = get_collector(metric.collector)
            collector = collector_cls()
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    collector.collect(metric),
                    timeout=metric.timeout_seconds,
                )
                result.duration_ms = (time.monotonic() - t0) * 1000
                log.debug(
                    "Collected %s = %s  (%.1fms)",
                    metric.key, result.value, result.duration_ms
                )
                return result
            except asyncio.TimeoutError:
                duration = (time.monotonic() - t0) * 1000
                log.warning(
                    "Collector TIMEOUT for metric '%s' (key=%s, %.0fms)",
                    metric.id, metric.key, duration
                )
                raw = MetricResult.make_timeout(metric, duration)
                return _apply_error_policy(raw, metric)
            except Exception as exc:
                duration = (time.monotonic() - t0) * 1000
                log.warning(
                    "Collector ERROR for metric '%s' (key=%s): %s (%.0fms)",
                    metric.id, metric.key, exc, duration
                )
                raw = MetricResult.make_error(metric, exc, duration)
                return _apply_error_policy(raw, metric)

    # Launch all tasks immediately (they queue behind the semaphore internally)
    immediate_tasks = [asyncio.create_task(run_one(m)) for m in immediate_metrics]
    batch_tasks = [asyncio.create_task(run_one(m)) for m in batch_metrics]

    # --- Immediate results: wait with no extra window (individual timeouts apply) ---
    immediate_results: List[MetricResult] = []
    if immediate_tasks:
        gathered = await asyncio.gather(*immediate_tasks, return_exceptions=False)
        immediate_results.extend(gathered)

    # --- Batch results: bounded by batch_collection_window_seconds ---
    batch_results: List[MetricResult] = []
    if batch_tasks:
        window = config.batching.batch_collection_window_seconds
        try:
            gathered = await asyncio.wait_for(
                asyncio.gather(*batch_tasks, return_exceptions=False),
                timeout=window,
            )
            batch_results.extend(gathered)
        except asyncio.TimeoutError:
            log.warning(
                "Batch collection window (%.0fs) expired — cancelling unfinished tasks",
                window,
            )
            for metric, task in zip(batch_metrics, batch_tasks):
                if task.done():
                    try:
                        batch_results.append(task.result())
                    except Exception as exc:
                        raw = MetricResult.make_error(metric, exc)
                        batch_results.append(_apply_error_policy(raw, metric))
                else:
                    task.cancel()
                    log.warning(
                        "Cancelled batch metric '%s' (key=%s) — window exceeded",
                        metric.id, metric.key,
                    )
                    raw = MetricResult.make_timeout(metric, window * 1000)
                    batch_results.append(_apply_error_policy(raw, metric))

    return immediate_results, batch_results


def update_summary(
    summary: RunSummary,
    immediate_results: List[MetricResult],
    batch_results: List[MetricResult],
) -> None:
    """Populate RunSummary counts from collector results."""
    for result in immediate_results + batch_results:
        if result.status == RESULT_FAILED:
            summary.collected_failed += 1
        elif result.status == RESULT_TIMEOUT:
            summary.collected_timeout += 1
        elif result.status == RESULT_SKIPPED:
            summary.skipped += 1
        else:
            summary.collected_ok += 1


# ---------------------------------------------------------------------------
# Error policy application
# ---------------------------------------------------------------------------

def _apply_error_policy(raw_result: MetricResult, metric: MetricDef) -> MetricResult:
    """
    Given a failed/timeout result and the metric definition, apply error_policy:
      skip        → mark status=skipped, value=None (not sent)
      fallback    → set value=fallback_value, status=fallback (sent if value set)
      mark_failed → keep status=failed, value=None (not sent, but logged)
    """
    if raw_result.status not in (RESULT_FAILED, RESULT_TIMEOUT):
        return raw_result  # already OK or fallback

    policy = metric.error_policy

    if policy == ERROR_POLICY_SKIP:
        raw_result.status = RESULT_SKIPPED
        raw_result.value = None
        return raw_result

    if policy == ERROR_POLICY_FALLBACK:
        if metric.fallback_value is not None:
            return MetricResult.make_fallback(metric, raw_result.duration_ms)
        # No fallback value defined — degrade to skip
        log.warning(
            "error_policy=fallback for metric '%s' but no fallback_value defined; skipping",
            metric.id,
        )
        raw_result.status = RESULT_SKIPPED
        raw_result.value = None
        return raw_result

    # mark_failed — keep as-is (not sendable, but logged)
    return raw_result
