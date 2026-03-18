#!/usr/bin/env bash
# =============================================================================
# scripts/wait-for-zabbix.sh — Wait until the Zabbix web UI responds
#
# Usage: bash scripts/wait-for-zabbix.sh [max_wait_seconds]
#
# Exits 0 when the UI is ready, exits 1 on timeout.
# =============================================================================
set -euo pipefail

# Maximum time to wait in seconds (default: 300 = 5 minutes)
MAX_WAIT="${1:-300}"
INTERVAL=5

# Load the port from .env if present
ZABBIX_WEB_PORT="${ZABBIX_WEB_PORT:-8080}"
# shellcheck source=/dev/null
[[ -f .env ]] && source <(grep -E '^ZABBIX_WEB_PORT=' .env | head -1) 2>/dev/null || true

URL="http://localhost:${ZABBIX_WEB_PORT}/index.php"
elapsed=0

echo "   Waiting for Zabbix web UI at ${URL} ..."
echo "   (timeout: ${MAX_WAIT}s, checking every ${INTERVAL}s)"

while true; do
  if curl -sf --max-time 5 "${URL}" | grep -qi "zabbix" 2>/dev/null; then
    echo "   ✅ Zabbix web UI is up! (${elapsed}s elapsed)"
    exit 0
  fi

  if (( elapsed >= MAX_WAIT )); then
    echo ""
    echo "   ❌ Timeout: Zabbix web UI did not become available within ${MAX_WAIT}s."
    echo "   Check container logs:  docker compose logs zabbix-server"
    echo "                          docker compose logs zabbix-web"
    exit 1
  fi

  printf "   Elapsed: %3ds — still waiting...\r" "${elapsed}"
  sleep "${INTERVAL}"
  (( elapsed += INTERVAL ))
done
