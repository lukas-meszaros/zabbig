"""
test_collector_probe.py — Tests for the network probe collector.
"""
import socket
import ssl
from unittest.mock import patch, MagicMock

import pytest

from conftest import make_metric
from zabbig_client.collectors.probe import (
    ProbeCollector,
    _run_tcp_probe,
    _run_http_probe,
    _ssl_cert_check,
    _eval_http_status,
    _eval_http_body,
    _http_sessions,
)
from zabbig_client.models import RESULT_OK, RESULT_FAILED


@pytest.fixture(autouse=True)
def clear_http_sessions():
    """Reset the HTTP session cache before each test to prevent cross-test bleed."""
    _http_sessions.clear()
    yield
    _http_sessions.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tcp_metric(**kwargs):
    params = {"mode": "tcp", "host": "127.0.0.1", "port": "9999"}
    params.update(kwargs)
    return make_metric(collector="probe", key="host.probe.tcp", params=params)


def _http_metric(**kwargs):
    params = {"mode": "http_status", "url": "http://example.com/"}
    params.update(kwargs)
    return make_metric(collector="probe", key="host.probe.http", params=params)


# ---------------------------------------------------------------------------
# TCP probe helpers
# ---------------------------------------------------------------------------

class TestRunTcpProbe:
    def test_success_returns_1(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric()
            results = _run_tcp_probe(metric)
        assert len(results) == 1
        assert results[0].value == "1"
        assert results[0].status == RESULT_OK

    def test_metric_host_name_on_result(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric()
            metric = make_metric(
                collector="probe",
                key="host.probe.tcp",
                params={"mode": "tcp", "host": "127.0.0.1", "port": "9999"},
                host_name="tcp-override",
            )
            results = _run_tcp_probe(metric)
        assert results[0].host_name == "tcp-override"

    def test_metric_host_name_none_by_default(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric()
            results = _run_tcp_probe(metric)
        assert results[0].host_name is None

    def test_rt_sub_key_uses_metric_host_name(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = make_metric(
                collector="probe",
                key="host.probe.tcp",
                params={"mode": "tcp", "host": "127.0.0.1", "port": "9999", "response_time_ms": True},
                host_name="tcp-override",
            )
            results = _run_tcp_probe(metric)
        rt_result = next(r for r in results if "response_time_ms" in r.key)
        assert rt_result.host_name == "tcp-override"

    def test_refused_returns_0(self):
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            metric = _tcp_metric()
            results = _run_tcp_probe(metric)
        assert results[0].value == "0"

    def test_timeout_returns_0(self):
        with patch("socket.create_connection", side_effect=socket.timeout):
            metric = _tcp_metric()
            results = _run_tcp_probe(metric)
        assert results[0].value == "0"

    def test_custom_on_success(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric(on_success=99)
            results = _run_tcp_probe(metric)
        assert results[0].value == "99"

    def test_custom_on_failure(self):
        with patch("socket.create_connection", side_effect=OSError):
            metric = _tcp_metric(on_failure=-1)
            results = _run_tcp_probe(metric)
        assert results[0].value == "-1"

    def test_response_time_sub_key_added(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric(response_time_ms=True)
            results = _run_tcp_probe(metric)
        assert len(results) == 2
        rt_result = results[1]
        assert "response_time_ms" in rt_result.key
        assert int(rt_result.value) >= 0

    def test_response_time_zero_on_failure(self):
        with patch("socket.create_connection", side_effect=OSError):
            metric = _tcp_metric(response_time_ms=True)
            results = _run_tcp_probe(metric)
        rt_result = next(r for r in results if "response_time_ms" in r.key)
        assert rt_result.value == "0"

    def test_no_response_time_by_default(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric()  # no response_time_ms param
            results = _run_tcp_probe(metric)
        assert len(results) == 1

    def test_result_collector_field(self):
        with patch("socket.create_connection", side_effect=OSError):
            metric = _tcp_metric()
            results = _run_tcp_probe(metric)
        assert results[0].collector == "probe"


# ---------------------------------------------------------------------------
# _eval_http_status
# ---------------------------------------------------------------------------

class TestEvalHttpStatus:
    def test_no_conditions_returns_default(self):
        # With no conditions, nothing matches, so default_value is returned
        value, host_name = _eval_http_status("200", [], "0")
        assert value == "0"
        assert host_name is None

    def test_no_conditions_catchall_returns_value(self):
        # A catch-all condition (no 'when') matches any input
        conds = [{"value": "200_raw"}]
        value, host_name = _eval_http_status("200", conds, "0")
        assert value == "200_raw"

    def test_matching_condition_returns_value(self):
        conds = [{"when": "200", "value": 1}]
        value, host_name = _eval_http_status("200", conds, "0")
        assert value == 1
        assert host_name is None

    def test_no_match_returns_default(self):
        conds = [{"when": "200", "value": 1}]
        value, host_name = _eval_http_status("404", conds, "0")
        assert value == "0"
        assert host_name is None

    def test_catchall_condition_matches(self):
        conds = [{"when": "200", "value": 1}, {"value": 0}]
        value, host_name = _eval_http_status("503", conds, "-1")
        assert value == 0

    def test_condition_host_name_returned(self):
        conds = [{"when": "200", "value": 1, "host_name": "web-ok"}, {"value": 0}]
        value, host_name = _eval_http_status("200", conds, "0")
        assert value == 1
        assert host_name == "web-ok"

    def test_no_condition_host_name_returns_none(self):
        conds = [{"when": "200", "value": 1}]
        value, host_name = _eval_http_status("200", conds, "0")
        assert host_name is None

    def test_no_match_host_name_is_none(self):
        conds = [{"when": "200", "value": 1, "host_name": "web-ok"}]
        value, host_name = _eval_http_status("404", conds, "0")
        assert host_name is None


# ---------------------------------------------------------------------------
# _eval_http_body
# ---------------------------------------------------------------------------

class TestEvalHttpBody:
    def test_matching_condition(self):
        conds = [{"when": "ok", "value": 1}, {"value": 0}]
        value, host_name = _eval_http_body("status: ok", r"status: (\w+)", conds, "last", "0")
        assert value == 1
        assert host_name is None

    def test_no_match_returns_default(self):
        conds = [{"when": "ok", "value": 1}]
        value, host_name = _eval_http_body("no match here", r"status: (\w+)", conds, "last", "0")
        assert value == "0"
        assert host_name is None

    def test_condition_host_name_returned(self):
        conds = [{"when": "ok", "value": 1, "host_name": "body-host"}, {"value": 0}]
        value, host_name = _eval_http_body("status: ok", r"status: (\w+)", conds, "last", "0")
        assert value == 1
        assert host_name == "body-host"

    def test_no_condition_host_name_none(self):
        conds = [{"when": "ok", "value": 1}]
        value, host_name = _eval_http_body("status: ok", r"status: (\w+)", conds, "last", "0")
        assert host_name is None


# ---------------------------------------------------------------------------
# HTTP probe helpers
# ---------------------------------------------------------------------------

def _make_fake_response(status_code=200, body=b"Hello World"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.encoding = "utf-8"
    resp.raw.read.return_value = body
    return resp


class TestRunHttpProbe:
    def test_http_status_no_conditions_returns_code(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(mode="http_status")
            results = _run_http_probe(metric)
        assert results[0].value == "200"

    def test_http_status_with_condition_match(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_status",
                conditions=[{"when": "200", "value": 1}, {"value": 0}],
            )
            results = _run_http_probe(metric)
        assert results[0].value == "1"

    def test_http_status_404_with_condition(self):
        resp = _make_fake_response(404)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_status",
                conditions=[{"when": "200", "value": 1}, {"value": 0}],
            )
            results = _run_http_probe(metric)
        assert results[0].value == "0"

    def test_connect_failure_returns_default(self):
        with patch("requests.Session.request", side_effect=Exception("connection refused")):
            metric = _http_metric(mode="http_status", default_value=99)
            results = _run_http_probe(metric)
        assert results[0].value == "99"

    def test_http_body_match(self):
        resp = _make_fake_response(200, body=b"status: ok\n")
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_body",
                match=r"status",
                conditions=[{"when": "ok", "value": 1}, {"value": 0}],
                default_value=0,
            )
            results = _run_http_probe(metric)
        assert results[0].value == "1"

    def test_http_body_no_match_returns_default(self):
        resp = _make_fake_response(200, body=b"status: degraded\n")
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_body",
                match=r"nonexistent_pattern",
                conditions=[{"when": "ok", "value": 1}],
                default_value=0,
            )
            results = _run_http_probe(metric)
        assert results[0].value == "0"

    def test_response_time_sub_key(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(mode="http_status", response_time_ms=True)
            results = _run_http_probe(metric)
        assert len(results) == 2
        rt = next(r for r in results if "response_time_ms" in r.key)
        assert int(rt.value) >= 0

    def test_ssl_check_sub_key_added(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp), \
             patch("zabbig_client.collectors.probe._ssl_cert_check", return_value=1):
            metric = _http_metric(mode="http_status", ssl_check=True)
            results = _run_http_probe(metric)
        ssl_result = next(r for r in results if "ssl_check" in r.key)
        assert ssl_result.value == "1"

    def test_ssl_check_invalid_cert_returns_0(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp), \
             patch("zabbig_client.collectors.probe._ssl_cert_check", return_value=0):
            metric = _http_metric(mode="http_status", ssl_check=True)
            results = _run_http_probe(metric)
        ssl_result = next(r for r in results if "ssl_check" in r.key)
        assert ssl_result.value == "0"

    def test_condition_host_name_on_primary_result(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_status",
                conditions=[{"when": "200", "value": 1, "host_name": "web-ok"}, {"value": 0}],
            )
            results = _run_http_probe(metric)
        assert results[0].host_name == "web-ok"

    def test_metric_host_name_used_when_no_condition_override(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = make_metric(
                collector="probe",
                key="host.probe.http",
                params={"mode": "http_status", "url": "http://example.com/"},
                host_name="metric-override",
            )
            results = _run_http_probe(metric)
        assert results[0].host_name == "metric-override"

    def test_sub_key_uses_metric_host_name_not_condition(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = make_metric(
                collector="probe",
                key="host.probe.http",
                params={
                    "mode": "http_status",
                    "url": "http://example.com/",
                    "response_time_ms": True,
                    "conditions": [{"when": "200", "value": 1, "host_name": "web-cond"}, {"value": 0}],
                },
                host_name="metric-override",
            )
            results = _run_http_probe(metric)
        rt_result = next(r for r in results if "response_time_ms" in r.key)
        # sub-keys use metric host_name, not condition host_name
        assert rt_result.host_name == "metric-override"

    def test_http_body_condition_host_name_on_result(self):
        resp = _make_fake_response(200, body=b"status: ok\n")
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_body",
                match=r"status: (\w+)",
                conditions=[{"when": "ok", "value": 1, "host_name": "body-host"}, {"value": 0}],
                default_value=0,
            )
            results = _run_http_probe(metric)
        assert results[0].host_name == "body-host"


# ---------------------------------------------------------------------------
# SSL cert check
# ---------------------------------------------------------------------------

class TestSslCertCheck:
    def test_valid_cert_returns_1(self):
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_ctx.wrap_socket.return_value = mock_sock

        with patch("ssl.create_default_context", return_value=mock_ctx):
            result = _ssl_cert_check("example.com", 443, 5.0)
        assert result == 1

    def test_invalid_cert_returns_0(self):
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.side_effect = ssl.SSLCertVerificationError

        with patch("ssl.create_default_context", return_value=mock_ctx):
            result = _ssl_cert_check("badcert.example.com", 443, 5.0)
        assert result == 0

    def test_unreachable_returns_2(self):
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.side_effect = OSError("connection refused")

        with patch("ssl.create_default_context", return_value=mock_ctx):
            result = _ssl_cert_check("unreachable.example.com", 443, 5.0)
        assert result == 2


# ---------------------------------------------------------------------------
# ProbeCollector async entrypoint
# ---------------------------------------------------------------------------

class TestProbeCollector:
    async def test_tcp_returns_list(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric()
            results = await ProbeCollector().collect(metric)
        assert isinstance(results, list)
        assert len(results) >= 1

    async def test_http_status_returns_list(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(mode="http_status")
            results = await ProbeCollector().collect(metric)
        assert isinstance(results, list)
        assert results[0].status == RESULT_OK

    async def test_unknown_mode_raises(self):
        metric = _tcp_metric(mode="ftp")
        with pytest.raises(ValueError, match="Unknown probe mode"):
            await ProbeCollector().collect(metric)

    async def test_tcp_with_all_sub_keys(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            metric = _tcp_metric(response_time_ms=True)
            results = await ProbeCollector().collect(metric)
        assert len(results) == 2
        keys = [r.key for r in results]
        assert any("response_time_ms" in k for k in keys)

    async def test_condition_host_name_propagated_to_result(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(
                mode="http_status",
                conditions=[{"when": "200", "value": 1, "host_name": "cond-host"}, {"value": 0}],
            )
            results = await ProbeCollector().collect(metric)
        assert results[0].host_name == "cond-host"

    async def test_metric_host_name_propagated_to_result(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = make_metric(
                collector="probe",
                key="host.probe.http",
                params={"mode": "http_status", "url": "http://example.com/"},
                host_name="async-override",
            )
            results = await ProbeCollector().collect(metric)
        assert results[0].host_name == "async-override"

    async def test_no_host_name_override_result_is_none(self):
        resp = _make_fake_response(200)
        with patch("requests.Session.request", return_value=resp):
            metric = _http_metric(mode="http_status")
            results = await ProbeCollector().collect(metric)
        assert results[0].host_name is None
