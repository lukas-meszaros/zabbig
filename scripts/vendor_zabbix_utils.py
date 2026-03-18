#!/usr/bin/env python3
"""
scripts/vendor_zabbix_utils.py
=============================================================================
Download the official Zabbix Python library (zabbix-utils) and extract its
source into vendor/zabbix_utils/ — no installation required.

Run this ONCE on any machine that has pip available (dev laptop, CI, etc.),
then copy the vendor/ directory alongside your scripts to any environment,
including ones where you cannot run `pip install`.

Usage:
    python3 scripts/vendor_zabbix_utils.py [--version X.Y.Z]

Result:
    vendor/
    └── zabbix_utils/
            __init__.py
            sender.py
            api.py
            getter.py
            ...

After running, add sys.path.insert(0, "path/to/vendor") in your script and
`from zabbix_utils import ZabbixSender` will work without any install.
=============================================================================
"""

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PACKAGE = "zabbix-utils"
VENDOR_DIR = Path(__file__).parent.parent / "vendor"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Vendor {PACKAGE} into vendor/")
    parser.add_argument(
        "--version",
        default=None,
        help="Specific version to download, e.g. 2.0.2  (default: latest)",
    )
    args = parser.parse_args()

    package_spec = f"{PACKAGE}=={args.version}" if args.version else PACKAGE

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Downloading {package_spec} wheel (no-deps) ...")
        subprocess.check_call(
            [
                sys.executable, "-m", "pip", "download",
                "--no-deps",
                "--dest", tmpdir,
                package_spec,
            ]
        )

        wheels = list(Path(tmpdir).glob("*.whl"))
        if not wheels:
            sys.exit("ERROR: pip download produced no wheel file.")

        wheel = wheels[0]
        print(f"Extracting {wheel.name} ...")

        target = VENDOR_DIR / "zabbix_utils"
        if target.exists():
            import shutil
            shutil.rmtree(target)

        with zipfile.ZipFile(wheel) as zf:
            members = [m for m in zf.namelist() if m.startswith("zabbix_utils/")]
            if not members:
                sys.exit("ERROR: No zabbix_utils/ package found inside the wheel.")
            for member in members:
                zf.extract(member, VENDOR_DIR)

    print(f"\nDone. Library extracted to: {target}")
    print("\nUsage in your scripts:")
    print("  import sys")
    print(f"  sys.path.insert(0, '{VENDOR_DIR}')")
    print("  from zabbix_utils import ZabbixSender")


if __name__ == "__main__":
    main()
