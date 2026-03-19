#!/usr/bin/env python3
"""
provision_zabbix.py — Provision a Zabbix host and all required trapper items for the
               zabbig monitoring client.

Reads Zabbix server connection details, host_name, and host_group from
client.yaml, and all item keys from metrics.yaml.  Idempotent — safe to
re-run; existing objects are updated (tags synced) but not recreated.

What this creates
-----------------
  Host group  : value of zabbix.host_group in client.yaml
  Host        : value of zabbix.host_name  in client.yaml
  Items       : one Zabbix Trapper item per enabled metric key in metrics.yaml
                + five self-monitoring items (zabbig.client.*)

Usage
-----
  cd zabbig_client
  python3 provision_zabbix.py [--config client.yaml] [--metrics metrics.yaml]
                       [--api-url URL] [--user USER] [--password PASS]
                       [--no-wait]

API credentials (only needed for bootstrap, not for the sender)
---------------------------------------------------------------
  --user / ZABBIX_ADMIN_USER          default: Admin
  --password / ZABBIX_ADMIN_PASSWORD  default: zabbix

Dependencies (all vendored in src/ — no pip install required)
-------------------------------------------------------------
  requests 2.32.5, urllib3 2.6.3, certifi 2026.2.25,
  charset-normalizer 3.4.6, idna 3.11

The API URL is derived automatically from zabbix.server_host in client.yaml:
  http://<server_host>:8080/api_jsonrpc.php
Override with --api-url or ZABBIX_API_URL env var.
"""

import argparse
import logging
import os
import re
import sys
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Make vendored deps (yaml, zabbig_client) importable without installation
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

try:
    import yaml  # vendored pure-Python PyYAML
except ImportError:
    sys.exit(
        "ERROR: PyYAML not found.\n"
        "       Expected vendored copy at: src/yaml/__init__.py"
    )

try:
    import requests  # vendored in src/requests/
except ImportError:
    sys.exit(
        "ERROR: 'requests' package not found.\n"
        "       Expected vendored copy at: src/requests/\n"
        "       Run: python3 scripts/vendor_requests.py"
    )

from zabbig_client.config_loader import load_client_config

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
    load_dotenv(os.path.join(_HERE, "..", ".env"))
except ImportError:
    pass  # python-dotenv is optional

# ---------------------------------------------------------------------------
# Credential defaults from env (API-only, not stored in client.yaml)
# ---------------------------------------------------------------------------
_DEFAULT_USER = os.getenv("ZABBIX_ADMIN_USER", "Admin")
_DEFAULT_PASSWORD = os.getenv("ZABBIX_ADMIN_PASSWORD", "zabbix")

# ---------------------------------------------------------------------------
# Zabbix value_type constants
# ---------------------------------------------------------------------------
_VT_FLOAT = 0   # Numeric float
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
_SELF_MON_TAGS = [{"tag": "zabbig", "value": ""}, {"tag": "self-monitoring", "value": ""}]

SELF_MONITORING_ITEMS = [
    {
        "name": "zabbig client: run success",
        "key_": "zabbig.client.run.success",
        "description": "1 = last run completed successfully, 0 = run ended with failures.",
        "value_type": _VT_INT,
        "tags": _SELF_MON_TAGS,
    },
    {
        "name": "zabbig client: collectors total",
        "key_": "zabbig.client.collectors.total",
        "description": "Total number of enabled collectors in the last run.",
        "value_type": _VT_INT,
        "tags": _SELF_MON_TAGS,
    },
    {
        "name": "zabbig client: collectors failed",
        "key_": "zabbig.client.collectors.failed",
        "description": "Number of collectors that failed or timed out in the last run.",
        "value_type": _VT_INT,
        "tags": _SELF_MON_TAGS,
    },
    {
        "name": "zabbig client: run duration (ms)",
        "key_": "zabbig.client.duration_ms",
        "description": "Wall-clock duration of the last client run in milliseconds.",
        "value_type": _VT_INT,
        "tags": _SELF_MON_TAGS,
    },
    {
        "name": "zabbig client: metrics sent",
        "key_": "zabbig.client.metrics.sent",
        "description": "Total number of metric values successfully accepted by Zabbix in the last run.",
        "value_type": _VT_INT,
        "tags": _SELF_MON_TAGS,
    },
]


# ---------------------------------------------------------------------------
# Metrics config loading
# ---------------------------------------------------------------------------

