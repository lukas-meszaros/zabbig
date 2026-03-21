"""
test_zabbix_common.py — Tests for zabbix_update/_common.py shared utilities.
"""
import os
from unittest.mock import patch, MagicMock

import pytest

import _common
from _common import (
    ZabbixAPI,
    YAML_VT_MAP,
    SEVERITY_MAP,
    VT_FLOAT,
    VT_INT,
    VT_TEXT,
    load_yaml,
    server_host_from_config,
    load_metrics,
    resolve_credentials,
    base_arg_parser,
    wait_for_api,
)


class TestLoadYaml:
    def test_load_valid_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("key: value\nlist:\n  - a\n  - b\n")
        result = load_yaml(str(f))
        assert result == {"key": "value", "list": ["a", "b"]}

    def test_load_empty_yaml(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        result = load_yaml(str(f))
        assert result == {}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_yaml(str(tmp_path / "nonexistent.yaml"))


class TestServerHostFromConfig:
    def test_reads_server_host(self, tmp_path):
        cfg = tmp_path / "client.yaml"
        cfg.write_text("zabbix:\n  server_host: 192.168.1.100\n")
        result = server_host_from_config(str(cfg))
        assert result == "192.168.1.100"

    def test_missing_file_returns_default(self, tmp_path):
        result = server_host_from_config(str(tmp_path / "missing.yaml"))
        assert result == "127.0.0.1"

    def test_missing_key_returns_default(self, tmp_path):
        cfg = tmp_path / "client.yaml"
        cfg.write_text("zabbix: {}\n")
        result = server_host_from_config(str(cfg))
        assert result == "127.0.0.1"


class TestLoadMetrics:
    def _write_metrics(self, tmp_path, content):
        f = tmp_path / "metrics.yaml"
        f.write_text(content)
        return str(f)

    def test_returns_all_metrics_by_default(self, tmp_path):
        path = self._write_metrics(tmp_path, """
metrics:
  - id: m1
    key: host.cpu
    enabled: true
  - id: m2
    key: host.mem
    enabled: false
""")
        result = load_metrics(path)
        assert len(result) == 2

    def test_only_enabled_filter(self, tmp_path):
        path = self._write_metrics(tmp_path, """
metrics:
  - id: m1
    key: host.cpu
    enabled: true
  - id: m2
    key: host.mem
    enabled: false
""")
        result = load_metrics(path, only_enabled=True)
        assert len(result) == 1
        assert result[0]["key"] == "host.cpu"

    def test_skips_metrics_without_key(self, tmp_path):
        path = self._write_metrics(tmp_path, """
metrics:
  - id: no_key_metric
  - id: with_key
    key: host.disk
""")
        result = load_metrics(path)
        assert len(result) == 1
        assert result[0]["key"] == "host.disk"

    def test_empty_metrics_section(self, tmp_path):
        path = self._write_metrics(tmp_path, "metrics: []\n")
        assert load_metrics(path) == []

    def test_enabled_defaults_to_true(self, tmp_path):
        """Metrics without 'enabled' field should be included by default."""
        path = self._write_metrics(tmp_path, """
metrics:
  - id: m1
    key: host.cpu
""")
        assert len(load_metrics(path, only_enabled=True)) == 1


class TestYamlVtMap:
    def test_float_maps_to_0(self):
        assert YAML_VT_MAP["float"] == VT_FLOAT == 0

    def test_int_maps_to_3(self):
        assert YAML_VT_MAP["int"] == VT_INT == 3

    def test_string_maps_to_4(self):
        assert YAML_VT_MAP["string"] == VT_TEXT == 4


class TestSeverityMap:
    def test_all_severities_present(self):
        assert SEVERITY_MAP["not_classified"] == 0
        assert SEVERITY_MAP["info"] == 1
        assert SEVERITY_MAP["warning"] == 2
        assert SEVERITY_MAP["average"] == 3
        assert SEVERITY_MAP["high"] == 4
        assert SEVERITY_MAP["disaster"] == 5


class TestZabbixAPICall:
    def _make_api(self):
        api = ZabbixAPI("http://test.example.com/api_jsonrpc.php")
        return api

    def _mock_response(self, result_data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"jsonrpc": "2.0", "result": result_data, "id": 1}
        resp.raise_for_status = MagicMock()
        return resp

    def test_call_returns_result(self):
        api = self._make_api()
        resp = self._mock_response({"test": "value"})
        with patch.object(api._session, "post", return_value=resp):
            result = api._call("test.method", {})
        assert result == {"test": "value"}

    def test_call_raises_on_api_error(self):
        api = self._make_api()
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "jsonrpc": "2.0",
            "error": {"code": -32602, "message": "Invalid params", "data": "details"},
            "id": 1,
        }
        with patch.object(api._session, "post", return_value=resp):
            with pytest.raises(RuntimeError, match="Zabbix API error"):
                api._call("test.method", {})

    def test_login_sets_auth(self):
        api = self._make_api()
        resp = self._mock_response("auth_token_12345")
        with patch.object(api._session, "post", return_value=resp):
            api.login("Admin", "password")
        assert api.auth == "auth_token_12345"

    def test_logout_clears_auth(self):
        api = self._make_api()
        api.auth = "some_token"
        resp = self._mock_response(True)
        with patch.object(api._session, "post", return_value=resp):
            api.logout()
        assert api.auth is None

    def test_logout_when_not_logged_in(self):
        """Logout should be a no-op when auth is None."""
        api = self._make_api()
        api.logout()  # should not raise
        assert api.auth is None

    def test_auth_included_in_payload(self):
        api = self._make_api()
        api.auth = "mytoken"
        resp = self._mock_response([])

        captured = {}
        def capture_post(url, json=None, **kwargs):
            captured["payload"] = json
            return resp

        with patch.object(api._session, "post", side_effect=capture_post):
            api._call("host.get", {})
        assert captured["payload"]["auth"] == "mytoken"


