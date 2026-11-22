#!/usr/bin/env bash
# ==============================================================================
# PC REMOTE SENTINEL — Native macOS Agent Installer
# Compatible with macOS Monterey, Ventura, Sonoma, Sequoia (M1/M2/M3/M4 & Intel)
# ==============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}"
echo "======================================================================"
echo "    🛡️  PC REMOTE SENTINEL — macOS AGENT INSTALLATION WIZARD"
echo "======================================================================"
echo -e "${NC}"

# 1. Platform & Architecture Validation
OS_NAME="$(uname -s)"
if [ "$OS_NAME" != "Darwin" ]; then
    echo -e "${RED}[ERROR] This installer is exclusively designed for macOS (Darwin). Current OS: $OS_NAME${NC}"
    exit 1
fi

ARCH="$(uname -m)"
echo -e "${GREEN}[+] Detected macOS platform ($ARCH architecture)${NC}"

# 2. Check for Python 3
PYTHON_BIN=""
for cmd in python3.11 python3.12 python3.13 python3.10 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON_BIN="$(command -v "$cmd")"
            echo -e "${GREEN}[+] Using Python: $PYTHON_BIN (v$VER)${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR] Python 3.9+ is required but was not found on this Mac.${NC}"
    echo -e "${YELLOW}Please install Python using one of these options:${NC}"
    echo "  Option A (Homebrew):  brew install python3"
    echo "  Option B (Official):  Download from https://www.python.org/downloads/macos/"
    exit 1
fi

# 3. Setup Target Installation Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INSTALL_DIR="${HOME}/Library/Application Support/PCSentinel"
LOG_DIR="${INSTALL_DIR}/logs"
VENV_DIR="${INSTALL_DIR}/venv"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_FILE="com.sentinel.agent.plist"
PLIST_DEST="${LAUNCH_AGENTS_DIR}/${PLIST_FILE}"

echo -e "${CYAN}[+] Setting up application directory:${NC} $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"

# 4. Copy Agent Files
echo -e "${CYAN}[+] Copying Sentinel agent modules...${NC}"
cp -f "$REPO_ROOT/agent.py" "$INSTALL_DIR/"
cp -f "$REPO_ROOT/system_controller.py" "$INSTALL_DIR/"
cp -f "$REPO_ROOT/screen_caster.py" "$INSTALL_DIR/"
cp -f "$REPO_ROOT/config.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$REPO_ROOT/encryption_manager.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$SCRIPT_DIR/requirements_mac.txt" "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR/start_agent_mac.sh" "$INSTALL_DIR/start_agent.sh"
chmod +x "$INSTALL_DIR/start_agent.sh"

# 5. Virtual Environment Creation
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo -e "${CYAN}[+] Creating isolated Python virtual environment...${NC}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo -e "${GREEN}[+] Reusing existing virtual environment in: $VENV_DIR${NC}"
fi

# Upgrade pip quietly
echo -e "${CYAN}[+] Updating pip tooling...${NC}"
"$VENV_DIR/bin/python" -m pip install --upgrade pip --quiet

# 6. Install Dependencies
echo -e "${CYAN}[+] Installing Core Sentinel packages...${NC}"
"$VENV_DIR/bin/pip" install --quiet \
    "fastapi>=0.104.0" \
    "uvicorn[standard]>=0.24.0" \
    "paho-mqtt>=2.0.0" \
    "cryptography>=41.0.0" \
    "httpx>=0.25.0" \
    "psutil>=5.9.0" \
    "pillow>=10.0.0" \
    "python-dotenv>=1.0.0" \
    "loguru>=0.7.0" \
    "python-multipart>=0.0.6"

echo -e "${CYAN}[+] Installing optional multimedia packages (OpenCV, NumPy)...${NC}"
"$VENV_DIR/bin/pip" install --quiet "opencv-python>=4.8.0" "numpy>=1.24.0" 2>/dev/null || {
    echo -e "${YELLOW}[!] Note: Optional OpenCV packages skipped; native macOS screencapture and CoreGraphics will be used.${NC}"
}

