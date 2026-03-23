#!/usr/bin/env python3
"""
provision_all.py — Full one-shot provisioning of a Zabbix template with
                   trapper items, triggers, and a host dashboard.

What this creates (in order)
-----------------------------
  1. Template group     : template.yaml → template.group
  2. Template           : template.yaml → template.name
  3. Trapper items      : one per metric key (metrics.yaml + template.yaml overrides)
                          plus self-monitoring and additional items from template.yaml
  4. Triggers           : all entries from triggers.yaml, on the template
  5. Dashboard          : dashboard.yaml, built against --host (requires the host
                          to already exist and have items — i.e. create_trapper_items.py
                          must have been run separately, or the host already has the
                          template linked and items inherited)

The dashboard step is optional: omit --host to skip it.

Idempotent — safe to re-run.  Existing objects are detected and skipped /
updated rather than duplicated.

Usage
-----
  cd zabbix_update

  # Template + items + triggers only (no dashboard):
  python3 provision_all.py

  # Full provisioning including dashboard:
  python3 provision_all.py --host prod-server-01

  # Custom YAML paths:
  python3 provision_all.py \\
      --template template.yaml \\
      --metrics  ../zabbig_client/metrics.yaml \\
      --triggers triggers.yaml \\
      --dashboard dashboard.yaml \\
      --host prod-server-01

  python3 provision_all.py --help
"""

import os
import sys

from _common import (
    ZabbixAPI,
    YAML_VT_MAP, VT_FLOAT,
    SEVERITY_MAP,
    base_arg_parser,
    load_yaml,
    load_metrics,
    resolve_api_url,
    resolve_credentials,
    server_host_from_config,
    wait_for_api,
    log,
)
from typing import Optional

# Re-use the builder functions from the individual scripts directly so there is
# one source of truth.  We import them as local functions to keep this script
# self-contained even if the individual scripts are reorganised in future.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from create_template import (
    _build_item_defs,
    _build_self_mon_defs,
    _build_additional_item_defs,
)
from create_triggers import _build_trigger_params
from create_dashboard import _build_page


_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TEMPLATE_YAML  = os.path.join(_HERE, "template.yaml")
_DEFAULT_METRICS_YAML   = os.path.join(_HERE, "..", "zabbig_client", "metrics.yaml")
_DEFAULT_TRIGGERS_YAML  = os.path.join(_HERE, "triggers.yaml")
_DEFAULT_DASHBOARD_YAML = os.path.join(_HERE, "dashboard.yaml")
_DEFAULT_CLIENT_YAML    = os.path.join(_HERE, "..", "zabbig_client", "client.yaml")


# ---------------------------------------------------------------------------
# Step 1+2+3 — Template, template group, all items
# ---------------------------------------------------------------------------

def _provision_template(api: ZabbixAPI, tpl_data: dict, metrics: list[dict]) -> str:
    """Create template group, template, and all items. Returns template id."""
    t = tpl_data["template"]
    tpl_name  = t["name"]
    tpl_group = t["group"]
    tpl_desc  = t.get("description", "")

    log.info("--- Template group ---")
    group_id = api.ensure_templategroup(tpl_group)

    log.info("--- Template ---")
    tpl_id = api.ensure_template(tpl_name, group_id, tpl_desc)

    log.info("--- Metric items (%d) ---", len(metrics))
    for item_def in _build_item_defs(metrics, tpl_data):
        api.ensure_item(tpl_id, item_def, on_template=True)

    sm_defs = _build_self_mon_defs(tpl_data)
    log.info("--- Self-monitoring items (%d) ---", len(sm_defs))
    for item_def in sm_defs:
        api.ensure_item(tpl_id, item_def, on_template=True)

    add_defs = _build_additional_item_defs(tpl_data)
    if add_defs:
        log.info("--- Additional items (%d) ---", len(add_defs))
        for item_def in add_defs:
            api.ensure_item(tpl_id, item_def, on_template=True)

    return tpl_id


# ---------------------------------------------------------------------------
# Step 4 — Triggers on the template
# ---------------------------------------------------------------------------

