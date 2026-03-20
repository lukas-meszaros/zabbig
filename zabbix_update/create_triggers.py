#!/usr/bin/env python3
"""
create_triggers.py — Create Zabbix triggers from triggers.yaml.

Triggers can target either a template or a host directly.  Use --target to
choose.  When targeting a template, expressions must use the template name
as the host part (already correct in triggers.yaml).  When targeting a host,
expressions are rewritten at runtime to replace the template name with the
host name.

What this creates
-----------------
  Triggers : one per entry in triggers.yaml

Idempotent — existing triggers (matched by name + host/template) are skipped.

Usage
-----
  cd zabbix_update

  # Create triggers on the template (recommended):
  python3 create_triggers.py --target template

  # Create triggers on a specific host:
  python3 create_triggers.py --target host --host prod-server-01

  python3 create_triggers.py --help
"""

import os
import sys

from _common import (
    ZabbixAPI,
    SEVERITY_MAP,
    base_arg_parser,
    load_yaml,
    resolve_api_url,
    resolve_credentials,
    wait_for_api,
    log,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TRIGGERS_YAML = os.path.join(_HERE, "triggers.yaml")


# ---------------------------------------------------------------------------
# Build trigger API params
# ---------------------------------------------------------------------------

def _build_trigger_params(
    trigger: dict,
    target_name: str,
    template_name: str,
    on_template: bool,
    dependencies: dict[str, str],
) -> dict:
    """
    Convert a triggers.yaml entry into a Zabbix trigger.create params dict.

    When targeting a host, the template name in expressions is replaced with
    the host name so the expression references the correct item source.
    """
    expression = trigger["expression"]
    if not on_template:
        expression = expression.replace(template_name, target_name)

    params: dict = {
        "description": trigger["name"],
        "expression":  expression,
        "priority":    SEVERITY_MAP.get(trigger.get("severity", "warning"), 2),
        "comments":    trigger.get("description", ""),
        "status":      0 if trigger.get("enabled", True) else 1,
    }

    recovery_expr = trigger.get("recovery_expression", "")
    if recovery_expr:
        params["recovery_mode"]       = 1   # custom recovery expression
        params["recovery_expression"] = recovery_expr
    else:
        params["recovery_mode"] = 0   # expression-based recovery (default)

    # Dependency resolution — requires previously created trigger IDs
    dep_names = trigger.get("depends_on", [])
    dep_ids = []
    for dep_name in dep_names:
        dep_id = dependencies.get(dep_name)
        if dep_id:
            dep_ids.append({"triggerid": dep_id})
        else:
            log.warning("  Dependency '%s' not found — skipping dependency link", dep_name)
    if dep_ids:
        params["dependencies"] = dep_ids

    # Internal marker used by ensure_trigger for duplicate detection
    params["_host"] = target_name

    return params


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def run(api: ZabbixAPI, trig_data: dict, target: str, host_name: str) -> None:
    template_name = trig_data.get("template_name", "zabbig Linux Host")
    on_template   = (target == "template")
    target_name   = template_name if on_template else host_name

    if on_template:
        tpl_id = api.get_template_id(template_name)
        if not tpl_id:
            log.error(
                "Template '%s' not found in Zabbix. "
                "Run create_template.py first.", template_name
            )
            raise RuntimeError(f"Template '{template_name}' not found.")
        log.info("Target    : template '%s' (id=%s)", template_name, tpl_id)
    else:
        host_id = api.get_host_id(host_name)
        if not host_id:
            log.error(
                "Host '%s' not found in Zabbix. "
                "Run create_trapper_items.py first.", host_name
            )
            raise RuntimeError(f"Host '{host_name}' not found.")
        log.info("Target    : host '%s' (id=%s)", host_name, host_id)

    triggers = trig_data.get("triggers", [])
    log.info("=" * 60)
    log.info("Creating %d triggers on %s '%s'", len(triggers),
             "template" if on_template else "host", target_name)
    log.info("=" * 60)

    # Track created trigger IDs for dependency resolution (processed in order)
    created: dict[str, str] = {}

    for trigger in triggers:
        params = _build_trigger_params(
            trigger, target_name, template_name, on_template, created
        )
        name = params["description"]
        tid  = api.get_trigger_id(name, target_name)
        if tid:
            log.info("  Trigger '%s' already exists (id=%s) — skipped", name, tid)
            created[name] = tid
        else:
            clean_params = {k: v for k, v in params.items() if not k.startswith("_")}
            try:
                tid = api._call("trigger.create", clean_params)["triggerids"][0]
                log.info("  Created trigger '%s' (id=%s)", name, tid)
                created[name] = tid
            except RuntimeError as exc:
                log.warning("  Failed to create trigger '%s': %s", name, exc)

    log.info("=" * 60)
    log.info("Done. %d/%d triggers processed.", len(created), len(triggers))
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    parser = base_arg_parser(
        "Create Zabbix triggers from triggers.yaml on a template or host."
    )
    parser.add_argument(
        "--triggers",
        default=_DEFAULT_TRIGGERS_YAML,
        metavar="PATH",
        help=f"Path to triggers.yaml (default: {_DEFAULT_TRIGGERS_YAML})",
    )
    parser.add_argument(
        "--target",
        choices=["template", "host"],
        default="template",
        help="Where to create triggers: 'template' (default) or 'host'.",
    )
    parser.add_argument(
        "--host",
        default=None,
        metavar="HOSTNAME",
        help="Zabbix host name (required when --target host).",
    )
    parser.add_argument(
        "--server-host",
        default="127.0.0.1",
        metavar="HOST",
        help="Zabbix server host for deriving the API URL (default: 127.0.0.1).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.target == "host" and not args.host:
        print("ERROR: --host is required when --target host", file=sys.stderr)
        return 1

    if not os.path.exists(args.triggers):
        log.error("triggers.yaml not found: %s", args.triggers)
        return 1

    trig_data = load_yaml(args.triggers)
    api_url   = resolve_api_url(args.api_url, args.server_host)

    log.info("API URL  : %s", api_url)
    log.info("Target   : %s", args.target)
    if args.target == "host":
        log.info("Host     : %s", args.host)

    if not args.no_wait:
        wait_for_api(api_url)

    user, password = resolve_credentials(args.user, args.password)

    api = ZabbixAPI(api_url)
    try:
        api.login(user, password)
        run(api, trig_data, args.target, args.host or "")
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        api.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
