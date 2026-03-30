# Database Collector

Runs a SQL query against a configured relational database and sends the result to Zabbix. Connection details are defined separately in `databases.yaml` so credentials never appear in `metrics.yaml`.

Supported databases: **PostgreSQL** (v1). The connection dispatcher is extensible; other drivers can be added without changes to the collector itself.

---

## Key Behaviours

**Thread-safe, non-blocking:** queries run in a thread pool via `asyncio.to_thread`. The async event loop is never blocked regardless of query duration.

**Connection-per-collection:** a fresh connection is opened for each collection run and closed immediately afterwards. Connection pooling is not used, keeping resource usage predictable and simple.

**Automatic connection cleanup:** the connection is always closed — even when the query or condition evaluation raises an exception — so no idle connections accumulate in the database.

**Pure-Python driver:** PostgreSQL connections use the vendored `pg8000` library (no system packages or compiled extensions required).

---

## Setup

Before using the database collector you need:

1. A `databases.yaml` file listing connection details (see [below](#databasesyaml)).
2. Optionally, an encrypted password created with [scripts/encrypt_password.py](encrypt-passwords.md).
3. Pass `--databases /path/to/databases.yaml` when starting the client, or place `databases.yaml` alongside `run.py` (the default).

---

## Params

| Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `database` | yes | string | — | Name of the entry in `databases.yaml`. |
| `sql` | yes | string | — | SQL `SELECT` statement to execute. |
| `mode` | no | string | `value` | `value` or `condition`. |
| `result_column` | no | int | `0` | 0-based index of the column to read. |
| `result` | no | string | `last` | Multi-row reduction: `first` / `last` / `max` / `min`. |
| `default_value` | no | string | — | Value sent when the query returns no rows. Omit to skip the metric on empty results. |
| `conditions` | required for `condition` mode | list | — | Ordered condition entries (same syntax as the log collector). |

---

## Modes

### `value` mode (default)

Reads the value at `result_column` from every row returned, then applies the `result` strategy to produce a single scalar.

- **`last`** — value from the last row (default).
- **`first`** — value from the first row.
- **`max`** — highest numeric value across all rows.
- **`min`** — lowest numeric value across all rows.

For simple single-row queries (`SELECT count(*) FROM …`) the default `last` strategy is always correct.

### `condition` mode

Evaluates each row's value at `result_column` against the `conditions` list using the same engine shared by the log and probe collectors. The first matching condition in each row determines its output value. The `result` strategy then reduces all per-row outputs to a single value.

This is useful for alerting on threshold breaches where you want to map a raw numeric value to a severity code, or where you need to route a result to a different Zabbix host via `host_name`.

See [configuration-metrics.yaml.md — Condition engine](configuration-metrics.yaml.md#condition-engine) for the full condition syntax.

---

## `databases.yaml`

Define all database connections in a single YAML file:

```yaml
version: 1

databases:
  - name: local_postgres        # identifier used in params.database
    type: postgres
    host: "127.0.0.1"
    port: 5432
    dbname: "appdb"
    username: "monitor"
    password: "ENC:..."         # from scripts/encrypt_password.py
    connect_timeout: 10         # optional, seconds (default: 10)
    options: {}                 # optional driver keyword args (e.g. ssl_context)
```

**`name`** must match the `params.database` value in `metrics.yaml` exactly.

**`password`** accepts either a plain-text string or an `ENC:…` token produced by `encrypt_password.py`. Plain-text passwords produce a startup warning. See [Encrypting Passwords](encrypt-passwords.md).

**`secret.key`** is stored inside `zabbig_client/` alongside `databases.yaml`. Copying the `zabbig_client/` directory to another server brings both the config and the key, so encrypted passwords work on every host without extra steps.

**`options`** is passed directly to the underlying driver as keyword arguments. For `pg8000` this includes flags such as `application_name` or `ssl_context`.

---

## Scenarios

### Count active database connections

```yaml
- id: db_active_connections
  name: "PostgreSQL active connections"
  collector: database
  key: pg.connections.active
  value_type: int
  delivery: batch
  params:
    database: local_postgres
    sql: "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
    mode: value
```

---

### Alert severity based on a threshold

Map a replication lag (in seconds) to a Zabbix severity code. `result: max` ensures the worst case is reported when multiple rows are returned.

```yaml
- id: db_replication_lag_alert
  name: "Replication lag alert level"
  collector: database
  key: pg.replication.lag.alert
  value_type: int
  delivery: immediate
  params:
    database: local_postgres
    sql: >
      SELECT extract(epoch FROM now() - pg_last_xact_replay_timestamp())::int
    mode: condition
    default_value: 0
    conditions:
      - extract: '(\d+)'
        compare: gt
        threshold: 300
        value: 3          # critical: > 5 min
      - extract: '(\d+)'
        compare: gt
        threshold: 60
        value: 2          # warning: > 1 min
      - value: 1          # ok
```

---

### Send per-table row counts using host_name routing

When `host_name` is set on a condition, the result is delivered to that Zabbix host instead of the metric's default host. This lets a single metric fan out to multiple hosts.

```yaml
- id: db_table_row_count
  name: "Table row counts"
  collector: database
  key: db.table.rows
  value_type: int
  delivery: batch
  params:
    database: local_postgres
    sql: "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname"
    mode: condition
    result_column: 1
    conditions:
      - extract: '(\d+)'
        value: "$1"
        host_name: "db-stats-host"
```

---

### Return a default when a monitored row disappears

```yaml
- id: db_config_flag
  name: "Maintenance mode flag"
  collector: database
  key: app.maintenance_mode
  value_type: int
  delivery: batch
  params:
    database: local_postgres
    sql: "SELECT value FROM app_config WHERE key = 'maintenance_mode'"
    mode: value
    default_value: "0"   # treat missing row as off
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Database not in `databases.yaml` | `KeyError` raised; metric skipped per `error_policy`. |
| Connection failure | Driver exception propagated; metric skipped per `error_policy`. |
| Query returns no rows | `default_value` used if set; otherwise metric is skipped. |
| `result_column` out of range | `IndexError` raised. |
| `mode: condition` with empty conditions | `ValueError` raised. |
| Unknown `mode` value | `ValueError` raised. |

---

## `result` Strategy Reference

| Strategy | Behaviour |
|---|---|
| `last` | Value from the **last** row (default). Good for single-row queries. |
| `first` | Value from the **first** row. |
| `max` | **Highest** numeric value across all rows. |
| `min` | **Lowest** numeric value across all rows. |
