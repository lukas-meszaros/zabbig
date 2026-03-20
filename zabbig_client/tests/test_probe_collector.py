"""
test_probe_collector.py — Unit tests for the probe collector.

Tests cover:
  - TCP probe: success, failure, response_time_ms sub-key
  - HTTP probe: http_status (raw and condition-based)
  - HTTP probe: http_body (match filter, conditions, result strategies)
  - SSL check helper: valid, invalid, unknown
  - Helper functions: _eval_http_status, _eval_http_body
  - ProbeCollector registration
  - Runner integration: list[MetricResult] return is handled correctly
"""
import asyncio
import os
import sys
import socket
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


# ---------------------------------------------------------------------------
# Helpers for creating MetricDef objects without a full config stack
# ---------------------------------------------------------------------------

def _make_metric(collector="probe", key="probe.test", params=None, **kwargs):
    from zabbig_client.models import MetricDef
    return MetricDef(
        id=kwargs.get("id", "test_probe"),
        name=kwargs.get("name", "Test Probe"),
        enabled=True,
        collector=collector,
        key=key,
        delivery=kwargs.get("delivery", "immediate"),
        timeout_seconds=kwargs.get("timeout_seconds", 5.0),
        error_policy=kwargs.get("error_policy", "skip"),
        value_type=kwargs.get("value_type", "int"),
        params=params or {},
    )


# ---------------------------------------------------------------------------
# TCP probe helpers
# ---------------------------------------------------------------------------

class TestTcpProbe(unittest.TestCase):

    def test_open_port_returns_on_success(self):
        """Connect to a local server socket — expect on_success value."""
        from zabbig_client.collectors.probe import _run_tcp_probe

        # Start a temporary TCP listener
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
            "on_success": 1,
            "on_failure": 0,
        })

        results = _run_tcp_probe(metric)
        srv.close()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, "1")
        self.assertEqual(results[0].key, "probe.test")
        self.assertEqual(results[0].collector, "probe")

    def test_closed_port_returns_on_failure(self):
        """Connect to a port nothing is listening on — expect on_failure value."""
        from zabbig_client.collectors.probe import _run_tcp_probe

        # Bind a socket, get a port, then close it so nothing is listening
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
            "on_success": 1,
            "on_failure": 0,
        })

        results = _run_tcp_probe(metric)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, "0")

    def test_response_time_ms_sub_key_on_success(self):
        """When response_time_ms=true, a second MetricResult with .response_time_ms is appended."""
        from zabbig_client.collectors.probe import _run_tcp_probe

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
            "on_success": 1,
            "on_failure": 0,
            "response_time_ms": True,
        })

        results = _run_tcp_probe(metric)
        srv.close()

        self.assertEqual(len(results), 2)
        keys = [r.key for r in results]
        self.assertIn("probe.test", keys)
        self.assertIn("probe.test.response_time_ms", keys)

        rt_result = next(r for r in results if r.key.endswith(".response_time_ms"))
        self.assertEqual(rt_result.unit, "ms")
        # Value is non-negative ms integer; sub-ms local connections may round to 0
        self.assertGreaterEqual(int(rt_result.value), 0)

    def test_response_time_ms_zero_on_failure(self):
        """response_time_ms sub-key reports 0 when the connection was refused."""
        from zabbig_client.collectors.probe import _run_tcp_probe

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
            "on_success": 1,
            "on_failure": 0,
            "response_time_ms": True,
        })

        results = _run_tcp_probe(metric)
        rt_result = next(r for r in results if r.key.endswith(".response_time_ms"))
        self.assertEqual(rt_result.value, "0")

    def test_custom_on_success_on_failure_values(self):
        """Custom on_success / on_failure literals are returned correctly."""
        from zabbig_client.collectors.probe import _run_tcp_probe

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
            "on_success": 42,
            "on_failure": 99,
        })
        results = _run_tcp_probe(metric)
        srv.close()
        self.assertEqual(results[0].value, "42")


