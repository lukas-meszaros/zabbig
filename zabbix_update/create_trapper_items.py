#!/usr/bin/env python3
"""
create_trapper_items.py — Create Zabbix trapper items directly on a host,
                          merging template.yaml (names/tags) and metrics.yaml
                          (keys/value_types).

This replicates the behaviour of the old provision_zabbix.py but reads item
presentation data from template.yaml rather than metrics.yaml.

What this creates
-----------------
  Host group  : zabbix.host_group from client.yaml
  Host        : zabbix.host_name  from client.yaml
  Items       : one Zabbix trapper item per metric (merged from both files)
  Self-mon    : five zabbig.client.* items from template.yaml

Idempotent — safe to re-run.  Existing items have their tags synced.

Usage
-----
  cd zabbix_update
  python3 create_trapper_items.py [options]

  python3 create_trapper_items.py --help
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
    wait_for_api,
    log,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TEMPLATE_YAML = os.path.join(_HERE, "template.yaml")
_DEFAULT_METRICS_YAML  = os.path.join(_HERE, "..", "zabbig_client", "metrics.yaml")
_DEFAULT_CLIENT_YAML   = os.path.join(_HERE, "..", "zabbig_client", "client.yaml")


# ---------------------------------------------------------------------------
# Build item definitions (identical logic to create_template.py)
# ---------------------------------------------------------------------------

def _build_item_defs(metrics: list[dict], tpl_data: dict) -> list[dict]:
    defaults    = tpl_data.get("item_defaults", {})
    def_history = defaults.get("history", "7d")
    def_trends  = defaults.get("trends", "365d")
    def_tags    = defaults.get("tags", [])

    overrides: dict[str, dict] = {}
    for item in tpl_data.get("items", []):
        overrides[item["key"]] = item

    result = []
    for m in metrics:
        key = m["key"]
        ov  = overrides.get(key, {})
        vt_int = YAML_VT_MAP.get(str(m.get("value_type", "float")).lower(), VT_FLOAT)

        item_def: dict = {
            "key_":        key,
            "name":        ov.get("name", key),
            "description": ov.get("description", ""),
            "value_type":  vt_int,
            "history":     ov.get("history", def_history),
            "trends":      ov.get("trends", def_trends),
        }
        tags = ov.get("tags", def_tags)
        if tags:
            item_def["tags"] = tags
        result.append(item_def)

    return result


def _build_self_mon_defs(tpl_data: dict) -> list[dict]:
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

def run(
    api: ZabbixAPI,
    host_name: str,
    host_group: str,
    item_defs: list[dict],
    sm_defs: list[dict],
) -> None:
    log.info("=" * 60)
    log.info("Host      : %s", host_name)
    log.info("Group     : %s", host_group)
    log.info("=" * 60)

    group_id = api.ensure_hostgroup(host_group)
    host_id  = api.ensure_host(host_name, group_id)

    log.info("--- Metric items (%d) ---", len(item_defs))
    for item_def in item_defs:
        api.ensure_item(host_id, item_def, on_template=False)

    log.info("--- Self-monitoring items (%d) ---", len(sm_defs))
    for item_def in sm_defs:
        api.ensure_item(host_id, item_def, on_template=False)

    log.info("=" * 60)
    log.info("Done. Host '%s' is ready to receive trapper data.", host_name)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = base_arg_parser(
        "Create Zabbix trapper items directly on a host (no template)."
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CLIENT_YAML,
        metavar="PATH",
        help=f"Path to client.yaml (default: {_DEFAULT_CLIENT_YAML})",
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
        "--only-enabled",
        action="store_true",
        help="Only provision metrics with enabled: true in metrics.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    for path, label in [
        (args.config, "client.yaml"),
        (args.template, "template.yaml"),
        (args.metrics, "metrics.yaml"),
    ]:
        if not os.path.exists(path):
            log.error("%s not found: %s", label, path)
            return 1

    # Load config to get host_name, host_group, server_host
    try:
        _client_src = os.path.join(os.path.dirname(args.config), "src")
        if _client_src not in sys.path:
            sys.path.insert(0, _client_src)
        from zabbig_client.config_loader import load_client_config
        client_cfg = load_client_config(args.config)
        zbx = client_cfg.zabbix
    except Exception as exc:
        log.error("Failed to load client.yaml: %s", exc)
        return 1

    tpl_data = load_yaml(args.template)
    metrics  = load_metrics(args.metrics, only_enabled=args.only_enabled)

    item_defs = _build_item_defs(metrics, tpl_data)
    sm_defs   = _build_self_mon_defs(tpl_data)

    api_url = resolve_api_url(args.api_url, zbx.server_host)
    log.info("API URL  : %s", api_url)
    log.info("Host     : %s", zbx.host_name)
    log.info("Group    : %s", zbx.host_group)
    log.info("Metrics  : %d items (%s)", len(metrics),
             "enabled only" if args.only_enabled else "all defined")

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)

    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)
        run(api, zbx.host_name, zbx.host_group, item_defs, sm_defs)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
