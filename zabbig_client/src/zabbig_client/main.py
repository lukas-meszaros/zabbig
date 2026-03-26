"""
main.py — Central orchestrator for the zabbig monitoring client.

Flow:
  1. Parse CLI args
  2. Load and validate client.yaml + metrics.yaml
  3. Acquire run lock (cron safety)
  4. Skip disabled metrics
  5. Run collectors asynchronously (immediate first, then batch within window)
  6. Route results to immediate / batch send queues
  7. Send immediate metrics (if flush_immediate_separately=true)
  8. Send batch metrics
  9. Emit self-monitoring metrics (if enabled)
  10. Save run state (if enabled)
  11. Log summary and exit with appropriate code
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import List

from .config_loader import ConfigError, load_client_config, load_metrics_config
from .locking import LockError, RunLock
from .logging_setup import setup_logging
from .models import ClientConfig, MetricDef, MetricsConfig, RunSummary
from .result_router import route
from .runner import run_all_collectors, update_summary
from .sender_manager import SenderManager
from .state_manager import save_state

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    client_config_path: str,
    metrics_config_path: str,
    dry_run: bool = False,
    log_level_override: str | None = None,
) -> int:
    """
    Run the full collection-and-send cycle.

    Returns an exit code:
      0 — success (all metrics collected and sent)
      1 — partial failure (some collectors or sends failed, but run completed)
      2 — fatal error (config error, lock conflict, overall timeout)
    """
    # --- Load config ---
    try:
        client_config = load_client_config(client_config_path)
    except (ConfigError, FileNotFoundError, Exception) as exc:
        # Logging not set up yet — print to stderr
        print(f"FATAL: Cannot load client config '{client_config_path}': {exc}", file=sys.stderr)
        return 2

    # Override dry_run from CLI flag
    if dry_run:
        client_config.runtime.dry_run = True

    # Override log level from CLI flag
    if log_level_override:
        client_config.logging.level = log_level_override.upper()

    # --- Set up logging now that we have the config ---
    setup_logging(client_config.logging)

    log.info("=" * 60)
    log.info("zabbig client starting")
    log.info("  servers: %s (port %d)", ", ".join(client_config.zabbix.server_hosts), client_config.zabbix.server_port)
    log.info("  host   : %s", client_config.zabbix.host_name)
    log.info("  dry_run: %s", client_config.runtime.dry_run)
    log.info("  configs: %s | %s", client_config_path, metrics_config_path)

    # --- Load metrics config ---
    try:
        metrics_config = load_metrics_config(
            metrics_config_path,
            strict=client_config.features.strict_config_validation,
        )
    except Exception as exc:
        log.error("Cannot load metrics config '%s': %s", metrics_config_path, exc)
        _send_fatal_failure(client_config)
        return 2

    # --- Filter enabled metrics ---
    all_metrics = metrics_config.metrics
    enabled_metrics: List[MetricDef] = [
        m for m in all_metrics if m.enabled
    ] if client_config.features.skip_disabled_metrics else all_metrics

    log.info(
        "Metrics: %d configured, %d enabled",
        len(all_metrics), len(enabled_metrics),
    )

    if not enabled_metrics:
        log.warning("No metrics are enabled. Nothing to do.")
        return 0

    # --- Acquire run lock ---
    summary = RunSummary(
        total_configured=len(all_metrics),
        enabled=len(enabled_metrics),
    )

    try:
        with RunLock(client_config.runtime.lock_file):
            exit_code = asyncio.run(
                _run_with_timeout(client_config, enabled_metrics, summary)
            )
    except LockError as exc:
        log.error("Cannot acquire run lock: %s", exc)
        return 2

    save_state(client_config, summary)
    _log_summary(summary)
    return exit_code


# ---------------------------------------------------------------------------
# Fatal-failure notifier
# ---------------------------------------------------------------------------

def _send_fatal_failure(config: ClientConfig) -> None:
    """
    Send zabbig.client.run.success=0 to Zabbix when a fatal error prevents the
    normal run loop from executing (e.g. bad metrics.yaml syntax).

    Only fires when self_monitoring_metrics is enabled and not in dry_run mode.
    Never raises — a notification failure must not mask the original error.
    """
    if not config.features.self_monitoring_metrics:
        return
    if config.runtime.dry_run:
        log.debug("[dry-run] Skipping fatal failure notification to Zabbix")
        return
    try:
        summary = RunSummary(success=False)
        sender = SenderManager(config)
        asyncio.run(sender.send_self_metrics(summary, config.zabbix.host_name))
        log.info("Sent fatal failure notification to Zabbix (zabbig.client.run.success=0)")
    except Exception as notify_exc:
        log.warning("Could not send fatal failure notification to Zabbix: %s", notify_exc)


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------

async def _run_with_timeout(
    config: ClientConfig,
    metrics: List[MetricDef],
    summary: RunSummary,
) -> int:
    """Wrapper that enforces overall_timeout_seconds over the entire async run."""
    try:
        return await asyncio.wait_for(
            _run_async(config, metrics, summary),
            timeout=config.runtime.overall_timeout_seconds,
        )
    except asyncio.TimeoutError:
        log.error(
            "Overall timeout (%.0fs) reached — aborting run",
            config.runtime.overall_timeout_seconds,
        )
        summary.success = False
        return 2


async def _run_async(
    config: ClientConfig,
    metrics: List[MetricDef],
    summary: RunSummary,
) -> int:
    t_start = time.monotonic()
    exit_code = 0

    # --- Run collectors ---
    log.info(
        "Running %d collector(s) — batch window=%.0fs, max_concurrency=%d",
        len(metrics),
        config.batching.batch_collection_window_seconds,
        config.runtime.max_concurrency,
    )

    immediate_raw, batch_raw = await run_all_collectors(metrics, config)
    update_summary(summary, immediate_raw, batch_raw)

    # --- Route to send queues ---
    batch_to_send, immediate_to_send = route(immediate_raw + batch_raw)
    # re-split by actual delivery flag set on results
    immediate_to_send_only = [r for r in immediate_to_send if True]  # already filtered
    batch_to_send_only = batch_to_send

    log.info(
        "Routing: %d batch metric(s) to send, %d immediate metric(s) to send",
        len(batch_to_send_only), len(immediate_to_send_only),
    )

    # Log per-metric host_name overrides
    overrides = [r for r in batch_to_send_only + immediate_to_send_only if r.host_name]
    if overrides:
        log.info("Host overrides: %d metric(s) sent under a different host name:", len(overrides))
        for r in overrides:
            log.info("  key=%-40s  host=%s", r.key, r.host_name)

    # --- Send ---
    sender = SenderManager(config)

    if config.batching.flush_immediate_separately and immediate_to_send_only:
        log.info("Sending %d immediate metric(s) ...", len(immediate_to_send_only))
        await sender.send_immediate(immediate_to_send_only, summary)

    if batch_to_send_only:
        log.info("Sending %d batch metric(s) ...", len(batch_to_send_only))
        await sender.send_batch(batch_to_send_only, summary)

    # If flush_immediate_separately=false, immediate metrics are included in batch send
    if not config.batching.flush_immediate_separately and immediate_to_send_only:
        log.info("Sending %d immediate metric(s) with batch ...", len(immediate_to_send_only))
        await sender.send_batch(immediate_to_send_only, summary)

    # --- Self-monitoring metrics ---
    if config.features.self_monitoring_metrics:
        summary.duration_ms = (time.monotonic() - t_start) * 1000
        log.debug("Sending self-monitoring metrics ...")
        await sender.send_self_metrics(summary, config.zabbix.host_name)

    summary.duration_ms = (time.monotonic() - t_start) * 1000
    summary.success = (
        summary.collected_failed == 0
        and summary.collected_timeout == 0
        and summary.sender_failures == 0
    )

    if summary.collected_failed > 0 or summary.collected_timeout > 0:
        exit_code = 1
    if summary.sender_failures > 0:
        exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# Summary logging
# ---------------------------------------------------------------------------

def _log_summary(summary: RunSummary) -> None:
    log.info("-" * 60)
    log.info("Run summary:")
    log.info("  Total configured  : %d", summary.total_configured)
    log.info("  Enabled           : %d", summary.enabled)
    log.info("  Collected OK      : %d", summary.collected_ok)
    log.info("  Failed            : %d", summary.collected_failed)
    log.info("  Timed out         : %d", summary.collected_timeout)
    log.info("  Skipped           : %d", summary.skipped)
    log.info("  Sent (batch)      : %d", summary.sent_batch)
    log.info("  Sent (immediate)  : %d", summary.sent_immediate)
    log.info("  Sender failures   : %d", summary.sender_failures)
    log.info("  Duration          : %.0fms", summary.duration_ms)
    log.info("  Success           : %s", summary.success)
    log.info("=" * 60)
