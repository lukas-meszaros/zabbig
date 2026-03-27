# Probe Collector

Performs active connectivity checks against TCP ports and HTTP(S) endpoints.
Returns a derived value (or raw status code) and optionally sends sub-key items
for response time and SSL certificate validity.

---

## Key Behaviours

**Always returns a value:** the probe never raises an error for connectivity
failures. A refused connection, timeout, or unreachable host maps to
`on_failure` / `default_value` rather than triggering `error_policy`. The
`error_policy` only applies when the metric itself is misconfigured (e.g.,
missing `url` or `host`).

**SSL check is independent:** when `ssl_check: true`, a separate TLS handshake
is made using the system default trust store. The main HTTP request always uses
`verify=False` so the probe always gets a response body and status code
regardless of certificate state.

**Sub-keys require their own Zabbix items:** `<key>.response_time_ms` and
`<key>.ssl_check` are sent as Trapper items in the same batch as the primary
result. Each sub-key needs a separate **Trapper** item configured in Zabbix with
the matching key string.

**Body response cap:** `http_body` mode reads at most `max_response_bytes` bytes
(default 65536, configurable per-metric) before closing the response stream.

---

## Modes

### `tcp`

Attempts a TCP socket connection to `host:port`. Measures elapsed time from
connection initiation to successful handshake. Returns `on_success` (default 1)
when the port is reachable within `timeout_seconds`, otherwise `on_failure`
(default 0).

### `http_status`

Makes an HTTP request and uses the numeric status code. Without `conditions`,
returns the raw integer status code (200, 404, 503, …). With `conditions`,
evaluates the status code as a string through the shared condition engine
(same as the log collector) and returns the matched value.

### `http_body`

Makes an HTTP request and scans the response body line-by-line. Optionally
pre-filters with `match` (only lines passing this regex are processed). Then
evaluates `conditions` against each passing line. The `result` strategy
reduces multiple per-line values into a single scalar.

Mirrors the log collector's `condition` mode, applied to HTTP response content
instead of a log file.

---

## Params

### Common params (all modes)

| Param | Required | Default | Description |
|---|---|---|---|
| `mode` | yes | — | `tcp` \| `http_status` \| `http_body` |
| `response_time_ms` | no | `false` | Send round-trip time to `<key>.response_time_ms`. Reports `0` on failure. |
| `timeout_seconds` | no | `10` | Connection timeout. Set this lower than the metric's outer timeout. Inherited from `collector_defaults.probe`. |

### `tcp` mode params

| Param | Required | Default | Description |
|---|---|---|---|
| `host` | yes | — | Hostname or IP address |
| `port` | yes | — | TCP port number |
| `on_success` | no | `1` | Value returned when port is reachable |
| `on_failure` | no | `0` | Value returned when port is refused or times out |

### HTTP mode params (`http_status` and `http_body`)

| Param | Required | Default | Description |
|---|---|---|---|
| `url` | yes | — | Full URL including scheme (`http://` or `https://`) |
| `method` | no | `GET` | HTTP method |
| `headers` | no | `{}` | Dictionary of request headers |
| `default_value` | no | `0` | Value sent when the connection fails entirely |
| `ssl_check` | no | `false` | Send cert validity to `<key>.ssl_check` (see below) |

### `http_status` additional params

| Param | Required | Default | Description |
|---|---|---|---|
| `conditions` | no | — | Condition list evaluated against the status code string. Without conditions, the raw integer status code is returned. |

### `http_body` additional params

| Param | Required | Default | Description |
|---|---|---|---|
| `match` | no | — | Python regex pre-filter. Only lines matching this pattern are passed to conditions. If provided and no lines match, `default_value` is returned. |
| `result` | no | `last` | `last` / `first` / `max` / `min` — reduces multiple per-line values |
| `conditions` | no | — | Condition list evaluated per qualifying body line. Without conditions, returns `1` when any matching line exists. |
| `max_response_bytes` | no | `65536` | Cap on bytes read from the response body before closing the stream. Override `defaults.max_response_bytes` globally or this param per-metric. |

---

## Sub-keys

### `response_time_ms`