class TestBaseArgParser:
    def test_has_api_url_arg(self):
        parser = base_arg_parser("test")
        args = parser.parse_args(["--api-url", "http://myhost/api"])
        assert args.api_url == "http://myhost/api"

    def test_has_user_arg(self):
        parser = base_arg_parser("test")
        args = parser.parse_args(["--user", "admin"])
        assert args.user == "admin"

    def test_has_password_arg(self):
        parser = base_arg_parser("test")
        args = parser.parse_args(["--password", "secret"])
        assert args.password == "secret"

    def test_has_no_wait_flag(self):
        parser = base_arg_parser("test")
        args = parser.parse_args(["--no-wait"])
        assert args.no_wait is True

    def test_defaults_all_none(self):
        parser = base_arg_parser("test")
        args = parser.parse_args([])
        assert args.api_url is None
        assert args.user is None
        assert args.password is None
        assert args.no_wait is False


class TestResolveCredentials:
    def test_cli_args_take_priority(self):
        user, password = resolve_credentials("cli_user", "cli_pass")
        assert user == "cli_user"
        assert password == "cli_pass"

    def test_env_vars_used_when_no_args(self):
        with patch.dict(os.environ, {"ZABBIX_ADMIN_USER": "env_user", "ZABBIX_ADMIN_PASSWORD": "env_pass"}):
            user, password = resolve_credentials(None, None)
        assert user == "env_user"
        assert password == "env_pass"

    def test_cli_arg_overrides_env(self):
        with patch.dict(os.environ, {"ZABBIX_ADMIN_USER": "env_user", "ZABBIX_ADMIN_PASSWORD": "env_pass"}):
            user, password = resolve_credentials("cli_user", "cli_pass")
        assert user == "cli_user"
        assert password == "cli_pass"


class TestWaitForApi:
    def test_returns_when_api_responds(self):
        resp = MagicMock()
        resp.status_code = 200
        import requests as req
        with patch("requests.get", return_value=resp):
            wait_for_api("http://localhost/api_jsonrpc.php", max_wait=5)

    def test_raises_when_timeout_exceeded(self):
        import requests as req
        with patch("requests.get", side_effect=req.RequestException("refused")), \
             patch("time.sleep"):
            with pytest.raises(RuntimeError, match="did not respond within"):
                wait_for_api("http://localhost/api_jsonrpc.php", max_wait=0)
