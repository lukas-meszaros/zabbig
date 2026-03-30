# Docker Client Container — Setup Guide

The `zabbig-client` container provides a Linux environment with the `zabbig_client` directory bind-mounted at `/app`. All collectors (CPU, memory, service, network) read from the real Linux kernel `/proc` inside Docker.

---

## Prerequisites

The Zabbix server stack must already be running before starting the client:

```bash
docker compose up -d        # start server stack first
docker compose ps           # verify all three containers show (healthy)
```

---

## Building and Starting the Container

```bash
docker compose -f docker-compose.client.yml up -d --build
```

`--build` rebuilds the image from `Dockerfile.client`. You only need this the first time or after changes to the Dockerfile. Subsequent starts can omit it:

```bash
docker compose -f docker-compose.client.yml up -d
```

Verify the container is running:

```bash
docker compose -f docker-compose.client.yml ps
```

---

## Running the Client

The container stays alive indefinitely (`command: sleep infinity`) so you can exec into it at any time.

```bash
# Validate metrics.yaml before deploying — no Zabbix connection needed
docker exec zabbig-client python3 run.py --validate
docker exec zabbig-client python3 run.py --validate --metrics /path/to/custom-metrics.yaml

# Dry-run — collects metrics, prints results, does NOT send to Zabbix
docker exec zabbig-client python3 run.py --config client.docker.yaml --dry-run

# Real run — collects and sends metrics to Zabbix
docker exec zabbig-client python3 run.py --config client.docker.yaml

# Open an interactive shell
docker exec -it zabbig-client bash
```

For the full list of `run.py` options, exit codes, cron setup, and `start.sh` wrapper see [running-the-client.md](running-the-client.md).

---

## Running the Test Suite

```bash
docker exec zabbig-client python3 -m unittest discover -s tests -v
```

---

## Config Files

Two config variants are provided:

| File | Used for |
|---|---|
| `client.docker.yaml` | Runs **inside** the container — uses Docker DNS name `zabbix-server` |
| `client.yaml` | Runs **directly on the host** — uses `127.0.0.1` |

See [configuration-client.yaml.md](configuration-client.yaml.md) for a full reference of all `client.yaml` fields, and [configuration-metrics.yaml.md](configuration-metrics.yaml.md) for `metrics.yaml`.

---

## Networking

The client container joins the same Docker network as the Zabbix stack (`zabbix-lab-net`). Inside the container, `zabbix-server` resolves to the Zabbix server container by Docker's internal DNS.

The network is declared as `external` in `docker-compose.client.yml` — it must already exist (created by `docker compose up -d`). If the server stack is not running, the client container will fail to start.

---

## Bind Mount

The entire `zabbig_client/` directory is bind-mounted read-write to `/app` inside the container:

```
./zabbig_client  →  /app  (read-write)
```

This means:
- Any file edit on the host is immediately visible inside the container — no rebuild needed.
- State files and log files written by the client inside the container appear on the host.

---

## Stopping and Removing

```bash
# Stop and remove the container
docker compose -f docker-compose.client.yml down
```

The bind-mounted source files on the host are unaffected.
