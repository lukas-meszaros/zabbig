"""
test_collector_database.py — Unit tests for the database collector.

Uses mock DB connections to test:
  - mode=value (single row, multi-row with reduction strategies)
  - mode=condition (condition engine integration)
  - Missing _db_registry raises cleanly
  - Unknown database name raises cleanly
  - Default value returned when no rows
  - result_column out of range raises
  - DB connection exceptions propagate
"""
import asyncio
import os
import sys
import time
import pytest
from unittest.mock import MagicMock, patch, call

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT_SRC = os.path.join(_ROOT, "zabbig_client", "src")
for _p in [_CLIENT_SRC]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zabbig_client.collectors.database import (
    DatabaseCollector,
    _run_query,
    _execute_query,
    _handle_value_mode,
    _handle_condition_mode,
    _make_result,
)
from zabbig_client.models import MetricDef, RESULT_OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_db_metric(
    mid="test_db",
    key="db.test",
    params=None,
) -> MetricDef:
    return MetricDef(
        id=mid,
        name=mid,
        enabled=True,
        collector="database",
        key=key,
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
        value_type="float",
        params=params or {},
    )


def _db_registry_for(host="127.0.0.1", port=5432, dbname="testdb",
                     username="monitor", password="pw"):
    return {
        "local_postgres": {
            "name": "local_postgres",
            "type": "postgres",
            "host": host,
            "port": port,
            "dbname": dbname,
            "username": username,
            "password": password,
            "connect_timeout": 10,
            "options": {},
        }
    }


# ---------------------------------------------------------------------------
# _execute_query — pg8000 native (has run()) vs DB-API cursor
# ---------------------------------------------------------------------------

class TestExecuteQuery:
    def test_native_connection_run(self):
        conn = MagicMock()
        conn.run.return_value = [[42]]
        rows = _execute_query(conn, "SELECT 42")
        conn.run.assert_called_once_with("SELECT 42")
        assert rows == [(42,)]

    def test_native_connection_multi_row(self):
        conn = MagicMock()
        conn.run.return_value = [[1, "a"], [2, "b"]]
        rows = _execute_query(conn, "SELECT id, name FROM t")
        assert rows == [(1, "a"), (2, "b")]

    def test_dbapi_cursor_fallback(self):
        cur = MagicMock()
        cur.fetchall.return_value = [(10, "x")]
        conn = MagicMock(spec=["cursor"])  # no .run attribute — forces cursor path
        conn.cursor.return_value = cur
        rows = _execute_query(conn, "SELECT 10")
        cur.execute.assert_called_once_with("SELECT 10")
        assert rows == [(10, "x")]


# ---------------------------------------------------------------------------
# _handle_value_mode
# ---------------------------------------------------------------------------

class TestHandleValueMode:
    def _make_metric(self, params=None):
        return make_db_metric(params=params or {})

    def test_single_row_value(self):
        m = self._make_metric()
        results = _handle_value_mode(m, [(99,)], 0, "last", None)
        assert len(results) == 1
        assert results[0].value == "99"
        assert results[0].status == RESULT_OK

    def test_first_strategy(self):
        m = self._make_metric()
        rows = [(10,), (20,), (30,)]
        results = _handle_value_mode(m, rows, 0, "first", None)
        assert results[0].value == "10"

    def test_last_strategy(self):
        m = self._make_metric()
        rows = [(10,), (20,), (30,)]
        results = _handle_value_mode(m, rows, 0, "last", None)
        assert results[0].value == "30"

    def test_max_strategy(self):
        m = self._make_metric()
        rows = [(5,), (100,), (42,)]
        results = _handle_value_mode(m, rows, 0, "max", None)
        assert results[0].value == "100.0"

    def test_min_strategy(self):
        m = self._make_metric()
        rows = [(5,), (100,), (42,)]
        results = _handle_value_mode(m, rows, 0, "min", None)
        assert results[0].value == "5.0"

    def test_non_zero_column(self):
        m = self._make_metric()
        rows = [("ignored", 77)]
        results = _handle_value_mode(m, rows, 1, "last", None)
        assert results[0].value == "77"

    def test_empty_rows_default_value(self):
        m = self._make_metric()
        results = _handle_value_mode(m, [], 0, "last", "-1")
        assert len(results) == 1
        assert results[0].value == "-1"

    def test_empty_rows_no_default_returns_empty(self):
        m = self._make_metric()
        results = _handle_value_mode(m, [], 0, "last", None)
        assert results == []

    def test_result_column_out_of_range(self):
        m = self._make_metric()
        with pytest.raises(IndexError, match="out of range"):
            _handle_value_mode(m, [(1,)], 5, "last", None)


# ---------------------------------------------------------------------------
# _handle_condition_mode
# ---------------------------------------------------------------------------

