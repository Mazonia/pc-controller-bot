#!/usr/bin/env bash
# Entrypoint for macOS Uninstaller
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR/mac/uninstall_mac.sh"
exec "$SCRIPT_DIR/mac/uninstall_mac.sh" "$@"
