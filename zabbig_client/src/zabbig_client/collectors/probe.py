"""
probe.py — Network endpoint probe collector.

Performs active connectivity checks against TCP ports and HTTP(S) endpoints.
Three modes:

  tcp         — Attempts a TCP socket connection and measures round-trip time.
                Returns `on_success` (default 1) when the port is reachable,
                `on_failure` (default 0) when it is not (refused or timeout).

  http_status — Makes an HTTP request and evaluates the HTTP status code
                (as a string) through the `conditions` engine. Without
                `conditions`, returns the raw numeric status code.

  http_body   — Makes an HTTP request, optionally filtered per-line by
                `match`, and evaluates the response body through the same
                `conditions` engine as the log collector. `result` strategy
                (first / last / max / min) reduces multiple per-line values.

Optional sub-keys (sent as additional Zabbix trapper items):

  response_time_ms — When `response_time_ms: true`, sends a second item
                     to `<key>.response_time_ms` with the round-trip time
                     in milliseconds. Reports 0 on probe failure.

  ssl_check        — When `ssl_check: true` (http modes only), sends a
                     second item to `<key>.ssl_check`:
                       1  =  certificate valid and trusted
                       0  =  certificate invalid (expired, wrong host, …)
                       2  =  unknown (SSL handshake failed or unreachable)

HTTP safety notes:
  All HTTP requests use `verify=False` so the probe ALWAYS completes and
  returns a value regardless of certificate state. SSL validity is checked
  independently via a separate TLS handshake using the system trust store.

  http_body reads at most `max_response_bytes` bytes from the response
  before closing the stream. The default is inherited from `defaults.
  max_response_bytes` (65536). Override per-metric in params.

Params reference — see docs/collector-probe.md and the metrics.yaml header.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
import warnings
from typing import Any
from urllib.parse import urlparse

import requests  # vendored in src/
from urllib3.exceptions import InsecureRequestWarning  # vendored in src/

from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector
from .log import _eval_conditions, _resolve_result, _resolve_result_with_host

import asyncio

_DEFAULT_MAX_RESPONSE_BYTES = 65536


@register_collector("probe")
class ProbeCollector(BaseCollector):

    async def collect(self, metric: MetricDef) -> list[MetricResult]:  # type: ignore[override]
        mode = metric.params.get("mode")

        if mode == "tcp":
            return await asyncio.to_thread(_run_tcp_probe, metric)
        elif mode in ("http_status", "http_body"):
            return await asyncio.to_thread(_run_http_probe, metric)
        else:
            raise ValueError(
                f"Unknown probe mode: '{mode}'. "
                "Valid values: tcp | http_status | http_body"
            )


# ---------------------------------------------------------------------------
# TCP probe
# ---------------------------------------------------------------------------

def _run_tcp_probe(metric: MetricDef) -> list[MetricResult]:
    """
    Attempt a TCP connection to host:port. Returns on_success or on_failure.
    Optionally appends a response_time_ms sub-key result.
    """
    params = metric.params
    host: str = params["host"]
    port: int = int(params["port"])
    on_success = params.get("on_success", 1)
    on_failure = params.get("on_failure", 0)
    want_rt: bool = bool(params.get("response_time_ms", False))

    t0 = time.monotonic()
    success = False
    try:
        with socket.create_connection((host, port), timeout=metric.timeout_seconds):
            pass
        success = True
    except (socket.timeout, OSError):
        pass
    elapsed_ms = (time.monotonic() - t0) * 1000

    now = int(time.time())
    primary_value = on_success if success else on_failure
    source = f"tcp host={host} port={port}"

    results = [MetricResult(
        metric_id=metric.id,
        key=metric.key,
        value=str(primary_value),
        value_type=metric.value_type,
        timestamp=now,
        collector="probe",
        delivery=metric.delivery,
        status=RESULT_OK,
        unit=metric.unit,
        tags=metric.tags,
        source=source,
        duration_ms=elapsed_ms,
        host_name=metric.host_name,
    )]

    if want_rt:
        results.append(MetricResult(
            metric_id=f"{metric.id}._rt",
            key=f"{metric.key}.response_time_ms",
            value=str(int(elapsed_ms)) if success else "0",
            value_type="int",
            timestamp=now,
            collector="probe",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit="ms",
            tags=metric.tags,
            source=source,
            duration_ms=elapsed_ms,
            host_name=metric.host_name,
        ))

    return results


# ---------------------------------------------------------------------------
# HTTP probe (http_status and http_body)
# ---------------------------------------------------------------------------

def _run_http_probe(metric: MetricDef) -> list[MetricResult]:
    """
    Make an HTTP request and evaluate the response status code or body.
    Optionally appends response_time_ms and ssl_check sub-key results.
    """
    params = metric.params
    url: str = params["url"]
    mode: str = params["mode"]
    method: str = params.get("method", "GET").upper()
    headers: dict = params.get("headers") or {}
    default_value = params.get("default_value", 0)
    want_rt: bool = bool(params.get("response_time_ms", False))
    want_ssl: bool = bool(params.get("ssl_check", False))
    max_bytes: int = int(params.get("max_response_bytes", _DEFAULT_MAX_RESPONSE_BYTES))

    # http_body specific
    match_pattern: str | None = params.get("match")
    result_strategy: str = params.get("result", "last")
    conditions: list[dict] = params.get("conditions", [])

    now = int(time.time())
    source = f"http mode={mode} url={url}"

    parsed = urlparse(url)
    ssl_host: str = parsed.hostname or ""
    ssl_port: int = parsed.port or (443 if parsed.scheme == "https" else 80)

    # --- SSL cert check (independent TLS handshake with system trust store) ---
    ssl_value: int = 2  # default: unknown until checked
    if want_ssl:
        ssl_value = _ssl_cert_check(ssl_host, ssl_port, metric.timeout_seconds)

    # --- Main HTTP request (verify=False — probe always completes) ---
    status_code: int | None = None
    body: str = ""
    connect_ok = False
    t0 = time.monotonic()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            resp = requests.request(
                method,
                url,
                headers=headers,
                timeout=metric.timeout_seconds,
                verify=False,
                stream=True,
                allow_redirects=True,
            )
        status_code = resp.status_code
        if mode == "http_body":
            raw_body = resp.raw.read(max_bytes, decode_content=True)
            body = raw_body.decode(resp.encoding or "utf-8", errors="replace")
        connect_ok = True
    except Exception:
        pass
    elapsed_ms = (time.monotonic() - t0) * 1000

    # --- Compute primary value ---
    primary_host_name: str | None = None
    if not connect_ok:
        primary_value = default_value
    elif mode == "http_status":
        if conditions:
            primary_value, primary_host_name = _eval_http_status(str(status_code), conditions, default_value)
        else:
            primary_value = status_code
    else:  # http_body
        primary_value, primary_host_name = _eval_http_body(
            body, match_pattern, conditions, result_strategy, default_value
        )

    results = [MetricResult(
        metric_id=metric.id,
        key=metric.key,
        value=str(primary_value),
        value_type=metric.value_type,
        timestamp=now,
        collector="probe",
        delivery=metric.delivery,
        status=RESULT_OK,
        unit=metric.unit,
        tags=metric.tags,
        source=source,
        duration_ms=elapsed_ms,
        host_name=primary_host_name or metric.host_name,
    )]

    if want_rt:
        rt_val = int(elapsed_ms) if connect_ok else 0
        results.append(MetricResult(
            metric_id=f"{metric.id}._rt",
            key=f"{metric.key}.response_time_ms",
            value=str(rt_val),
            value_type="int",
            timestamp=now,
            collector="probe",
            delivery=metric.delivery,
            status=RESULT_OK,
            unit="ms",
            tags=metric.tags,
            source=source,
            duration_ms=elapsed_ms,
            host_name=metric.host_name,
        ))

    if want_ssl:
        results.append(MetricResult(
            metric_id=f"{metric.id}._ssl",
            key=f"{metric.key}.ssl_check",
            value=str(ssl_value),
            value_type="int",
            timestamp=now,
            collector="probe",
            delivery=metric.delivery,
            status=RESULT_OK,
            tags=metric.tags,
            source=source,
            duration_ms=elapsed_ms,
            host_name=metric.host_name,
        ))

    return results


# ---------------------------------------------------------------------------
# SSL certificate check
# ---------------------------------------------------------------------------

def _ssl_cert_check(host: str, port: int, timeout: float) -> int:
    """
    Attempt a TLS handshake using the system default trust store.

    Returns:
      1  — certificate is valid and trusted
      0  — certificate is invalid (expired, hostname mismatch, untrusted CA)
      2  — unknown (handshake failed for non-cert reasons, or host unreachable)
    """
    ctx = ssl.create_default_context()
    try:
        with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
            s.settimeout(timeout)
            s.connect((host, port))
        return 1
    except ssl.SSLCertVerificationError:
        return 0
    except (ssl.SSLError, OSError):
        return 2


# ---------------------------------------------------------------------------
# HTTP body and status helpers
# ---------------------------------------------------------------------------

def _eval_http_status(
    status_str: str,
    conditions: list[dict],
    default_value: Any,
) -> tuple[Any, str | None]:
    """
    Evaluate HTTP status code string (e.g. "200") through the condition engine.
    Returns (value, host_name). host_name is None when no condition override applies.
    Falls back to (default_value, None) when no condition matches.
    """
    val, host_name = _eval_conditions(conditions, status_str)
    if val is not None:
        return val, host_name
    return default_value, None


def _eval_http_body(
    body: str,
    match_pattern: str | None,
    conditions: list[dict],
    result_strategy: str,
    default_value: Any,
) -> tuple[Any, str | None]:
    """
    Scan response body line by line. Optionally pre-filter with `match`.
    Apply condition engine to each passing line and reduce via strategy.

    Returns (value, host_name). host_name comes from the winning condition entry
    (or None when no condition override applies or no conditions are defined).
    Falls back to (default_value, None) when no qualifying line is found.

    Mirrors the log collector’s condition mode, applied to response body
    text instead of a log file.
    """
    if not body:
        return default_value, None

    lines = body.splitlines()
    match_re = re.compile(match_pattern) if match_pattern else None
    entries: list[tuple[Any, str | None]] = []

    for line in lines:
        if match_re and not match_re.search(line):
            continue

        if conditions:
            val, cond_host = _eval_conditions(conditions, line)
            if val is not None:
                entries.append((val, cond_host))
        else:
            # No conditions — each matching line contributes 1
            entries.append((1, None))

    if not entries:
        return default_value, None

    return _resolve_result_with_host(entries, result_strategy)
