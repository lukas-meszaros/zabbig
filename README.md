# zabbig — Zabbix Local Lab

A fully containerized Zabbix monitoring lab running on macOS via Docker Desktop, with a local Python client for sending values to Zabbix trapper items.

**Purpose:** Local development playground / learning environment. Not intended for production use.

---

## Architecture overview

```
macOS host (your laptop)
│
│  zabbix_sender / Python client  ──TCP:10051──►  Zabbix server
│  browser                        ──HTTP:8080──►  Zabbix web UI
│
└── Docker Desktop ─────────────────────────────────────────────
    │
    ├── zabbix-server  (zabbix/zabbix-server-pgsql:alpine-7.0)
    ├── zabbix-web     (zabbix/zabbix-web-nginx-pgsql:alpine-7.0)
    └── postgres       (postgres:16-alpine)
```

See [docs/architecture.md](docs/architecture.md) for the full architecture description.

---

## Prerequisites

| Tool           | Version  | Install                        |
|----------------|----------|--------------------------------|
| Docker Desktop | ≥ 4.x    | https://www.docker.com/products/docker-desktop |
| Python         | ≥ 3.9    | `brew install python`          |
| `curl`         | any      | pre-installed on macOS         |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/lukas-meszaros/zabbig.git
cd zabbig

# 2. Set up environment
cp .env.example .env

# 3. Start Docker Desktop (open the app)

# 4. Start the stack (one command)
bash scripts/start.sh

# 5. Provision host + items + triggers
pip3 install requests python-dotenv
python3 scripts/bootstrap.py

# 6. Open the Zabbix web UI
open http://localhost:8080
# Login: Admin / zabbix
```

See [docs/quickstart.md](docs/quickstart.md) for detailed step-by-step instructions.

---

## Accessing the Zabbix web UI

| URL                      | Credentials        |
|--------------------------|--------------------|
| http://localhost:8080    | Admin / zabbix     |

---

## Sending test values

### Using the Python client

```bash
cd client
pip3 install -e .

# Send a heartbeat
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1

# Send all starter items
zabbix-sender \
  --host macos-local-sender \
  --key macos.heartbeat   --value 1 \
  --key macos.status      --value 0 \
  --key macos.error_count --value 0 \
  --key macos.message     --value "All OK"
```

### Using zabbix_sender (Homebrew)

```bash
brew install zabbix

zabbix_sender \
  --zabbix-server 127.0.0.1 \
  --port 10051 \
  --host macos-local-sender \
  --key macos.heartbeat \
  --value 1
```

See [docs/testing.md](docs/testing.md) for complete testing instructions.

---

## Trapper items

| Item key              | Type          | Description                          |
|-----------------------|---------------|--------------------------------------|
| `macos.heartbeat`     | Numeric float | `1` = alive; missing 5 min = problem |
| `macos.status`        | Numeric uint  | `0`=OK, `1`=WARN, `2`=CRITICAL       |
| `macos.error_count`   | Numeric uint  | Alert when `> 10`                    |
| `macos.message`       | Text          | Free-form message, Latest Data only  |

## Triggers

| Trigger                                    | Condition                     | Severity |
|--------------------------------------------|-------------------------------|----------|
| Heartbeat missing for 5 minutes            | `nodata(5m) = 1`              | HIGH     |
| Status is CRITICAL                         | `last(macos.status) >= 2`     | HIGH     |
| Error count above threshold                | `last(macos.error_count) > 10`| AVERAGE  |

See [docs/zabbix-setup.md](docs/zabbix-setup.md) for details.

---

## Stopping and resetting

```bash
# Stop containers (data preserved)
bash scripts/stop.sh

# Full reset — wipes all data (requires confirmation)
bash scripts/reset.sh
```

---

## Project structure

```
.
├── .env.example              Environment variable template
├── docker-compose.yml        Zabbix stack (postgres + server + web)
├── Makefile                  Convenience targets
├── client/                   Python sender client
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── src/zabbix_sender/    Sender package (stdlib only)
│   └── tests/                Unit tests
├── docs/                     Documentation
│   ├── architecture.md
│   ├── quickstart.md
│   ├── zabbix-setup.md
│   ├── testing.md
│   └── troubleshooting.md
├── examples/sender/          Example send scripts
│   ├── send_heartbeat.sh
│   ├── send_all.sh
│   ├── trigger_problem.sh
│   └── send_all_python.py
└── scripts/                  Helper scripts
    ├── bootstrap.py          API-based provisioning (idempotent)
    ├── start.sh
    ├── stop.sh
    ├── reset.sh
    └── wait-for-zabbix.sh
```

---

## Documentation

| Document                             | Content                                     |
|--------------------------------------|---------------------------------------------|
| [docs/architecture.md](docs/architecture.md) | Container topology, network flow, design decisions |
| [docs/quickstart.md](docs/quickstart.md)     | Clone → start → first login → first test   |
| [docs/zabbix-setup.md](docs/zabbix-setup.md) | Host, items, triggers, provisioning         |
| [docs/testing.md](docs/testing.md)           | zabbix_sender and Python client test flows  |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes               |

---

## Common issues

| Problem                         | Fix                                           |
|---------------------------------|-----------------------------------------------|
| Web UI unreachable              | Wait 2 min after start; check `docker compose logs zabbix-web` |
| Sender connection refused       | Ensure stack is running; check port 10051     |
| `failed: 1` in sender output   | Run `python3 scripts/bootstrap.py`; check host/key names |
| Container not healthy           | `docker compose restart zabbix-server`        |
| Trigger not firing              | Verify Latest Data received the value; wait 30s |

Full troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)

---

## Security notes

- `.env` is git-ignored. Never commit real credentials.
- Default passwords in `.env.example` are for local use only.
- If this machine is shared, change passwords in `.env` before starting.
- PostgreSQL is not exposed to localhost — only accessible within Docker.
- The trapper port (`10051`) accepts data from any IP by default (`0.0.0.0/0`). Restrict `ZBX_ALLOWED_HOSTS` in `.env` if needed.

---

## License

MIT — see [LICENSE](LICENSE).