"""
result_router.py — Routes MetricResult objects to batch or immediate send queues.

Routing is based on MetricResult.delivery, not on whether the result is sendable.
Only sendable results (status ok or fallback with a value) are forwarded.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from .models import (
    DELIVERY_BATCH,
    DELIVERY_IMMEDIATE,
    MetricResult,
    RESULT_SKIPPED,
    RESULT_FAILED,
    RESULT_TIMEOUT,
)

log = logging.getLogger(__name__)


def route(
    results: List[MetricResult],
) -> Tuple[List[MetricResult], List[MetricResult]]:
    """
    Split a flat list of results into (batch_sendable, immediate_sendable).

    Non-sendable results (skipped, failed, no value) are dropped here
    after a debug log entry.
    """
    batch: List[MetricResult] = []
    immediate: List[MetricResult] = []

    for r in results:
        if not r.is_sendable:
            if r.status not in (RESULT_SKIPPED,):
                log.debug(
                    "Dropping non-sendable result for key=%s status=%s error=%s",
                    r.key, r.status, r.error,
                )
            continue

        if r.delivery == DELIVERY_IMMEDIATE:
            immediate.append(r)
        else:
            batch.append(r)

    return batch, immediate
