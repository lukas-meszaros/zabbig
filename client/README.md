# Zabbix Sender — Python Client

A minimal Python client for sending values to Zabbix trapper items.

## Features

- **Direct protocol implementation** — no `zabbix_sender` binary required
- Pure Python stdlib — zero runtime dependencies
- Clean CLI with `--dry-run` support
- Configurable via environment variables or CLI flags
- Useful logging and error messages

## Quick start

```bash
# From the repo root, create a virtual environment:
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Send a heartbeat value:
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1

# Send multiple values at once:
zabbix-sender \
  --host macos-local-sender \
  --key macos.heartbeat --value 1 \
  --key macos.status --value 0 \
  --key macos.error_count --value 0 \
  --key macos.message --value "All systems nominal"

# Dry-run (no network connection):
zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1 --dry-run
```

## Configuration

All options can be set via CLI flags **or** environment variables:

| CLI flag          | Env var          | Default         | Description                          |
|-------------------|------------------|-----------------|--------------------------------------|
| `--server`        | `ZABBIX_SERVER`  | `127.0.0.1`     | Zabbix server host                   |
| `--port`          | `ZABBIX_PORT`    | `10051`         | Zabbix trapper port                  |
| `--host`          | `ZABBIX_HOST`    | —               | Zabbix host name (as configured in Zabbix) |
| `--key`           | —                | —               | Item key (repeatable)                |
| `--value`         | —                | —               | Item value (repeatable, paired with `--key`) |
| `--timeout`       | `ZABBIX_TIMEOUT` | `10`            | Socket timeout in seconds            |
| `--dry-run`       | —                | `false`         | Log what would be sent, don't connect|
| `--verbose`, `-v` | —                | `false`         | Enable debug logging                 |

## Running tests

```bash
cd client
pip install -e ".[dev]"
pytest
```