# ---------------------------------------------------------------------------
# HTTP probe helpers (using mock responses)
# ---------------------------------------------------------------------------

def _mock_response(status_code=200, body="", encoding="utf-8"):
    """Build a minimal requests.Response mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.encoding = encoding
    raw_mock = MagicMock()
    raw_mock.read.return_value = body.encode(encoding)
    resp.raw = raw_mock
    return resp


class TestHttpStatusProbe(unittest.TestCase):

    def _run(self, params, status_code=200, body=""):
        from zabbig_client.collectors.probe import _run_http_probe
        metric = _make_metric(params=params)
        with patch("requests.request", return_value=_mock_response(status_code, body)):
            return _run_http_probe(metric)

    def test_raw_status_code_without_conditions(self):
        """http_status without conditions returns the raw status code integer."""
        results = self._run({
            "url": "http://example.com/health",
            "mode": "http_status",
        }, status_code=200)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, "200")

    def test_condition_maps_2xx_to_1(self):
        results = self._run({
            "url": "http://example.com/health",
            "mode": "http_status",
            "default_value": 0,
            "conditions": [
                {"when": "^2", "value": 1},
                {"value": 0},
            ],
        }, status_code=200)
        self.assertEqual(results[0].value, "1")

    def test_condition_maps_5xx_to_3(self):
        results = self._run({
            "url": "http://example.com/health",
            "mode": "http_status",
            "default_value": 0,
            "conditions": [
                {"when": "^2", "value": 1},
                {"when": "^4", "value": 2},
                {"when": "^5", "value": 3},
                {"value": 0},
            ],
        }, status_code=503)
        self.assertEqual(results[0].value, "3")

    def test_connection_failure_returns_default_value(self):
        """When requests.request raises, default_value is returned."""
        from zabbig_client.collectors.probe import _run_http_probe
        import requests as rq
        metric = _make_metric(params={
            "url": "http://nonexistent.example.com/",
            "mode": "http_status",
            "default_value": 0,
        })
        with patch("requests.request", side_effect=rq.exceptions.ConnectionError("refused")):
            results = _run_http_probe(metric)
        self.assertEqual(results[0].value, "0")

    def test_response_time_ms_sub_key_present(self):
        results = self._run({
            "url": "http://example.com/",
            "mode": "http_status",
            "response_time_ms": True,
        })
        self.assertEqual(len(results), 2)
        self.assertIn("probe.test.response_time_ms", [r.key for r in results])

    def test_ssl_check_sub_key_present(self):
        results = self._run({
            "url": "https://example.com/",
            "mode": "http_status",
            "ssl_check": True,
        })
        ssl_result = next((r for r in results if r.key.endswith(".ssl_check")), None)
        self.assertIsNotNone(ssl_result)
        self.assertIn(ssl_result.value, ("0", "1", "2"))


class TestHttpBodyProbe(unittest.TestCase):

    def _run(self, params, body="", status_code=200):
        from zabbig_client.collectors.probe import _run_http_probe
        metric = _make_metric(params=params)
        with patch("requests.request", return_value=_mock_response(status_code, body)):
            return _run_http_probe(metric)

    def test_body_condition_match(self):
        results = self._run({
            "url": "http://example.com/health",
            "mode": "http_body",
            "match": '"status"',
            "conditions": [
                {"when": '"status":\\s*"ok"', "value": 1},
                {"value": 0},
            ],
            "default_value": 0,
        }, body='{"status": "ok"}')
        self.assertEqual(results[0].value, "1")

    def test_body_condition_no_match_returns_default(self):
        results = self._run({
            "url": "http://example.com/health",
            "mode": "http_body",
            "match": '"status"',
            "conditions": [{"when": '"status":\\s*"ok"', "value": 1}, {"value": 0}],
            "default_value": 99,
        }, body="<html>error page</html>")
        # match guard fails — no line contains '"status"'
        self.assertEqual(results[0].value, "99")

    def test_body_no_conditions_returns_1_when_match(self):
        """No conditions but a match filter — returns 1 when any line passes."""
        results = self._run({
            "url": "http://example.com/",
            "mode": "http_body",
            "match": "healthy",
        }, body="status: healthy\nuptime: 99.9%")
        self.assertEqual(results[0].value, "1")

    def test_body_result_max_strategy(self):
        """result: max returns the highest value across all matching lines."""
        from zabbig_client.collectors.probe import _eval_http_body
        body = "WARN level=1\nERROR level=3\nINFO level=0"
        result = _eval_http_body(
            body=body,
            match_pattern=r"level=\d",
            conditions=[
                {"extract": r"level=(\d+)", "compare": "gte", "threshold": 0, "value": "$1"},
            ],
            result_strategy="max",
            default_value=0,
        )
        self.assertEqual(float(result), 3.0)

    def test_body_result_min_strategy(self):
        from zabbig_client.collectors.probe import _eval_http_body
        body = "level=5\nlevel=1\nlevel=3"
        result = _eval_http_body(
            body=body,
            match_pattern=None,
            conditions=[
                {"extract": r"level=(\d+)", "compare": "gte", "threshold": 0, "value": "$1"},
            ],
            result_strategy="min",
            default_value=0,
        )
        self.assertEqual(float(result), 1.0)

    def test_empty_body_returns_default(self):
        from zabbig_client.collectors.probe import _eval_http_body
        result = _eval_http_body("", None, [], "last", 42)
        self.assertEqual(result, 42)

    def test_no_conditions_no_match_filter(self):
        """Without conditions or match, returns 1 for any non-empty body."""
        results = self._run({
            "url": "http://example.com/",
            "mode": "http_body",
        }, body="anything at all")
        self.assertEqual(results[0].value, "1")


# ---------------------------------------------------------------------------
# SSL check helper
# ---------------------------------------------------------------------------

class TestSslCertCheck(unittest.TestCase):

    def test_returns_int_in_valid_range(self):
        """_ssl_cert_check always returns 0, 1, or 2."""
        from zabbig_client.collectors.probe import _ssl_cert_check
        result = _ssl_cert_check("github.com", 443, timeout=5.0)
        self.assertIn(result, (0, 1, 2))

    def test_valid_public_cert(self):
        """Public CA-signed certs should return 1 on a machine with internet access."""
        from zabbig_client.collectors.probe import _ssl_cert_check
        result = _ssl_cert_check("github.com", 443, timeout=5.0)
        # May return 2 on systems without network; accept both
        self.assertIn(result, (1, 2))

    def test_unreachable_returns_2(self):
        """An unreachable host returns 2 (unknown), not 0 or an exception."""
        from zabbig_client.collectors.probe import _ssl_cert_check
        # Port 1 on localhost is never listening
        result = _ssl_cert_check("127.0.0.1", 1, timeout=1.0)
        self.assertEqual(result, 2)


# ---------------------------------------------------------------------------
# eval_http_status helper
# ---------------------------------------------------------------------------

class TestEvalHttpStatus(unittest.TestCase):

    def test_2xx_maps_to_1(self):
        from zabbig_client.collectors.probe import _eval_http_status
        conditions = [
            {"when": "^2", "value": 1},
            {"when": "^5", "value": 3},
            {"value": 0},
        ]
        self.assertEqual(_eval_http_status("200", conditions, 0), 1)
        self.assertEqual(_eval_http_status("201", conditions, 0), 1)

    def test_5xx_maps_to_3(self):
        from zabbig_client.collectors.probe import _eval_http_status
        conditions = [
            {"when": "^2", "value": 1},
            {"when": "^5", "value": 3},
            {"value": 0},
        ]
        self.assertEqual(_eval_http_status("503", conditions, 0), 3)

    def test_catch_all_returns_0(self):
        from zabbig_client.collectors.probe import _eval_http_status
        conditions = [{"when": "^2", "value": 1}, {"value": 0}]
        self.assertEqual(_eval_http_status("404", conditions, 0), 0)

    def test_no_conditions_match_returns_default(self):
        from zabbig_client.collectors.probe import _eval_http_status
        # No catch-all condition — fallback to default_value
        conditions = [{"when": "^2", "value": 1}]
        self.assertEqual(_eval_http_status("503", conditions, 99), 99)


# ---------------------------------------------------------------------------
# ProbeCollector registration and async interface
# ---------------------------------------------------------------------------

class TestProbeCollectorRegistration(unittest.TestCase):

    def test_probe_is_registered(self):
        from zabbig_client.collector_registry import registered_names
        self.assertIn("probe", registered_names())

    def test_probe_in_valid_collectors(self):
        from zabbig_client.models import VALID_COLLECTORS
        self.assertIn("probe", VALID_COLLECTORS)

    def test_collect_returns_list(self):
        """ProbeCollector.collect() must return a list of MetricResult."""
        from zabbig_client.collectors.probe import ProbeCollector, _run_tcp_probe

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        metric = _make_metric(params={
            "host": "127.0.0.1",
            "port": port,
            "mode": "tcp",
        })

        collector = ProbeCollector()
        results = asyncio.get_event_loop().run_until_complete(collector.collect(metric))
        srv.close()

        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_invalid_mode_raises(self):
        from zabbig_client.collectors.probe import ProbeCollector

        metric = _make_metric(params={"mode": "invalid_mode"})
        collector = ProbeCollector()
        with self.assertRaises(ValueError):
            asyncio.get_event_loop().run_until_complete(collector.collect(metric))


# ---------------------------------------------------------------------------
# Runner integration: list[MetricResult] is flattened correctly
# ---------------------------------------------------------------------------

class TestRunnerHandlesListResult(unittest.TestCase):
    """Verify that run_all_collectors correctly flattens list results from probe."""

    def test_probe_results_flattened_in_immediate_queue(self):
        """
        When a probe collector returns two results (primary + response_time_ms),
        both must appear in the flattened immediate_results list.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch
        from zabbig_client.runner import run_all_collectors
        from zabbig_client.models import (
            ClientConfig, MetricResult, RESULT_OK, DELIVERY_IMMEDIATE
        )

        two_results = [
            MetricResult(
                metric_id="p1",
                key="probe.test",
                value="1",
                value_type="int",
                timestamp=int(time.time()),
                collector="probe",
                delivery=DELIVERY_IMMEDIATE,
                status=RESULT_OK,
            ),
            MetricResult(
                metric_id="p1._rt",
                key="probe.test.response_time_ms",
                value="42",
                value_type="int",
                timestamp=int(time.time()),
                collector="probe",
                delivery=DELIVERY_IMMEDIATE,
                status=RESULT_OK,
                unit="ms",
            ),
        ]

        metric = _make_metric(params={"host": "x", "port": 1, "mode": "tcp"})

        async def fake_collect(m):
            return two_results

        config = ClientConfig()

        with patch(
            "zabbig_client.collector_registry.get_collector",
            return_value=lambda: type("C", (), {"collect": fake_collect})(),
        ):
            # Manually patch get_collector to return a class whose instance
            # has a fake async collect method
            class FakeCollector:
                async def collect(self, m):
                    return two_results

            with patch("zabbig_client.runner.get_collector", return_value=FakeCollector):
                immediate, batch = asyncio.get_event_loop().run_until_complete(
                    run_all_collectors([metric], config)
                )

        self.assertEqual(len(immediate), 2)
        keys = [r.key for r in immediate]
        self.assertIn("probe.test", keys)
        self.assertIn("probe.test.response_time_ms", keys)


if __name__ == "__main__":
    unittest.main()
