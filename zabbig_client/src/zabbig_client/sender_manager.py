"""
sender_manager.py — Wraps zabbix_utils.Sender for batch and immediate delivery.

Key behaviours:
- Uses chunk_size=1 when sending so response.details maps directly to items.
  (chunk_size could be bumped to batch_send_max_size for large batches, but 1
   gives exact per-item failure attribution at negligible cost for typical volumes.)
- Each send call has its own asyncio.to_thread dispatch, keeping the event loop free.
- A single Sender instance is reused; the underlying TCP connection is opened per send.
- In dry_run mode nothing is sent; a synthetic success response is returned.
- Each immediate send failure is isolated — it never raises, always returns counts.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import os
import time
from typing import List

from .models import ClientConfig, MetricResult, RunSummary

log = logging.getLogger(__name__)


def _import_sender():
    """Import Sender and ItemValue from the vendored zabbix_utils."""
    # src/ is already on sys.path — direct import
    from zabbix_utils import Sender, ItemValue  # type: ignore
    return Sender, ItemValue


class SenderManager:
    """Handles Zabbix trapper delivery for both batch and immediate results."""

    def __init__(self, config: ClientConfig) -> None:
        self.config = config
        Sender, ItemValue = _import_sender()
        self._Sender = Sender
        self._ItemValue = ItemValue
        self._sender = Sender(
            server=config.zabbix.server_host,
            port=config.zabbix.server_port,
            chunk_size=1,  # enables per-item failure attribution via response.details
        )

    async def send_batch(self, results: List[MetricResult], summary: RunSummary) -> None:
        """Send all batch-mode results in one call (chunked by batch_send_max_size)."""
        if not results:
            return
        max_size = self.config.batching.batch_send_max_size
        chunks = [results[i:i + max_size] for i in range(0, len(results), max_size)]
        for chunk in chunks:
            sent = await self._send(chunk, label="batch")
            summary.sent_batch += sent[0]
            summary.sender_failures += sent[1]

    async def send_immediate(self, results: List[MetricResult], summary: RunSummary) -> None:
        """Send immediate-mode results; each failure is isolated."""
        if not results:
            return
        # Send all immediate metrics together in one call for efficiency,
        # but isolate failures per-item via response.details
        sent = await self._send(results, label="immediate")
        summary.sent_immediate += sent[0]
        summary.sender_failures += sent[1]

    async def send_self_metrics(self, run_summary: RunSummary, host_name: str) -> None:
        """Emit client self-monitoring metrics if enabled."""
        now = int(time.time())
        items = [
            (f"zabbig.client.run.success",     "1" if run_summary.success else "0"),
            (f"zabbig.client.collectors.total", str(run_summary.enabled)),
            (f"zabbig.client.collectors.failed", str(run_summary.collected_failed + run_summary.collected_timeout)),
            (f"zabbig.client.duration_ms",      str(int(run_summary.duration_ms))),
            (f"zabbig.client.metrics.sent",     str(run_summary.sent_batch + run_summary.sent_immediate)),
        ]
        self_results = [
            MetricResult(
                metric_id=f"self_{key.replace('.', '_')}",
                key=key,
                value=value,
                value_type="float",
                timestamp=now,
                collector="self",
                delivery="batch",
                status="ok",
            )
            for key, value in items
        ]
        await self._send(self_results, label="self-metrics")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send(
        self, results: List[MetricResult], label: str
    ) -> tuple[int, int]:
        """
        Dispatch the send to the thread pool.
        Returns (sent_count, failure_count).
        """
        if self.config.runtime.dry_run:
            log.info("[dry-run] Would send %d %s metric(s):", len(results), label)
            for r in results:
                log.info("[dry-run]   key=%-40s  value=%s", r.key, r.value)
            return len(results), 0

        try:
            sent, failed = await asyncio.wait_for(
                asyncio.to_thread(self._do_send, results, label),
                timeout=self.config.zabbix.send_timeout_seconds,
            )
            return sent, failed
        except asyncio.TimeoutError:
            log.error(
                "Send timeout after %.0fs for %d %s metric(s)",
                self.config.zabbix.send_timeout_seconds, len(results), label,
            )
            return 0, len(results)
        except Exception as exc:
            log.error("Send error for %s metrics: %s", label, exc)
            return 0, len(results)

    def _do_send(self, results: List[MetricResult], label: str) -> tuple[int, int]:
        """Blocking Zabbix send — runs in thread pool."""
        host_name = self.config.zabbix.host_name
        items = [
            self._ItemValue(host_name, r.key, r.value)
            for r in results
        ]

        response = self._sender.send(items)

        if response.failed == 0:
            log.info(
                "Send OK [%s]: processed=%d total=%d (%.3fs)",
                label, response.processed, response.total, float(response.time),
            )
            return response.processed, 0

        # At least one item failed — identify which ones using response.details
        log.warning(
            "Send PARTIAL [%s]: processed=%d failed=%d total=%d",
            label, response.processed, response.failed, response.total,
        )
        if response.details:
            for node, chunks in response.details.items():
                for resp in chunks:
                    item = results[resp.chunk - 1]
                    if resp.failed:
                        log.warning(
                            "  REJECTED  key=%-40s  value=%s  (node=%s)",
                            item.key, item.value, node,
                        )
        return response.processed, response.failed
