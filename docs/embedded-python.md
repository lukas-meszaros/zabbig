# Running zabbig_client Without Installing Python

This guide covers deploying `zabbig_client` on servers where:

- Python is absent, or
- The system Python is too old (e.g. Python 3.6 on RHEL 7/8), and
- You cannot install or upgrade packages (no `sudo`, no `yum`/`dnf`, no compiling).

The solution is **python-build-standalone** — a fully self-contained Python binary that unpacks into your app directory and requires no installation.

---

## Requirements

| Requirement | Detail |
|---|---|
| Python version | **3.9 minimum** (3.11 recommended) |
| Architecture | `x86_64` (most servers) or `aarch64` (ARM) |
| glibc | 2.17+ — satisfied by RHEL 7+, RHEL 8, RHEL 9, Ubuntu 18.04+ |
| Disk space | ~70 MB extracted |
| Root access | Not required |

---

## Step 1 — Download the Standalone Python

Do this on any machine that has internet access (e.g. your laptop).

Go to the [releases page](https://github.com/indygreg/python-build-standalone/releases/latest) and download:

```
cpython-3.11.<patch>+<date>-x86_64-unknown-linux-gnu-install_only.tar.gz
```

Key points when picking the file:
- Use `install_only` — smaller, no debug symbols, all you need.
- Match the architecture: `x86_64` for Intel/AMD, `aarch64` for ARM.
- Avoid the `musl` variant — it targets Alpine Linux, not RHEL.

Alternatively, download directly from the command line (substitute the exact version):

```bash
# On your Mac / any internet-connected machine
RELEASE=20241016
VERSION=3.11.10
curl -LO "https://github.com/indygreg/python-build-standalone/releases/download/${RELEASE}/cpython-${VERSION}+${RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
```

---

## Step 2 — Copy to the Server

```bash
scp cpython-3.11.*-x86_64-unknown-linux-gnu-install_only.tar.gz user@server:~/zabbig_client/
```

---

## Step 3 — Extract Next to the App

On the server:

```bash
cd ~/zabbig_client
tar -xzf cpython-3.11.*-x86_64-unknown-linux-gnu-install_only.tar.gz
```

This creates a `python/` directory inside `zabbig_client/`:

```
zabbig_client/
  python/
    bin/
      python3        ← the standalone interpreter
      python3.11
    lib/
      python3.11/    ← full standard library
  run.py
  client.yaml
  src/
    ...
```

You can delete the `.tar.gz` after extracting.

---

## Step 4 — Verify

```bash
./python/bin/python3 --version
# Python 3.11.x

./python/bin/python3 run.py --dry-run
```

All vendored dependencies (`requests`, `urllib3`, `PyYAML`, etc.) in `src/` are picked up automatically — no `pip install` required.

---

## Step 5 — Create a Wrapper Script (Recommended)

Rather than typing the full path every time, create a small shell wrapper.
The wrapper below also includes startup optimisations — see [configuration-performance.md](configuration-performance.md) for details.

```bash
cat > start.sh << 'EOF'
#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$DIR/python/bin/python3" -s -O "$DIR/run.py" "$@"
EOF
chmod +x start.sh
```

Then run the client as:

```bash
./start.sh --dry-run
./start.sh --config client.yaml
```

For the full list of `run.py` options and exit codes see [running-the-client.md](running-the-client.md).

---

## Cron Setup

Point cron directly at the standalone Python:

```cron
*/5 * * * * cd /home/user/zabbig_client && ./python/bin/python3 run.py --config client.yaml >> /var/log/zabbig/client.log 2>&1
```

Or use the wrapper:

```cron
*/5 * * * * /home/user/zabbig_client/start.sh --config /home/user/zabbig_client/client.yaml >> /var/log/zabbig/client.log 2>&1
```

---

## Keeping the Directory Clean

Recommended layout after setup:

```
zabbig_client/
  python/          ← standalone Python (do not commit to git)
  src/             ← vendored dependencies + zabbig_client package
  state/           ← runtime state files (lock, last_run.json, log offsets)
  client.yaml      ← your configuration
  run.py           ← entry point
  start.sh         ← wrapper (optional)
```

Add `python/` to `.gitignore` if the directory is version-controlled:

```
echo "python/" >> .gitignore
```

---

## Troubleshooting

### `./python/bin/python3: /lib64/libc.so.6: version GLIBC_2.17 not found`

Your system glibc is older than 2.17. This is only seen on RHEL 6 / CentOS 6 (end-of-life since 2020). RHEL 7+ (glibc 2.17) and all later releases are fine.

### `./python/bin/python3: cannot execute binary file: Exec format error`

Architecture mismatch — you downloaded the `x86_64` build but the server is ARM (`aarch64`). Re-download with the correct architecture.

### Permission denied on `python/bin/python3`

```bash
chmod +x python/bin/python3
```

### The `python/` directory was extracted somewhere else

```bash
ls python/bin/python3   # should exist
```

If the tarball extracted into a subdirectory like `python/python/`, move it:

```bash
mv python/python/* python/ && rmdir python/python
```
