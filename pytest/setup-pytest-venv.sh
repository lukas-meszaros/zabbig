#!/usr/bin/env bash
# =============================================================================
# setup-pytest-venv.sh — Create and populate the pytest virtual environment.
#
# Usage:
#   bash pytest/setup-pytest-venv.sh          # from project root
#   bash setup-pytest-venv.sh                 # from inside pytest/
#
# What it does:
#   1. Resolves the project root (one directory above this script).
#   2. Creates a Python 3 venv at <project-root>/pytest-venv/ if it does not
#      already exist.
#   3. Installs (or upgrades) pytest and pytest-asyncio into the venv.
#   4. Prints the command to run the full test suite.
#
# Requirements:
#   - python3 (3.11 or newer recommended; 3.13 tested)
#   - pip available inside the venv (standard)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/pytest-venv"

echo ""
echo "=== zabbig pytest environment setup ==="
echo "Project root : ${PROJECT_ROOT}"
echo "Venv path    : ${VENV_DIR}"
echo ""

# ---------------------------------------------------------------------------
# Detect Python interpreter
# ---------------------------------------------------------------------------
if command -v python3.13 &>/dev/null; then
    PYTHON="python3.13"
elif command -v python3.12 &>/dev/null; then
    PYTHON="python3.12"
elif command -v python3.11 &>/dev/null; then
    PYTHON="python3.11"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "ERROR: No suitable Python 3 interpreter found." >&2
    echo "       Install Python 3.11+ and re-run this script." >&2
    exit 1
fi

PYTHON_VERSION="$("${PYTHON}" --version 2>&1)"
echo "Using Python : ${PYTHON_VERSION} (${PYTHON})"

# ---------------------------------------------------------------------------
# Create venv (skip if it already exists)
# ---------------------------------------------------------------------------
if [[ -d "${VENV_DIR}" ]]; then
    echo "Venv already exists — skipping creation."
else
    echo "Creating venv..."
    "${PYTHON}" -m venv "${VENV_DIR}"
    echo "Venv created."
fi

# ---------------------------------------------------------------------------
# Install / upgrade packages
# ---------------------------------------------------------------------------
echo ""
echo "Installing packages..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --upgrade \
    "pytest>=9.0" \
    "pytest-asyncio>=1.3"

echo ""
echo "Installed packages:"
"${VENV_DIR}/bin/pip" show pytest pytest-asyncio | grep -E "^(Name|Version):"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== Setup complete ==="
echo ""
echo "Run the full test suite with:"
echo "  ${VENV_DIR}/bin/pytest pytest/ -v"
echo ""
echo "Or from the project root using the relative path:"
echo "  pytest-venv/bin/pytest pytest/ -v"
echo ""
