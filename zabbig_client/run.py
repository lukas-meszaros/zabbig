#!/usr/bin/env python3
"""
run.py — Entry point for the zabbig monitoring client.

Usage:
    python3 run.py [options]

Options:
    --config   PATH   Path to client.yaml       (default: client.yaml)
    --metrics  PATH   Path to metrics.yaml      (default: metrics.yaml)
    --dry-run         Collect but do not send to Zabbix
    --log-level LEVEL Override logging.level from client.yaml
    --validate        Validate metrics.yaml and exit (no collectors, no Zabbix)

Exit codes:
    0  All metrics collected and sent successfully
    1  Partial failure (some collectors or sends failed)
    2  Fatal error (config, lock, timeout)

    When --validate is used:
    0  File is valid — no issues found
    1  File parsed but issues were found
    2  File not found or YAML syntax error
"""
import os
import sys

# Add src/ to sys.path so all packages (zabbig_client, zabbix_utils, yaml)
# can be imported without installation.
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import argparse
from zabbig_client.main import run, validate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="zabbig — standalone Zabbix trapper monitoring client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "client.yaml"),
        metavar="PATH",
        help="Path to client.yaml (default: client.yaml alongside run.py)",
    )
    parser.add_argument(
        "--metrics",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics.yaml"),
        metavar="PATH",
        help="Path to metrics.yaml (default: metrics.yaml alongside run.py)",
    )
    parser.add_argument(
        "--databases",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "databases.yaml"),
        metavar="PATH",
        help=(
            "Path to databases.yaml (default: databases.yaml alongside run.py). "
            "Optional: if the file does not exist, database metrics are not loaded."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Collect metrics but do not send them to Zabbix",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override the log level from client.yaml",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help=(
            "Validate the metrics file without running collectors or connecting "
            "to Zabbix. Uses --metrics path (or the default metrics.yaml). "
            "Does not require --config. "
            "Exit 0 = valid, 1 = issues found, 2 = file unreadable."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=(
            "Write collected metric values to PATH after collection. "
            "Format is controlled by --output-format (default: json)."
        ),
    )
    parser.add_argument(
        "--output-format",
        default="json",
        choices=["json", "csv", "table"],
        metavar="FORMAT",
        help="Output format when --output is specified: json | csv | table (default: json)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.validate:
        sys.exit(validate(metrics_config_path=args.metrics))

    exit_code = run(
        client_config_path=args.config,
        metrics_config_path=args.metrics,
        databases_config_path=args.databases,
        dry_run=args.dry_run,
        log_level_override=args.log_level,
        output_path=args.output,
        output_format=args.output_format,
    )
    sys.exit(exit_code)