# 7. Configure agent.env
ENV_FILE="$INSTALL_DIR/agent.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${CYAN}[+] Generating agent configuration ($ENV_FILE)...${NC}"
    
    # Read from existing .env or deploy_config.env if available
    SRC_ENV=""
    if [ -f "$REPO_ROOT/deploy_config.env" ]; then
        SRC_ENV="$REPO_ROOT/deploy_config.env"
    elif [ -f "$REPO_ROOT/.env" ]; then
        SRC_ENV="$REPO_ROOT/.env"
    fi

    # Defaults
    BOT_TOKEN="8219154654:AAG9s9fpcTMJqB76Cq8iMrCD4nDobg6kaS8"
    AUTH_IDS="6513180621"
    FLEET_SEC="sentinel-fleet-secret-2026"
    HOST_NAME="$(scutil --get ComputerName 2>/dev/null || hostname -s || echo "MacBook")"

    if [ -n "$SRC_ENV" ]; then
        TOKEN_VAL=$(grep -E "^TELEGRAM_BOT_TOKEN=" "$SRC_ENV" | cut -d= -f2- | tr -d ' "\r\n' || true)
        AUTH_VAL=$(grep -E "^AUTHORIZED_USER_IDS=" "$SRC_ENV" | cut -d= -f2- | tr -d ' "\r\n' || true)
        SEC_VAL=$(grep -E "^FLEET_SECRET=" "$SRC_ENV" | cut -d= -f2- | tr -d ' "\r\n' || true)
        
        [ -n "$TOKEN_VAL" ] && BOT_TOKEN="$TOKEN_VAL"
        [ -n "$AUTH_VAL" ] && AUTH_IDS="$AUTH_VAL"
        [ -n "$SEC_VAL" ] && FLEET_SEC="$SEC_VAL"
    fi

    cat <<EOF > "$ENV_FILE"
# PC Remote Sentinel — macOS Agent Configuration
PC_NAME=${HOST_NAME}
TELEGRAM_BOT_TOKEN=${BOT_TOKEN}
AUTHORIZED_USER_IDS=${AUTH_IDS}
FLEET_SECRET=${FLEET_SEC}
AGENT_PORT=9010
MQTT_BROKER_HOST=broker.emqx.io
MQTT_BROKER_PORT=8883
ENABLE_LIVE_RADAR=true
ENABLE_CLOUD_TUNNEL=true
EOF
    chmod 600 "$ENV_FILE"
    echo -e "${GREEN}[+] Configured PC_NAME='$HOST_NAME' in agent.env${NC}"
fi

# 8. Setup launchd LaunchAgent Service
echo -e "${CYAN}[+] Installing macOS LaunchAgent background service...${NC}"
PLIST_TEMPLATE="$SCRIPT_DIR/com.sentinel.agent.plist"

sed \
    -e "s|__PYTHON_BIN__|${VENV_DIR}/bin/python3|g" \
    -e "s|__AGENT_PY__|${INSTALL_DIR}/agent.py|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__LOG_DIR__|${LOG_DIR}|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

# Unload previous instance if running
if launchctl list com.sentinel.agent >/dev/null 2>&1; then
    echo -e "${YELLOW}[+] Unloading previous Sentinel daemon...${NC}"
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load new LaunchAgent
echo -e "${CYAN}[+] Loading LaunchAgent service with launchctl...${NC}"
launchctl load "$PLIST_DEST"

# 9. Verify Service
sleep 1.5
if launchctl list com.sentinel.agent >/dev/null 2>&1; then
    echo -e "${GREEN}${BOLD}[✔] Sentinel macOS Agent service is active and running!${NC}"
else
    echo -e "${YELLOW}[!] LaunchAgent loaded. Check logs at: $LOG_DIR/agent_launchd_err.log${NC}"
fi

echo -e "\n${BOLD}${GREEN}======================================================================${NC}"
echo -e "${BOLD}${GREEN}      🎉 PC REMOTE SENTINEL SUCCESSFULLY INSTALLED ON MAC!${NC}"
echo -e "${BOLD}${GREEN}======================================================================${NC}"

echo -e "\n${BOLD}${YELLOW}⚠️  CRITICAL: macOS PRIVACY & SECURITY PERMISSIONS REQUIRED${NC}"
echo -e "macOS requires explicit authorization for remote administration tools."
echo -e "Open ${BOLD}System Settings > Privacy & Security${NC} and grant permissions to Terminal / Python:"
echo -e "  1. ${CYAN}Screen Recording:${NC} Allows remote screenshots & high-FPS video streaming."
echo -e "  2. ${CYAN}Accessibility:${NC}    Allows synthetic mouse clicks, scrolling & keyboard input."
echo -e "  3. ${CYAN}Camera (Optional):${NC} Allows remote webcam snapshots."
echo -e "\nTo open System Settings directly to Privacy & Security, run:"
echo -e "   ${BOLD}open x-apple.systempreferences:com.apple.preference.security?Privacy${NC}\n"

echo -e "${CYAN}Service Management Commands:${NC}"
echo -e "  • Check Status:    ${BOLD}launchctl list com.sentinel.agent${NC}"
echo -e "  • Stop Agent:      ${BOLD}launchctl unload \"$PLIST_DEST\"${NC}"
echo -e "  • Start Agent:     ${BOLD}launchctl load \"$PLIST_DEST\"${NC}"
echo -e "  • View Live Logs:  ${BOLD}tail -f \"$INSTALL_DIR/agent.log\"${NC}"
echo -e "  • Run Foreground:  ${BOLD}\"$INSTALL_DIR/start_agent.sh\"${NC}"
echo ""
