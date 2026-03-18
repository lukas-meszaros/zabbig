"""
tests/test_config.py — Unit tests for the Config class.
"""

import os

import pytest

from zabbix_sender.config import Config


class TestConfig:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("ZABBIX_SERVER", raising=False)
        monkeypatch.delenv("ZABBIX_PORT", raising=False)
        monkeypatch.delenv("ZABBIX_TIMEOUT", raising=False)
        cfg = Config()
        assert cfg.server == "127.0.0.1"
        assert cfg.port == 10051
        assert cfg.timeout == 10.0

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ZABBIX_SERVER", "192.168.1.50")
        monkeypatch.setenv("ZABBIX_PORT", "10052")
        monkeypatch.setenv("ZABBIX_TIMEOUT", "30")
        cfg = Config()
        assert cfg.server == "192.168.1.50"
        assert cfg.port == 10052
        assert cfg.timeout == 30.0

    def test_explicit_args_override_env(self, monkeypatch):
        monkeypatch.setenv("ZABBIX_SERVER", "192.168.1.50")
        cfg = Config(server="10.0.0.1", port=9999, timeout=5.0)
        assert cfg.server == "10.0.0.1"
        assert cfg.port == 9999
        assert cfg.timeout == 5.0

    def test_repr(self):
        cfg = Config(server="127.0.0.1", port=10051)
        r = repr(cfg)
        assert "127.0.0.1" in r
        assert "10051" in r
