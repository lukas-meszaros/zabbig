#!/bin/bash
# start.sh — Wrapper to run the zabbig client using the embedded Python.
#
# Usage:
#   ./start.sh [options]          # normal run
#   ./start.sh --dry-run          # collect but do not send
#   ./start.sh --validate         # validate metrics.yaml and exit
#   ./start.sh --log-level DEBUG  # override log level
#
# All arguments are forwarded to run.py unchanged.
#
# Performance notes:
#   -s   Skip user site-packages scan (saves a filesystem stat on every run).
#   -O   Remove assert statements; sets __debug__ = False.
#   PYTHONPATH pre-set so the sys.path.insert in run.py becomes a no-op.

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$DIR/python/bin/python3" -s -O "$DIR/run.py" "$@"
