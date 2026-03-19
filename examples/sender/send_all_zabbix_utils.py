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

# chunk_size=1 puts each item in its own chunk, so resp.chunk maps back to
# the original items list by index (chunk numbers are 1-based).
sender   = Sender(server=ZABBIX_SERVER, port=ZABBIX_PORT, chunk_size=1)
response = sender.send(items)

print(
    f"Response: processed={response.processed}  "
    f"failed={response.failed}  "
    f"total={response.total}"
)

if response.failed:
    print(f"\nWARNING: {response.failed} item(s) rejected by Zabbix:\n")
    if response.details:
        for node, chunks in response.details.items():
            for resp in chunks:
                item = items[resp.chunk - 1]   # chunk is 1-based
                status = "OK    " if resp.failed == 0 else "FAILED"
                print(
                    f"  [{status}]  host={item.host!r}  "
                    f"key={item.key!r}  value={item.value!r}"
                    + (f"  (node={node})" if len(response.details) > 1 else "")
                )
    print("\nEnsure each host and trapper item exists in Zabbix.")
    print("Run: python3 scripts/bootstrap.py")
    sys.exit(1)

print("\nDone.  Open Zabbix web UI → Monitoring → Latest data to verify.")
