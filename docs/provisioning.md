# Provisioning Zabbix — provision_zabbix.py

`provision_zabbix.py` uses the Zabbix JSON-RPC API to create the monitoring host, host group, and all required trapper items in Zabbix. It is **idempotent** — safe to run multiple times; existing objects are updated rather than recreated.

---

## What It Creates

| Object | Source |
|---|---|
| Host group | Value of `zabbix.host_group` in `client.yaml` |
| Host | Value of `zabbix.host_name` in `client.yaml` |
| Trapper items | One per metric in `metrics.yaml` (all defined by default) |
| Self-monitoring items | Five `zabbig.client.*` items for client health monitoring |

**Self-monitoring items:**

| Key | Description |
|---|---|
| `zabbig.client.run.success` | `1` = run succeeded, `0` = fatal error |
| `zabbig.client.collectors.total` | Total metrics attempted in the last run |
| `zabbig.client.collectors.failed` | Metrics that failed or timed out |
| `zabbig.client.duration_ms` | Total run duration in milliseconds |
| `zabbig.client.metrics.sent` | Values accepted by Zabbix in the last run |

---

## Running the Script

### From inside the container (recommended)

```bash
docker exec zabbig-client python3 provision_zabbix.py --config client.docker.yaml
```

### From the macOS host

```bash
cd zabbig_client
python3 provision_zabbix.py --config client.yaml
```

The API URL is derived automatically from `zabbix.server_host` in `client.yaml`:

```
http://<server_host>:8080/api_jsonrpc.php
```

Override this with `--api-url` if your setup uses a different port or path.

---

## Credentials

API credentials are required only for provisioning — `run.py` does not need them.

Credentials are resolved in this priority order:

1. CLI flags (`--user`, `--password`)
2. Environment variables (`ZABBIX_ADMIN_USER`, `ZABBIX_ADMIN_PASSWORD`)
3. Interactive prompt (if not supplied by either above)

The password prompt is hidden (no echo). The username prompt defaults to `Admin` if you press Enter without typing anything.

---

## All CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `client.yaml` | Path to client config file |
| `--metrics PATH` | `metrics.yaml` | Path to metrics definitions file |
| `--api-url URL` | derived from `server_host` | Zabbix JSON-RPC endpoint URL |
| `--user USER` | prompted if not set | Zabbix admin username |
| `--password PASS` | prompted if not set | Zabbix admin password |
| `--only-enabled` | off | Provision only metrics with `enabled: true` |
| `--no-wait` | off | Skip waiting for the web UI to become available |

---

## `--only-enabled` vs default behaviour

By default, **all defined metrics** are provisioned regardless of their `enabled` flag. This ensures a Zabbix trapper item exists and is ready to receive data whenever a metric is later enabled — you won't get a "no item" error when you turn a metric on.

Use `--only-enabled` if you want Zabbix to only contain items for currently active metrics.

---

## Re-running After Changes

After adding, removing, or renaming metrics in `metrics.yaml`, re-run the script. It will create any new items and update existing ones. It does **not** delete items that have been removed from `metrics.yaml` — remove those manually in the Zabbix UI if needed.

```bash
docker exec zabbig-client python3 provision_zabbix.py --config client.docker.yaml
```

---

## Dependencies

All dependencies are vendored in `src/` — no `pip install` is needed:

- `requests` — HTTP calls to the Zabbix API
- `requests` transitive deps: `urllib3`, `certifi`, `charset_normalizer`, `idna`
- `yaml` (PyYAML) — config file parsing
