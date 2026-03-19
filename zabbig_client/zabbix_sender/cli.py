"""
cli.py — Command-line interface for the Zabbix sender client.

Usage:
    zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1
    zabbix-sender --host macos-local-sender \\
        --key macos.heartbeat --value 1 \\
        --key macos.status --value 0 \\
        --server 127.0.0.1 --port 10051 \\
        --verbose

    # Dry-run mode (no network connection):
    zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1 --dry-run
"""

import argparse
import logging
import sys

from .config import Config
from .sender import SenderItem, ZabbixSender


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zabbix-sender",
        description="Send values to Zabbix trapper items via the Zabbix sender protocol.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send a heartbeat:
  zabbix-sender --host macos-local-sender --key macos.heartbeat --value 1

  # Send multiple values:
  zabbix-sender --host macos-local-sender \\
      --key macos.heartbeat --value 1 \\
      --key macos.status   --value 0 \\
      --key macos.message  --value "All OK"

  # Use a custom server:
  zabbix-sender --server 192.168.1.100 --port 10051 \\
      --host myhost --key mykey --value 42

  # Environment variable overrides:
  ZABBIX_SERVER=192.168.1.100 ZABBIX_HOST=myhost \\
      zabbix-sender --key mykey --value 42
        """,
    )

    # Connection options
    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--server", "-s",
        default=None,
        metavar="HOST",
        help="Zabbix server hostname or IP  [env: ZABBIX_SERVER, default: 127.0.0.1]",
    )
    conn.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        metavar="PORT",
        help="Zabbix trapper port  [env: ZABBIX_PORT, default: 10051]",
    )
    conn.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Socket timeout in seconds  [env: ZABBIX_TIMEOUT, default: 10]",
    )

    # Data options
    data = parser.add_argument_group("data")
    data.add_argument(
        "--host", "-H",
        default=None,
        metavar="HOSTNAME",
        help=(
            "Zabbix host name (as configured in Zabbix UI/API)  "
            "[env: ZABBIX_HOST]"
        ),
    )
    data.add_argument(
        "--key", "-k",
        action="append",
        dest="keys",
        default=[],
        metavar="KEY",
        help="Item key.  Can be specified multiple times (paired with --value).",
    )
    data.add_argument(
        "--value", "-V",
        action="append",
        dest="values",
        default=[],
        metavar="VALUE",
        help="Item value.  Must appear the same number of times as --key.",
    )

    # Behaviour options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log what would be sent without opening a network connection.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug-level logging.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger(__name__)

    # Resolve host
    import os
    host = args.host or os.environ.get("ZABBIX_HOST")
    if not host:
        parser.error(
            "--host is required (or set ZABBIX_HOST environment variable)."
        )

    # Validate keys/values pairing
    if not args.keys:
        parser.error("At least one --key / --value pair is required.")
    if len(args.keys) != len(args.values):
        parser.error(
            f"Number of --key ({len(args.keys)}) and --value ({len(args.values)}) "
            "arguments must match."
        )

    # Build items
    items = [
        SenderItem(host=host, key=k, value=v)
        for k, v in zip(args.keys, args.values)
    ]

    # Build config
    config = Config(server=args.server, port=args.port, timeout=args.timeout)
    log.debug("Config: %s", config)

    # Send
    sender = ZabbixSender(
        server=config.server,
        port=config.port,
        timeout=config.timeout,
    )

    try:
        response = sender.send(items, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        log.error("Send failed: %s", exc)
        return 1

    # Report result
    if response.success:
        log.info(
            "✅ Success: processed=%d  failed=%d  total=%d",
            response.processed,
            response.failed,
            response.total,
        )
        return 0
    else:
        log.error(
            "❌ Send result: response=%s  info=%s",
            response.response,
            response.info,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
