# Provisioning Zabbix — zabbix_update/

The `zabbix_update/` directory contains scripts that use the Zabbix JSON-RPC API to set up all monitoring objects. All scripts are **idempotent** — safe to run multiple times.

---

## Scripts

| Script | What it creates |
|---|---|
| `create_template.py` | Zabbix template + trapper items on the template |
| `create_trapper_items.py` | Host group, host, and trapper items directly on a host |
| `create_triggers.py` | Triggers (on a template or host) |
| `create_dashboard.py` | A host-scoped overview dashboard |

Run scripts from the `zabbix_update/` directory.

---

## Typical Setup Order

```bash
cd zabbix_update

# 1. Create items on the host (replaces the old provision_zabbix.py)
python3 create_trapper_items.py --config ../zabbig_client/client.yaml

# 2. Optionally create a shared template
python3 create_template.py

# 3. Create triggers (on template by default)
python3 create_triggers.py --target template

# 4. Create the overview dashboard for a host
python3 create_dashboard.py --host prod-server-01
```

### From inside the Docker container

```bash
docker exec zabbig-client bash -c "cd /app/../zabbix_update && python3 create_trapper_items.py --config /app/client.docker.yaml"
```

---

## Credentials

API credentials are required only for provisioning — `run.py` does not need them.

Credentials are resolved in this priority order for all scripts:

1. CLI flags (`--user`, `--password`)
2. Environment variables (`ZABBIX_ADMIN_USER`, `ZABBIX_ADMIN_PASSWORD`)
3. Interactive prompt (if not supplied by either above)

The password prompt is hidden (no echo). The username prompt defaults to `Admin` if you press Enter without typing anything.

---

## Common Flags (all scripts)

| Flag | Default | Description |
|---|---|---|
| `--api-url URL` | derived from `--server-host` | Zabbix JSON-RPC endpoint URL |
| `--server-host HOST` | `127.0.0.1` | Derives API URL as `http://<HOST>:8080/api_jsonrpc.php` |
| `--user USER` | prompted if not set | Zabbix admin username |
| `--password PASS` | prompted if not set | Zabbix admin password |
| `--no-wait` | off | Skip waiting for the Zabbix web UI to become available |

---

## create_trapper_items.py

Creates the host group, host, and all trapper items on the host directly. Reads host name and host group from `client.yaml`.

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `../zabbig_client/client.yaml` | Path to `client.yaml` |
| `--template PATH` | `template.yaml` | Item presentation overrides |
| `--metrics PATH` | `../zabbig_client/metrics.yaml` | Metric definitions |
| `--only-enabled` | off | Provision only metrics with `enabled: true` |

**`--only-enabled` vs default:** By default all defined metrics are provisioned regardless of their `enabled` flag. This ensures a trapper item exists before you enable a metric — no "no item" errors. Use `--only-enabled` if you want Zabbix to only contain items for currently active metrics.

**Re-running after changes:** After adding or renaming metrics in `metrics.yaml`, re-run the script. New items are created; existing ones are skipped. Items removed from `metrics.yaml` are not deleted automatically — remove them manually in the Zabbix UI.

---

## create_template.py

Creates a shared Zabbix template and all trapper items on it.

| Flag | Default | Description |
|---|---|---|
| `--template PATH` | `template.yaml` | Template + item definitions |
| `--metrics PATH` | `../zabbig_client/metrics.yaml` | Metric definitions |
| `--only-enabled` | off | Provision only enabled metrics |

---

## create_triggers.py

Creates triggers from `triggers.yaml` on a template or directly on a host.

| Flag | Default | Description |
|---|---|---|
| `--triggers PATH` | `triggers.yaml` | Trigger definitions |
| `--target` | `template` | `template` or `host` |
| `--host HOSTNAME` | — | Required when `--target host` |

---

## create_dashboard.py

Creates or updates an overview dashboard for a specific host.

| Flag | Default | Description |
|---|---|---|
| `--dashboard PATH` | `dashboard.yaml` | Dashboard definition |
| `--host HOSTNAME` | required | Zabbix host name |

---

## Self-monitoring Items

| Key | Description |
|---|---|
| `zabbig.client.run.success` | `1` = run succeeded, `0` = fatal error |
| `zabbig.client.collectors.total` | Total metrics attempted in the last run |
| `zabbig.client.collectors.failed` | Metrics that failed or timed out |
| `zabbig.client.duration_ms` | Total run duration in milliseconds |
| `zabbig.client.metrics.sent` | Values accepted by Zabbix in the last run |

These items are defined in `template.yaml` under `self_monitoring_items` and are created by both `create_template.py` and `create_trapper_items.py`.

---

## Dependencies

All dependencies are vendored in `zabbig_client/src/` — no `pip install` is needed:

- `requests` — HTTP calls to the Zabbix API
- `requests` transitive deps: `urllib3`, `certifi`, `charset_normalizer`, `idna`
- `yaml` (PyYAML) — config file parsing
