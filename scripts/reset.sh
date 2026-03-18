#!/usr/bin/env bash
# =============================================================================
# scripts/reset.sh — Full wipe: stop + remove containers AND all data volumes
#
# ⚠  WARNING: This deletes the PostgreSQL data volume.
#    All Zabbix configuration (hosts, items, triggers, history) will be lost.
#    Re-run bootstrap.py after reset to reprovision.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

echo "⚠  WARNING: This will DELETE all Zabbix data volumes!"
echo ""
read -r -p "   Type 'yes' to confirm: " confirmation

if [[ "${confirmation}" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""
echo "▶  Stopping and removing containers + volumes..."
docker compose down --volumes --remove-orphans

echo ""
echo "✅ Reset complete."
echo "   Start fresh with: bash scripts/start.sh"
echo "   Then provision:   python3 scripts/bootstrap.py"
