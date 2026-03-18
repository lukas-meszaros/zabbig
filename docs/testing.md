# Testing

## Overview

There are two supported sender paths:

1. **`zabbix_sender`** — Homebrew binary (macOS)
2. **Python client** — Direct protocol implementation, stdlib only

Both paths send values to the same Zabbix trapper items on `macos-local-sender`.

---

## Prerequisites

- Zabbix lab running (`bash scripts/start.sh`)
- Bootstrap done (`python3 scripts/bootstrap.py`)
- Zabbix web UI accessible at http://localhost:8080

---

## Path 1: zabbix_sender

### Install

```bash
brew install zabbix
```

Verify:
```bash
zabbix_sender --version
# zabbix_sender (Zabbix) 7.x.x
```

### Send a single value

```bash
zabbix_sender \
  --zabbix-server 127.0.0.1 \
  --port 10051 \
  --host macos-local-sender \
  --key macos.heartbeat \
  --value 1
```

Expected output:
```
zabbix_sender [timestamp]: INFO: 1 (1 sent, 0 skipped, 0 not sent)
```

### Send all starter items at once

```bash
bash examples/sender/send_all.sh
```

### Trigger a problem

```bash
bash examples/sender/trigger_problem.sh
```

### Recover from a problem

```bash
bash examples/sender/trigger_problem.sh 127.0.0.1 10051 --recover
```

### Send from input file

```bash
zabbix_sender \
  --zabbix-server 127.0.0.1 \
  --port 10051 \
  --with-timestamps \
  --input-file - <<EOF
macos-local-sender macos.heartbeat     1   $(date +%s)
macos-local-sender macos.status        0   $(date +%s)
macos-local-sender macos.error_count   0   $(date +%s)
macos-local-sender macos.message       "Hello Zabbix"   $(date +%s)
EOF
```

---

## Path 2: Python client

### Install

```bash
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Basic usage

```bash
# Send a heartbeat
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1

# Send multiple items
zabbix-sender \
  --host macos-local-sender \
  --key macos.heartbeat   --value 1 \
  --key macos.status      --value 0 \
  --key macos.error_count --value 0 \
  --key macos.message     --value "Test from Python client"

# Verbose output
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1 --verbose

# Dry run (no network connection)
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1 --dry-run
```

### Environment variable configuration

```bash
export ZABBIX_SERVER=127.0.0.1
export ZABBIX_PORT=10051
export ZABBIX_HOST=macos-local-sender

zabbix-sender --key macos.heartbeat --value 1
```

### Trigger a problem from Python

```bash
zabbix-sender \
  --host macos-local-sender \
  --key macos.status --value 2 \
  --key macos.error_count --value 15
```

### Recover from Python

```bash
zabbix-sender \
  --host macos-local-sender \
  --key macos.status --value 0 \
  --key macos.error_count --value 0
```

### Python example script

```bash
python3 examples/sender/send_all_python.py
```

### Run unit tests

```bash
cd client
pytest
```

---

## Verifying values in the Zabbix UI

### Latest Data

1. Open http://localhost:8080
2. Go to **Monitoring → Latest data**
3. In the filter:
   - **Host groups**: `MacOS Senders`
   - **Hosts**: `macos-local-sender`
4. Click **Apply**
5. You should see all four items with recent timestamps and the values you sent.

### Problems view

1. Go to **Monitoring → Problems**
2. After sending `macos.status=2`, a HIGH severity problem should appear within a few seconds.
3. After sending `macos.error_count=15`, an AVERAGE severity problem should appear.
4. After sending `macos.heartbeat` values stop for 5 minutes, a HIGH "no data" problem appears.

### Trigger status

1. Go to **Configuration → Hosts**
2. Click on `macos-local-sender`
3. Click **Triggers**
4. The **Status** column shows whether each trigger is in OK or PROBLEM state.

---

## Test scenario: full cycle

```bash
# 1. Send healthy values
zabbix-sender --host macos-local-sender \
  --key macos.heartbeat --value 1 \
  --key macos.status --value 0 \
  --key macos.error_count --value 0 \
  --key macos.message --value "System healthy"

# 2. Verify latest data shows the values
#    → open http://localhost:8080 → Monitoring → Latest data

# 3. Trigger a problem
zabbix-sender --host macos-local-sender \
  --key macos.status --value 2 \
  --key macos.error_count --value 15

# 4. Verify problems appear
#    → open http://localhost:8080 → Monitoring → Problems

# 5. Recover
zabbix-sender --host macos-local-sender \
  --key macos.status --value 0 \
  --key macos.error_count --value 0

# 6. Verify problems are resolved
#    → http://localhost:8080 → Monitoring → Problems (should be empty)
```
