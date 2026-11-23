#!/usr/bin/env bash
# ==============================================================================
# PC REMOTE SENTINEL — Native macOS Agent Installer
# Compatible with macOS Monterey, Ventura, Sonoma, Sequoia (M1/M2/M3/M4 & Intel)
# ==============================================================================

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

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

# 2. Check for Python 3 (Checking Homebrew, framework, and system locations)
PYTHON_BIN=""
CANDIDATES=(
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "python3.13"
    "python3.12"
    "python3.11"
    "python3.10"
    "python3"
)

for cmd in "${CANDIDATES[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
        RESOLVED_BIN="$(command -v "$cmd")"
        VER=$("$RESOLVED_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$VER" ]; then
            MAJOR=$(echo "$VER" | cut -d. -f1)
            MINOR=$(echo "$VER" | cut -d. -f2)
            if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 9 ]; then
                PYTHON_BIN="$RESOLVED_BIN"
                echo -e "${GREEN}[+] Using Python: $PYTHON_BIN (v$VER)${NC}"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR] Python 3.9+ is required but was not found on this Mac.${NC}"
    echo -e "${YELLOW}Please install Python using one of these options:${NC}"
    echo "  Option A (Homebrew - Recommended):  brew install python3"
    echo "  Option B (Official Installer):      https://www.python.org/downloads/macos/"
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
cp -f "$REPO_ROOT/fleet_relay.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$REPO_ROOT/config.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$REPO_ROOT/encryption_manager.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -f "$SCRIPT_DIR/requirements_mac.txt" "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR/start_agent_mac.sh" "$INSTALL_DIR/start_agent.sh"
chmod +x "$INSTALL_DIR/start_agent.sh"

# 5. Virtual Environment Creation
VENV_PYTHON="$VENV_DIR/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${CYAN}[+] Creating isolated Python virtual environment...${NC}"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null; then
        echo -e "${YELLOW}[!] Standard venv creation returned warning. Retrying with --without-pip fallback...${NC}"
        "$PYTHON_BIN" -m venv --without-pip "$VENV_DIR"
        curl -sS https://bootstrap.pypa.io/get-pip.py | "$VENV_PYTHON" >/dev/null 2>&1 || true
    fi
else
    echo -e "${GREEN}[+] Reusing existing virtual environment in: $VENV_DIR${NC}"
fi

# Upgrade pip quietly
echo -e "${CYAN}[+] Updating pip tooling...${NC}"
"$VENV_PYTHON" -m pip install --upgrade pip --quiet 2>/dev/null || true

# 6. Install Dependencies
echo -e "${CYAN}[+] Installing Core Sentinel packages...${NC}"
"$VENV_PYTHON" -m pip install --quiet \
    "fastapi>=0.104.0" \
    "uvicorn>=0.23.0" \
    "paho-mqtt>=2.0.0" \
    "cryptography>=41.0.0" \
    "httpx>=0.25.0" \
    "psutil>=5.9.0" \
    "pillow>=10.0.0" \
    "python-dotenv>=1.0.0" \
    "loguru>=0.7.0" \
    "python-multipart>=0.0.6"

echo -e "${CYAN}[+] Installing optional multimedia packages (OpenCV, NumPy)...${NC}"
"$VENV_PYTHON" -m pip install --quiet "opencv-python>=4.8.0" "numpy>=1.24.0" 2>/dev/null || {
    echo -e "${YELLOW}[!] Note: Optional OpenCV packages skipped; native macOS screencapture and CoreGraphics will be used.${NC}"
}

# 7. Configure agent.env
ENV_FILE="$INSTALL_DIR/agent.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${CYAN}[+] Generating agent configuration ($ENV_FILE)...${NC}"
    
    SRC_ENV=""
    if [ -f "$REPO_ROOT/deploy_config.env" ]; then
        SRC_ENV="$REPO_ROOT/deploy_config.env"
    elif [ -f "$REPO_ROOT/.env" ]; then
        SRC_ENV="$REPO_ROOT/.env"
    fi

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
MQTT_BROKER=broker.emqx.io
MQTT_PORT=8883
MQTT_USE_TLS=true
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
    -e "s|__PYTHON_BIN__|${VENV_PYTHON}|g" \
    -e "s|__AGENT_PY__|${INSTALL_DIR}/agent.py|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__LOG_DIR__|${LOG_DIR}|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

# Unload previous instance safely
CURRENT_UID="$(id -u)"
launchctl bootout "gui/${CURRENT_UID}/com.sentinel.agent" 2>/dev/null || launchctl unload "$PLIST_DEST" 2>/dev/null || true
sleep 0.5

# Load new LaunchAgent
echo -e "${CYAN}[+] Registering LaunchAgent service with launchctl...${NC}"
if ! launchctl bootstrap "gui/${CURRENT_UID}" "$PLIST_DEST" 2>/dev/null; then
    launchctl load -w "$PLIST_DEST" 2>/dev/null || true
fi

# 9. Verify Service and Environment
echo -e "${CYAN}[+] Running environment health check...${NC}"
"$VENV_PYTHON" -c "
import fastapi, paho.mqtt, PIL, psutil
print('    [✔] Python dependencies loaded successfully')
" 2>/dev/null || echo -e "${YELLOW}[!] Warning: Dependency verification reported notice.${NC}"

sleep 1.0
if launchctl list com.sentinel.agent >/dev/null 2>&1; then
    echo -e "${GREEN}${BOLD}[✔] Sentinel macOS Agent service is active and running!${NC}"
else
    echo -e "${YELLOW}[!] Service registered. If prompted, please allow background items in macOS System Settings.${NC}"
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
echo -e "  • Stop Agent:      ${BOLD}launchctl bootout gui/$(id -u)/com.sentinel.agent 2>/dev/null || launchctl unload \"$PLIST_DEST\"${NC}"
echo -e "  • Start Agent:     ${BOLD}launchctl bootstrap gui/$(id -u) \"$PLIST_DEST\" 2>/dev/null || launchctl load -w \"$PLIST_DEST\"${NC}"
echo -e "  • View Live Logs:  ${BOLD}tail -f \"$INSTALL_DIR/agent.log\"${NC}"
echo -e "  • Run Foreground:  ${BOLD}\"$INSTALL_DIR/start_agent.sh\"${NC}"
echo ""
