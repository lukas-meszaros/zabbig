"""
zabbix_sender — Python client for sending values to Zabbix trapper items.

Design: Direct protocol implementation (no external binaries required).
        Uses the stdlib socket module only — zero runtime dependencies.
"""

from .protocol import ZabbixProtocol, ZabbixResponse
from .sender import ZabbixSender, SenderItem

__all__ = ["ZabbixProtocol", "ZabbixResponse", "ZabbixSender", "SenderItem"]
__version__ = "0.1.0"
