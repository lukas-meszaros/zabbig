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
from pathlib import Path

# ---------------------------------------------------------------------------
# Inject vendor/ so zabbix_utils can be imported without installation
# ---------------------------------------------------------------------------
VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "vendor"

if not (VENDOR_DIR / "zabbix_utils").is_dir():
    sys.exit(
        f"ERROR: zabbix_utils not found in {VENDOR_DIR}\n"
        "Run once:  python3 scripts/vendor_zabbix_utils.py"
    )

sys.path.insert(0, str(VENDOR_DIR))

# ---------------------------------------------------------------------------
# Official Zabbix library imports (zabbix-utils v2)
# ---------------------------------------------------------------------------
from zabbix_utils import Sender, ItemValue  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ZABBIX_SERVER = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
ZABBIX_PORT   = int(sys.argv[2]) if len(sys.argv) > 2 else 10051
HOST_NAME     = "macos-local-sender"

items = [
    ItemValue(HOST_NAME, "macos.heartbeat",   "1"),
    ItemValue(HOST_NAME, "macos.status",      "0"),
    ItemValue(HOST_NAME, "macos.error_count", "0"),
    ItemValue(HOST_NAME, "macos.message",     "All OK"),
]

# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
print(f"Sending {len(items)} items to {ZABBIX_SERVER}:{ZABBIX_PORT} ...")
print(f"  library: zabbix-utils (vendored, no install needed)")
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
        "Run: python3 scripts/bootstrap.py"
    )
    sys.exit(1)

print("\nDone.  Open Zabbix web UI → Monitoring → Latest data to verify.")
