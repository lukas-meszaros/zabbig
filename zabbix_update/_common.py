"""
_common.py — Shared utilities for all zabbix_update scripts.

Provides:
  - sys.path setup for vendored dependencies
  - ZabbixAPI  — minimal JSON-RPC client (reused from provision_zabbix.py)
  - load_yaml  — safe YAML loader
  - load_metrics — parse metrics.yaml into a list of dicts
  - credential resolution helpers
  - _wait_for_api
  - standard argument parsing helpers
"""

import argparse
import getpass
import logging
import os
import re
import sys
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup — vendored deps live in zabbig_client/src/
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.join(_HERE, "..", "zabbig_client")
_SRC = os.path.join(_CLIENT_DIR, "src")

for _p in (_SRC, _CLIENT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import yaml
except ImportError:
    sys.exit(
        "ERROR: PyYAML not found.\n"
        f"       Expected vendored copy at: {_SRC}/yaml/__init__.py"
    )

try:
    import requests
except ImportError:
    sys.exit(
        "ERROR: 'requests' package not found.\n"
        f"       Expected vendored copy at: {_SRC}/requests/"
    )

# ---------------------------------------------------------------------------
# Logging — scripts configure their own handler; this just gets the logger
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("zabbix_update")


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> dict:
    """Load and return a YAML file as a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def server_host_from_config(config_path: str) -> str:
    """Read zabbix.server_host from client.yaml (plain YAML, no validation)."""
    try:
        data = load_yaml(config_path)
        return data.get("zabbix", {}).get("server_host", "127.0.0.1")
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Zabbix value_type constants
# ---------------------------------------------------------------------------
VT_FLOAT  = 0   # Numeric float
VT_INT    = 3   # Numeric unsigned integer
VT_TEXT   = 4   # Text

YAML_VT_MAP: dict[str, int] = {
    "float":  VT_FLOAT,
    "int":    VT_INT,
    "string": VT_TEXT,
}

# ---------------------------------------------------------------------------
# Zabbix trigger severity constants
# ---------------------------------------------------------------------------
SEVERITY_MAP: dict[str, int] = {
    "not_classified": 0,
    "info":           1,
    "warning":        2,
    "average":        3,
    "high":           4,
    "disaster":       5,
}


# ---------------------------------------------------------------------------
# Metrics loader
# ---------------------------------------------------------------------------

def load_metrics(path: str, only_enabled: bool = False) -> list[dict]:
    """
    Return raw metric dicts from metrics.yaml.

    By default ALL metrics are returned (so Zabbix items can be created for
    metrics that are currently disabled).  Pass only_enabled=True to skip
    metrics with enabled: false.
    """
    data = load_yaml(path)
    result = []
    for m in data.get("metrics", []):
        if only_enabled and m.get("enabled", True) is False:
            continue
        if m.get("key"):
            result.append(m)
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

    # -- Template group ------------------------------------------------------

    def get_templategroup_id(self, name: str) -> Optional[str]:
        r = self._call("templategroup.get", {"filter": {"name": [name]}, "output": ["groupid"]})
        return r[0]["groupid"] if r else None

    def ensure_templategroup(self, name: str) -> str:
        gid = self.get_templategroup_id(name)
        if gid:
            log.info("Template group '%s' already exists (id=%s)", name, gid)
            return gid
        gid = self._call("templategroup.create", {"name": name})["groupids"][0]
        log.info("Created template group '%s' (id=%s)", name, gid)
        return gid

    # -- Template ------------------------------------------------------------

    def get_template_id(self, name: str) -> Optional[str]:
        r = self._call("template.get", {"filter": {"host": [name]}, "output": ["templateid"]})
        return r[0]["templateid"] if r else None

    def ensure_template(self, name: str, group_id: str, description: str = "") -> str:
        tid = self.get_template_id(name)
        if tid:
            log.info("Template '%s' already exists (id=%s)", name, tid)
            return tid
        tid = self._call(
            "template.create",
            {
                "host": name,
                "name": name,
                "description": description,
                "groups": [{"groupid": group_id}],
            },
        )["templateids"][0]
        log.info("Created template '%s' (id=%s)", name, tid)
        return tid

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
                "interfaces": [
                    {
                        "type": 1,
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

    # -- Items (host or template) --------------------------------------------

    def get_item_id(self, host_or_template_id: str, key: str, on_template: bool = False) -> Optional[str]:
        # Zabbix item.get accepts hostids for both hosts and templates
        r = self._call("item.get", {"hostids": [host_or_template_id], "filter": {"key_": [key]}, "output": ["itemid"]})
        return r[0]["itemid"] if r else None

    def ensure_item(self, host_or_template_id: str, item_def: dict, on_template: bool = False) -> str:
        key = item_def["key_"]
        iid = self.get_item_id(host_or_template_id, key, on_template)
        # Zabbix item.create uses hostid for both hosts and templates
        id_field = "hostid"
        if iid:
            self._call("item.update", {"itemid": iid, "tags": item_def.get("tags", [])})
            log.info("  Item '%s' already exists (id=%s) — tags synced", key, iid)
            return iid
        params = {
            id_field: host_or_template_id,
            "type": 2,      # Zabbix Trapper
            "delay": "0",
            **item_def,
        }
        iid = self._call("item.create", params)["itemids"][0]
        log.info("  Created item '%s' (id=%s)", key, iid)
        return iid

    # -- Triggers ------------------------------------------------------------

    def get_trigger_id(self, description: str, host_or_template: str) -> Optional[str]:
        r = self._call(
            "trigger.get",
            {
                "filter": {"description": [description]},
                "host": host_or_template,
                "output": ["triggerid"],
            },
        )
        return r[0]["triggerid"] if r else None

    def ensure_trigger(self, trigger_def: dict) -> str:
        desc = trigger_def["description"]
        host = trigger_def.get("_host")
        tid = self.get_trigger_id(desc, host)
        if tid:
            log.info("  Trigger '%s' already exists (id=%s) — skipped", desc, tid)
            return tid
        params = {k: v for k, v in trigger_def.items() if not k.startswith("_")}
        tid = self._call("trigger.create", params)["triggerids"][0]
        log.info("  Created trigger '%s' (id=%s)", desc, tid)
        return tid

    # -- Dashboards ----------------------------------------------------------

    def get_dashboard_id(self, name: str) -> Optional[str]:
        r = self._call("dashboard.get", {"filter": {"name": [name]}, "output": ["dashboardid"]})
        return r[0]["dashboardid"] if r else None

    def create_dashboard(self, dashboard_def: dict) -> str:
        did = self._call("dashboard.create", dashboard_def)["dashboardids"][0]
        log.info("Created dashboard '%s' (id=%s)", dashboard_def.get("name"), did)
        return did

    def update_dashboard(self, dashboard_id: str, dashboard_def: dict) -> None:
        self._call("dashboard.update", {"dashboardid": dashboard_id, **dashboard_def})
        log.info("Updated dashboard id=%s", dashboard_id)


# ---------------------------------------------------------------------------
# Wait for API readiness
# ---------------------------------------------------------------------------

def wait_for_api(api_url: str, max_wait: int = 120) -> None:
    log.info("Waiting for Zabbix API at %s ...", api_url)
    ui_url = re.sub(r"api_jsonrpc\.php$", "index.php", api_url)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(ui_url, timeout=5)
            if r.status_code < 500:
                log.info("Zabbix web UI responding (HTTP %s)", r.status_code)
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(
        f"Zabbix API at {api_url} did not respond within {max_wait}s.\n"
        "  Check: docker compose ps && docker compose logs zabbix-web"
    )


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def resolve_credentials(args_user: Optional[str], args_password: Optional[str]) -> tuple[str, str]:
    """Resolve Zabbix admin credentials: CLI arg > env var > interactive prompt."""
    user = args_user or os.getenv("ZABBIX_ADMIN_USER")
    password = args_password or os.getenv("ZABBIX_ADMIN_PASSWORD")
    if not user:
        user = input("Zabbix admin username [Admin]: ").strip() or "Admin"
    if not password:
        password = getpass.getpass("Zabbix admin password: ")
    return user, password


# ---------------------------------------------------------------------------
# Common argument parser base
# ---------------------------------------------------------------------------

def base_arg_parser(description: str) -> argparse.ArgumentParser:
    """Return an ArgumentParser pre-loaded with arguments common to all scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--api-url",
        default=None,
        metavar="URL",
        help="Zabbix JSON-RPC API URL. Also read from ZABBIX_API_URL env var.",
    )
    parser.add_argument(
        "--user",
        default=None,
        metavar="USER",
        help="Zabbix admin username (env: ZABBIX_ADMIN_USER; prompted if not set).",
    )
    parser.add_argument(
        "--password",
        default=None,
        metavar="PASS",
        help="Zabbix admin password (env: ZABBIX_ADMIN_PASSWORD; prompted if not set).",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for the Zabbix web UI to be ready.",
    )
    return parser


def resolve_api_url(args_api_url: Optional[str], server_host: str) -> str:
    return (
        args_api_url
        or os.getenv("ZABBIX_API_URL")
        or f"http://{server_host}:8080/api_jsonrpc.php"
    )
