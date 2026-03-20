# zabbig — Zabbix Local Lab

A fully containerized Zabbix monitoring lab running on macOS via Docker Desktop, with a Python metrics client (`zabbig_client`) that collects host metrics and sends them to Zabbix via the trapper protocol.

**Purpose:** Local development playground / learning environment. Not intended for production use.

---

## Architecture overview

```
macOS host (your laptop)
│
│  browser  ──────────────────────────HTTP:8080──►  Zabbix web UI
│
└── Docker Desktop  (network: zabbix-lab-net)
    │
    ├── postgres        postgres:16-alpine
    ├── zabbix-server   zabbix/zabbix-server-pgsql:alpine-7.0  ◄─ TCP:10051
    ├── zabbix-web      zabbix/zabbix-web-nginx-pgsql:alpine-7.0
    └── zabbig-client   zabbig-client:latest (built locally)
          │ bind-mount: ./zabbig_client → /app
          └─ sends metrics ──TCP:10051──► zabbix-server
```

Two separate compose files manage the stack:

| File | Purpose |
|---|---|
| `docker-compose.yml` | Zabbix server stack (postgres + zabbix-server + zabbix-web) |
| `docker-compose.client.yml` | `zabbig-client` container (metrics collector) |

---

## Prerequisites

| Tool           | Version  | Install                        |
|----------------|----------|--------------------------------|
| Docker Desktop | ≥ 4.x    | https://www.docker.com/products/docker-desktop |
| Python         | ≥ 3.9    | `brew install python` (for running provisioning from host) |

---

## 1 — Start the Zabbix server stack

The server stack runs three containers on a shared Docker network (`zabbix-lab-net`).

```bash
# Start postgres, zabbix-server, and zabbix-web
docker compose up -d

# Wait until all containers are healthy (takes about 60–90 seconds)
docker compose ps
```

Verify the web UI is reachable:

```
http://localhost:8080     Login: Admin / zabbix
```

**Exposed ports**

| Port  | Service      | Description                              |
|-------|--------------|------------------------------------------|
| 8080  | zabbix-web   | Zabbix web frontend                      |
| 10051 | zabbix-server| Trapper port — accepts metric values      |

**Environment variables (optional overrides)**

All variables have sensible defaults and the stack starts without a `.env` file.
Create one to override any value:

```bash
cp .env.example .env   # only needed if you want to change defaults
```

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB` | `zabbix` | Database name |
| `POSTGRES_USER` | `zabbix` | Database user |
| `POSTGRES_PASSWORD` | `zabbix_lab_password` | Database password |
| `ZBX_ALLOWED_HOSTS` | `0.0.0.0/0` | IPs allowed to push trapper data |
| `ZABBIX_TRAPPER_PORT` | `10051` | Host-side trapper port |
| `ZABBIX_WEB_PORT` | `8080` | Host-side web UI port |
| `PHP_TZ` | `Europe/Berlin` | Timezone shown in the web UI |

---

## 2 — Configure the metrics client

The client is configured by `zabbig_client/client.yaml`.
A Docker-specific config (`client.docker.yaml`) is already provided and used inside the container.

Minimum fields to set in `client.docker.yaml` (or `client.yaml`):

```yaml
zabbix:
  server_host: "zabbix-server"   # Docker DNS name — resolves inside the container
  server_port: 10051
  host_name: "prod-server-01"    # Must match the host created by provision_zabbix.py
```

The client also needs API credentials for provisioning only (not for metric collection):

```yaml
# These are used by provision_zabbix.py, not by run.py
zabbix:
  api_url: "http://zabbix-web:8080/api_jsonrpc.php"  # auto-derived if omitted
  api_user: "Admin"
  api_password: "zabbix"
```

See [zabbig_client/README.md](zabbig_client/README.md) for a full reference of every `client.yaml` field.

---

## 3 — Start the client container

The client container bind-mounts `./zabbig_client` to `/app`, so any edits on the host are immediately visible inside the container without a rebuild.

```bash
# Build and start the container (runs in background)
docker compose -f docker-compose.client.yml up -d --build

# Verify it is running
docker compose -f docker-compose.client.yml ps
```

**Useful exec commands**

```bash
# Open an interactive shell
docker exec -it zabbig-client bash

