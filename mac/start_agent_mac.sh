#!/usr/bin/env bash
# ==============================================================================
# PC REMOTE SENTINEL — Foreground macOS Agent Launcher
# Useful for live debugging, log viewing, and testing.
# ==============================================================================

INSTALL_DIR="${HOME}/Library/Application Support/PCSentinel"
VENV_DIR="${INSTALL_DIR}/venv"

if [ -f "$VENV_DIR/bin/python3" ]; then
    PYTHON_EXEC="$VENV_DIR/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXEC="$(command -v python3)"
else
    echo "[-] Python 3 not found. Please install Python 3 first."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$INSTALL_DIR/agent.py" ]; then
    RUN_DIR="$INSTALL_DIR"
else
    RUN_DIR="$SCRIPT_DIR/.."
fi

cd "$RUN_DIR"
echo "[+] Starting PC Remote Sentinel Agent in foreground..."
echo "[+] Working directory: $RUN_DIR"
echo "[+] Python runtime:    $PYTHON_EXEC"
echo "----------------------------------------------------------------------"

exec "$PYTHON_EXEC" "agent.py"
