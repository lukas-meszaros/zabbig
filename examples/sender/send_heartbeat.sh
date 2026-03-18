#!/usr/bin/env bash
# =============================================================================
# examples/sender/send_heartbeat.sh
#
# Send a single heartbeat value using zabbix_sender (macOS Homebrew binary).
#
# Prerequisites:
#   brew install zabbix
#
# Usage:
#   bash examples/sender/send_heartbeat.sh [server] [port]
# =============================================================================
set -euo pipefail

# Load .env if present (for ZABBIX_TRAPPER_PORT)
# shellcheck source=/dev/null
[[ -f .env ]] && source <(grep -E '^ZABBIX_(TRAPPER_PORT|WEB_PORT)=' .env) 2>/dev/null || true

ZABBIX_SERVER="${1:-127.0.0.1}"
ZABBIX_PORT="${2:-${ZABBIX_TRAPPER_PORT:-10051}}"
HOST_NAME="macos-local-sender"

echo "Sending heartbeat to ${ZABBIX_SERVER}:${ZABBIX_PORT} ..."

zabbix_sender \
  --zabbix-server "${ZABBIX_SERVER}" \
  --port          "${ZABBIX_PORT}" \
  --host          "${HOST_NAME}" \
  --key           "macos.heartbeat" \
  --value         "1"

echo "Done."
