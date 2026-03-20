# zabbig — Zabbix Local Lab

A fully containerized Zabbix monitoring lab running on macOS via Docker Desktop, with a Python metrics client (`zabbig_client`) that collects host metrics and sends them to Zabbix via the trapper protocol.

**Purpose:** Local development playground / learning environment. Not intended for production use.

---

## Components

### Zabbix server stack (`docker-compose.yml`)

Three Docker containers on a shared network (`zabbix-lab-net`):

| Container | Image | Role |
|---|---|---|
| `zabbix-postgres` | `postgres:16-alpine` | PostgreSQL database |
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-7.0-latest` | Zabbix server process |
| `zabbix-web` | `zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest` | Web frontend (nginx + PHP-FPM) |

Web UI: `http://localhost:8080` — default login: `Admin / zabbix`
Trapper port: `10051`

→ Full setup guide: [docs/server-setup.md](docs/server-setup.md)

---

### zabbig-client container (`docker-compose.client.yml`)

A Linux Docker container with `zabbig_client/` bind-mounted at `/app`. Provides a working Linux environment for the metrics client — CPU, memory, service, and network collectors all read from the real Linux `/proc` inside Docker, even on macOS.

→ Full setup guide: [docs/client-setup.md](docs/client-setup.md)

---

### zabbig_client app

The metrics collection application. Collects CPU, memory, disk, network, service, and log metrics on a schedule and pushes them to Zabbix via the trapper protocol.

→ App overview and quick start: [zabbig_client/README.md](zabbig_client/README.md)

---

## Architecture

```
macOS host
│
│  browser  ────────────────────HTTP:8080──► Zabbix web UI
│
└── Docker Desktop  (network: zabbix-lab-net)
    │
    ├── zabbix-postgres
    ├── zabbix-server  ◄── TCP:10051
    ├── zabbix-web
    └── zabbig-client  (bind-mount: ./zabbig_client → /app)
          └─ sends metrics ──TCP:10051──► zabbix-server
```

---

## Quick Start

```bash
# 1. Start the Zabbix server stack
docker compose up -d

# 2. Wait for all containers to show (healthy)
docker compose ps

# 3. Build and start the client container
docker compose -f docker-compose.client.yml up -d --build

# 4. Provision the Zabbix host and trapper items
docker exec zabbig-client python3 provision_zabbix.py --config client.docker.yaml

# 5. Verify with a dry-run
docker exec zabbig-client python3 run.py --config client.docker.yaml --dry-run

# 6. Collect and send real metrics
docker exec zabbig-client python3 run.py --config client.docker.yaml
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/server-setup.md](docs/server-setup.md) | Zabbix server stack — start, stop, env vars, volumes |
| [docs/client-setup.md](docs/client-setup.md) | Docker client container — build, run, networking |
| [docs/provisioning.md](docs/provisioning.md) | provision_zabbix.py — CLI flags, credentials, idempotency |
| [docs/configuration.md](docs/configuration.md) | client.yaml and metrics.yaml full reference |
| [docs/collector-cpu.md](docs/collector-cpu.md) | CPU collector — modes and scenarios |
| [docs/collector-memory.md](docs/collector-memory.md) | Memory collector — modes and scenarios |
| [docs/collector-disk.md](docs/collector-disk.md) | Disk collector — modes and scenarios |
| [docs/collector-service.md](docs/collector-service.md) | Service collector — systemd and process modes |
| [docs/collector-network.md](docs/collector-network.md) | Network collector — throughput, errors, sockets |
| [docs/collector-log.md](docs/collector-log.md) | Log collector — condition and count modes, all params |
| [docs/adding-metrics.md](docs/adding-metrics.md) | How to add a new metric or a new collector |

---

## License

MIT — see [LICENSE](LICENSE).