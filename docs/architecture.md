# Architecture

## Overview

```
macOS host (your laptop)
│
│  zabbix_sender / Python client (TCP :10051)
│
▼
┌──────────────────────────────────────────────────────────────┐
│  Docker Desktop (macOS)                                      │
│                                                              │
│  ┌──────────────────┐   SQL   ┌──────────────────────────┐  │
│  │  zabbix-server   │────────►│  postgres (PostgreSQL 16) │  │
│  │  (port 10051)    │         └──────────────────────────┘  │
│  └─────────┬────────┘                                        │
│            │ internal API                                     │
│  ┌─────────▼────────┐                                        │
│  │  zabbix-web      │──── HTTP :8080 ──►  browser           │
│  │  (nginx+PHP-FPM) │                                        │
│  └──────────────────┘                                        │
│                                                              │
│  Network: zabbix-lab-net (bridge)                            │
└──────────────────────────────────────────────────────────────┘
```

## Container topology

| Container      | Image                                      | Role                             |
|----------------|--------------------------------------------|----------------------------------|
| `zabbix-postgres` | `postgres:16-alpine`                    | PostgreSQL database              |
| `zabbix-server`   | `zabbix/zabbix-server-pgsql:alpine-7.0-latest` | Zabbix server process       |
| `zabbix-web`      | `zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest` | Web frontend (nginx+PHP) |

All three containers share the `zabbix-lab-net` bridge network, which means they can reach each other by container name.

## Network flow

### Web UI access (browser → Zabbix web)

```
browser  →  localhost:8080  →  docker-port-mapping  →  zabbix-web:8080
```

### Trapper data (Python/zabbix_sender → Zabbix server)

```
macOS  →  localhost:10051  →  docker-port-mapping  →  zabbix-server:10051
```

The macOS host sends data over TCP to `localhost:10051`. Docker Desktop maps this to the `zabbix-server` container's port 10051 (the Zabbix trapper listener).

### Zabbix server → database

```
zabbix-server  →  postgres:5432  (container-internal, not exposed to host)
```

The PostgreSQL port is intentionally **not** published to localhost. It is only accessible within the `zabbix-lab-net` network.

## Why trapper items?

Trapper items are the right ingest mechanism for externally pushed data because:

1. **Push model** — The sender decides when to push data. No Zabbix agent or scheduler pull is needed.
2. **No agent required** — The macOS laptop does not need to run `zabbix_agentd`. It only needs TCP access to port 10051.
3. **Simple protocol** — The Zabbix sender protocol is a minimal JSON-over-TCP framing that is easy to implement in Python without external libraries.
4. **Decoupled** — The sender is responsible only for delivering values. All alerting, thresholds, and event logic stay in Zabbix.

## Why alerts/events are generated in Zabbix, not by the sender

The sender is intentionally kept as a "dumb value courier":

- It sends numeric/string values to specific item keys.
- It does **not** know whether a value constitutes a problem.
- All threshold evaluation, trigger logic, and escalation happen inside Zabbix.

This separation keeps the sender simple, reusable, and testable. It also means the monitoring rules can be updated in Zabbix without changing any client code.

## Why no agent is needed

This lab focuses on **externally pushed (trapper) data** only. Zabbix agents are used for:
- Pull-based metric collection from the monitored host.
- Active checks where the agent polls and pushes on a schedule.

Since our macOS laptop is the **sender** (not a monitored target), and it explicitly pushes values on demand, no agent is needed. A placeholder agent interface is created on the Zabbix host record to satisfy the Zabbix API requirement, but it is never actively polled.

## Volume strategy

| Volume name                     | Purpose                             |
|---------------------------------|-------------------------------------|
| `zabbix-lab-postgres-data`      | PostgreSQL data files (persistent)  |
| `zabbix-lab-alertscripts`       | Custom alert scripts (persistent)   |
| `zabbix-lab-externalscripts`    | External check scripts (persistent) |

Volumes persist across `docker compose down` (restart). They are removed only by `docker compose down --volumes` (which `scripts/reset.sh` runs after confirmation).

## Security notes (lab context)

- PostgreSQL port 5432 is **not** exposed to localhost.
- Zabbix trapper port 10051 is exposed to `127.0.0.1` only on macOS via Docker Desktop's default binding.
- `ZBX_ALLOWEDIPRANGE=0.0.0.0/0` allows any sender — acceptable for a local lab, but should be restricted for shared or networked machines.
- Credentials are stored in `.env` (git-ignored). See `.env.example` for defaults.