class TestHandleConditionMode:
    def _make_metric(self, conditions):
        return make_db_metric(params={"conditions": conditions})

    def test_catch_all_condition(self):
        m = self._make_metric([{"value": 1}])
        results = _handle_condition_mode(m, [("any text",)], 0, [{"value": 1}], "last", None)
        assert results[0].value == "1"

    def test_when_condition_match(self):
        conditions = [
            {"when": "ERROR", "value": 2},
            {"value": 0},
        ]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("ERROR: disk full",)], 0, conditions, "last", 0)
        assert results[0].value == "2"

    def test_when_condition_no_match_fallthrough(self):
        conditions = [
            {"when": "CRITICAL", "value": 3},
            {"value": 0},
        ]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("just a message",)], 0, conditions, "last", 0)
        assert results[0].value == "0"

    def test_extract_compare_gt(self):
        conditions = [
            {"extract": r"(\d+)", "compare": "gt", "threshold": 100, "value": 2},
            {"value": 0},
        ]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("active: 150",)], 0, conditions, "last", 0)
        assert results[0].value == "2"

    def test_extract_dollar_one_value(self):
        conditions = [
            {"extract": r"(\d+)", "compare": "gt", "threshold": 0, "value": "$1"},
        ]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("count: 42",)], 0, conditions, "last", 0)
        assert results[0].value == "42.0"

    def test_empty_conditions_raises(self):
        m = self._make_metric([])
        with pytest.raises(ValueError, match="conditions to be non-empty"):
            _handle_condition_mode(m, [("row",)], 0, [], "last", None)

    def test_host_name_override(self):
        conditions = [
            {"when": "host1", "value": 1, "host_name": "myhost.example.com"},
            {"value": 0},
        ]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("host1 metric",)], 0, conditions, "last", 0)
        assert results[0].host_name == "myhost.example.com"

    def test_no_match_returns_default(self):
        conditions = [{"when": "NEVER_MATCHES_THIS_EXACT_PATTERN_XYZ", "value": 9}]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [("normal",)], 0, conditions, "last", -1)
        assert results[0].value == "-1"

    def test_empty_rows_returns_default(self):
        conditions = [{"value": 1}]
        m = self._make_metric(conditions)
        results = _handle_condition_mode(m, [], 0, conditions, "last", "0")
        assert results[0].value == "0"


# ---------------------------------------------------------------------------
# _run_query — integration of connection + query + mode dispatch
# ---------------------------------------------------------------------------

class TestRunQuery:
    def _metric(self, mode="value", sql="SELECT 1", conditions=None, default_value=None):
        p = {
            "database": "local_postgres",
            "sql": sql,
            "mode": mode,
            "_db_registry": _db_registry_for(),
        }
        if conditions is not None:
            p["conditions"] = conditions
        if default_value is not None:
            p["default_value"] = default_value
        return make_db_metric(params=p)

    def test_value_mode_single_row(self):
        m = self._metric(mode="value")
        mock_conn = MagicMock()
        mock_conn.run.return_value = [[42]]
        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            results = _run_query(m)
        assert results[0].value == "42"

    def test_condition_mode(self):
        conditions = [{"value": 7}]
        m = self._metric(mode="condition", conditions=conditions)
        mock_conn = MagicMock()
        mock_conn.run.return_value = [["anything"]]
        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            results = _run_query(m)
        assert results[0].value == "7"

    def test_missing_db_registry_raises(self):
        m = make_db_metric(params={"database": "local_postgres", "sql": "SELECT 1"})
        with pytest.raises(KeyError, match="local_postgres"):
            _run_query(m)

    def test_unknown_database_name_raises(self):
        m = make_db_metric(params={
            "database": "nonexistent",
            "sql": "SELECT 1",
            "_db_registry": _db_registry_for(),
        })
        with pytest.raises(KeyError, match="nonexistent"):
            _run_query(m)

    def test_unknown_mode_raises(self):
        m = make_db_metric(params={
            "database": "local_postgres",
            "sql": "SELECT 1",
            "mode": "invalid_mode",
            "_db_registry": _db_registry_for(),
        })
        mock_conn = MagicMock()
        mock_conn.run.return_value = [[1]]
        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            with pytest.raises(ValueError, match="Unknown database collector mode"):
                _run_query(m)

    def test_connection_exception_propagates(self):
        m = self._metric()
        with patch(
            "zabbig_client.db_loader.get_connection",
            side_effect=ConnectionRefusedError("refused"),
        ):
            with pytest.raises(ConnectionRefusedError):
                _run_query(m)

    def test_conn_closed_on_error(self):
        m = self._metric()
        mock_conn = MagicMock()
        mock_conn.run.side_effect = RuntimeError("query failed")
        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="query failed"):
                _run_query(m)
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# DatabaseCollector.collect (async)
# ---------------------------------------------------------------------------

class TestDatabaseCollectorAsync:
    @pytest.mark.asyncio
    async def test_collect_calls_run_query(self):
        m = make_db_metric(params={
            "database": "local_postgres",
            "sql": "SELECT 1",
            "_db_registry": _db_registry_for(),
        })
        collector = DatabaseCollector()
        mock_conn = MagicMock()
        mock_conn.run.return_value = [[99]]
        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            results = await collector.collect(m)
        assert len(results) == 1
        assert results[0].value == "99"
        assert results[0].collector == "database"
