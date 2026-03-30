"""
test_database_integration.py — Integration tests for the database collector.

These tests require a live PostgreSQL instance started with:

  docker-compose -f docker-compose.postgres-test.yml up -d

All tests in this file are marked @pytest.mark.integration and are skipped
unless the container is reachable.  Run them explicitly with:

  cd pytest && pytest -m integration

Connection details are taken from environment variables with fallbacks
matching docker-compose.postgres-test.yml:

  ZABBIG_TEST_PG_HOST     (default: 127.0.0.1)
  ZABBIG_TEST_PG_PORT     (default: 15432)
  ZABBIG_TEST_PG_DBNAME   (default: testdb)
  ZABBIG_TEST_PG_USER     (default: monitor)
  ZABBIG_TEST_PG_PASSWORD (default: monitor_pw)
"""
import asyncio
import os
import sys
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT_SRC = os.path.join(_ROOT, "zabbig_client", "src")
for _p in [_CLIENT_SRC]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zabbig_client.collectors.database import DatabaseCollector, _run_query
from zabbig_client.models import MetricDef

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------

_PG_HOST = os.environ.get("ZABBIG_TEST_PG_HOST", "127.0.0.1")
_PG_PORT = int(os.environ.get("ZABBIG_TEST_PG_PORT", "15432"))
_PG_DBNAME = os.environ.get("ZABBIG_TEST_PG_DBNAME", "testdb")
_PG_USER = os.environ.get("ZABBIG_TEST_PG_USER", "monitor")
_PG_PASSWORD = os.environ.get("ZABBIG_TEST_PG_PASSWORD", "monitor_pw")


def _db_registry():
    return {
        "test_pg": {
            "name": "test_pg",
            "type": "postgres",
            "host": _PG_HOST,
            "port": _PG_PORT,
            "dbname": _PG_DBNAME,
            "username": _PG_USER,
            "password": _PG_PASSWORD,
            "connect_timeout": 5,
            "options": {},
        }
    }


def _metric(
    sql: str,
    mode: str = "value",
    conditions: list = None,
    default_value=None,
    result: str = "last",
    result_column: int = 0,
    value_type: str = "float",
) -> MetricDef:
    params = {
        "database": "test_pg",
        "sql": sql,
        "mode": mode,
        "result": result,
        "result_column": result_column,
        "_db_registry": _db_registry(),
    }
    if conditions is not None:
        params["conditions"] = conditions
    if default_value is not None:
        params["default_value"] = default_value
    return MetricDef(
        id="integration_test",
        name="integration_test",
        enabled=True,
        collector="database",
        key="db.integration.test",
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
        value_type=value_type,
        params=params,
    )


# ---------------------------------------------------------------------------
# Reachability check — skip all tests if Postgres is not up
# ---------------------------------------------------------------------------

def _pg_reachable() -> bool:
    try:
        import pg8000.native as pg
        conn = pg.Connection(
            host=_PG_HOST,
            port=_PG_PORT,
            database=_PG_DBNAME,
            user=_PG_USER,
            password=_PG_PASSWORD,
            timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _pg_reachable(),
        reason=(
            f"Postgres not reachable at {_PG_HOST}:{_PG_PORT}/{_PG_DBNAME}. "
            "Start with: docker-compose -f docker-compose.postgres-test.yml up -d"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestDatabaseCollectorIntegration:
    def test_select_literal_value_mode(self):
        m = _metric("SELECT 42")
        results = _run_query(m)
        assert len(results) == 1
        assert results[0].value == "42"

    def test_count_active_users(self):
        m = _metric("SELECT count(*) FROM users WHERE active = TRUE")
        results = _run_query(m)
        assert len(results) == 1
        assert float(results[0].value) >= 0

    def test_count_pending_orders(self):
        m = _metric("SELECT count(*) FROM orders WHERE status = 'pending'")
        results = _run_query(m)
        assert len(results) == 1
        assert float(results[0].value) >= 0

    def test_metrics_test_table_lookup(self):
        m = _metric(
            "SELECT value FROM metrics_test WHERE key = 'active_users'",
        )
        results = _run_query(m)
        assert len(results) == 1
        val = float(results[0].value)
        assert val >= 0

    def test_empty_result_returns_default(self):
        m = _metric(
            "SELECT id FROM users WHERE id = -99999",
            default_value="-1",
        )
        results = _run_query(m)
        assert len(results) == 1
        assert results[0].value == "-1"

    def test_multi_row_max_strategy(self):
        m = _metric(
            "SELECT amount FROM orders ORDER BY amount",
            result="max",
        )
        results = _run_query(m)
        assert len(results) == 1
        # 200.00 is the max order amount in seed data
        assert float(results[0].value) >= 200.0

    def test_multi_row_min_strategy(self):
        m = _metric(
            "SELECT amount FROM orders ORDER BY amount",
            result="min",
        )
        results = _run_query(m)
        assert len(results) == 1
        # 29.00 is the min order amount in seed data
        assert float(results[0].value) <= 30.0

    def test_condition_mode_catch_all(self):
        conditions = [{"value": 1}]
        m = _metric(
            "SELECT status FROM orders WHERE status = 'pending' LIMIT 1",
            mode="condition",
            conditions=conditions,
        )
        results = _run_query(m)
        assert results[0].value == "1"

    def test_condition_mode_when_match(self):
        conditions = [
            {"when": "pending", "value": 2},
            {"value": 0},
        ]
        m = _metric(
            "SELECT status FROM orders WHERE status = 'pending' LIMIT 1",
            mode="condition",
            conditions=conditions,
        )
        results = _run_query(m)
        assert results[0].value == "2"

    def test_condition_mode_no_match_default(self):
        conditions = [
            {"when": "NEVER_MATCHES_XYZ", "value": 9},
        ]
        m = _metric(
            "SELECT status FROM orders LIMIT 1",
            mode="condition",
            conditions=conditions,
            default_value="0",
        )
        results = _run_query(m)
        assert results[0].value == "0"

    def test_second_column(self):
        m = _metric(
            "SELECT id, amount FROM orders ORDER BY amount DESC LIMIT 1",
            result_column=1,
        )
        results = _run_query(m)
        assert len(results) == 1
        assert float(results[0].value) >= 200.0

    @pytest.mark.asyncio
    async def test_async_collect(self):
        m = _metric("SELECT 7")
        collector = DatabaseCollector()
        results = await collector.collect(m)
        assert len(results) == 1
        assert results[0].value == "7"
