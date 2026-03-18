# Quick Start

## Prerequisites

| Tool           | Minimum version | Install (macOS)              |
|----------------|-----------------|------------------------------|
| Docker Desktop | 4.x             | https://www.docker.com/products/docker-desktop |
| Python         | 3.9             | `brew install python`        |
| `curl`         | any             | pre-installed on macOS       |

> **Note:** `zabbix_sender` is optional — the Python client provides equivalent functionality without any binary dependencies.

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/lukas-meszaros/zabbig.git
cd zabbig
```

---

## Step 2 — Set up environment variables

```bash
cp .env.example .env
```

Open `.env` and review the defaults. For a personal local lab, the defaults are fine. If your machine is shared, change the passwords.

---

## Step 3 — Start Docker Desktop

Open Docker Desktop from your Applications folder and wait for it to show the green "Docker Desktop is running" status.

---

## Step 4 — Start the Zabbix stack

```bash
bash scripts/start.sh
```

This will:
1. Pull all Docker images (first run only — may take a few minutes).
2. Start PostgreSQL, Zabbix server, and Zabbix web frontend.
3. Wait until the Zabbix web UI is accessible.
4. Print the URL and default login.

Expected output (truncated):
```
▶  Pulling Docker images...
▶  Starting containers...
▶  Waiting for Zabbix web UI at http://localhost:8080/index.php ...
   ✅ Zabbix web UI is up! (75s elapsed)

╔══════════════════════════════════════════════════════╗
║  ✅ Zabbix lab is ready!                             ║
║  Web UI:   http://localhost:8080                     ║
║  Login:    Admin / zabbix                            ║
╚══════════════════════════════════════════════════════╝
```

Or equivalently with Make:
```bash
make up
```

---

## Step 5 — First login to the Zabbix web UI

1. Open **http://localhost:8080** in your browser.
2. Log in with:
   - Username: `Admin`
   - Password: `zabbix`
3. You will see the Zabbix dashboard.

> **Tip:** Zabbix may prompt you to change the default password. You can do so or skip for a lab.

---

## Step 6 — Provision the starter host, items, and triggers

Run the bootstrap script (requires Python and `requests`):

```bash
pip3 install requests python-dotenv   # one-time install
python3 scripts/bootstrap.py
```

Expected output:
```
10:00:00  INFO     Zabbix Lab Bootstrap
10:00:00  INFO     API URL: http://localhost:8080/api_jsonrpc.php
10:00:01  INFO     Authenticated as 'Admin'
10:00:01  INFO     Created host group 'MacOS Senders' (id=2)
10:00:01  INFO     Created host 'macos-local-sender' (id=10084)
10:00:01  INFO     Created item 'macos.heartbeat' (id=...)
10:00:01  INFO     Created item 'macos.status' (id=...)
10:00:01  INFO     Created item 'macos.error_count' (id=...)
10:00:01  INFO     Created item 'macos.message' (id=...)
10:00:01  INFO     Created trigger 'Heartbeat missing for 5 minutes'
10:00:01  INFO     Created trigger 'Status is CRITICAL (macos.status >= 2)'
10:00:01  INFO     Created trigger 'Error count above threshold (macos.error_count > 10)'
10:00:01  INFO     ✅  Provisioning complete!
```

The script is **idempotent** — safe to run multiple times.

---

## Step 7 — Send your first test value

### Option A — Python client (no extra binary needed)

```bash
cd client
pip3 install -e .

# Send a heartbeat
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1
```

### Option B — zabbix_sender binary (Homebrew)

```bash
brew install zabbix

zabbix_sender \
  --zabbix-server 127.0.0.1 \
  --port 10051 \
  --host macos-local-sender \
  --key macos.heartbeat \
  --value 1
```

---

## Step 8 — Verify in Zabbix

1. Open **http://localhost:8080**.
2. Navigate to **Monitoring → Latest data**.
3. Filter by **Host**: `macos-local-sender`.
4. You should see `macos.heartbeat` with value `1` and a recent timestamp.

---

## Stopping the lab

```bash
bash scripts/stop.sh   # stops containers, data preserved
```

## Full reset (wipe all data)

```bash
bash scripts/reset.sh  # destroys volumes after confirmation
```
