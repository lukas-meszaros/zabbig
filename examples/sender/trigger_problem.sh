#!/usr/bin/env bash
# =============================================================================
# examples/sender/trigger_problem.sh
#
# Force trigger conditions to demonstrate Zabbix problem detection.
#
# Sends:
#   macos.status       = 2   → triggers "Status is CRITICAL"
#   macos.error_count  = 15  → triggers "Error count above threshold"
#
# To recover, send status=0 and error_count=0.
#
# Prerequisites:
#   brew install zabbix
#
# Usage:
#   bash examples/sender/trigger_problem.sh [server] [port]
#   bash examples/sender/trigger_problem.sh 127.0.0.1 10051 --recover
# =============================================================================
set -euo pipefail

# shellcheck source=/dev/null
[[ -f .env ]] && source <(grep -E '^ZABBIX_TRAPPER_PORT=' .env) 2>/dev/null || true

ZABBIX_SERVER="${1:-127.0.0.1}"
ZABBIX_PORT="${2:-${ZABBIX_TRAPPER_PORT:-10051}}"
RECOVER="${3:-}"
HOST_NAME="macos-local-sender"
TIMESTAMP=$(date +%s)

if [[ "${RECOVER}" == "--recover" ]]; then
  STATUS=0
  ERROR_COUNT=0
  echo "▶  Sending RECOVERY values ..."
else
  STATUS=2
  ERROR_COUNT=15
  echo "▶  Sending PROBLEM values ..."
fi

zabbix_sender \
  --zabbix-server "${ZABBIX_SERVER}" \
  --port          "${ZABBIX_PORT}" \
  --input-file    - <<EOF
${HOST_NAME} macos.heartbeat     1
${HOST_NAME} macos.status        ${STATUS}
${HOST_NAME} macos.error_count   ${ERROR_COUNT}
${HOST_NAME} macos.message       "Error Connection"
EOF

echo ""
if [[ "${RECOVER}" == "--recover" ]]; then
  echo "Recovery values sent.  Check Zabbix → Problems — problems should clear."
else
  echo "Problem values sent.  Check Zabbix → Problems for new alerts."
  echo "To recover, run:  $0 ${ZABBIX_SERVER} ${ZABBIX_PORT} --recover"
fi
