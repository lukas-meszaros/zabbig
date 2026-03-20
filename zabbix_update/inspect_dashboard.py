#!/usr/bin/env python3
"""
inspect_dashboard.py — Dump the raw widget field definitions of an existing dashboard.

Use this to see exactly what field names and types Zabbix stores for a
manually created/edited widget, so you can match the format in create_dashboard.py.

Usage
-----
  python3 inspect_dashboard.py --name "zabbig Linux Host Overview"
  python3 inspect_dashboard.py --name "zabbig Linux Host Overview" --widget "CPU Utilisation %"
"""

import json
import os
import sys

from _common import (
    ZabbixAPI,
    base_arg_parser,
    resolve_api_url,
    resolve_credentials,
    server_host_from_config,
    wait_for_api,
    log,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CLIENT_YAML = os.path.join(_HERE, "..", "zabbig_client", "client.yaml")


def _parse_args():
    parser = base_arg_parser("Dump raw widget fields from an existing Zabbix dashboard.")
    parser.add_argument("--name",   required=True, metavar="DASHBOARD", help="Dashboard name to inspect.")
    parser.add_argument("--widget", default=None,  metavar="WIDGET",    help="Only show fields for this widget name.")
    parser.add_argument("--config", default=_DEFAULT_CLIENT_YAML, metavar="PATH",
                        help=f"Path to client.yaml (default: {_DEFAULT_CLIENT_YAML})")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    server_host = server_host_from_config(args.config)
    api_url     = resolve_api_url(args.api_url, server_host)

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)
    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)

        result = api._call("dashboard.get", {
            "filter":      {"name": args.name},
            "output":      ["dashboardid", "name"],
            "selectPages": "extend",
        })

        if not result:
            print(f"Dashboard '{args.name}' not found.", file=sys.stderr)
            return 1

        dash = result[0]
        print(f"\nDashboard: {dash['name']}  (id={dash['dashboardid']})")

        pages = dash.get("pages") or []
        for page in pages:
            widgets = page.get("widgets", [])
            print(f"\n  Page: {page.get('name', '(unnamed)')}")
            for widget in widgets:
                w_name = widget.get("name", "")
                if args.widget and args.widget.lower() not in w_name.lower():
                    continue
                print(f"\n    Widget: '{w_name}'  type={widget['type']}  "
                      f"pos=({widget['x']},{widget['y']})  size=({widget['width']}x{widget['height']})")
                fields = widget.get("fields", [])
                for f in fields:
                    print(f"      type={f['type']:>2}  name={f['name']!r:40s}  value={f['value']!r}")
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
