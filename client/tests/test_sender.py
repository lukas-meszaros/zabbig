"""
tests/test_sender.py — Unit tests for the high-level ZabbixSender.

Uses monkeypatching to avoid real network connections.
"""

import pytest

from zabbix_sender.protocol import ZabbixResponse
from zabbix_sender.sender import SenderItem, ZabbixSender


# ---------------------------------------------------------------------------
# SenderItem
# ---------------------------------------------------------------------------


class TestSenderItem:
    def test_to_dict_without_clock(self):
        item = SenderItem(host="h", key="k", value="v")
        d = item.to_dict()
        assert d == {"host": "h", "key": "k", "value": "v"}
        assert "clock" not in d

    def test_to_dict_with_clock(self):
        item = SenderItem(host="h", key="k", value="v", clock=1700000000, ns=123)
        d = item.to_dict()
        assert d["clock"] == 1700000000
        assert d["ns"] == 123

    def test_value_is_string(self):
        item = SenderItem(host="h", key="k", value="42")
        assert isinstance(item.to_dict()["value"], str)


# ---------------------------------------------------------------------------
# ZabbixSender
# ---------------------------------------------------------------------------


class TestZabbixSender:
    def test_dry_run_returns_success(self):
        sender = ZabbixSender()
        items = [SenderItem(host="h", key="k", value="1")]
        resp = sender.send(items, dry_run=True)
        assert resp.success is True
        assert resp.processed == 1
        assert resp.failed == 0

    def test_dry_run_multiple_items(self):
        sender = ZabbixSender()
        items = [
            SenderItem(host="h", key="k1", value="1"),
            SenderItem(host="h", key="k2", value="2"),
            SenderItem(host="h", key="k3", value="3"),
        ]
        resp = sender.send(items, dry_run=True)
        assert resp.processed == 3

    def test_empty_items_raises(self):
        sender = ZabbixSender()
        with pytest.raises(ValueError, match="No items to send"):
            sender.send([], dry_run=True)

    def test_send_uses_protocol(self, monkeypatch):
        """Test that send() delegates correctly to ZabbixProtocol."""
        calls = []
        fake_response = ZabbixResponse(
            response="success",
            info="processed: 1; failed: 0; total: 1",
            processed=1,
            failed=0,
            total=1,
        )

        class FakeProtocol:
            def __init__(self, server, port, timeout):
                calls.append(("init", server, port, timeout))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def send(self, payload):
                calls.append(("send", payload))
                return fake_response

        import zabbix_sender.sender as sender_module
        monkeypatch.setattr(sender_module, "ZabbixProtocol", FakeProtocol)

        sender = ZabbixSender(server="10.0.0.1", port=10051, timeout=5.0)
        items = [SenderItem(host="myhost", key="mykey", value="99")]
        resp = sender.send(items)

        assert resp.success is True
        assert len(calls) == 2
        assert calls[0] == ("init", "10.0.0.1", 10051, 5.0)
        send_call_payload = calls[1][1]
        assert send_call_payload["request"] == "sender data"
        assert send_call_payload["data"][0]["host"] == "myhost"
        assert send_call_payload["data"][0]["key"] == "mykey"
        assert send_call_payload["data"][0]["value"] == "99"
