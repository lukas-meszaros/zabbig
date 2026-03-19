#!/usr/bin/env python3
"""
Vendor the pure-Python files from PyYAML into src/yaml/.
Run once on any machine that has pip.
"""
import subprocess
import sys
import tempfile
import zipfile
import glob
import os
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "src" / "yaml"

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        print("Downloading PyYAML wheel ...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "download",
            "--no-deps", "--quiet", "PyYAML", "-d", tmpdir,
        ])
        wheels = glob.glob(os.path.join(tmpdir, "*.whl"))
        if not wheels:
            sys.exit("ERROR: No wheel found")
        with zipfile.ZipFile(wheels[0]) as zf:
            py_files = [m for m in zf.namelist()
                        if m.startswith("yaml/") and m.endswith(".py")]
            print(f"Extracting {len(py_files)} .py files ...")
            for member in py_files:
                data = zf.read(member)
                out = DEST / os.path.basename(member)
                out.write_bytes(data)
                print(f"  {out.name}")
    print(f"\nDone. PyYAML vendored into {DEST}")

if __name__ == "__main__":
    main()
