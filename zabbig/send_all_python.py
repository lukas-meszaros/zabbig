#!/usr/bin/env python3
"""
examples/sender/send_all_python.py — Send all starter items using the Python client.

This is a standalone usage example.  The actual sender logic lives in
client/src/zabbix_sender/.

Usage (from repo root, with the client package installed):
    cd client && pip install -e .
    cd ..
    python3 examples/sender/send_all_python.py

Or directly with env vars:
    ZABBIX_SERVER=127.0.0.1 python3 examples/sender/send_all_python.py
"""

import logging
import os
import sys
import time

# Allow running from repo root without installing the package
#sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../client/src"))

from zabbix_sender import ZabbixSender, SenderItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

SERVER = os.environ.get("ZABBIX_SERVER", "127.0.0.1")
PORT = int(os.environ.get("ZABBIX_PORT", "10051"))
HOST = os.environ.get("ZABBIX_HOST", "macos-local-sender")

items = [
    SenderItem(host=HOST, key="macos.heartbeat",   value="1"),
    SenderItem(host=HOST, key="macos.status",      value="0"),
    SenderItem(host=HOST, key="macos.error_count", value="0"),
    SenderItem(host=HOST, key="macos.message",     value="All systems nominal"),
]

sender = ZabbixSender(server=SERVER, port=PORT)
response = sender.send(items)

if response.success:
    print(f"✅  Sent {response.processed} item(s) successfully.")
else:
    print(f"❌  Send failed: {response.info}")
    sys.exit(1)
