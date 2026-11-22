#!/usr/bin/env bash
# Entrypoint for macOS Foreground Agent Launcher
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR/mac/start_agent_mac.sh"
exec "$SCRIPT_DIR/mac/start_agent_mac.sh" "$@"