def _provision_triggers(api: ZabbixAPI, trig_data: dict, tpl_name: str) -> int:
    """Create all triggers from triggers.yaml on the template. Returns count created."""
    triggers  = trig_data.get("triggers", [])
    created:  dict[str, str] = {}

    log.info("--- Triggers (%d) ---", len(triggers))
    for trigger in triggers:
        params = _build_trigger_params(
            trigger,
            target_name=tpl_name,
            template_name=tpl_name,
            on_template=True,
            dependencies=created,
        )
        name = params["description"]
        tid  = api.get_trigger_id(name, tpl_name)
        if tid:
            log.info("  Trigger '%s' already exists (id=%s) — skipped", name, tid)
            created[name] = tid
        else:
            clean = {k: v for k, v in params.items() if not k.startswith("_")}
            try:
                tid = api._call("trigger.create", clean)["triggerids"][0]
                log.info("  Created trigger '%s' (id=%s)", name, tid)
                created[name] = tid
            except RuntimeError as exc:
                log.warning("  Failed to create trigger '%s': %s", name, exc)

    return len(created)


# ---------------------------------------------------------------------------
# Step 5 — Template dashboard (always created, lives inside the template)
# ---------------------------------------------------------------------------

def _provision_template_dashboard(
    api: ZabbixAPI, dash_data: dict, tpl_name: str, tpl_id: str
) -> None:
    """
    Create or update the dashboard on the template itself.

    Template dashboards appear under Configuration → Templates → [template] →
    Dashboards tab and are inherited by every host linked to the template.
    Items are resolved against the template's own item IDs; graph widget
    datasources use the template name as the host reference.
    """
    dash_name = dash_data.get("name", "zabbig Linux Host Overview")
    log.info("--- Template dashboard '%s' on template '%s' (id=%s) ---",
             dash_name, tpl_name, tpl_id)

    pages = []
    for page_def in dash_data.get("pages", []):
        log.info("  Building page: %s", page_def.get("name", ""))
        # Pass tpl_id as host_id — item.get accepts template IDs via hostids.
        # Pass tpl_name as host_name — graph widgets reference the template name
        # in datasource fields, which is correct for template-level dashboards.
        pages.append(_build_page(page_def, tpl_id, tpl_name, api))

    payload = {
        "name":       dash_name,
        "templateid": tpl_id,
        "pages":      pages,
    }

    # templatedashboard.get supports templateids as a first-class filter
    existing = api._call("templatedashboard.get", {
        "output":      "extend",
        "templateids": [tpl_id],
        "filter":      {"name": dash_name},
    })
    if existing:
        dash_id = existing[0]["dashboardid"]
        update_payload = {k: v for k, v in payload.items() if k != "templateid"}
        update_payload["dashboardid"] = dash_id
        api._call("templatedashboard.update", update_payload)
        log.info("  Updated template dashboard '%s' (id=%s)", dash_name, dash_id)
    else:
        dash_id = api._call("templatedashboard.create", payload)["dashboardids"][0]
        log.info("  Created template dashboard '%s' (id=%s)", dash_name, dash_id)


# ---------------------------------------------------------------------------
# Step 6 — Host dashboard (optional, requires --host)
# ---------------------------------------------------------------------------

