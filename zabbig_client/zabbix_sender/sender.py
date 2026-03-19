"""
sender.py — High-level Zabbix sender interface.

Usage example:

    from zabbix_sender import ZabbixSender, SenderItem

    sender = ZabbixSender(server="127.0.0.1", port=10051)

    items = [
        SenderItem(host="macos-local-sender", key="macos.heartbeat", value="1"),
        SenderItem(host="macos-local-sender", key="macos.status", value="0"),
    ]

    response = sender.send(items)
    print(response)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .protocol import ZabbixProtocol, ZabbixResponse

log = logging.getLogger(__name__)


@dataclass
class SenderItem:
    """A single data point to send to Zabbix."""

    host: str
    key: str
    value: str
    clock: Optional[int] = None   # Unix timestamp; None = let server assign
    ns: int = 0                   # Nanoseconds sub-second precision

    def to_dict(self) -> dict:
        d: dict = {"host": self.host, "key": self.key, "value": self.value}
        if self.clock is not None:
            d["clock"] = self.clock
            d["ns"] = self.ns
        return d


class ZabbixSender:
    """
    High-level Zabbix sender.

    Builds the protocol payload, delegates to ZabbixProtocol for the
    actual TCP communication, and returns a ZabbixResponse.
    """

    def __init__(
        self,
        server: str = "127.0.0.1",
        port: int = 10051,
        timeout: float = 10.0,
    ) -> None:
        self.server = server
        self.port = port
        self.timeout = timeout

    def send(self, items: list[SenderItem], dry_run: bool = False) -> ZabbixResponse:
        """
        Send a list of SenderItems to the Zabbix server.

        Args:
            items:    List of SenderItem objects.
            dry_run:  If True, log what would be sent but don't open a connection.

        Returns:
            ZabbixResponse with parsed result.
        """
        if not items:
            raise ValueError("No items to send.")

        now = int(time.time())
        payload = {
            "request": "sender data",
            "data": [item.to_dict() for item in items],
            "clock": now,
            "ns": 0,
        }

        log.debug("Payload to send: %s", payload)

        if dry_run:
            log.info("[dry-run] Would send %d item(s) to %s:%d:", len(items), self.server, self.port)
            for item in items:
                log.info("[dry-run]   host=%-30s  key=%-30s  value=%s", item.host, item.key, item.value)
            # Return a synthetic success response
            return ZabbixResponse(
                response="success",
                info=f"processed: {len(items)}; failed: 0; total: {len(items)}; seconds spent: 0",
                processed=len(items),
                failed=0,
                total=len(items),
            )

        log.info("Sending %d item(s) to %s:%d ...", len(items), self.server, self.port)

        with ZabbixProtocol(self.server, self.port, self.timeout) as proto:
            response = proto.send(payload)

        log.debug("Response: %s", response)
        return response
