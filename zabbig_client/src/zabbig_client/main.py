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

from .collector_registry import load_collectors_for
from .config_loader import ConfigError, load_client_config, load_metrics_config, validate_metrics_file
from .locking import LockError, RunLock
from .logging_setup import setup_logging
from .models import ClientConfig, MetricDef, MetricsConfig, RunSummary
from .result_router import route
from .runner import run_all_collectors, update_summary
from .scheduler import should_execute, today_str
from .sender_manager import SenderManager
from .state_manager import save_state, load_schedule_state, save_schedule_state

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validator entry point  (--validate flag)
# ---------------------------------------------------------------------------

def validate(metrics_config_path: str) -> int:
    """
    Validate a metrics.yaml file and print a human-readable report to stdout.

    Unlike the normal run path this function:
      - requires no client.yaml
      - acquires no run lock
      - runs no collectors
      - makes no Zabbix connection
      - always completes — all issues are collected before reporting

    Returns:
      0 — file is valid (no issues found)
      1 — file parsed but issues were found
      2 — file could not be read (not found or YAML syntax error)
    """
    print(f"Validating: {metrics_config_path}")

    try:
        issues, metrics = validate_metrics_file(metrics_config_path)
    except FileNotFoundError:
        print(f"ERROR: File not found: {metrics_config_path}", file=sys.stderr)
        return 2

    # Print the list of successfully parsed metrics.
    if metrics:
        print(f"\nMetrics parsed ({len(metrics)}):")
        id_w = max(len(m.id) for m in metrics)
        col_w = max(len(m.collector) for m in metrics)
        for m in metrics:
            print(f"  {m.id:<{id_w}}  {m.collector:<{col_w}}  {m.key}")
    else:
        print("\n  (no metrics were successfully parsed)")

    # Print issues if any.
    if issues:
        print(f"\nIssues found ({len(issues)}):")
        for i, issue in enumerate(issues, 1):
            print(f"  [{i}] {issue}")
        print(f"\nValidation complete: {len(metrics)} metric(s) parsed, {len(issues)} issue(s) found.")
        return 1

    print(f"\nValidation passed: {len(metrics)} metric(s), no issues found.")
    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    client_config_path: str,
    metrics_config_path: str,
    databases_config_path: str | None = None,
    dry_run: bool = False,
    log_level_override: str | None = None,
    output_path: str | None = None,
    output_format: str = "json",
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

    # --- Load databases config (optional) ---
    db_registry: dict = {}
    if databases_config_path and os.path.isfile(databases_config_path):
        try:
            from .db_loader import DatabaseConfigError, load_databases_config  # noqa: PLC0415
            db_registry = load_databases_config(
                databases_config_path,
                strict=client_config.features.strict_config_validation,
                strict_passwords=False,  # warn rather than abort on plain-text passwords
            )
            log.info("  databases: %s (%d entries)", databases_config_path, len(db_registry))
        except (DatabaseConfigError, FileNotFoundError) as exc:
            log.error(
                "Cannot load databases config '%s': %s", databases_config_path, exc
            )
            _send_fatal_failure(client_config)
            return 2
    elif databases_config_path:
        log.warning(
            "databases config path '%s' specified but file not found — "
            "database metrics will fail",
            databases_config_path,
        )

    # --- Filter enabled metrics ---
    all_metrics = metrics_config.metrics
    enabled_metrics: List[MetricDef] = [
        m for m in all_metrics if m.enabled
    ] if client_config.features.skip_disabled_metrics else all_metrics

    # Inject _db_registry into params for all database-type metrics so the
    # collector can look up connection details at run time.
    # Also inject a shared mutable _db_conn_cache dict so connections are
    # reused across multiple database metrics in the same run.
    if db_registry:
        import dataclasses as _dc
        db_conn_cache: dict = {}
        enabled_metrics = [
            _dc.replace(m, params={**m.params, "_db_registry": db_registry, "_db_conn_cache": db_conn_cache})
            if m.collector == "database"
            else m
            for m in enabled_metrics
        ]

    log.info(
        "Metrics: %d configured, %d enabled",
        len(all_metrics), len(enabled_metrics),
    )

    if not enabled_metrics:
        log.warning("No metrics are enabled. Nothing to do.")
        return 0

    # --- Acquire run lock and execute ---
    summary = RunSummary(
        total_configured=len(all_metrics),
        enabled=len(enabled_metrics),
    )

    try:
        with RunLock(client_config.runtime.lock_file):
            # ------------------------------------------------------------------
            # Schedule filtering: compute today's run counter and decide which
            # metrics are eligible for this invocation.
            # ------------------------------------------------------------------
            schedule_state = load_schedule_state(client_config)
            today = today_str()
            if schedule_state.get("date") != today:
                # New calendar day — reset all counters.
                schedule_state = {"date": today, "run_counter": 0, "metrics": {}}

            run_counter: int = schedule_state.get("run_counter", 0) + 1
            schedule_state["run_counter"] = run_counter
            metric_exec_counts: dict = schedule_state.get("metrics", {})

            scheduled_metrics: List[MetricDef] = []
            for m in enabled_metrics:
                exec_count = metric_exec_counts.get(m.id, {}).get("execution_count", 0)
                can_run, reason = should_execute(
                    m, run_counter, exec_count,
                    dry_run=client_config.runtime.dry_run,
                )
                if can_run:
                    scheduled_metrics.append(m)
                else:
                    log.debug("[SCHED-SKIP] key=%-40s  reason=%s", m.key, reason)
                    summary.schedule_skipped += 1

            if summary.schedule_skipped:
                log.info(
                    "Schedule: %d of %d enabled metric(s) skipped for this run "
                    "(run_counter=%d)",
                    summary.schedule_skipped, len(enabled_metrics), run_counter,
                )

            if not scheduled_metrics:
                log.info("No metrics scheduled for run #%d — nothing to collect.", run_counter)
                if not client_config.runtime.dry_run:
                    save_schedule_state(client_config, schedule_state)
                save_state(client_config, summary)
                _log_summary(summary)
                return 0

            # Import only the collector modules that are actually needed for
            # this run.  Heavy dependencies (requests, pg8000, ssl) are only
            # pulled in when a metric that requires them is scheduled.
            load_collectors_for({m.collector for m in scheduled_metrics})

            exit_code = asyncio.run(
                _run_with_timeout(client_config, scheduled_metrics, summary, output_path, output_format)
            )

            # Update per-metric execution counts (skip in dry-run so state
            # files are not mutated by test/preview invocations).
            if not client_config.runtime.dry_run:
                for m in scheduled_metrics:
                    entry = metric_exec_counts.setdefault(m.id, {"execution_count": 0})
                    entry["execution_count"] += 1
                schedule_state["metrics"] = metric_exec_counts
                save_schedule_state(client_config, schedule_state)

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
    output_path: str | None = None,
    output_format: str = "json",
) -> int:
    """Wrapper that enforces overall_timeout_seconds over the entire async run."""
    try:
        return await asyncio.wait_for(
            _run_async(config, metrics, summary, output_path, output_format),
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
    output_path: str | None = None,
    output_format: str = "json",
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

    # --- Write output file if requested ---
    if output_path:
        all_results = immediate_raw + batch_raw
        _write_output(all_results, output_path, output_format)

    # --- Close cached DB connections now that all collectors have finished ---
    _close_db_conn_caches(metrics)

    # --- Send ---
    sender = SenderManager(config)

    if config.batching.flush_immediate_separately and immediate_to_send_only:
        log.info("Sending %d immediate metric(s) ...", len(immediate_to_send_only))

    if config.batching.flush_immediate_separately and immediate_to_send_only and batch_to_send_only:
        # Both queues have data — send them in parallel
        log.info("Sending %d batch metric(s) in parallel with immediate ...", len(batch_to_send_only))
        await asyncio.gather(
            sender.send_immediate(immediate_to_send_only, summary),
            sender.send_batch(batch_to_send_only, summary),
        )
    else:
        if config.batching.flush_immediate_separately and immediate_to_send_only:
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
# Output helpers
# ---------------------------------------------------------------------------

def _write_output(results: List, path: str, fmt: str) -> None:
    """Write collected MetricResult objects to a file in the requested format."""
    import csv as _csv
    import dataclasses as _dc
    import io
    import json as _json

    sendable = [r for r in results if r.is_sendable]

    try:
        if fmt == "json":
            rows = [_dc.asdict(r) for r in sendable]
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(rows, fh, indent=2)
        elif fmt == "csv":
            if not sendable:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("")
                return
            fields = list(_dc.fields(sendable[0]))
            with open(path, "w", encoding="utf-8", newline="") as fh:
                writer = _csv.DictWriter(fh, fieldnames=[f.name for f in fields])
                writer.writeheader()
                for r in sendable:
                    writer.writerow(_dc.asdict(r))
        elif fmt == "table":
            if not sendable:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("(no results)\n")
                return
            col_key = max(len(r.key) for r in sendable)
            col_val = max(len(str(r.value)) for r in sendable)
            col_sta = max(len(r.status) for r in sendable)
            header = f"{'key':<{col_key}}  {'value':<{col_val}}  {'status':<{col_sta}}  collector"
            sep = "-" * len(header)
            buf = io.StringIO()
            buf.write(header + "\n")
            buf.write(sep + "\n")
            for r in sendable:
                buf.write(
                    f"{r.key:<{col_key}}  {str(r.value):<{col_val}}  "
                    f"{r.status:<{col_sta}}  {r.collector}\n"
                )
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(buf.getvalue())
        log.info("Output written to '%s' (format=%s, %d metrics)", path, fmt, len(sendable))
    except OSError as exc:
        log.error("Could not write output to '%s': %s", path, exc)


def _close_db_conn_caches(metrics: List) -> None:
    """Close all cached database connections injected via _db_conn_cache."""
    seen_caches: set[int] = set()
    for m in metrics:
        if m.collector != "database":
            continue
        cache = m.params.get("_db_conn_cache")
        if cache is None or id(cache) in seen_caches:
            continue
        seen_caches.add(id(cache))
        for db_name, conn in list(cache.items()):
            try:
                conn.close()
            except Exception:
                pass
        cache.clear()


# ---------------------------------------------------------------------------
# Summary logging
# ---------------------------------------------------------------------------

def _log_summary(summary: RunSummary) -> None:
    log.info("-" * 60)
    log.info("Run summary:")
    log.info("  Total configured  : %d", summary.total_configured)
    log.info("  Enabled           : %d", summary.enabled)
    log.info("  Sched. skipped    : %d", summary.schedule_skipped)
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
