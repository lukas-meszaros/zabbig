#!/usr/bin/env python3
"""
zabbig_client/scripts/bootstrap_zabbix.py
──────────────────────────────────────────
Provision a Zabbix host and all required trapper items for the zabbig client.

Reads client.yaml (for host_name) and metrics.yaml (for item keys) then uses
the Zabbix JSON-RPC API to create everything.  Idempotent — safe to re-run;
objects that already exist are left untouched.

What this creates
-----------------
  Host group  : "zabbig Clients"  (configurable via ZABBIX_HOST_GROUP env var)
  Host        : value of zabbix.host_name in client.yaml (default: system hostname)
  Items       : one Zabbix Trapper item per enabled metric key in metrics.yaml
                + five self-monitoring items (zabbig.client.*)

Usage
-----
  cd zabbig_client
  python3 scripts/bootstrap_zabbix.py [--config client.yaml] [--metrics metrics.yaml]

Environment variables (can also be set in .env at the repo root)
----------------------------------------------------------------
  ZABBIX_API_URL        default: http://localhost:8080/api_jsonrpc.php
  ZABBIX_ADMIN_USER     default: Admin
  ZABBIX_ADMIN_PASSWORD default: zabbix
  ZABBIX_HOST_GROUP     default: zabbig Clients
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import socket
import sys
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Make vendored deps (yaml) importable without installation
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_SCRIPT_DIR, "..", "src")
sys.path.insert(0, _SRC)

try:
    import yaml
except ImportError:
    sys.exit(
        "ERROR: PyYAML not found.\n"
        "       Expected vendored copy at: src/yaml/__init__.py\n"
        "       Run: python3 scripts/vendor_yaml.py"
    )

try:
    import requests  # type: ignore[import]
except ImportError:
    sys.exit(
        "ERROR: 'requests' is not installed.\n"
        "       Run:  pip install requests   (only needed for this bootstrap script)"
    )

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env from the repo root (optional — graceful no-op when absent)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore[import]
    load_dotenv(os.path.join(_SCRIPT_DIR, "..", "..", ".env"))
except ImportError:
    pass  # python-dotenv is optional

# ---------------------------------------------------------------------------
# Defaults (can be overridden via env vars)
# ---------------------------------------------------------------------------
DEFAULT_API_URL = os.getenv("ZABBIX_API_URL", "http://localhost:8080/api_jsonrpc.php")
DEFAULT_ADMIN_USER = os.getenv("ZABBIX_ADMIN_USER", "Admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ZABBIX_ADMIN_PASSWORD", "zabbix")
DEFAULT_HOST_GROUP = os.getenv("ZABBIX_HOST_GROUP", "zabbig Clients")

# ---------------------------------------------------------------------------
# Zabbix value_type constants
# ---------------------------------------------------------------------------
_VT_FLOAT = 0   # Numeric float
_VT_STR   = 1   # Character string (up to 255 chars)
_VT_INT   = 3   # Numeric unsigned integer
_VT_TEXT  = 4   # Text (unlimited)

_YAML_VT_MAP = {
    "float":  _VT_FLOAT,
    "int":    _VT_INT,
    "string": _VT_TEXT,
}

# ---------------------------------------------------------------------------
# Self-monitoring items emitted by sender_manager.py
# ---------------------------------------------------------------------------
SELF_MONITORING_ITEMS = [
    {
        "name": "zabbig client: run success",
        "key_": "zabbig.client.run.success",
        "description": "1 = last run completed successfully, 0 = run ended with failures.",
        "value_type": _VT_INT,
    },
    {
        "name": "zabbig client: collectors total",
        "key_": "zabbig.client.collectors.total",
        "description": "Total number of enabled collectors in the last run.",
        "value_type": _VT_INT,
    },
    {
        "name": "zabbig client: collectors failed",
        "key_": "zabbig.client.collectors.failed",
        "description": "Number of collectors that failed or timed out in the last run.",
        "value_type": _VT_INT,
    },
    {
        "name": "zabbig client: run duration (ms)",
        "key_": "zabbig.client.duration_ms",
        "description": "Wall-clock duration of the last client run in milliseconds.",
        "value_type": _VT_INT,
    },
    {
        "name": "zabbig client: metrics sent",
        "key_": "zabbig.client.metrics.sent",
        "description": "Total number of metric values successfully accepted by Zabbix in the last run.",
        "value_type": _VT_INT,
    },
]

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_client_config(path: str) -> dict:
    data = _load_yaml(path)
    zabbix = data.get("zabbix", {})
    return {
        "host_name": zabbix.get("host_name") or socket.gethostname(),
    }


def load_metrics_config(path: str) -> list[dict]:
    """Return list of (key, value_type_int, name, description) for each enabled metric."""
    data = _load_yaml(path)
    metrics_list = data.get("metrics", [])
    result = []
    for m in metrics_list:
        if m.get("enabled", True) is False:
            continue
        key = m.get("key")
        if not key:
            continue
        vt_str = m.get("value_type", "float")
        vt_int = _YAML_VT_MAP.get(str(vt_str).lower(), _VT_FLOAT)
        result.append({
            "name": m.get("name") or key,
            "key_": key,
            "description": m.get("description") or "",
            "value_type": vt_int,
        })
    return result


# ---------------------------------------------------------------------------
# Zabbix JSON-RPC API client
# ---------------------------------------------------------------------------

class ZabbixAPI:
    """Minimal synchronous Zabbix JSON-RPC client."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.auth: Optional[str] = None
        self._req_id = 0
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json-rpc"})

    def _call(self, method: str, params: Any) -> Any:
        self._req_id += 1
        payload: dict = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._req_id,
        }
        if self.auth:
            payload["auth"] = self.auth
        try:
            resp = self._session.post(self.url, json=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP error calling {method}: {exc}") from exc
        data = resp.json()
        if "error" in data:
            raise RuntimeError(
                f"Zabbix API error [{method}]: "
                f"{data['error'].get('message')} — {data['error'].get('data')}"
            )
        return data["result"]

    def login(self, user: str, password: str) -> None:
        # Zabbix 6.4+ uses "username"; older versions use "user".
        try:
            self.auth = self._call("user.login", {"username": user, "password": password})
        except RuntimeError:
            self.auth = self._call("user.login", {"user": user, "password": password})
        log.info("Authenticated as '%s'", user)

    def logout(self) -> None:
        if self.auth:
            try:
                self._call("user.logout", [])
            except RuntimeError:
                pass
            self.auth = None

    # -- Host group ----------------------------------------------------------

    def get_hostgroup_id(self, name: str) -> Optional[str]:
        r = self._call("hostgroup.get", {"filter": {"name": [name]}, "output": ["groupid"]})
        return r[0]["groupid"] if r else None

    def ensure_hostgroup(self, name: str) -> str:
        gid = self.get_hostgroup_id(name)
        if gid:
            log.info("Host group '%s' already exists (id=%s)", name, gid)
            return gid
        gid = self._call("hostgroup.create", {"name": name})["groupids"][0]
        log.info("Created host group '%s' (id=%s)", name, gid)
        return gid

    # -- Host ----------------------------------------------------------------

    def get_host_id(self, hostname: str) -> Optional[str]:
        r = self._call("host.get", {"filter": {"host": [hostname]}, "output": ["hostid"]})
        return r[0]["hostid"] if r else None

    def ensure_host(self, hostname: str, group_id: str) -> str:
        hid = self.get_host_id(hostname)
        if hid:
            log.info("Host '%s' already exists (id=%s)", hostname, hid)
            return hid
        hid = self._call(
            "host.create",
            {
                "host": hostname,
                "name": hostname,
                "groups": [{"groupid": group_id}],
                # Trapper items don't use an agent interface, but Zabbix requires
                # at least one interface per host.
                "interfaces": [
                    {
                        "type": 1,       # Zabbix agent (placeholder)
                        "main": 1,
                        "useip": 1,
                        "ip": "127.0.0.1",
                        "dns": "",
                        "port": "10050",
                    }
                ],
            },
        )["hostids"][0]
        log.info("Created host '%s' (id=%s)", hostname, hid)
        return hid

    # -- Items ---------------------------------------------------------------

    def get_item_id(self, host_id: str, key: str) -> Optional[str]:
        r = self._call(
            "item.get",
            {"hostids": [host_id], "filter": {"key_": [key]}, "output": ["itemid"]},
        )
        return r[0]["itemid"] if r else None

    def ensure_item(self, host_id: str, item_def: dict) -> str:
        key = item_def["key_"]
        iid = self.get_item_id(host_id, key)
        if iid:
            log.info("  Item '%s' already exists (id=%s)", key, iid)
            return iid
        params = {
            "hostid": host_id,
            "type": 2,           # Zabbix Trapper
            "delay": "0",        # required 0 for trapper items
            **item_def,
        }
        iid = self._call("item.create", params)["itemids"][0]
        log.info("  Created item '%s' (id=%s)", key, iid)
        return iid


# ---------------------------------------------------------------------------
# Wait for API
# ---------------------------------------------------------------------------

def _wait_for_api(api_url: str, max_wait: int = 120) -> None:
    log.info("Waiting for Zabbix API at %s ...", api_url)
    ui_url = re.sub(r"api_jsonrpc\.php$", "index.php", api_url)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(ui_url, timeout=5)
            if r.status_code < 500:
                log.info("Zabbix web UI is responding (HTTP %s)", r.status_code)
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(
        f"Zabbix API at {api_url} did not respond within {max_wait}s.\n"
        "  Check:  docker compose ps\n"
        "          docker compose logs zabbix-server\n"
        "          docker compose logs zabbix-web"
    )


# ---------------------------------------------------------------------------
# Main provisioning flow
# ---------------------------------------------------------------------------

def provision(
    api: ZabbixAPI,
    host_name: str,
    host_group: str,
    metric_items: list[dict],
) -> None:
    log.info("=" * 60)
    log.info("Provisioning host='%s'  group='%s'", host_name, host_group)
    log.info("=" * 60)

    # 1. Host group
    log.info("--- Host group ---")
    group_id = api.ensure_hostgroup(host_group)

    # 2. Host
    log.info("--- Host ---")
    host_id = api.ensure_host(host_name, group_id)

    # 3. Metric items
    log.info("--- Metric items (%d) ---", len(metric_items))
    for item in metric_items:
        api.ensure_item(host_id, item)

    # 4. Self-monitoring items
    log.info("--- Self-monitoring items (%d) ---", len(SELF_MONITORING_ITEMS))
    for item in SELF_MONITORING_ITEMS:
        api.ensure_item(host_id, item)

    log.info("=" * 60)
    log.info("Done.  Host '%s' is ready to receive trapper data.", host_name)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    here = os.path.join(_SCRIPT_DIR, "..")
    parser = argparse.ArgumentParser(
        description="Provision a Zabbix host and trapper items for zabbig_client."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(here, "client.yaml"),
        metavar="PATH",
        help="Path to client.yaml (default: ../client.yaml relative to this script)",
    )
    parser.add_argument(
        "--metrics",
        default=os.path.join(here, "metrics.yaml"),
        metavar="PATH",
        help="Path to metrics.yaml (default: ../metrics.yaml relative to this script)",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        metavar="URL",
        help=f"Zabbix JSON-RPC API URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_ADMIN_USER,
        metavar="USER",
        help=f"Zabbix admin username (default: {DEFAULT_ADMIN_USER})",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_ADMIN_PASSWORD,
        metavar="PASS",
        help="Zabbix admin password",
    )
    parser.add_argument(
        "--host-group",
        default=DEFAULT_HOST_GROUP,
        metavar="GROUP",
        help=f"Zabbix host group name (default: {DEFAULT_HOST_GROUP})",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for the Zabbix web UI to become available.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Load configs
    if not os.path.exists(args.config):
        log.error("client.yaml not found: %s", args.config)
        log.error("  Hint: cp client.yaml.example client.yaml")
        return 1
    if not os.path.exists(args.metrics):
        log.error("metrics.yaml not found: %s", args.metrics)
        log.error("  Hint: cp metrics.yaml.example metrics.yaml")
        return 1

    client_cfg = load_client_config(args.config)
    metric_items = load_metrics_config(args.metrics)
    host_name = client_cfg["host_name"]

    log.info("Target host   : %s", host_name)
    log.info("Metrics file  : %s (%d enabled items)", args.metrics, len(metric_items))
    log.info("API URL       : %s", args.api_url)

    # Wait for Zabbix to be ready
    if not args.no_wait:
        _wait_for_api(args.api_url)

    api = ZabbixAPI(args.api_url)
    try:
        api.login(args.user, args.password)
        provision(api, host_name, args.host_group, metric_items)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
