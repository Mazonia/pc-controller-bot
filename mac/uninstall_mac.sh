#!/usr/bin/env bash
# ==============================================================================
# PC REMOTE SENTINEL — macOS Agent Uninstaller
# ==============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${YELLOW}${BOLD}"
echo "======================================================================"
echo "    🗑️  PC REMOTE SENTINEL — macOS UNINSTALLER"
echo "======================================================================"
echo -e "${NC}"

INSTALL_DIR="${HOME}/Library/Application Support/PCSentinel"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.sentinel.agent.plist"
CURRENT_UID="$(id -u)"

# 1. Unload LaunchAgent
if [ -f "$PLIST_DEST" ]; then
    echo -e "${CYAN}[+] Stopping and unloading LaunchAgent service...${NC}"
    launchctl bootout "gui/${CURRENT_UID}/com.sentinel.agent" 2>/dev/null || launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo -e "${GREEN}[✔] Removed $PLIST_DEST${NC}"
fi

# 2. Kill any stray agent processes
echo -e "${CYAN}[+] Terminating any running agent processes...${NC}"
pkill -f "agent.py" 2>/dev/null || true

# 3. Clean files
if [ -d "$INSTALL_DIR" ]; then
    response=""
    if [ -t 0 ]; then
        read -r -p "Delete configuration and logs in $INSTALL_DIR? [y/N]: " response
    else
        response="n"
    fi
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        rm -rf "$INSTALL_DIR"
        echo -e "${GREEN}[✔] Deleted $INSTALL_DIR${NC}"
    else
        echo -e "${CYAN}[+] Preserved configuration files in $INSTALL_DIR${NC}"
    fi
fi

echo -e "\n${BOLD}${GREEN}Sentinel macOS agent has been successfully uninstalled.${NC}\n"
