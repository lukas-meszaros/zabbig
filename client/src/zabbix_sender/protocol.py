"""
protocol.py — Low-level Zabbix sender protocol implementation.

The Zabbix sender protocol (TCP, port 10051):

  Request frame:
    ZBXD\x01                   – 5-byte magic header
    <length: uint64 LE>        – 8-byte payload length
    <json payload>

  The JSON request body:
    {
        "request": "sender data",
        "data": [
            {
                "host":  "<zabbix host name>",
                "key":   "<item key>",
                "value": "<string value>",
                "clock": <unix timestamp>,   // optional
                "ns":    <nanoseconds>        // optional
            }
        ],
        "clock": <unix timestamp>,
        "ns":    <nanoseconds>
    }

  Response frame (same framing):
    {
        "response": "success",
        "info": "processed: N; failed: M; total: T; seconds spent: S"
    }

Reference: https://www.zabbix.com/documentation/current/en/manual/appendix/protocols/header_datalen
"""

import json
import logging
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Protocol constants
ZABBIX_HEADER = b"ZBXD"
ZABBIX_PROTOCOL_VERSION = 0x01
# Minimum header: 4 (ZBXD) + 1 (version) + 8 (data length) + 4 (reserved) = 17 bytes
HEADER_SIZE = 13  # 4 + 1 + 8 (Zabbix ≥ 6.0 uses 13-byte header)
MAX_RESPONSE_SIZE = 128 * 1024  # 128 KB safety cap


@dataclass
class ZabbixResponse:
    """Parsed response from the Zabbix server."""

    response: str         # "success" or "failed"
    info: str             # raw info string, e.g. "processed: 1; failed: 0; ..."
    processed: int = 0
    failed: int = 0
    total: int = 0

    @property
    def success(self) -> bool:
        return self.response == "success" and self.failed == 0

    def __str__(self) -> str:
        return f"ZabbixResponse(response={self.response!r}, info={self.info!r})"

    @classmethod
    def from_dict(cls, data: dict) -> "ZabbixResponse":
        info = data.get("info", "")
        processed = failed = total = 0
        for part in info.split(";"):
            part = part.strip()
            if part.startswith("processed:"):
                processed = int(part.split(":")[1].strip())
            elif part.startswith("failed:"):
                failed = int(part.split(":")[1].strip())
            elif part.startswith("total:"):
                total = int(part.split(":")[1].strip())
        return cls(
            response=data.get("response", ""),
            info=info,
            processed=processed,
            failed=failed,
            total=total,
        )


class ZabbixProtocol:
    """
    Handles the Zabbix sender wire protocol.

    Usage:
        with ZabbixProtocol("127.0.0.1", 10051, timeout=10) as proto:
            response = proto.send(payload_dict)
    """

    def __init__(self, server: str, port: int, timeout: float = 10.0) -> None:
        self.server = server
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------ #
    # Context manager                                                       #
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "ZabbixProtocol":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                                  #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        log.debug("Connecting to %s:%d (timeout=%.1fs)", self.server, self.port, self.timeout)
        self._sock = socket.create_connection(
            (self.server, self.port), timeout=self.timeout
        )
        log.debug("Connected.")

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            log.debug("Connection closed.")

    # ------------------------------------------------------------------ #
    # Wire-level encode / decode                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def encode_frame(payload: dict) -> bytes:
        """Encode a dict as a Zabbix sender protocol frame."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        # Header: ZBXD (4) + version (1) + body length uint64 LE (8) = 13 bytes total
        header = (
            ZABBIX_HEADER
            + bytes([ZABBIX_PROTOCOL_VERSION])
            + struct.pack("<Q", len(body))  # uint64 LE
        )
        log.debug("Encoding frame: header=%d bytes, body=%d bytes", len(header), len(body))
        return header + body

    @staticmethod
    def decode_frame(data: bytes) -> dict:
        """Decode a raw Zabbix response frame into a dict."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Response too short: {len(data)} bytes")

        magic = data[:4]
        if magic != ZABBIX_HEADER:
            raise ValueError(f"Invalid Zabbix header magic: {magic!r}")

        # version = data[4]
        length = struct.unpack("<Q", data[5:13])[0]  # uint64 LE
        body = data[13:13 + length]
        log.debug("Decoded frame: body length=%d bytes", len(body))
        return json.loads(body.decode("utf-8"))

    # ------------------------------------------------------------------ #
    # Send / receive                                                        #
    # ------------------------------------------------------------------ #

    def send(self, payload: dict) -> ZabbixResponse:
        """Send a payload dict and return a parsed ZabbixResponse."""
        if not self._sock:
            raise RuntimeError("Not connected. Call connect() or use as context manager.")

        frame = self.encode_frame(payload)
        log.debug("Sending %d bytes...", len(frame))
        self._sock.sendall(frame)

        raw = self._recv_all()
        data = self.decode_frame(raw)
        log.debug("Received response: %s", data)
        return ZabbixResponse.from_dict(data)

    def _recv_all(self) -> bytes:
        """Read the full response from the socket."""
        if not self._sock:
            raise RuntimeError("Not connected.")

        # Read header first to get declared body length
        header = b""
        while len(header) < HEADER_SIZE:
            chunk = self._sock.recv(HEADER_SIZE - len(header))
            if not chunk:
                break
            header += chunk

        if len(header) < HEADER_SIZE:
            raise ValueError(f"Incomplete header received: {len(header)} bytes")

        magic = header[:4]
        if magic != ZABBIX_HEADER:
            raise ValueError(f"Invalid Zabbix header magic: {magic!r}")

        body_length = struct.unpack("<Q", header[5:13])[0]
        if body_length > MAX_RESPONSE_SIZE:
            raise ValueError(f"Response body too large: {body_length} bytes")

        body = b""
        while len(body) < body_length:
            chunk = self._sock.recv(body_length - len(body))
            if not chunk:
                break
            body += chunk

        return header + body
