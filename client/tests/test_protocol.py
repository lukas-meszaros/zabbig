"""
tests/test_protocol.py — Unit tests for the low-level Zabbix sender protocol.

These tests exercise encode/decode logic without any network connections.
"""

import json
import struct

import pytest

from zabbix_sender.protocol import (
    ZABBIX_HEADER,
    ZABBIX_PROTOCOL_VERSION,
    ZabbixProtocol,
    ZabbixResponse,
)


# ---------------------------------------------------------------------------
# ZabbixResponse
# ---------------------------------------------------------------------------


class TestZabbixResponse:
    def test_success_response(self):
        data = {
            "response": "success",
            "info": "processed: 3; failed: 0; total: 3; seconds spent: 0.000123",
        }
        r = ZabbixResponse.from_dict(data)
        assert r.response == "success"
        assert r.processed == 3
        assert r.failed == 0
        assert r.total == 3
        assert r.success is True

    def test_partial_failure(self):
        data = {
            "response": "success",
            "info": "processed: 2; failed: 1; total: 3; seconds spent: 0.000100",
        }
        r = ZabbixResponse.from_dict(data)
        assert r.processed == 2
        assert r.failed == 1
        assert r.success is False  # failed > 0

    def test_failed_response(self):
        data = {"response": "failed", "info": ""}
        r = ZabbixResponse.from_dict(data)
        assert r.success is False

    def test_str(self):
        r = ZabbixResponse(response="success", info="processed: 1; failed: 0; total: 1")
        assert "success" in str(r)

    def test_empty_info(self):
        data = {"response": "success", "info": ""}
        r = ZabbixResponse.from_dict(data)
        assert r.processed == 0
        assert r.failed == 0
        assert r.total == 0


# ---------------------------------------------------------------------------
# ZabbixProtocol.encode_frame
# ---------------------------------------------------------------------------


class TestEncodeFrame:
    def test_header_magic(self):
        payload = {"request": "sender data", "data": []}
        frame = ZabbixProtocol.encode_frame(payload)
        assert frame[:4] == ZABBIX_HEADER

    def test_header_version(self):
        payload = {"request": "sender data", "data": []}
        frame = ZabbixProtocol.encode_frame(payload)
        assert frame[4] == ZABBIX_PROTOCOL_VERSION

    def test_body_length_field(self):
        payload = {"request": "sender data", "data": []}
        frame = ZabbixProtocol.encode_frame(payload)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        declared_length = struct.unpack("<Q", frame[5:13])[0]
        assert declared_length == len(body)

    def test_body_content(self):
        payload = {"request": "sender data", "data": [{"host": "h", "key": "k", "value": "v"}]}
        frame = ZabbixProtocol.encode_frame(payload)
        # body starts at byte 13
        body = frame[13:]
        decoded = json.loads(body.decode("utf-8"))
        assert decoded == payload

    def test_roundtrip(self):
        payload = {
            "request": "sender data",
            "data": [{"host": "my-host", "key": "my.key", "value": "42"}],
            "clock": 1700000000,
            "ns": 0,
        }
        frame = ZabbixProtocol.encode_frame(payload)
        decoded = ZabbixProtocol.decode_frame(frame)
        assert decoded == payload


# ---------------------------------------------------------------------------
# ZabbixProtocol.decode_frame
# ---------------------------------------------------------------------------


class TestDecodeFrame:
    def _make_frame(self, payload: dict) -> bytes:
        return ZabbixProtocol.encode_frame(payload)

    def test_decode_success(self):
        payload = {"response": "success", "info": "processed: 1; failed: 0; total: 1"}
        frame = self._make_frame(payload)
        result = ZabbixProtocol.decode_frame(frame)
        assert result == payload

    def test_invalid_magic(self):
        payload = {"response": "success", "info": ""}
        frame = bytearray(self._make_frame(payload))
        frame[0] = ord("X")  # corrupt magic byte
        with pytest.raises(ValueError, match="Invalid Zabbix header magic"):
            ZabbixProtocol.decode_frame(bytes(frame))

    def test_too_short(self):
        with pytest.raises(ValueError, match="Response too short"):
            ZabbixProtocol.decode_frame(b"ZBXD\x01")
