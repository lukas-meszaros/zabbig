"""
tests/test_cli.py — Unit tests for the CLI interface.

Uses monkeypatching to avoid real network connections.
"""

import pytest

from zabbix_sender.cli import build_parser, main
from zabbix_sender.protocol import ZabbixResponse


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["--host", "h", "--key", "k", "--value", "v"])
        assert args.host == "h"
        assert args.keys == ["k"]
        assert args.values == ["v"]
        assert args.dry_run is False
        assert args.verbose is False
        assert args.server is None
        assert args.port is None

    def test_multiple_key_value(self):
        parser = build_parser()
        args = parser.parse_args([
            "--host", "h",
            "--key", "k1", "--value", "v1",
            "--key", "k2", "--value", "v2",
        ])
        assert args.keys == ["k1", "k2"]
        assert args.values == ["v1", "v2"]

    def test_dry_run_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--host", "h", "--key", "k", "--value", "v", "--dry-run"])
        assert args.dry_run is True

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--host", "h", "--key", "k", "--value", "v", "--verbose"])
        assert args.verbose is True


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_dry_run_success(self):
        """Dry-run mode should succeed without any network call."""
        rc = main([
            "--host", "macos-local-sender",
            "--key", "macos.heartbeat",
            "--value", "1",
            "--dry-run",
        ])
        assert rc == 0

    def test_key_value_mismatch_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([
                "--host", "h",
                "--key", "k1",
                "--key", "k2",
                "--value", "v1",
                "--dry-run",
            ])
        assert exc.value.code != 0

    def test_missing_host_exits(self, monkeypatch, capsys):
        monkeypatch.delenv("ZABBIX_HOST", raising=False)
        with pytest.raises(SystemExit) as exc:
            main(["--key", "k", "--value", "v", "--dry-run"])
        assert exc.value.code != 0

    def test_no_keys_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--host", "h", "--dry-run"])
        assert exc.value.code != 0

    def test_send_failure_returns_nonzero(self, monkeypatch):
        """If send raises, main() returns exit code 1."""
        import zabbix_sender.cli as cli_module

        def fake_send(items, dry_run=False):
            raise ConnectionRefusedError("refused")

        class FakeSender:
            def __init__(self, **kwargs):
                pass

            def send(self, items, dry_run=False):
                raise ConnectionRefusedError("refused")

        monkeypatch.setattr(cli_module, "ZabbixSender", FakeSender)

        rc = main(["--host", "h", "--key", "k", "--value", "v"])
        assert rc == 1
