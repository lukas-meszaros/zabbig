"""
database.py — Database query collector.

Runs a SQL query against a configured database and sends the result to Zabbix.

Supported modes
---------------
  value      — Sends the raw value from column *result_column* (default: 0) of
               the first row returned by the query.  Subsequent rows are ignored.
               Use params.result to choose max/min over ALL rows when multi-row
               reduction is needed (see below).

  condition  — Evaluates each result row against an ordered condition list using
               the same engine as the log and probe collectors.  The first
               matching condition determines the metric value (and optional
               host_name override).  A result_strategy (first/last/max/min)
               collapses multiple matching rows into one final value.

Params reference
----------------
  database       (required) Name of the database entry in databases.yaml.
  sql            (required) SQL query to execute. Must be a SELECT statement.
  result_column  (int, default 0) 0-based column index to extract.
  mode           value | condition  (default: value)
  default_value  Value to send when the query returns no rows (default: None
                 → metric is skipped unless fallback_value is set in MetricDef).
  result         first | last | max | min  (multi-row reduction, default: last)
  conditions     List of condition entries (required when mode=condition).
                 Same syntax as the log collector — supports:
                   { when: <regex>, value: X [, host_name: H] }
                   { extract: <regex>, compare: gt|lt|gte|lte|eq,
                     threshold: N, value: X | "$1" [, host_name: H] }
                   { value: X [, host_name: H] }  (catch-all)

Database config
---------------
  Database connections are defined in databases.yaml and passed in via
  metric.params["_db_registry"] (injected by the runner).  Passwords may be
  encrypted with scripts/encrypt_password.py (ENC: prefix).

Example metrics.yaml snippet
-----------------------------
  - id: db_active_connections
    name: "PostgreSQL active connections"
    collector: database
    key: pg.connections.active
    params:
      database: local_postgres
      sql: "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
      mode: value

  - id: db_replication_lag
    name: "Replication lag alert"
    collector: database
    key: pg.replication.lag.alert
    value_type: int
    params:
      database: local_postgres
      sql: "SELECT extract(epoch FROM now() - pg_last_xact_replay_timestamp())"
      mode: condition
      conditions:
        - extract: '(\\d+)'
          compare: gt
          threshold: 300
          value: 2
        - extract: '(\\d+)'
          compare: gt
          threshold: 60
          value: 1
        - value: 0
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector
from .log import _eval_conditions, _resolve_result_with_host


@register_collector("database")
class DatabaseCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> list[MetricResult]:  # type: ignore[override]
        return await asyncio.to_thread(_run_query, metric)


# ---------------------------------------------------------------------------
# Blocking implementation (runs in a thread pool via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _run_query(metric: MetricDef) -> list[MetricResult]:
    params = metric.params
    db_registry: dict = params.get("_db_registry") or {}
    db_name: str = params["database"]
    sql: str = params["sql"]
    result_column: int = int(params.get("result_column", 0))
    mode: str = params.get("mode", "value")
    default_value = params.get("default_value")
    result_strategy: str = params.get("result", "last")
    conditions: list[dict] = params.get("conditions", [])

    db_config = db_registry.get(db_name)
    if db_config is None:
        raise KeyError(
            f"Database '{db_name}' not found in databases.yaml. "
            f"Known databases: {sorted(db_registry.keys())}"
        )

    from ..db_loader import get_connection  # local import avoids circular deps

    conn = get_connection(db_config)
    try:
        rows = _execute_query(conn, sql)
    finally:
        _close_connection(conn)

    if mode == "value":
        return _handle_value_mode(metric, rows, result_column, result_strategy, default_value)
    elif mode == "condition":
        return _handle_condition_mode(metric, rows, result_column, conditions, result_strategy, default_value)
    else:
        raise ValueError(
            f"Unknown database collector mode: '{mode}'. "
            "Valid values: value | condition"
        )


def _execute_query(conn: Any, sql: str) -> list[tuple]:
    """Run a SELECT query and return all rows as a list of tuples."""
    # pg8000 native Connection uses run() method
    if hasattr(conn, "run"):
        result = conn.run(sql)
        # pg8000 native returns a list of lists; normalise to list of tuples
        return [tuple(row) for row in result]
    # Fallback: DB-API 2.0 cursor interface
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


def _close_connection(conn: Any) -> None:
    """Close the connection, silently ignoring errors."""
    try:
        conn.close()
    except Exception:
        pass


def _make_result(
    metric: MetricDef,
    value: Any,
    host_name: str | None = None,
) -> MetricResult:
    return MetricResult(
        metric_id=metric.id,
        key=metric.key,
        value=str(value) if value is not None else None,
        value_type=metric.value_type,
        timestamp=int(time.time()),
        collector=metric.collector,
        delivery=metric.delivery,
        status=RESULT_OK,
        unit=metric.unit,
        tags=metric.tags,
        host_name=host_name or metric.host_name,
    )


def _make_default_result(metric: MetricDef, default_value: Any) -> list[MetricResult]:
    """Return a result with the default value (or empty list if default is None)."""
    if default_value is None:
        return []
    return [_make_result(metric, default_value)]


def _handle_value_mode(
    metric: MetricDef,
    rows: list[tuple],
    result_column: int,
    result_strategy: str,
    default_value: Any,
) -> list[MetricResult]:
    """
    Extract values from *result_column* of all rows, then reduce using
    *result_strategy* (first/last/max/min).  A single MetricResult is returned.
    """
    if not rows:
        return _make_default_result(metric, default_value)

    values: list[Any] = []
    for row in rows:
        try:
            values.append(row[result_column])
        except IndexError:
            raise IndexError(
                f"result_column={result_column} is out of range "
                f"(row has {len(row)} column(s)): {row!r}"
            )

    from .log import _resolve_result as _res

    final = _res(values, result_strategy)
    return [_make_result(metric, final)]


def _handle_condition_mode(
    metric: MetricDef,
    rows: list[tuple],
    result_column: int,
    conditions: list[dict],
    result_strategy: str,
    default_value: Any,
) -> list[MetricResult]:
    """
    Evaluate each row's text cell against the condition engine.
    One MetricResult is emitted (using result_strategy to reduce multi-row matches).
    Optionally returns a second result with a different host_name when the winning
    condition specifies host_name.
    """
    if not rows:
        return _make_default_result(metric, default_value)

    if not conditions:
        raise ValueError(
            "Database collector mode=condition requires params.conditions to be non-empty"
        )

    entries: list[tuple[Any, str | None]] = []
    for row in rows:
        try:
            cell = str(row[result_column])
        except IndexError:
            raise IndexError(
                f"result_column={result_column} is out of range "
                f"(row has {len(row)} column(s)): {row!r}"
            )
        val, cond_host = _eval_conditions(conditions, cell)
        if val is not None:
            entries.append((val, cond_host))

    if not entries:
        return _make_default_result(metric, default_value)

    final_val, final_host = _resolve_result_with_host(entries, result_strategy)
    return [_make_result(metric, final_val, final_host)]
