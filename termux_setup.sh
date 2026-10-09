#!/data/data/com.termux/files/usr/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#   PC Remote Sentinel — Android Phone Server Setup (Termux)
#   Turns any Android phone into a 24/7 Fleet Commander Bot
# ══════════════════════════════════════════════════════════════════════════════

echo "=========================================================="
echo "🛡️ PC REMOTE SENTINEL — ANDROID COMMANDER SETUP 📱"
echo "=========================================================="
echo ""

# 1. Update Termux Packages
echo "[1/5] Updating Termux packages..."
pkg update -y && pkg install -y python git openssl

# 2. Install Python Bot Dependencies
echo "[2/5] Installing lightweight bot dependencies..."
pip install --upgrade pip
pip install -r requirements-bot.txt

# 3. Check for .env file
echo "[3/5] Checking configuration..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "⚠️ Created .env from .env.example."
        echo "👉 Please edit .env and insert your TELEGRAM_BOT_TOKEN and AUTHORIZED_USER_IDS:"
        echo "   nano .env"
    else
        echo "⚠️ .env not found. Please create one with your bot token."
    fi
else
    echo "✓ .env configuration found."
fi

# 4. Check for fleet.json
if [ ! -f fleet.json ]; then
    if [ -f fleet.json.example ]; then
        cp fleet.json.example fleet.json
        echo "✓ Initialized fleet.json from template."
    fi
fi

# 5. Prevent Android from sleeping (Wake Lock)
echo "[4/5] Enabling background wake lock (prevents sleep)..."
if command -v termux-wake-lock &> /dev/null; then
    termux-wake-lock
    echo "✓ termux-wake-lock activated! Android won't suspend the bot when screen is off."
else
    echo "ℹ️ Note: Install Termux:API and run 'termux-wake-lock' to prevent Android sleeping."
fi

echo ""
echo "=========================================================="
echo "🎉 SETUP COMPLETE! 🚀"
echo "=========================================================="
echo ""
echo "To launch your 24/7 Fleet Commander Bot on this phone:"
echo "   python bot.py"
echo ""
echo "To run silently in the background (survives closing the terminal):"
echo "   nohup python bot.py > bot.log 2>&1 &"
echo ""
echo "To view background logs:"
echo "   tail -f bot.log"
echo "=========================================================="
