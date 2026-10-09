"""
Configuration Module for PC Remote Sentinel
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
RAW_AUTHORIZED_IDS = os.getenv("AUTHORIZED_USER_IDS", "0").strip()

AUTHORIZED_USER_IDS: set[int] = set()
for item in RAW_AUTHORIZED_IDS.split(","):
    item = item.strip()
    if item and item.isdigit() and int(item) != 0:
        AUTHORIZED_USER_IDS.add(int(item))

RECORDINGS_DIR = BASE_DIR / os.getenv("RECORDINGS_DIR", "recordings")
DOWNLOADS_DIR = BASE_DIR / os.getenv("DOWNLOADS_DIR", "downloads")

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# PIN Login Authentication
BOT_PIN = os.getenv("BOT_PIN", "").strip()
SESSION_TIMEOUT_MINS = int(os.getenv("SESSION_TIMEOUT_MINS", "60"))

# Remote Screen Casting Tunnel
ENABLE_PUBLIC_TUNNEL = os.getenv("ENABLE_PUBLIC_TUNNEL", "true").strip().lower() in ("1", "true", "yes")
STREAM_PORT = int(os.getenv("STREAM_PORT", "8585"))


def update_pin(new_pin: str) -> bool:
    """Dynamically set or clear the BOT_PIN and persist to .env."""
    global BOT_PIN
    BOT_PIN = new_pin.strip()
    env_path = BASE_DIR / ".env"
    try:
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
        
        lines = content.splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith("BOT_PIN="):
                new_lines.append(f"BOT_PIN={BOT_PIN}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"BOT_PIN={BOT_PIN}")
        
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False

