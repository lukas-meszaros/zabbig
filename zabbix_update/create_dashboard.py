#!/usr/bin/env python3
"""
create_dashboard.py — Create or update a Zabbix dashboard from dashboard.yaml.

Resolves item IDs for each widget from the target host, then builds the
Zabbix dashboard.create / dashboard.update API payload.

Widget types in dashboard.yaml → Zabbix API widget types
---------------------------------------------------------
  graph       → svggraph
  plain_value → item
  problems    → problems
  clock       → clock

Grid layout
-----------
  The Zabbix dashboard grid is 24 columns wide.  Widgets are placed
  left-to-right, wrapping to the next row when they exceed 24 columns.

Usage
-----
  cd zabbix_update

  python3 create_dashboard.py --host prod-server-01
  python3 create_dashboard.py --host prod-server-01 --server-host 192.168.1.10
  python3 create_dashboard.py --help
"""

import os
import sys

from _common import (
    ZabbixAPI,
    base_arg_parser,
    load_yaml,
    resolve_api_url,
    resolve_credentials,
    server_host_from_config,
    wait_for_api,
    log,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DASHBOARD_YAML = os.path.join(_HERE, "dashboard.yaml")
_DEFAULT_CLIENT_YAML    = os.path.join(_HERE, "..", "zabbig_client", "client.yaml")

_GRID_WIDTH = 24

_WIDGET_TYPE_MAP = {
    "graph":       "svggraph",
    "plain_value": "item",
    "problems":    "problems",
    "clock":       "clock",
}


# ---------------------------------------------------------------------------
# Item ID resolution
# ---------------------------------------------------------------------------

def _resolve_item_ids(api: ZabbixAPI, host_id: str, keys: list[str]) -> list[str]:
    """Return ordered list of itemids for *keys* on *host_id*; warn on misses."""
    if not keys:
        return []
    result = api._call("item.get", {
        "output":   ["itemid", "key_"],
        "hostids":  [host_id],
        "filter":   {"key_": keys},
    })
    key_to_id = {r["key_"]: r["itemid"] for r in result}
    ids = []
    for k in keys:
        if k in key_to_id:
            ids.append(key_to_id[k])
        else:
            log.warning("    Item key '%s' not found on host (skipped)", k)
    return ids


# ---------------------------------------------------------------------------
# Widget builders
# ---------------------------------------------------------------------------

def _build_item_widget(widget: dict, host_id: str, api: ZabbixAPI,
                       x: int, y: int) -> dict:
    """Build a Zabbix 'item' (plain_value) widget payload."""
    keys   = widget.get("keys", [])
    item_ids = _resolve_item_ids(api, host_id, keys[:1])  # item widget shows one key
    fields = []
    if item_ids:
        fields.append({"type": 4, "name": "itemid",
                        "value": {"host": "", "key": "", "itemid": item_ids[0]}})
    fields.append({"type": 0, "name": "show_description", "value": "1"})
    fields.append({"type": 0, "name": "dynamic",          "value": "0"})
    return _wrap_widget(widget, x, y, "item", fields)


def _build_graph_widget(widget: dict, host_id: str, api: ZabbixAPI,
                        x: int, y: int) -> dict:
    """Build a Zabbix 'svggraph' widget payload."""
    keys     = widget.get("keys", [])
    item_ids = _resolve_item_ids(api, host_id, keys)
    ds_fields = []
    for idx, iid in enumerate(item_ids):
        ds_fields.append({
            "type":  4,
            "name":  f"ds.itemids.{idx}.0",
            "value": {"host": "", "key": "", "itemid": iid},
        })
        ds_fields.append({"type": 0, "name": f"ds.type.{idx}", "value": "0"})
        ds_fields.append({"type": 1, "name": f"ds.color.{idx}",
                           "value": _default_color(idx)})
    base_fields = [
        {"type": 0, "name": "source_type", "value": "1"},   # SIMPLE_ITEMS
        {"type": 0, "name": "show_legend",  "value": "1"},
        {"type": 0, "name": "show_working_time", "value": "1"},
    ]
    return _wrap_widget(widget, x, y, "svggraph", base_fields + ds_fields)


def _build_problems_widget(widget: dict, x: int, y: int) -> dict:
    """Build a Zabbix 'problems' widget payload."""
    fields = [
        {"type": 0, "name": "show_lines", "value": "25"},
        {"type": 0, "name": "sort_triggers", "value": "0"},
    ]
    return _wrap_widget(widget, x, y, "problems", fields)


def _build_clock_widget(widget: dict, x: int, y: int) -> dict:
    """Build a Zabbix 'clock' widget payload."""
    fields = [
        {"type": 0, "name": "time_type", "value": "0"},  # HOST_TIME
        {"type": 0, "name": "clock_type", "value": "0"},  # DIGITAL
    ]
    return _wrap_widget(widget, x, y, "clock", fields)


def _wrap_widget(widget: dict, x: int, y: int, zabbix_type: str,
                 fields: list) -> dict:
    return {
        "type":   zabbix_type,
        "name":   widget.get("title", ""),
        "x":      x,
        "y":      y,
        "width":  widget.get("width", 6),
        "height": widget.get("height", 5),
        "fields": fields,
    }


_PALETTE = [
    "1A7C11", "2774A4", "F63100", "A54F10", "FC6EA3",
    "6C59CC", "AC8C14", "611F27", "F230E0", "5CCD18",
]

def _default_color(idx: int) -> str:
    return _PALETTE[idx % len(_PALETTE)]


# ---------------------------------------------------------------------------
# Page builder
# ---------------------------------------------------------------------------

def _build_page(page_def: dict, host_id: str, api: ZabbixAPI) -> dict:
    widgets      = page_def.get("widgets", [])
    built        = []
    x, y         = 0, 0
    row_height   = 0

    for w in widgets:
        w_width  = w.get("width",  6)
        w_height = w.get("height", 5)

        # Wrap to next row if this widget doesn't fit
        if x + w_width > _GRID_WIDTH:
            x        = 0
            y       += row_height
            row_height = 0

        w_type = w.get("type", "graph")
        log.info("    Widget %-12s  '%s'  pos=(%d,%d)  size=(%dx%d)",
                 w_type, w.get("title", ""), x, y, w_width, w_height)

        if w_type == "graph":
            entry = _build_graph_widget(w, host_id, api, x, y)
        elif w_type == "plain_value":
            entry = _build_item_widget(w, host_id, api, x, y)
        elif w_type == "problems":
            entry = _build_problems_widget(w, x, y)
        elif w_type == "clock":
            entry = _build_clock_widget(w, x, y)
        else:
            log.warning("    Unknown widget type '%s' — skipped", w_type)
            continue

        built.append(entry)
        x          += w_width
        row_height  = max(row_height, w_height)

    return {
        "name":    page_def.get("name", ""),
        "widgets": built,
    }


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def run(api: ZabbixAPI, dash_data: dict, host_name: str) -> None:
    host_id = api.get_host_id(host_name)
    if not host_id:
        raise RuntimeError(
            f"Host '{host_name}' not found in Zabbix. "
            "Run create_trapper_items.py first."
        )
    log.info("Host      : %s (id=%s)", host_name, host_id)

    dash_name = dash_data.get("name", "zabbig Linux Host Overview")
    log.info("Dashboard : %s", dash_name)

    log.info("=" * 60)
    pages_def = dash_data.get("pages", [])
    pages     = []
    for page_def in pages_def:
        log.info("  Building page: %s", page_def.get("name", ""))
        pages.append(_build_page(page_def, host_id, api))

    # Check for existing dashboard
    existing = api._call("dashboard.get", {
        "output": ["dashboardid"],
        "filter": {"name": dash_name},
    })

    payload = {
        "name":           dash_name,
        "display_period": 30,
        "auto_start":     1,
        "pages":          pages,
    }

    if existing:
        dash_id = existing[0]["dashboardid"]
        payload["dashboardid"] = dash_id
        api._call("dashboard.update", payload)
        log.info("=" * 60)
        log.info("Updated dashboard '%s' (id=%s)", dash_name, dash_id)
    else:
        result  = api._call("dashboard.create", payload)
        dash_id = result["dashboardids"][0]
        log.info("=" * 60)
        log.info("Created dashboard '%s' (id=%s)", dash_name, dash_id)

    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = base_arg_parser(
        "Create or update a Zabbix dashboard from dashboard.yaml."
    )
    parser.add_argument(
        "--dashboard",
        default=_DEFAULT_DASHBOARD_YAML,
        metavar="PATH",
        help=f"Path to dashboard.yaml (default: {_DEFAULT_DASHBOARD_YAML})",
    )
    parser.add_argument(
        "--host",
        default=None,
        metavar="HOSTNAME",
        help="Zabbix host name for which to build the dashboard. "
             "Defaults to zabbix.host_name from client.yaml.",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CLIENT_YAML,
        metavar="PATH",
        help=f"Path to client.yaml — server_host and host_name are read from it "
             f"(default: {_DEFAULT_CLIENT_YAML})",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not os.path.exists(args.dashboard):
        log.error("dashboard.yaml not found: %s", args.dashboard)
        return 1

    client_cfg  = load_yaml(args.config)
    zabbix_cfg  = client_cfg.get("zabbix", {})
    server_host = zabbix_cfg.get("server_host", "127.0.0.1")
    host_name   = args.host or zabbix_cfg.get("host_name") or ""

    if not host_name:
        log.error("Host name not specified. Use --host or set zabbix.host_name in client.yaml.")
        return 1

    dash_data = load_yaml(args.dashboard)
    api_url   = resolve_api_url(args.api_url, server_host)

    log.info("API URL  : %s", api_url)
    log.info("Host     : %s", host_name)

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)

    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)
        run(api, dash_data, host_name)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
