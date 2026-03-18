#!/usr/bin/env python3
"""
scripts/bootstrap.py — Automated Zabbix lab provisioning via the Zabbix API.

Idempotent: safe to run multiple times.  Objects are only created when they
don't already exist.  Existing objects are left untouched.

What this creates:
  - Host group:  MacOS Senders
  - Host:        macos-local-sender (with a placeholder agent interface)
  - Items (trapper type):
      macos.heartbeat     – numeric float 0/1
      macos.status        – numeric integer  0=ok / 1=warning / 2=critical
      macos.error_count   – numeric integer  (cumulative error count)
      macos.message       – text string      (latest message, no trigger)
  - Triggers:
      heartbeat missing 5 min   → HIGH
      status >= 2               → HIGH
      error_count > 10          → AVERAGE

Prerequisites:
  pip install requests python-dotenv
  (or:  pip install -r scripts/requirements-bootstrap.txt)
"""

import json
import logging
import os
import sys
import time
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.exit(
        "ERROR: 'requests' is not installed.\n"
        "       Run:  pip install requests python-dotenv"
    )

try:
    from dotenv import load_dotenv
except ImportError:
    # python-dotenv is optional — fall back to env vars only
    def load_dotenv(*_args: Any, **_kwargs: Any) -> None:  # type: ignore[misc]
        pass


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

API_URL: str = os.getenv("ZABBIX_API_URL", "http://localhost:8080/api_jsonrpc.php")
ADMIN_USER: str = os.getenv("ZABBIX_ADMIN_USER", "Admin")
ADMIN_PASSWORD: str = os.getenv("ZABBIX_ADMIN_PASSWORD", "zabbix")
SENDER_HOST_NAME: str = os.getenv("SENDER_HOST_NAME", "macos-local-sender")
SENDER_HOST_GROUP: str = os.getenv("SENDER_HOST_GROUP", "MacOS Senders")

# ---------------------------------------------------------------------------
# Trapper items to create
# ---------------------------------------------------------------------------
TRAPPER_ITEMS = [
    {
        "name": "Heartbeat",
        "key_": "macos.heartbeat",
        "type": 2,           # Zabbix trapper
        "value_type": 0,     # numeric float
        "units": "",
        "description": (
            "Heartbeat signal from the macOS sender. "
            "Send 1 to indicate alive. "
            "Missing data for 5 min triggers an alert."
        ),
        "delay": "0",        # delay=0 is required for trapper items
    },
    {
        "name": "Status",
        "key_": "macos.status",
        "type": 2,
        "value_type": 3,     # numeric unsigned integer
        "units": "",
        "description": "Status code: 0=OK, 1=WARNING, 2=CRITICAL",
        "delay": "0",
    },
    {
        "name": "Error Count",
        "key_": "macos.error_count",
        "type": 2,
        "value_type": 3,
        "units": "",
        "description": "Cumulative error count. Triggers alert when > 10.",
        "delay": "0",
    },
    {
        "name": "Message",
        "key_": "macos.message",
        "type": 2,
        "value_type": 4,     # text
        "units": "",
        "description": (
            "Free-form text message from the macOS sender. "
            "Visible in Latest Data. No trigger attached."
        ),
        "delay": "0",
    },
]

# ---------------------------------------------------------------------------
# Zabbix API helper
# ---------------------------------------------------------------------------