def _provision_dashboard(api: ZabbixAPI, dash_data: dict, host_name: str) -> None:
    """Create or update the standalone host dashboard under Monitoring → Dashboards."""
    host_id = api.get_host_id(host_name)
    if not host_id:
        log.warning(
            "Host '%s' not found in Zabbix — host dashboard step skipped. "
            "Link the template to the host first, then re-run with --host.",
            host_name,
        )
        return

    dash_name = dash_data.get("name", "zabbig Linux Host Overview")
    log.info("--- Host dashboard '%s' for host '%s' (id=%s) ---",
             dash_name, host_name, host_id)

    pages = []
    for page_def in dash_data.get("pages", []):
        log.info("  Building page: %s", page_def.get("name", ""))
        pages.append(_build_page(page_def, host_id, host_name, api))

    payload = {
        "name":           dash_name,
        "display_period": 30,
        "auto_start":     0,
        "pages":          pages,
    }

    existing = api._call("dashboard.get", {
        "output": ["dashboardid"],
        "filter": {"name": dash_name},
    })
    if existing:
        dash_id = existing[0]["dashboardid"]
        payload["dashboardid"] = dash_id
        api._call("dashboard.update", payload)
        log.info("  Updated host dashboard '%s' (id=%s)", dash_name, dash_id)
    else:
        dash_id = api._call("dashboard.create", payload)["dashboardids"][0]
        log.info("  Created host dashboard '%s' (id=%s)", dash_name, dash_id)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(
    api:        ZabbixAPI,
    tpl_data:   dict,
    trig_data:  dict,
    dash_data:  dict,
    metrics:    list,
    host_name:  Optional[str],
) -> None:
    tpl_name = tpl_data["template"]["name"]

    log.info("=" * 60)
    log.info("provision_all — zabbig full template provisioning")
    log.info("  Template : %s", tpl_name)
    log.info("  Host     : %s", host_name or "(skipped — no --host given)")
    log.info("=" * 60)

    # 1-3: template + items
    tpl_id = _provision_template(api, tpl_data, metrics)

    # 4: triggers on the template
    _provision_triggers(api, trig_data, tpl_name)

    # 5: template dashboard (always — lives inside the template)
    _provision_template_dashboard(api, dash_data, tpl_name, tpl_id)

    # 6: host dashboard (optional — standalone dashboard under Monitoring → Dashboards)
    if host_name:
        _provision_dashboard(api, dash_data, host_name)
    else:
        log.info("--- Host dashboard skipped (no --host given) ---")

    log.info("=" * 60)
    log.info("All done.")
    log.info("  Template dashboard: Configuration → Templates → %s → Dashboards", tpl_name)
    if host_name:
        log.info("  Host dashboard    : Monitoring → Dashboards → %s",
                 dash_data.get("name", "zabbig Linux Host Overview"))
        log.info("  Verify template is linked: Configuration → Hosts → %s → Templates",
                 host_name)
    else:
        log.info("  To also create a host dashboard, re-run with --host <hostname>.")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = base_arg_parser(
        "Full one-shot Zabbix provisioning: template + items + triggers + dashboard."
    )
    parser.add_argument(
        "--template",
        default=_DEFAULT_TEMPLATE_YAML,
        metavar="PATH",
        help=f"Path to template.yaml (default: {_DEFAULT_TEMPLATE_YAML})",
    )
    parser.add_argument(
        "--metrics",
        default=_DEFAULT_METRICS_YAML,
        metavar="PATH",
        help=f"Path to metrics.yaml (default: {_DEFAULT_METRICS_YAML})",
    )
    parser.add_argument(
        "--triggers",
        default=_DEFAULT_TRIGGERS_YAML,
        metavar="PATH",
        help=f"Path to triggers.yaml (default: {_DEFAULT_TRIGGERS_YAML})",
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
        help="Zabbix host name for the dashboard step. "
             "Omit to skip dashboard creation. "
             "Defaults to zabbix.host_name from client.yaml if that file is present.",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CLIENT_YAML,
        metavar="PATH",
        help=f"Path to client.yaml — server_host and host_name are read from it "
             f"(default: {_DEFAULT_CLIENT_YAML})",
    )
    parser.add_argument(
        "--only-enabled",
        action="store_true",
        help="Only include metrics with enabled: true in metrics.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Validate required files
    for path, label in [
        (args.template,  "template.yaml"),
        (args.metrics,   "metrics.yaml"),
        (args.triggers,  "triggers.yaml"),
        (args.dashboard, "dashboard.yaml"),
    ]:
        if not os.path.exists(path):
            log.error("%s not found: %s", label, path)
            return 1

    tpl_data  = load_yaml(args.template)
    trig_data = load_yaml(args.triggers)
    dash_data = load_yaml(args.dashboard)
    metrics   = load_metrics(args.metrics, only_enabled=args.only_enabled)

    # Resolve host: CLI > client.yaml
    host_name = args.host
    if not host_name and os.path.exists(args.config):
        client_cfg = load_yaml(args.config)
        host_name  = client_cfg.get("zabbix", {}).get("host_name") or None

    server_host = server_host_from_config(args.config)
    api_url     = resolve_api_url(args.api_url, server_host)

    log.info("API URL  : %s", api_url)
    log.info("Metrics  : %d items (%s)", len(metrics),
             "enabled only" if args.only_enabled else "all defined")

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)

    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)
        run(api, tpl_data, trig_data, dash_data, metrics, host_name)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
