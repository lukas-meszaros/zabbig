#!/usr/bin/env bash
# =============================================================================
# scripts/stop.sh — Stop the Zabbix local lab stack (data is preserved)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

echo "▶  Stopping Zabbix lab containers (data volumes preserved)..."
docker compose down

echo "✅ All containers stopped.  Run 'bash scripts/start.sh' to restart."