class ZabbixAPI:
    """Minimal synchronous Zabbix API client."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.auth: Optional[str] = None
        self._request_id = 0
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json-rpc"})

    def _call(self, method: str, params: Any) -> Any:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._request_id,
        }
        if self.auth:
            payload["auth"] = self.auth

        try:
            resp = self.session.post(self.url, json=payload, timeout=30)
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
        # Zabbix 6.4+ renamed the login parameter from "user" to "username".
        # Try "username" first (Zabbix 6.4+), fall back to "user" for older versions.
        try:
            self.auth = self._call(
                "user.login", {"username": user, "password": password}
            )
        except RuntimeError:
            self.auth = self._call(
                "user.login", {"user": user, "password": password}
            )
        log.info("Authenticated as '%s'", user)

    def logout(self) -> None:
        if self.auth:
            try:
                self._call("user.logout", [])
            except RuntimeError:
                pass
            self.auth = None

    # -- Host group -----------------------------------------------------------

    def get_hostgroup_id(self, name: str) -> Optional[str]:
        result = self._call("hostgroup.get", {"filter": {"name": [name]}, "output": ["groupid"]})
        return result[0]["groupid"] if result else None

    def create_hostgroup(self, name: str) -> str:
        result = self._call("hostgroup.create", {"name": name})
        return result["groupids"][0]

    def ensure_hostgroup(self, name: str) -> str:
        gid = self.get_hostgroup_id(name)
        if gid:
            log.info("Host group '%s' already exists (id=%s)", name, gid)
            return gid
        gid = self.create_hostgroup(name)
        log.info("Created host group '%s' (id=%s)", name, gid)
        return gid

    # -- Host -----------------------------------------------------------------

    def get_host_id(self, hostname: str) -> Optional[str]:
        result = self._call(
            "host.get", {"filter": {"host": [hostname]}, "output": ["hostid"]}
        )
        return result[0]["hostid"] if result else None

    def create_host(self, hostname: str, group_id: str) -> str:
        result = self._call(
            "host.create",
            {
                "host": hostname,
                "name": hostname,
                "groups": [{"groupid": group_id}],
                # Placeholder agent interface — trapper items don't use it,
                # but Zabbix requires at least one interface per host.
                "interfaces": [
                    {
                        "type": 1,         # Zabbix agent
                        "main": 1,
                        "useip": 1,
                        "ip": "127.0.0.1",
                        "dns": "",
                        "port": "10050",
                    }
                ],
            },
        )
        return result["hostids"][0]

    def ensure_host(self, hostname: str, group_id: str) -> str:
        hid = self.get_host_id(hostname)
        if hid:
            log.info("Host '%s' already exists (id=%s)", hostname, hid)
            return hid
        hid = self.create_host(hostname, group_id)
        log.info("Created host '%s' (id=%s)", hostname, hid)
        return hid

    # -- Items ----------------------------------------------------------------

    def get_item_id(self, host_id: str, key: str) -> Optional[str]:
        result = self._call(
            "item.get",
            {"hostids": [host_id], "filter": {"key_": [key]}, "output": ["itemid"]},
        )
        return result[0]["itemid"] if result else None

    def create_item(self, host_id: str, item_def: dict) -> str:
        params = {**item_def, "hostid": host_id}
        result = self._call("item.create", params)
        return result["itemids"][0]

    def ensure_item(self, host_id: str, item_def: dict) -> str:
        key = item_def["key_"]
        iid = self.get_item_id(host_id, key)
        if iid:
            log.info("  Item '%s' already exists (id=%s)", key, iid)
            return iid
        iid = self.create_item(host_id, item_def)
        log.info("  Created item '%s' (id=%s)", key, iid)
        return iid

    # -- Triggers -------------------------------------------------------------

    def get_trigger_id(self, description: str, host_id: str) -> Optional[str]:
        result = self._call(
            "trigger.get",
            {
                "hostids": [host_id],
                "filter": {"description": [description]},
                "output": ["triggerid"],
            },
        )
        return result[0]["triggerid"] if result else None

    def create_trigger(self, trigger_def: dict) -> str:
        result = self._call("trigger.create", trigger_def)
        return result["triggerids"][0]

    def ensure_trigger(self, trigger_def: dict, host_id: str) -> str:
        desc = trigger_def["description"]
        tid = self.get_trigger_id(desc, host_id)
        if tid:
            log.info("  Trigger '%s' already exists (id=%s)", desc, tid)
            return tid
        tid = self.create_trigger(trigger_def)
        log.info("  Created trigger '%s' (id=%s)", desc, tid)
        return tid


# ---------------------------------------------------------------------------
# Provisioning logic
# ---------------------------------------------------------------------------

def wait_for_api(api_url: str, max_wait: int = 120) -> None:
    """Poll the API URL until it responds (container startup can be slow)."""
    log.info("Waiting for Zabbix API at %s ...", api_url)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(api_url.replace("api_jsonrpc.php", "index.php"), timeout=5)
            if r.status_code < 500:
                log.info("Zabbix web UI is responding.")
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(
        f"Zabbix API at {api_url} did not become available within {max_wait}s.\n"
        "  Check: docker compose ps\n"
        "         docker compose logs zabbix-server\n"
        "         docker compose logs zabbix-web"
    )


def provision(api: ZabbixAPI) -> None:
    log.info("=" * 60)
    log.info("Starting provisioning...")
    log.info("=" * 60)

    # 1. Host group
    log.info("--- Host group ---")
    group_id = api.ensure_hostgroup(SENDER_HOST_GROUP)

    # 2. Host
    log.info("--- Host ---")
    host_id = api.ensure_host(SENDER_HOST_NAME, group_id)

    # 3. Trapper items
    log.info("--- Trapper items ---")
    for item_def in TRAPPER_ITEMS:
        api.ensure_item(host_id, item_def)

    # 4. Triggers
    # Zabbix 7.0 uses expression syntax with function calls.
    log.info("--- Triggers ---")

    triggers = [
        {
            "description": "Heartbeat missing for 5 minutes",
            "expression": f"nodata(/{SENDER_HOST_NAME}/macos.heartbeat,5m)=1",
            "priority": 4,   # HIGH
            "manual_close": 0,
            "comments": (
                "No heartbeat received for 5 minutes. "
                "The macOS sender may be down or offline."
            ),
        },
        {
            "description": "Status is CRITICAL (macos.status >= 2)",
            "expression": f"last(/{SENDER_HOST_NAME}/macos.status)>=2",
            "priority": 4,   # HIGH
            "manual_close": 1,
            "comments": "The sender reported a CRITICAL status (value >= 2).",
        },
        {
            "description": "Error count above threshold (macos.error_count > 10)",
            "expression": f"last(/{SENDER_HOST_NAME}/macos.error_count)>10",
            "priority": 3,   # AVERAGE
            "manual_close": 1,
            "comments": "More than 10 errors reported by the macOS sender.",
        },
    ]

    for tdef in triggers:
        api.ensure_trigger(tdef, host_id)

    log.info("=" * 60)
    log.info("✅  Provisioning complete!")
    log.info("")
    log.info("  Host:   %s", SENDER_HOST_NAME)
    log.info("  Group:  %s", SENDER_HOST_GROUP)
    log.info("  Items:  %s", ", ".join(i["key_"] for i in TRAPPER_ITEMS))
    log.info("  Triggers: 3 created")
    log.info("=" * 60)


def main() -> None:
    log.info("Zabbix Lab Bootstrap")
    log.info("  API URL:  %s", API_URL)
    log.info("  Admin:    %s", ADMIN_USER)
    log.info("  Host:     %s", SENDER_HOST_NAME)

    # Wait until the API is accessible
    wait_for_api(API_URL)

    api = ZabbixAPI(API_URL)
    try:
        api.login(ADMIN_USER, ADMIN_PASSWORD)
        provision(api)
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)
    finally:
        api.logout()


if __name__ == "__main__":
    main()
