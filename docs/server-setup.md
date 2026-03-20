# Zabbix Server Stack — Setup Guide

The Zabbix server stack runs three Docker containers on a shared network. It provides the Zabbix trapper endpoint that receives metrics, the database that stores them, and the web UI for visualisation and alerting.

---

## Containers

| Container | Image | Role |
|---|---|---|
| `zabbix-postgres` | `postgres:16-alpine` | PostgreSQL database |
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-7.0-latest` | Zabbix server process |
| `zabbix-web` | `zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest` | Nginx + PHP-FPM web frontend |

All three containers share a Docker bridge network named `zabbix-lab-net`.

---

## Prerequisites

- Docker Desktop ≥ 4.x running on macOS

No other tools are required on the host — everything runs inside Docker.

---

## Starting the Stack

```bash
# From the repo root
docker compose up -d
```

All three containers start in dependency order: postgres first, then zabbix-server (waits for postgres healthy), then zabbix-web (waits for both).

**Wait for startup** — initial startup takes 60–90 seconds during which Zabbix initialises the database schema. Check health status:

```bash
docker compose ps
```

All three containers should show `(healthy)` before proceeding. If any container is still starting, wait and re-run.

---

## Verifying the Web UI

Once healthy, open the Zabbix web UI:

```
http://localhost:8080     Login: Admin / zabbix
```

---

## Exposed Ports

| Host Port | Container | Description |
|-----------|-----------|-------------|
| `8080` | zabbix-web | Zabbix web frontend |
| `10051` | zabbix-server | Trapper port — accepts pushed metric values |

PostgreSQL is not exposed to the host — it is only reachable within the Docker network.

---

## Environment Variables

All variables have built-in defaults. The stack starts without any `.env` file. Add one only to override defaults:

```bash
cp .env.example .env
# then edit .env
```

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB` | `zabbix` | Database name |
| `POSTGRES_USER` | `zabbix` | Database user |
| `POSTGRES_PASSWORD` | `zabbix_lab_password` | Database password |
| `ZBX_ALLOWED_HOSTS` | `0.0.0.0/0` | IP range allowed to push trapper data |
| `ZABBIX_TRAPPER_PORT` | `10051` | Host-side trapper port mapping |
| `ZABBIX_WEB_PORT` | `8080` | Host-side web UI port mapping |
| `PHP_TZ` | `Europe/Berlin` | Timezone displayed in the web UI |

> **Security note:** `ZBX_ALLOWED_HOSTS: 0.0.0.0/0` is permissive and suitable for local lab use only. In any shared environment, restrict this to the IP of the client container or host.

---

## Viewing Logs

```bash
# Follow all container logs
docker compose logs -f

# Follow a single container
docker compose logs -f zabbix-server
docker compose logs -f zabbix-web
```

---

## Stopping the Stack

```bash
# Stop containers — data in volumes is preserved
docker compose down

# Full reset — removes all containers AND all volumes (database wiped)
docker compose down -v
```

After a full reset the database is empty. You will need to re-run `provision_zabbix.py` to recreate the Zabbix host and items. See [provisioning.md](provisioning.md).

---

## Persistent Volumes

| Volume | Contents |
|---|---|
| `zabbix-lab-postgres-data` | All Zabbix configuration and collected data |
| `zabbix-lab-alertscripts` | Custom alert scripts (empty by default) |
| `zabbix-lab-externalscripts` | Custom external scripts (empty by default) |

Volumes survive `docker compose down` but are removed by `docker compose down -v`.
