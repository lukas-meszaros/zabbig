"""
test_db_conn_cache.py — Tests for per-run database connection caching in database.py.
"""
import pytest
from unittest.mock import MagicMock, call, patch

from zabbig_client.collectors.database import _run_query
from zabbig_client.models import MetricDef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_metric(db_name="mydb", sql="SELECT 1", cache=None):
    registry = {db_name: {"host": "localhost", "port": 5432, "user": "u", "password": "p", "database": db_name}}
    params = {
        "database": db_name,
        "sql": sql,
        "_db_registry": registry,
        "mode": "value",
    }
    if cache is not None:
        params["_db_conn_cache"] = cache

    return MetricDef(
        id="test_db",
        name="Test DB",
        enabled=True,
        collector="database",
        key="db.test",
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
        params=params,
    )


def _make_mock_conn(rows=None):
    conn = MagicMock()
    conn.run.return_value = rows or [[42]]
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDbConnCache:
    def test_new_connection_stored_in_cache(self):
        """When no cached connection exists, a new one is opened and stored."""
        cache = {}
        metric = _make_db_metric(cache=cache)
        mock_conn = _make_mock_conn()

        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn) as mock_get:
            _run_query(metric)

        mock_get.assert_called_once()
        assert "mydb" in cache
        assert cache["mydb"] is mock_conn

    def test_cached_connection_reused(self):
        """When a cached connection exists, get_connection is NOT called again."""
        mock_conn = _make_mock_conn()
        cache = {"mydb": mock_conn}
        metric = _make_db_metric(cache=cache)

        with patch("zabbig_client.db_loader.get_connection") as mock_get:
            _run_query(metric)

        mock_get.assert_not_called()
        mock_conn.run.assert_called_once()

    def test_no_cache_falls_back_to_fresh_connection(self):
        """Without _db_conn_cache in params, each call opens a new connection."""
        metric = _make_db_metric(cache=None)
        mock_conn = _make_mock_conn()

        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn) as mock_get:
            _run_query(metric)

        mock_get.assert_called_once()

    def test_query_error_removes_connection_from_cache(self):
        """On query failure, the broken connection is evicted from the cache."""
        mock_conn = _make_mock_conn()
        mock_conn.run.side_effect = Exception("broken pipe")
        cache = {"mydb": mock_conn}
        metric = _make_db_metric(cache=cache)

        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn):
            with pytest.raises(Exception, match="broken pipe"):
                _run_query(metric)

        assert "mydb" not in cache

    def test_two_metrics_same_db_reuse_connection(self):
        """Two metrics sharing the same cache dict reuse the same connection."""
        cache = {}
        metric1 = _make_db_metric(db_name="db1", cache=cache)
        metric2 = _make_db_metric(db_name="db1", cache=cache)
        mock_conn = _make_mock_conn()

        with patch("zabbig_client.db_loader.get_connection", return_value=mock_conn) as mock_get:
            _run_query(metric1)
            _run_query(metric2)

        assert mock_get.call_count == 1  # only opened once


class TestCloseDbConnCaches:
    def test_close_called_for_all_cached_connections(self):
        """_close_db_conn_caches closes every connection and clears the cache."""
        from zabbig_client.main import _close_db_conn_caches

        conn_a = MagicMock()
        conn_b = MagicMock()
        cache = {"db1": conn_a, "db2": conn_b}

        metric = MetricDef(
            id="m1",
            name="M1",
            enabled=True,
            collector="database",
            key="db.m1",
            delivery="batch",
            timeout_seconds=10.0,
            error_policy="skip",
            params={"_db_conn_cache": cache, "_db_registry": {}, "database": "db1", "sql": "SELECT 1"},
        )

        _close_db_conn_caches([metric])

        conn_a.close.assert_called_once()
        conn_b.close.assert_called_once()
        assert len(cache) == 0

    def test_non_database_metrics_skipped(self):
        """Metrics that aren't database-type are safely ignored."""
        from zabbig_client.main import _close_db_conn_caches

        metric = MetricDef(
            id="cpu1",
            name="CPU",
            enabled=True,
            collector="cpu",
            key="host.cpu.util",
            delivery="batch",
            timeout_seconds=5.0,
            error_policy="skip",
            params={"mode": "percent"},
        )
        # Must not raise
        _close_db_conn_caches([metric])

    def test_same_cache_not_closed_twice(self):
        """When two metrics share the same cache dict, connections are only closed once."""
        from zabbig_client.main import _close_db_conn_caches

        mock_conn = MagicMock()
        cache = {"db1": mock_conn}
        shared_params = {"_db_conn_cache": cache, "_db_registry": {}, "database": "db1", "sql": "SELECT 1"}

        m1 = MetricDef(id="m1", name="", enabled=True, collector="database", key="db.m1",
                       delivery="batch", timeout_seconds=10.0, error_policy="skip", params=shared_params)
        m2 = MetricDef(id="m2", name="", enabled=True, collector="database", key="db.m2",
                       delivery="batch", timeout_seconds=10.0, error_policy="skip", params=shared_params)

        _close_db_conn_caches([m1, m2])

        mock_conn.close.assert_called_once()
