"""
base.py — Abstract base class for all collectors.

Every collector must implement collect(metric) and return a MetricResult.
Collectors should NOT catch their own exceptions — the runner does that.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import MetricDef, MetricResult


class BaseCollector(ABC):
    """
    Minimal interface for a metric collector.

    Implementations should be stateless — a new instance is created per
    metric collection invocation.
    """

    @abstractmethod
    async def collect(self, metric: MetricDef) -> MetricResult:
        """
        Collect the metric described by `metric` and return a MetricResult.

        Raise any exception on failure; the runner handles error policy.
        Do not swallow exceptions — let them propagate.
        """
        ...