def _tags_to_zabbix(tags: list) -> list[dict]:
    """Convert ["cpu", "env:prod"] → [{"tag":"cpu","value":""},{"tag":"env","value":"prod"}]."""
    result = []
    for t in tags:
        t = str(t)
        if ":" in t:
            name, _, value = t.partition(":")
            result.append({"tag": name.strip(), "value": value.strip()})
        else:
            result.append({"tag": t.strip(), "value": ""})
    return result


def load_metrics_config(path: str) -> list[dict]:
    """Return item defs (key, value_type, name, description, tags) for each enabled metric."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    result = []
    for m in data.get("metrics", []):
        if m.get("enabled", True) is False:
            continue
        key = m.get("key")
        if not key:
            continue
        vt_int = _YAML_VT_MAP.get(str(m.get("value_type", "float")).lower(), _VT_FLOAT)
        zbx_tags = _tags_to_zabbix(m.get("tags") or [])
        item: dict = {
            "name": m.get("name") or key,
            "key_": key,
            "description": m.get("description") or "",
            "value_type": vt_int,
        }
        if zbx_tags:
            item["tags"] = zbx_tags
        result.append(item)
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
            # Item exists — update tags so re-running bootstrap syncs them.
            update_params: dict = {"itemid": iid}
            update_params["tags"] = item_def.get("tags", [])
            self._call("item.update", update_params)
            log.info("  Item '%s' already exists (id=%s) — tags synced", key, iid)
            return iid
        params = {
            "hostid": host_id,
            "type": 2,      # Zabbix Trapper
            "delay": "0",   # required 0 for trapper items
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

    log.info("--- Host group ---")
    group_id = api.ensure_hostgroup(host_group)

    log.info("--- Host ---")
    host_id = api.ensure_host(host_name, group_id)

    log.info("--- Metric items (%d) ---", len(metric_items))
    for item in metric_items:
        api.ensure_item(host_id, item)

    log.info("--- Self-monitoring items (%d) ---", len(SELF_MONITORING_ITEMS))
    for item in SELF_MONITORING_ITEMS:
        api.ensure_item(host_id, item)

    log.info("=" * 60)
    log.info("Done.  Host '%s' is ready to receive trapper data.", host_name)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(default_api_url: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision a Zabbix host and trapper items for zabbig_client."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(_HERE, "client.yaml"),
        metavar="PATH",
        help="Path to client.yaml (default: client.yaml next to this script)",
    )
    parser.add_argument(
        "--metrics",
        default=os.path.join(_HERE, "metrics.yaml"),
        metavar="PATH",
        help="Path to metrics.yaml (default: metrics.yaml next to this script)",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        metavar="URL",
        help=(
            f"Zabbix JSON-RPC API URL.  "
            f"Defaults to http://<server_host>:8080/api_jsonrpc.php "
            f"(derived from zabbix.server_host in client.yaml).  "
            f"Also read from ZABBIX_API_URL env var."
        ),
    )
    parser.add_argument(
        "--user",
        default=_DEFAULT_USER,
        metavar="USER",
        help=f"Zabbix admin username (default: {_DEFAULT_USER})",
    )
    parser.add_argument(
        "--password",
        default=_DEFAULT_PASSWORD,
        metavar="PASS",
        help="Zabbix admin password (env: ZABBIX_ADMIN_PASSWORD)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for the Zabbix web UI to become available.",
    )
    return parser.parse_args()


def main() -> int:
    # Parse args with a placeholder first to load client.yaml for the API URL default.
    args = _parse_args(default_api_url="")

    if not os.path.exists(args.config):
        log.error("client.yaml not found: %s", args.config)
        return 1
    if not os.path.exists(args.metrics):
        log.error("metrics.yaml not found: %s", args.metrics)
        return 1

    # Load client configuration — server_host, host_name, host_group all come from here.
    client_cfg = load_client_config(args.config)
    zbx = client_cfg.zabbix

    # Derive API URL: CLI arg > env var > default based on server_host
    api_url = (
        args.api_url
        or os.getenv("ZABBIX_API_URL")
        or f"http://{zbx.server_host}:8080/api_jsonrpc.php"
    )

    metric_items = load_metrics_config(args.metrics)

    log.info("Config file   : %s", args.config)
    log.info("Metrics file  : %s (%d enabled items)", args.metrics, len(metric_items))
    log.info("Target host   : %s", zbx.host_name)
    log.info("Host group    : %s", zbx.host_group)
    log.info("API URL       : %s", api_url)

    if not args.no_wait:
        _wait_for_api(api_url)

    api = ZabbixAPI(api_url)
    try:
        api.login(args.user, args.password)
        provision(api, zbx.host_name, zbx.host_group, metric_items)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