When `response_time_ms: true`, an additional Zabbix item is sent to
`<key>.response_time_ms` containing the round-trip latency in integer milliseconds.

- **TCP mode:** time from connection start to successful handshake. Reports `0` on failure.
- **HTTP modes:** time from first byte sent to response headers received. Reports `0` on connection failure.

This item requires a separate **Trapper** item in Zabbix with key
`<key>.response_time_ms` and type **Numeric (unsigned)**.

### `ssl_check`

When `ssl_check: true` (HTTP modes only), an additional Zabbix item is sent to
`<key>.ssl_check` with one of these values:

| Value | Meaning |
|---|---|
| `1` | Certificate is valid and trusted by the system trust store |
| `0` | Certificate is **invalid** — expired, hostname mismatch, untrusted CA |
| `2` | **Unknown** — SSL handshake failed, host unreachable, or non-HTTPS URL |

The check uses a separate TLS handshake with the default system trust store
(Python's `ssl.create_default_context()`). The main HTTP request always uses
`verify=False` so the primary metric value is always collected regardless of
certificate state.

This item requires a separate **Trapper** item in Zabbix with key
`<key>.ssl_check` and type **Numeric (unsigned)**.

---

## Conditions Reference

The condition engine for `http_status` and `http_body` modes is identical to the log collector (Forms 1–3, `result` strategies, per-condition `host_name`). See [metric-fields.md — Condition Engine](metric-fields.md#condition-engine) for the full syntax reference.

> Sub-key items (`response_time_ms`, `ssl_check`) always use the metric-level `host_name` and are not affected by per-condition overrides.

---

## Scenarios

### TCP port check

```yaml
- id: probe_db_port
  collector: probe
  key: probe.db.port.open
  value_type: int
  delivery: immediate
  timeout_seconds: 5
  error_policy: skip
  params:
    host: db.internal
    port: 5432
    mode: tcp
    on_success: 1
    on_failure: 0
    response_time_ms: true
```

Creates two Zabbix items: `probe.db.port.open` (0 or 1) and
`probe.db.port.open.response_time_ms` (ms integer).

---

### HTTP status — raw status code

```yaml
- id: probe_payment_status
  collector: probe
  key: probe.payment.api.status
  value_type: int
  delivery: immediate
  timeout_seconds: 10
  error_policy: skip
  params:
    url: https://payment.internal/health
    mode: http_status
    response_time_ms: false
```

Returns the raw HTTP status code (e.g. `200`, `503`). Returns `0` on connection
failure.

---

### HTTP status — severity mapping with SSL check

```yaml
- id: probe_auth_up
  collector: probe
  key: probe.auth.service.up
  value_type: int
  delivery: immediate
  timeout_seconds: 10
  error_policy: skip
  params:
    url: https://auth.internal/health
    mode: http_status
    default_value: 0
    response_time_ms: true
    ssl_check: true
    conditions:
      - when: "^2"
        value: 1
      - when: "^5"
        value: 2
      - value: 0
```

Creates three Zabbix items: `probe.auth.service.up`, `.response_time_ms`,
and `.ssl_check`.

---

### HTTP body — JSON field check

```yaml
- id: probe_api_health_status
  collector: probe
  key: probe.api.health.status
  value_type: int
  delivery: immediate
  timeout_seconds: 10
  error_policy: skip
  params:
    url: https://api.example.com/health
    mode: http_body
    method: GET
    headers:
      Authorization: "Bearer token123"
      Accept: "application/json"
    match: '"status"'
    result: max
    default_value: 0
    max_response_bytes: 8192
    response_time_ms: true
    ssl_check: true
    conditions:
      - when: '"status":\s*"ok"'
        value: 1
      - when: '"status":\s*"degraded"'
        value: 2
      - when: '"status":\s*"error"'
        value: 3
      - value: 0
```

The `match: '"status"'` guard skips lines that don't mention `status`. The
`conditions` list maps the JSON field value to a severity integer. `result: max`
ensures the worst severity is reported when the body contains multiple status
references.

---

For `host_name` override, scheduling fields (`time_window_from`, `time_window_till`, `max_executions_per_day`, `run_frequency`), and all other common metric fields see [metric-fields.md](metric-fields.md).
