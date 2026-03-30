"""
test_probe_session.py — Tests for HTTP session reuse in the probe collector.
"""
import pytest
from unittest.mock import MagicMock, patch

from zabbig_client.collectors.probe import _http_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metric(url="http://example.com/health", mode="http_status", conditions=None):
    from zabbig_client.models import MetricDef
    return MetricDef(
        id="test_probe",
        name="Test probe",
        enabled=True,
        collector="probe",
        key="test.probe",
        delivery="immediate",
        timeout_seconds=5.0,
        error_policy="skip",
        params={
            "mode": mode,
            "url": url,
            **({"conditions": conditions} if conditions else {}),
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHttpSessionReuse:
    def setup_method(self):
        _http_sessions.clear()

    def teardown_method(self):
        _http_sessions.clear()

    def test_session_created_on_first_request(self):
        """A session is created and stored in _http_sessions after the first call."""
        import requests as req_module

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_resp_obj = MagicMock()

        metric = _make_metric()

        with patch.object(req_module.Session, "request", return_value=mock_response) as mock_req:
            from zabbig_client.collectors.probe import _run_http_probe
            _run_http_probe(metric)

        assert len(_http_sessions) == 1
        key = ("http", "example.com", 80)
        assert key in _http_sessions

    def test_same_session_reused_second_call(self):
        """The same Session object is reused for requests to the same (scheme, host, port)."""
        import requests as req_module

        mock_response = MagicMock()
        mock_response.status_code = 200
        metric = _make_metric()

        with patch.object(req_module.Session, "request", return_value=mock_response):
            from zabbig_client.collectors.probe import _run_http_probe
            _run_http_probe(metric)
            first_session = _http_sessions.get(("http", "example.com", 80))
            _run_http_probe(metric)
            second_session = _http_sessions.get(("http", "example.com", 80))

        assert first_session is second_session

    def test_different_hosts_get_different_sessions(self):
        """Requests to different hosts get separate cached sessions."""
        import requests as req_module

        mock_response = MagicMock()
        mock_response.status_code = 200
        metric_a = _make_metric(url="http://host-a.example.com/")
        metric_b = _make_metric(url="http://host-b.example.com/")

        with patch.object(req_module.Session, "request", return_value=mock_response):
            from zabbig_client.collectors.probe import _run_http_probe
            _run_http_probe(metric_a)
            _run_http_probe(metric_b)

        assert len(_http_sessions) == 2
        assert ("http", "host-a.example.com", 80) in _http_sessions
        assert ("http", "host-b.example.com", 80) in _http_sessions

    def test_https_uses_port_443_key(self):
        """HTTPS URLs default to port 443 for the session cache key."""
        import requests as req_module

        mock_response = MagicMock()
        mock_response.status_code = 200
        metric = _make_metric(url="https://secure.example.com/api")

        with patch.object(req_module.Session, "request", return_value=mock_response):
            from zabbig_client.collectors.probe import _run_http_probe
            _run_http_probe(metric)

        assert ("https", "secure.example.com", 443) in _http_sessions

    def test_connection_failure_does_not_store_bad_session(self):
        """Even when a request fails (exception), a session object is still cached
        (it's the Session itself, not the connection, that goes bad)."""
        import requests as req_module

        metric = _make_metric()

        with patch.object(req_module.Session, "request", side_effect=ConnectionError("refused")):
            from zabbig_client.collectors.probe import _run_http_probe
            results = _run_http_probe(metric)

        # We still get a result (default_value=0)
        assert results[0].value == "0"
        # Session remains in cache for potential retry
        assert ("http", "example.com", 80) in _http_sessions
