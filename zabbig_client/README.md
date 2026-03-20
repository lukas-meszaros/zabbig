# zabbig_client — Standalone Zabbix Monitoring Client

A self-contained Python monitoring client that collects host metrics and service states, then pushes them to a Zabbix server via the trapper protocol. Designed to run under cron with no external package installation on production systems.

---

## What It Does

- Collects CPU, memory, disk, network, service, application log, and probe (TCP/HTTP endpoint) metrics
- Pushes values to Zabbix using the bundled `zabbix_utils` library (trapper protocol)
- Runs safely from cron — PID lock prevents overlapping executions
- Requires **zero pip/apt/yum install** — all dependencies are vendored in `src/`

---

## Collectors

| Collector | Metrics collected | Reference |
|-----------|------------------|-----------|
| `cpu` | Utilisation %, load averages (1/5/15 min), uptime | [collector-cpu.md](../docs/collector-cpu.md) |
| `memory` | RAM used %, available bytes, swap used % | [collector-memory.md](../docs/collector-memory.md) |
| `disk` | Space used/free (bytes + %), inode used/free/total | [collector-disk.md](../docs/collector-disk.md) |
| `service` | Running state via systemd or /proc cmdline scan | [collector-service.md](../docs/collector-service.md) |
| `network` | Throughput, errors, drops, TCP/UDP socket counts | [collector-network.md](../docs/collector-network.md) |
| `log` | Log file scanning — event detection, severity, counts | [collector-log.md](../docs/collector-log.md) |
| `probe` | Active TCP/HTTP endpoint checks — reachability, status, SSL | [collector-probe.md](../docs/collector-probe.md) |

---

## Directory Layout

```
zabbig_client/
  run.py                          # entry point — add to cron
  client.yaml                     # runtime config
  metrics.yaml                    # metric definitions

  src/
    zabbig_client/                # main application package
      main.py                     # orchestrator
      config_loader.py            # YAML config loading + validation
      models.py                   # dataclasses (MetricDef, MetricResult, ...)
      runner.py                   # async collector runner
      sender_manager.py           # Zabbix send wrapper
      result_router.py            # routes results to batch/immediate queues
      collector_registry.py       # maps collector names to classes
      locking.py                  # cron-safe PID file lock
      logging_setup.py            # configures Python logging
      state_manager.py            # optional run-state persistence (JSON)
      collectors/                 # cpu, memory, disk, service, network, log, probe

    zabbix_utils/                 # vendored official Zabbix Python library
    yaml/                         # vendored PyYAML pure-Python source
    requests/                     # vendored requests (used by zabbix_update/ scripts)

  tests/
    test_config_loader.py
    test_models.py
    test_result_router.py
    test_collectors.py
    test_log_writer.py

  state/                          # state files written here by default
  logs/                           # optional: set logging.file here
```

---

## Quick Start

### 1. Configure client.yaml

Set at minimum:
- `zabbix.server_host` — IP or hostname of your Zabbix server
- `zabbix.host_name` — host name exactly as it appears in the Zabbix frontend

### 2. Provision Zabbix host and trapper items

```bash
cd ../zabbix_update
python3 create_trapper_items.py --config ../zabbig_client/client.yaml
```

Prompts for your Zabbix admin credentials if not supplied via `--user`/`--password` or the `ZABBIX_ADMIN_USER`/`ZABBIX_ADMIN_PASSWORD` env vars. The password prompt is hidden. Creates the host, host group, and all trapper items defined in `metrics.yaml`.

### 3. Dry-run to verify

```bash
python3 run.py --dry-run
```

Runs all collectors and logs what would be sent — nothing is sent to Zabbix.

### 4. Real run

```bash
python3 run.py
```

### 5. Cron entry (every 5 minutes)

```cron
*/5 * * * * /usr/bin/python3 /opt/zabbig_client/run.py >> /var/log/zabbig/client.log 2>&1
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | All metrics collected and sent successfully |
| `1`  | Partial failure — some collectors failed or some sends were rejected |
| `2`  | Fatal error — config invalid, lock conflict, or overall timeout |

---

## Lock File Behaviour

`run.py` creates a PID lock file (default: `state/zabbig_client.lock`) when it starts and removes it on exit. If a lock exists with a PID that is still running, the new instance exits immediately with code 2. Stale locks (PID no longer running) are cleared automatically. The path is configurable via `runtime.lock_file` in `client.yaml`.

---

## Documentation

| Document | Contents |
|----------|----------|
| [configuration.md](../docs/configuration.md) | Full `client.yaml` and `metrics.yaml` reference |
| [provisioning.md](../docs/provisioning.md) | `zabbix_update/` scripts — provisioning templates, items, triggers, dashboards |
| [collector-cpu.md](../docs/collector-cpu.md) | CPU collector modes and scenarios |
| [collector-memory.md](../docs/collector-memory.md) | Memory collector modes and scenarios |
| [collector-disk.md](../docs/collector-disk.md) | Disk collector modes and scenarios |
| [collector-service.md](../docs/collector-service.md) | Service collector modes and scenarios |
| [collector-network.md](../docs/collector-network.md) | Network collector modes and scenarios |
| [collector-log.md](../docs/collector-log.md) | Log collector modes, conditions, and scenarios |
| [collector-probe.md](../docs/collector-probe.md) | Probe collector — TCP/HTTP active endpoint checks |
| [adding-metrics.md](../docs/adding-metrics.md) | How to add a new metric or a new collector |
| [server-setup.md](../docs/server-setup.md) | Docker Zabbix server stack setup |
| [client-setup.md](../docs/client-setup.md) | Docker client container setup |
