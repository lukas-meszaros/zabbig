#!/usr/bin/env bash
# =============================================================================
# scripts/start.sh — Start the Zabbix local lab stack
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║          Zabbix Local Lab — Starting up              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Ensure .env exists
if [[ ! -f .env ]]; then
  echo "⚠  No .env file found. Copying .env.example → .env"
  cp .env.example .env
  echo "   Please review .env before running in a shared environment."
  echo ""
fi

# Pull images (skipped if already present)
echo "▶  Pulling Docker images (may take a while on first run)..."
docker compose pull --quiet

# Start all services
echo "▶  Starting containers..."
docker compose up -d

echo ""
echo "▶  Waiting for Zabbix web UI to become available..."
bash "${SCRIPT_DIR}/wait-for-zabbix.sh"

# Load port from .env (default 8080)
ZABBIX_WEB_PORT="${ZABBIX_WEB_PORT:-8080}"
# shellcheck source=/dev/null
[[ -f .env ]] && source <(grep -E '^ZABBIX_WEB_PORT=' .env | head -1)

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ Zabbix lab is ready!                             ║"
echo "║                                                      ║"
echo "║  Web UI:   http://localhost:${ZABBIX_WEB_PORT}                ║"
echo "║  Login:    Admin / zabbix                            ║"
echo "║                                                      ║"
echo "║  Run:  python3 scripts/bootstrap.py                 ║"
echo "║  to provision the starter host + items + triggers.  ║"
echo "╚══════════════════════════════════════════════════════╝"
