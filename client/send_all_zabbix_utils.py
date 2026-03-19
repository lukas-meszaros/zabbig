#!/usr/bin/env python3
# =============================================================================
# examples/sender/send_all_zabbix_utils.py
#
# Send all four starter trapper item values using the OFFICIAL Zabbix Python
# library (zabbix-utils), vendored locally — no pip install required at
# runtime.
#
# Prerequisites:
#   Run the vendor script ONCE on any machine that has pip available
#   (dev laptop, CI, build server):
#
#     python3 scripts/vendor_zabbix_utils.py
#
#   This populates vendor/zabbix_utils/ which is the only thing needed at
#   runtime.  Copy vendor/ alongside this script to your production host.
#
# Usage:
#   python3 examples/sender/send_all_zabbix_utils.py [server] [port]
# =============================================================================

import sys

# ---------------------------------------------------------------------------
# Official Zabbix library imports (zabbix-utils v2)
# ---------------------------------------------------------------------------
from src.zabbix_utils import Sender, ItemValue  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ZABBIX_SERVER = "127.0.0.1"
ZABBIX_PORT   = 10051
HOST_NAME     = "macos-local-sender"

items = [
    ItemValue(HOST_NAME, "macos.heartbeat",   "5"),
    ItemValue(HOST_NAME, "macos.status2",      "5"),
    ItemValue(HOST_NAME, "macos.error_count", "5"),
    ItemValue(HOST_NAME, "macos.message",     "All OK - message"),
]

# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
print(f"Sending {len(items)} items to {ZABBIX_SERVER}:{ZABBIX_PORT} ...")
print(f"  host:    {HOST_NAME}")
print()

sender   = Sender(server=ZABBIX_SERVER, port=ZABBIX_PORT)
response = sender.send(items)

print(
    f"Response: processed={response.processed}  "
    f"failed={response.failed}  "
    f"total={response.total}"
)

if response.failed:
    print(
        "\nWARNING: Zabbix rejected some items. "
        "Ensure the host and trapper items exist.\n"
    )
    sys.exit(1)

print("\nDone.  Open Zabbix web UI → Monitoring → Latest data to verify.")
