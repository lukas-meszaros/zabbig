#!/usr/bin/env bash
# =============================================================================
# examples/sender/send_all.sh
#
# Send all four starter trapper item values at once using zabbix_sender.
#
# Prerequisites:
#   brew install zabbix
#
# Usage:
#   bash examples/sender/send_all.sh [server] [port]
# =============================================================================
set -euo pipefail

# shellcheck source=/dev/null
[[ -f .env ]] && source <(grep -E '^ZABBIX_TRAPPER_PORT=' .env) 2>/dev/null || true

ZABBIX_SERVER="${1:-127.0.0.1}"
ZABBIX_PORT="${2:-${ZABBIX_TRAPPER_PORT:-10051}}"
HOST_NAME="macos-local-sender"
TIMESTAMP=$(date +%s)

echo "Sending all starter items to ${ZABBIX_SERVER}:${ZABBIX_PORT} ..."
echo "  host: ${HOST_NAME}"
echo ""

# zabbix_sender supports an input file with one "host key value" per line.
# Using a here-document avoids creating temp files.
zabbix_sender \
  --zabbix-server "${ZABBIX_SERVER}" \
  --port          "${ZABBIX_PORT}" \
  --with-timestamps \
  --input-file    - <<EOF
${HOST_NAME} macos.heartbeat     1          ${TIMESTAMP}
${HOST_NAME} macos.status        0          ${TIMESTAMP}
${HOST_NAME} macos.error_count   0          ${TIMESTAMP}
${HOST_NAME} macos.message       "All OK"   ${TIMESTAMP}
EOF

echo ""
echo "Done.  Open Zabbix web UI → Monitoring → Latest data to verify."