# Run a dry-run (collects metrics, prints them, does NOT send to Zabbix)
docker exec zabbig-client python3 run.py --config client.docker.yaml --dry-run

# Run for real (collects and sends metrics to Zabbix)
docker exec zabbig-client python3 run.py --config client.docker.yaml

# Run the test suite
docker exec zabbig-client python3 -m unittest discover -s tests -v
```

**Stop / remove the client container**

```bash
docker compose -f docker-compose.client.yml down
```

---

## 4 — Provision Zabbix (create host and items)

`provision_zabbix.py` uses the Zabbix JSON-RPC API to create the monitoring host, host group, and all trapper items defined in `metrics.yaml`. It is idempotent — safe to run multiple times.

**Run from inside the container (recommended)**

```bash
docker exec zabbig-client python3 provision_zabbix.py --config client.docker.yaml
```

**Run from the macOS host**

```bash
cd zabbig_client
python3 provision_zabbix.py --config client.yaml
```

The script automatically derives the API URL from `server_host` in `client.yaml`
(`http://<server_host>:8080/api_jsonrpc.php`). Override with `--api-url` if needed.

**All CLI flags**

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `client.yaml` | Path to client config file |
| `--metrics PATH` | `metrics.yaml` | Path to metrics definition file |
| `--api-url URL` | derived from `server_host` | Zabbix JSON-RPC endpoint |
| `--user USER` | `Admin` (or `ZABBIX_ADMIN_USER` env) | Zabbix admin username |
| `--password PASS` | `zabbix` (or `ZABBIX_ADMIN_PASSWORD` env) | Zabbix admin password |
| `--only-enabled` | off | Only provision metrics with `enabled: true` |
| `--no-wait` | off | Skip waiting for web UI readiness check |

**What it creates**

- Host group — value of `zabbix.host_group` in `client.yaml`
- Host — value of `zabbix.host_name` in `client.yaml`
- Trapper items — one per metric in `metrics.yaml` (all by default, or only enabled ones with `--only-enabled`)
- Self-monitoring items — `zabbig.client.*` items for client health tracking

---

## 5 — Verify metrics are arriving

After provisioning, trigger a real run and check the Zabbix UI:

```bash
# Send one round of metrics
docker exec zabbig-client python3 run.py --config client.docker.yaml
```

In the Zabbix web UI:

1. Go to **Monitoring → Latest data**
2. Filter by the host name set in `client.yaml` (e.g. `prod-server-01`)
3. Verify values are populated and timestamps are recent

---

## Stopping and resetting

```bash
# Stop the client container
docker compose -f docker-compose.client.yml down

# Stop the Zabbix stack (data preserved in Docker volumes)
docker compose down

# Full reset — removes ALL containers, volumes, and collected data
docker compose down -v
docker compose -f docker-compose.client.yml down
```

---

## Project structure

```
.
├── docker-compose.yml              Zabbix server stack (postgres + server + web)
├── docker-compose.client.yml       zabbig-client container
├── Dockerfile.client               Client container image definition
├── Makefile                        Convenience targets (make help)
├── zabbig_client/                  Metrics client
│   ├── client.yaml                 Client config (host/macOS variant)
│   ├── client.docker.yaml          Client config (Docker container variant)
│   ├── metrics.yaml                Metric definitions (what to collect)
│   ├── run.py                      Entry point — collect and send metrics
│   ├── provision_zabbix.py         API provisioning script
│   ├── src/zabbig_client/          Client source packages
│   │   ├── collectors/             cpu, memory, disk, network, service, log
│   │   ├── runner.py               Orchestrates collectors and sender
│   │   ├── config_loader.py        Loads and validates client.yaml
│   │   └── models.py               Metric/config data models
│   └── tests/                      Unit tests
├── docs/                           Documentation
│   ├── architecture.md
│   ├── quickstart.md
│   ├── zabbix-setup.md
│   ├── testing.md
│   └── troubleshooting.md
├── examples/                       Example scripts
└── scripts/                        Helper scripts (bootstrap, reset)
```

---

## Further reading

| Document | Content |
|---|---|
| [zabbig_client/README.md](zabbig_client/README.md) | Full client reference — all `client.yaml` fields, collectors, metrics |
| [docs/architecture.md](docs/architecture.md) | Container topology, network flow, design decisions |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes |

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