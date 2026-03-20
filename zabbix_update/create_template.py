#!/usr/bin/env python3
"""
create_template.py — Create a Zabbix template with all trapper items defined
                     in template.yaml (names/descriptions/tags) and metrics.yaml
                     (keys/value_types).

What this creates
-----------------
  Template group  : template.yaml → template.group
  Template        : template.yaml → template.name
  Trapper items   : one per metric key, merging metrics.yaml + template.yaml
  Self-monitoring : five zabbig.client.* items from template.yaml

Idempotent — safe to re-run.  Existing items have their tags synced.

Usage
-----
  cd zabbix_update
  python3 create_template.py [options]

  python3 create_template.py --help
"""

import os
import sys

from _common import (
    ZabbixAPI,
    YAML_VT_MAP, VT_FLOAT,
    base_arg_parser,
    load_yaml,
    load_metrics,
    resolve_api_url,
    resolve_credentials,
    server_host_from_config,
    wait_for_api,
    log,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TEMPLATE_YAML = os.path.join(_HERE, "template.yaml")
_DEFAULT_METRICS_YAML  = os.path.join(_HERE, "..", "zabbig_client", "metrics.yaml")
_DEFAULT_CLIENT_YAML   = os.path.join(_HERE, "..", "zabbig_client", "client.yaml")


# ---------------------------------------------------------------------------
# Build item definitions
# ---------------------------------------------------------------------------

def _build_item_defs(metrics: list[dict], tpl_data: dict) -> list[dict]:
    """
    Merge metrics.yaml entries with template.yaml item overrides.

    metrics.yaml  → key, value_type
    template.yaml → name, description, history, trends, tags
    item_defaults → history, trends, tags (fallback)
    """
    defaults   = tpl_data.get("item_defaults", {})
    def_history = defaults.get("history", "7d")
    def_trends  = defaults.get("trends", "365d")
    def_tags    = defaults.get("tags", [])

    # Build lookup: key → override dict from template.yaml items list
    overrides: dict[str, dict] = {}
    for item in tpl_data.get("items", []):
        overrides[item["key"]] = item

    result = []
    for m in metrics:
        key = m["key"]
        ov  = overrides.get(key, {})

        vt_int = YAML_VT_MAP.get(str(m.get("value_type", "float")).lower(), VT_FLOAT)

        item_def: dict = {
            "key_":       key,
            "name":       ov.get("name", key),
            "description": ov.get("description", ""),
            "value_type": vt_int,
            "history":    ov.get("history", def_history),
            "trends":     ov.get("trends", def_trends),
        }
        tags = ov.get("tags", def_tags)
        if tags:
            item_def["tags"] = tags
        result.append(item_def)

    return result


def _build_self_mon_defs(tpl_data: dict) -> list[dict]:
    """Build item defs for the self-monitoring items from template.yaml."""
    result = []
    for sm in tpl_data.get("self_monitoring_items", []):
        vt_int = YAML_VT_MAP.get(str(sm.get("value_type", "int")).lower(), VT_FLOAT)
        item_def: dict = {
            "key_":        sm["key"],
            "name":        sm.get("name", sm["key"]),
            "description": sm.get("description", ""),
            "value_type":  vt_int,
            "history":     sm.get("history", "7d"),
            "trends":      sm.get("trends", "365d"),
        }
        if sm.get("tags"):
            item_def["tags"] = sm["tags"]
        result.append(item_def)
    return result


# ---------------------------------------------------------------------------
# Main provisioning flow
# ---------------------------------------------------------------------------

def run(api: ZabbixAPI, tpl_data: dict, metrics: list[dict]) -> None:
    t = tpl_data["template"]
    tpl_name  = t["name"]
    tpl_group = t["group"]
    tpl_desc  = t.get("description", "")

    log.info("=" * 60)
    log.info("Template  : %s", tpl_name)
    log.info("Group     : %s", tpl_group)
    log.info("=" * 60)

    # Template group
    group_id = api.ensure_templategroup(tpl_group)

    # Template
    tpl_id = api.ensure_template(tpl_name, group_id, tpl_desc)

    # Metric items
    item_defs = _build_item_defs(metrics, tpl_data)
    log.info("--- Metric items (%d) ---", len(item_defs))
    for item_def in item_defs:
        api.ensure_item(tpl_id, item_def, on_template=True)

    # Self-monitoring items
    sm_defs = _build_self_mon_defs(tpl_data)
    log.info("--- Self-monitoring items (%d) ---", len(sm_defs))
    for item_def in sm_defs:
        api.ensure_item(tpl_id, item_def, on_template=True)

    log.info("=" * 60)
    log.info("Done. Template '%s' is ready.", tpl_name)
    log.info("Link it to hosts via: Configuration → Hosts → select host → Templates")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = base_arg_parser(
        "Create a Zabbix template with all trapper items from template.yaml + metrics.yaml."
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
        "--config",
        default=_DEFAULT_CLIENT_YAML,
        metavar="PATH",
        help=f"Path to client.yaml — server_host is read from it (default: {_DEFAULT_CLIENT_YAML})",
    )
    parser.add_argument(
        "--only-enabled",
        action="store_true",
        help="Only include metrics with enabled: true in metrics.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    for path, label in [(args.template, "template.yaml"), (args.metrics, "metrics.yaml")]:
        if not os.path.exists(path):
            log.error("%s not found: %s", label, path)
            return 1

    tpl_data = load_yaml(args.template)
    metrics  = load_metrics(args.metrics, only_enabled=args.only_enabled)

    server_host = server_host_from_config(args.config)
    api_url = resolve_api_url(args.api_url, server_host)
    log.info("API URL  : %s", api_url)
    log.info("Metrics  : %d items (%s)", len(metrics),
             "enabled only" if args.only_enabled else "all defined")

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)

    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)
        run(api, tpl_data, metrics)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
