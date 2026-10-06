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
