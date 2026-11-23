"""
PC Remote Sentinel — Agent
Dual-mode agent that runs on each monitored PC:
1. Connects to the Fleet Cloud Relay (MQTT over TLS) — works seamlessly across
   Wi-Fi, Ethernet, Mobile Hotspots, 4G/5G modems, and CGNAT.
2. Exposes a local FastAPI HTTP server on port 9010 for direct LAN access.
3. Uploads screenshots/videos directly to Telegram API for zero broker bandwidth.
"""

import os
import sys
import ctypes

if sys.platform == "win32":
    try:
        ctypes.windll.kernel32.SetConsoleTitleW('PC-Sentinel-Agent')
    except Exception:
        pass
else:
    try:
        sys.stdout.write("\x1b]2;PC-Sentinel-Agent\x07")
        sys.stdout.flush()
    except Exception:
        pass
import io
import hmac
import json
import time
import socket
import asyncio
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
import uvicorn
from dotenv import load_dotenv
from loguru import logger

# ── Configuration ──────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / "agent.env")
load_dotenv(BASE_DIR / ".env")

# Configure persistent rotating file logging (C:\PCSentinel\agent.log)
LOG_FILE = BASE_DIR / "agent.log"
logger.add(
    str(LOG_FILE),
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    backtrace=True,
    diagnose=True,
    encoding="utf-8",
)

PC_NAME = os.getenv("PC_NAME", "").strip() or os.environ.get("COMPUTERNAME") or socket.gethostname() or "Unknown-PC"
AGENT_PORT = int(os.getenv("AGENT_PORT", "9010"))
AGENT_SECRET = os.getenv("AGENT_SECRET", "").strip()
FLEET_SECRET = os.getenv("FLEET_SECRET", "").strip() or AGENT_SECRET or "sentinel-fleet-secret-2026"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTHORIZED_USER_IDS = os.getenv("AUTHORIZED_USER_IDS", "").strip()
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io").strip()
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USE_TLS = os.getenv("MQTT_USE_TLS", "true").strip().lower() in ("1", "true", "yes")

STREAM_PORT = int(os.getenv("STREAM_PORT", "8585"))
ENABLE_PUBLIC_TUNNEL = True  # Always enabled for global mobile data streaming

RECORDINGS_DIR = BASE_DIR / "recordings"
DOWNLOADS_DIR = BASE_DIR / "downloads"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ── Import System Modules ──────────────────────────────────────────────

from system_controller import SystemController
from screen_caster import screen_caster, get_active_window_title
from fleet_relay import FleetAgentRelay, get_network_info

hardware_lock = threading.Lock()
relay: Optional[FleetAgentRelay] = None

# ── Lockdown & Security Guard State ────────────────────────────────────
LOCKDOWN_ACTIVE: bool = False
LOCKDOWN_CONFIG: dict = {"silent": False, "alarm": True, "start_time": None}
_lockdown_thread: Optional[threading.Thread] = None
_lockdown_stop_event = threading.Event()
AGENT_START_TIME: str = datetime.now(timezone.utc).isoformat()


def _lockdown_guard_worker(chat_id: Optional[int] = None):
    """Monitors desktop state during lockdown. If screen is unlocked, immediately re-locks and snaps intruder."""
    logger.warning(f"🚨 Lockdown Guard Worker activated on {PC_NAME}")
    while LOCKDOWN_ACTIVE and not _lockdown_stop_event.is_set():
        try:
            session = SystemController.get_session_state().lower()
            if "unlocked" in session or "interactive desktop" in session:
                logger.warning(f"🚨 LOCKDOWN BREACH DETECTED on {PC_NAME}! Immediate re-lock initiated.")
                SystemController.lock_workstation()
                SystemController.turn_off_monitors()

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = RECORDINGS_DIR / f"intruder_{ts}.jpg"
                with hardware_lock:
                    ok, _ = SystemController.take_webcam_photo(path)

                if chat_id and ok and path.exists():
                    caption = (
                        f"🚨 <b>SECURITY BREACH DETECTED ON {PC_NAME}!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ <i>Workstation was unlocked while under LOCKDOWN!</i>\n"
                        f"🔒 <b>Action Taken:</b> Workstation immediately re-locked.\n"
                        f"⏱️ <b>Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
                    )
                    send_photo_to_telegram(chat_id, path, caption)
                elif chat_id and TELEGRAM_BOT_TOKEN:
                    try:
                        text_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        httpx.post(
                            text_url,
                            json={
                                "chat_id": chat_id,
                                "text": f"🚨 <b>SECURITY BREACH ON {PC_NAME}!</b>\nWorkstation was unlocked while under LOCKDOWN! Re-locked immediately.",
                                "parse_mode": "HTML"
                            },
                            timeout=5.0
                        )
                    except Exception:
                        pass

                if relay:
                    relay.send_alert({
                        "type": "lockdown_breach",
                        "pc_name": PC_NAME,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
        except Exception as ge:
            logger.debug(f"Lockdown guard loop exception: {ge}")

        _lockdown_stop_event.wait(1.5)


def apply_agent_update(zip_b64: Optional[str] = None, files_dict: Optional[dict] = None) -> dict:
    """
    Safely apply OTA code update received over Telegram/MQTT/HTTP:
    1. Create automatic backup of current codebase in backup_updates/
    2. Extract/write files to temporary staging folder
    3. Verify SHA-256 checksums if manifest is included
    4. Validate Python syntax on all .py files using py_compile (prevents bricking)
    5. Overwrite production files
    6. Prune old backups (keep last 10)
    7. Schedule clean process restart with multi-fallback launcher
    """
    import io
    import zipfile
    import base64
    import shutil
    import py_compile
    import hashlib
    import json

    ts = int(time.time())
    backup_dir = BASE_DIR / "backup_updates" / f"backup_{ts}"
    staging_dir = BASE_DIR / "_update_staging"

    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged_files = []

        if zip_b64:
            raw_zip = base64.b64decode(zip_b64)
            with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
                for member in zf.namelist():
                    safe_name = Path(member).name
                    if not safe_name:
                        continue
                    target_path = staging_dir / safe_name
                    with zf.open(member) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    staged_files.append(safe_name)
        elif files_dict:
            for fname, fcontent_b64 in files_dict.items():
                safe_name = Path(fname).name
                raw_bytes = base64.b64decode(fcontent_b64)
                target_path = staging_dir / safe_name
                with open(target_path, "wb") as f:
                    f.write(raw_bytes)
                staged_files.append(safe_name)
        else:
            return {"ok": False, "error": "No update package data provided."}

        if not staged_files:
            return {"ok": False, "error": "Update package was empty."}

        # 3. Cryptographic checksum verification if manifest.json exists
        manifest_file = staging_dir / "manifest.json"
        if manifest_file.exists():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                expected_files = manifest_data.get("files", {})
                for fname, expected_hash in expected_files.items():
                    target_f = staging_dir / fname
                    if target_f.exists():
                        actual_hash = hashlib.sha256(target_f.read_bytes()).hexdigest()
                        if actual_hash.lower() != expected_hash.lower():
                            shutil.rmtree(staging_dir, ignore_errors=True)
                            err_msg = f"Checksum mismatch for {fname}: expected {expected_hash[:12]}..., got {actual_hash[:12]}..."
                            logger.error(f"OTA update rejected: {err_msg}")
                            return {"ok": False, "error": err_msg}
            except Exception as me:
                logger.warning(f"Manifest checksum check warning: {me}")

        # 4. Python syntax verification on all .py files in staging (prevents bricking)
        for staged_name in staged_files:
            if staged_name.endswith(".py"):
                py_file = staging_dir / staged_name
                try:
                    py_compile.compile(str(py_file), doraise=True)
                except py_compile.PyCompileError as pe:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    logger.error(f"OTA update rejected due to syntax error in {staged_name}: {pe}")
                    return {"ok": False, "error": f"Syntax error in {staged_name}: {pe}"}

        # 5. Backup existing files before overwriting
        backup_dir.mkdir(parents=True, exist_ok=True)
        for staged_name in staged_files:
            existing_file = BASE_DIR / staged_name
            if existing_file.exists():
                shutil.copy2(existing_file, backup_dir / staged_name)

        # 6. Overwrite production files
        for staged_name in staged_files:
            src_path = staging_dir / staged_name
            dst_path = BASE_DIR / staged_name
            shutil.copy2(src_path, dst_path)

        shutil.rmtree(staging_dir, ignore_errors=True)
        logger.info(f"OTA update applied successfully: {len(staged_files)} files: {staged_files}")

        # 7. Prune older backups (keep last 10)
        try:
            backups_dir = BASE_DIR / "backup_updates"
            if backups_dir.exists():
                all_b = sorted([p for p in backups_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
                if len(all_b) > 10:
                    for old_b in all_b[:-10]:
                        shutil.rmtree(old_b, ignore_errors=True)
        except Exception:
            pass

        # 8. Schedule restart with multi-level fallback
        def _delayed_restart():
            time.sleep(1.2)
            if sys.platform == "win32":
                restarted = False
                vbs_path = BASE_DIR / "start_agent_hidden.vbs"
                if vbs_path.exists():
                    try:
                        subprocess.Popen(
                            ["cmd.exe", "/c", "timeout /t 2 /nobreak >nul & wscript.exe start_agent_hidden.vbs"],
                            cwd=str(BASE_DIR),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                        )
                        restarted = True
                    except Exception as re:
                        logger.debug(f"VBS restart notice: {re}")
                if not restarted:
                    try:
                        subprocess.Popen(
                            ["cmd.exe", "/c", f'timeout /t 2 /nobreak >nul & "{sys.executable}" "{BASE_DIR / "agent.py"}"'],
                            cwd=str(BASE_DIR),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                        )
                    except Exception as re:
                        logger.debug(f"Direct Python restart notice: {re}")
            logger.info("Restarting agent process to load updated code...")
            os._exit(0)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "ok": True,
            "success": True,
            "msg": f"OTA update applied successfully ({len(staged_files)} files). Agent restarting...",
            "updated_files": staged_files,
            "backup_id": backup_dir.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        shutil.rmtree(staging_dir, ignore_errors=True)
        logger.error(f"Error applying OTA agent update: {e}")
        return {"ok": False, "error": f"Failed to apply update: {e}"}


def rollback_agent_update(backup_id: Optional[str] = None) -> dict:
    """
    Safely rollback to the latest backup in backup_updates/ (or a specified backup_id).
    Validates syntax and restarts the agent.
    """
    import shutil
    import py_compile
    backups_dir = BASE_DIR / "backup_updates"
    if not backups_dir.exists():
        return {"ok": False, "error": "No backup directory found on this PC."}

    available_backups = sorted([p for p in backups_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not available_backups:
        return {"ok": False, "error": "No backups available for rollback."}

    target_backup = None
    if backup_id:
        for b in available_backups:
            if b.name == backup_id or backup_id in b.name:
                target_backup = b
                break
        if not target_backup:
            return {"ok": False, "error": f"Backup '{backup_id}' not found."}
    else:
        target_backup = available_backups[0]

    restored_files = []
    try:
        # Pre-verify syntax on Python files in the backup
        for f in target_backup.iterdir():
            if f.is_file() and f.suffix == ".py":
                py_compile.compile(str(f), doraise=True)

        for f in target_backup.iterdir():
            if f.is_file():
                dest = BASE_DIR / f.name
                shutil.copy2(f, dest)
                restored_files.append(f.name)

        def _delayed_restart():
            time.sleep(1.2)
            if sys.platform == "win32":
                restarted = False
                vbs_path = BASE_DIR / "start_agent_hidden.vbs"
                if vbs_path.exists():
                    try:
                        subprocess.Popen(
                            ["cmd.exe", "/c", "timeout /t 2 /nobreak >nul & wscript.exe start_agent_hidden.vbs"],
                            cwd=str(BASE_DIR),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                        )
                        restarted = True
                    except Exception:
                        pass
                if not restarted:
                    try:
                        subprocess.Popen(
                            ["cmd.exe", "/c", f'timeout /t 2 /nobreak >nul & "{sys.executable}" "{BASE_DIR / "agent.py"}"'],
                            cwd=str(BASE_DIR),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                        )
                    except Exception:
                        pass
            logger.info("Restarting agent process after rollback...")
            os._exit(0)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "ok": True,
            "success": True,
            "msg": f"Rollback successful from {target_backup.name}. Restored {len(restored_files)} files. Agent restarting...",
            "restored_files": restored_files,
            "backup_id": target_backup.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Rollback error: {e}")
        return {"ok": False, "error": f"Rollback failed: {e}"}


def get_agent_version_info() -> dict:
    """Calculate SHA-256 hashes of running core files and return version and backup status."""
    import hashlib
    core_files = [
        "agent.py", "fleet_relay.py", "system_controller.py",
        "screen_caster.py", "manager_auth.py", "start_agent.bat"
    ]
    hashes = {}
    for cf in core_files:
        p = BASE_DIR / cf
        if p.exists():
            try:
                hashes[cf] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            except Exception:
                hashes[cf] = "error"

    backups_dir = BASE_DIR / "backup_updates"
    available_backups = []
    if backups_dir.exists():
        available_backups = [p.name for p in sorted(backups_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if p.is_dir()][:5]

    return {
        "ok": True,
        "pc_name": PC_NAME,
        "hashes": hashes,
        "backups": available_backups,
        "start_time": AGENT_START_TIME,
    }



# ═══════════════════════════════════════════════════════════════════════
#   DIRECT TELEGRAM UPLOAD HELPERS
# ═══════════════════════════════════════════════════════════════════════

def send_photo_to_telegram(chat_id: int, photo_path: Path, caption: str = "") -> bool:
    """Upload photo directly to Telegram chat with automatic JPEG compression and retries."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Cannot upload to Telegram: TELEGRAM_BOT_TOKEN not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    # Optimize PNG or large images to JPEG to drastically speed up transmission on poor internet
    upload_path = photo_path
    temp_jpg = None
    try:
        if photo_path.suffix.lower() == ".png" or photo_path.stat().st_size > 400 * 1024:
            from PIL import Image
            temp_jpg = photo_path.with_suffix(".opt.jpg")
            with Image.open(photo_path) as img:
                rgb = img.convert("RGB")
                rgb.save(temp_jpg, "JPEG", quality=85, optimize=True)
            upload_path = temp_jpg
    except Exception as e:
        logger.debug(f"Could not convert image to JPEG: {e}")
        upload_path = photo_path

    for attempt in range(1, 4):
        try:
            with open(upload_path, "rb") as f:
                r = httpx.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": f},
                    timeout=50.0,
                )
                if r.status_code == 200:
                    logger.info(f"Photo successfully uploaded to Telegram (attempt {attempt})")
                    if temp_jpg and temp_jpg.exists():
                        try:
                            temp_jpg.unlink()
                        except Exception:
                            pass
                    return True
                else:
                    logger.warning(f"Telegram upload attempt {attempt} returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Telegram photo upload attempt {attempt} error: {e}")

        if attempt < 3:
            time.sleep(2.0 * attempt)

    if temp_jpg and temp_jpg.exists():
        try:
            temp_jpg.unlink()
        except Exception:
            pass
    return False


def send_video_to_telegram(chat_id: int, video_path: Path, caption: str = "") -> bool:
    """Upload video directly to Telegram chat with retries."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    for attempt in range(1, 4):
        try:
            with open(video_path, "rb") as f:
                r = httpx.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                    files={"video": f},
                    timeout=90.0,
                )
                if r.status_code == 200:
                    return True
                logger.warning(f"Telegram video upload attempt {attempt} returned {r.status_code}")
        except Exception as e:
            logger.warning(f"Telegram video upload attempt {attempt} error: {e}")
        if attempt < 3:
            time.sleep(2.0 * attempt)
    return False


def send_document_to_telegram(chat_id: int, file_path: Path, caption: str = "") -> bool:
    """Upload document directly to Telegram chat with retries."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for attempt in range(1, 4):
        try:
            with open(file_path, "rb") as f:
                r = httpx.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                    files={"document": f},
                    timeout=90.0,
                )
                if r.status_code == 200:
                    return True
                logger.warning(f"Telegram doc upload attempt {attempt} returned {r.status_code}")
        except Exception as e:
            logger.warning(f"Telegram doc upload attempt {attempt} error: {e}")
        if attempt < 3:
            time.sleep(2.0 * attempt)
    return False


# ═══════════════════════════════════════════════════════════════════════
#   CLOUD RELAY COMMAND DISPATCHER
# ═══════════════════════════════════════════════════════════════════════

def handle_relay_command(data: dict) -> dict:
    """
    Handle commands received via MQTT Cloud Relay.
    Works over mobile hotspots, cellular modems, or local network.
    """
    global LOCKDOWN_ACTIVE, LOCKDOWN_CONFIG, _lockdown_thread
    cmd = data.get("cmd", "")
    params = data.get("params", {})
    chat_id = params.get("chat_id")

    logger.info(f"Processing command [{cmd}] for {PC_NAME}")

    # 1. STATUS
    if cmd == "status":
        stats = SystemController.get_system_stats()
        stats["pc_name"] = PC_NAME
        stats["active_window"] = get_active_window_title()
        stats["network"] = get_network_info()
        return {"ok": True, "stats": stats}

    elif cmd in ("memory", "ram_status", "mem"):
        mem_data = SystemController.get_memory_status()
        mem_data["pc_name"] = PC_NAME
        return {"ok": True, "memory": mem_data}

    # 2. SCREENSHOT
    elif cmd == "screenshot":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RECORDINGS_DIR / f"shot_{ts}.png"
        with hardware_lock:
            ok, msg = SystemController.take_screenshot(path)
        if ok and path.exists():
            if chat_id:
                caption = f"📸 Screenshot from <b>{PC_NAME}</b>\n⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                if send_photo_to_telegram(chat_id, path, caption):
                    return {"ok": True, "direct_upload": True, "msg": "Screenshot uploaded to chat."}
                else:
                    return {"ok": False, "error": "Screenshot captured, but Telegram upload timed out due to unstable internet connection."}
            return {"ok": True, "path": str(path)}
        return {"ok": False, "error": f"Screenshot failed: {msg}"}

    # 3. WEBCAM
    elif cmd == "webcam":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RECORDINGS_DIR / f"webcam_{ts}.jpg"
        with hardware_lock:
            ok, msg = SystemController.take_webcam_photo(path)
        if ok and path.exists():
            if chat_id:
                caption = f"🎥 Webcam capture from <b>{PC_NAME}</b>\n⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                if send_photo_to_telegram(chat_id, path, caption):
                    return {"ok": True, "direct_upload": True, "msg": "Webcam photo uploaded to chat."}
                else:
                    return {"ok": False, "error": "Webcam captured, but Telegram upload timed out due to unstable internet connection."}
            return {"ok": True, "path": str(path)}
        return {"ok": False, "error": f"Webcam capture failed: {msg}"}

    # 4. RECORD SCREEN
    elif cmd == "record_screen":
        duration = min(max(int(params.get("duration", 10)), 3), 60)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RECORDINGS_DIR / f"screen_{ts}_{duration}s.mp4"
        with hardware_lock:
            ok, msg = SystemController.record_screen_video(path, duration_sec=duration)
        if ok and path.exists():
            if chat_id:
                caption = f"🔴 Screen recording ({duration}s) from <b>{PC_NAME}</b>"
                if send_video_to_telegram(chat_id, path, caption):
                    return {"ok": True, "direct_upload": True, "msg": "Screen video uploaded to chat."}
                else:
                    return {"ok": False, "error": "Screen video recorded, but Telegram upload timed out due to unstable internet connection."}
            return {"ok": True, "path": str(path)}
        return {"ok": False, "error": f"Screen recording failed: {msg}"}

    # 5. RECORD WEBCAM
    elif cmd == "record_webcam":
        duration = min(max(int(params.get("duration", 10)), 3), 60)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RECORDINGS_DIR / f"webcam_{ts}_{duration}s.mp4"
        with hardware_lock:
            ok, msg = SystemController.record_webcam_video(path, duration_sec=duration)
        if ok and path.exists():
            if chat_id:
                caption = f"📹 Webcam recording ({duration}s) from <b>{PC_NAME}</b>"
                if send_video_to_telegram(chat_id, path, caption):
                    return {"ok": True, "direct_upload": True, "msg": "Webcam video uploaded to chat."}
                else:
                    return {"ok": False, "error": "Webcam video recorded, but Telegram upload timed out due to unstable internet connection."}
            return {"ok": True, "path": str(path)}
        return {"ok": False, "error": f"Webcam recording failed: {msg}"}

    # 6. LIVE SCREEN CAST (Global via Cloudflare Quick Tunnel)
    elif cmd == "cast_start":
        res = screen_caster.start_web_cast(STREAM_PORT, enable_tunnel=True)
        return {
            "ok": True,
            "lan_url": res.get("lan_url", ""),
            "public_url": res.get("public_url", ""),
            "token": res.get("token", ""),
            "pc_name": PC_NAME,
        }

    elif cmd == "cast_stop":
        screen_caster.stop_web_cast()
        return {"ok": True, "msg": "Live stream stopped."}

    elif cmd == "cast_status":
        status = screen_caster.get_status()
        status["pc_name"] = PC_NAME
        return {"ok": True, "status": status}

    elif cmd == "cast_frame":
        import base64
        quality = int(params.get("quality", 60))
        max_width = int(params.get("max_width", 960))
        frame = screen_caster.capture_single_frame(quality=quality, max_w=max_width)
        return {"ok": True, "frame_b64": base64.b64encode(frame).decode("ascii")}

    elif cmd == "switch_desktop":
        action = params.get("action", "next")
        ok, msg = SystemController.switch_virtual_desktop(action)
        return {
            "ok": ok,
            "msg": msg,
            "action": action,
            "active_window": get_active_window_title(),
            "pc_name": PC_NAME,
        }

    elif cmd == "windows_list":
        limit = int(params.get("limit", 20))
        windows = SystemController.get_open_windows(limit=limit)
        return {
            "ok": True,
            "windows": windows,
            "active_window": get_active_window_title(),
            "pc_name": PC_NAME,
        }

    elif cmd == "window_focus":
        target = params.get("target") or params.get("hwnd") or params.get("query")
        if not target:
            return {"ok": False, "error": "No target window specified."}
        ok, msg = SystemController.focus_window(target)
        return {
            "ok": ok,
            "msg": msg,
            "active_window": get_active_window_title(),
            "pc_name": PC_NAME,
        }

    elif cmd == "window_cycle":
        direction = params.get("direction", "next")
        ok, msg = SystemController.cycle_window(direction)
        return {
            "ok": ok,
            "msg": msg,
            "direction": direction,
            "active_window": get_active_window_title(),
            "pc_name": PC_NAME,
        }

    # Remote Mouse & Keyboard Inputs
    elif cmd == "mouse_input":
        def _safe_int(v, d=0):
            try:
                return int(round(float(v))) if v is not None and v != "" else d
            except (ValueError, TypeError):
                return d
        def _safe_float(v, d=0.0):
            try:
                return float(v) if v is not None and v != "" else d
            except (ValueError, TypeError):
                return d

        action = str(params.get("action", "move")).lower().strip()
        ok = False
        if action == "move":
            dx = _safe_int(params.get("dx", 0))
            dy = _safe_int(params.get("dy", 0))
            ok = SystemController.mouse_move(dx, dy)
        elif action == "move_abs":
            x = _safe_float(params.get("x", 0))
            y = _safe_float(params.get("y", 0))
            norm = bool(params.get("norm", False))
            ok = SystemController.mouse_move_abs(x, y, normalized=norm)
        elif action in ("click", "down", "up", "double"):
            btn = str(params.get("btn", "left"))
            act = "click" if action == "click" else action
            if action == "double":
                btn = "double"
            ok = SystemController.mouse_click(button=btn, action=act)
        elif action == "scroll":
            delta = _safe_int(params.get("delta", 0))
            ok = SystemController.mouse_scroll(delta)
        elif action in ("scroll_h", "hscroll"):
            delta = _safe_int(params.get("delta", 0))
            ok = SystemController.mouse_scroll_h(delta)
        elif action == "gesture":
            gesture = str(params.get("gesture", ""))
            ok, msg = SystemController.execute_gesture(gesture)
            return {"ok": ok, "msg": msg, "cursor": SystemController.get_cursor_pos(), "pc_name": PC_NAME}
        return {"ok": ok, "cursor": SystemController.get_cursor_pos(), "pc_name": PC_NAME}

    elif cmd == "type_text":
        text = str(params.get("text", ""))
        ok, msg = SystemController.type_text(text)
        return {"ok": ok, "msg": msg, "pc_name": PC_NAME}

    elif cmd == "press_key":
        key = str(params.get("key", ""))
        ok, msg = SystemController.press_key(key)
        return {"ok": ok, "msg": msg, "pc_name": PC_NAME}

    elif cmd == "get_cursor":
        return {"ok": True, "cursor": SystemController.get_cursor_pos(), "pc_name": PC_NAME}

    # 7. POWER & LOCK
    elif cmd in ("lock", "power_lock"):
        ok = SystemController.lock_workstation()
        return {"ok": ok, "msg": "Workstation locked." if ok else "Lock failed."}

    elif cmd in ("sleep", "power_sleep"):
        ok = SystemController.sleep_pc()
        return {"ok": ok, "msg": "PC entered sleep mode." if ok else "Sleep failed."}

    elif cmd in ("reboot", "restart"):
        delay = int(params.get("delay", 5))
        ok = SystemController.restart_pc(seconds=delay)
        return {"ok": ok, "msg": f"PC restarting in {delay}s." if ok else "Restart failed."}

    elif cmd == "shutdown":
        delay = int(params.get("delay", 0))
        ok = SystemController.shutdown_pc(seconds=delay)
        return {"ok": ok, "msg": f"PC shutting down in {delay}s." if ok else "Shutdown failed."}

    elif cmd == "cancel_shutdown":
        ok = SystemController.cancel_shutdown()
        return {"ok": ok, "msg": "Scheduled shutdown cancelled." if ok else "No scheduled shutdown active."}

    elif cmd in ("monitor_off", "monitors_off"):
        ok = SystemController.turn_off_monitors()
        return {"ok": ok, "msg": "Monitors turned off." if ok else "Failed to turn off monitors."}

    elif cmd in ("monitor_on", "monitors_on"):
        ok = SystemController.turn_on_monitors()
        return {"ok": ok, "msg": "Monitors turned on." if ok else "Failed to turn on monitors."}

    # 8. PROCESSES & TERMINAL
    elif cmd == "processes":
        procs = SystemController.list_top_processes(limit=int(params.get("limit", params.get("count", 25))))
        return {"ok": True, "processes": procs}

    elif cmd == "kill_process":
        target = params.get("target")
        if not target:
            return {"ok": False, "error": "No target process specified."}
        ok, msg = SystemController.kill_process(target)
        return {"ok": ok, "msg": msg}

    elif cmd == "cmd":
        command_str = params.get("command", "")
        if not command_str:
            return {"ok": False, "error": "No command specified."}
        rc, output = SystemController.run_cmd(command_str)
        return {"ok": True, "output": output, "returncode": rc}

    # 9. VOLUME & MEDIA
    elif cmd == "volume_set":
        level = int(params.get("level", 50))
        ok = SystemController.change_volume(level)
        return {"ok": ok, "msg": f"Volume set to {level}%." if ok else "Volume change failed."}

    elif cmd in ("volume_mute", "mute"):
        ok, msg = SystemController.press_media_key("mute")
        return {"ok": ok, "msg": msg}

    elif cmd == "media_key":
        action = params.get("action", "")
        ok, msg = SystemController.press_media_key(action)
        return {"ok": ok, "msg": msg}

    # 10. CLIPBOARD
    elif cmd == "clipboard_get":
        text = SystemController.get_clipboard()
        return {"ok": True, "text": text}

    elif cmd == "clipboard_set":
        text = params.get("text", "")
        ok = SystemController.set_clipboard(text)
        return {"ok": ok, "msg": "Clipboard updated." if ok else "Failed to set clipboard."}

    # 11. ALARM
    elif cmd in ("alarm_start", "alarm_trigger"):
        label = params.get("label", "Manual Telegram Alarm")
        SystemController.play_alert_siren(label)
        return {"ok": True, "msg": f"Alarm siren triggered ({label})."}

    elif cmd == "alarm_set":
        seconds = int(params.get("seconds", params.get("duration", 30)))
        label = params.get("label", "Scheduled Alarm")
        res = SystemController.set_alarm(seconds, label)
        return {"ok": True, "alarm": res}

    elif cmd == "alarm_status":
        st = SystemController.get_alarm_status()
        return {"ok": True, "status": st}

    elif cmd in ("alarm_stop", "alarm_silence"):
        ok = SystemController.stop_alarm()
        return {"ok": ok, "msg": "Alarm silenced." if ok else "No active alarm."}

    elif cmd == "alarm_cancel":
        ok = SystemController.cancel_alarm()
        return {"ok": ok, "msg": "Alarm cancelled." if ok else "No active alarm."}

    # 12. TTS
    elif cmd == "tts":
        text = params.get("text", "")
        if not text:
            return {"ok": False, "error": "No text provided for TTS."}
        ok = SystemController.speak_text(text)
        return {"ok": ok, "msg": "Text spoken on PC." if ok else "Text-to-speech failed."}


    # 13. FILE OPERATIONS
    elif cmd in ("dir_list", "file_browse", "browse"):
        target_path = params.get("path", "")
        data = SystemController.browse_directory(target_path)
        data["pc_name"] = PC_NAME
        return data

    elif cmd == "file_list":
        dir_name = params.get("dir", "downloads")
        target_dir = RECORDINGS_DIR if dir_name == "recordings" else DOWNLOADS_DIR
        files = []
        for p in target_dir.glob("*"):
            if p.is_file():
                files.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                })
        return {"ok": True, "files": sorted(files, key=lambda x: x["modified"], reverse=True)[:30]}

    elif cmd == "file_download":
        raw_target = params.get("path") or params.get("name") or ""
        p = Path(raw_target)
        if not p.is_absolute():
            p1 = RECORDINGS_DIR / raw_target
            p2 = DOWNLOADS_DIR / raw_target
            p = p1 if p1.exists() else (p2 if p2.exists() else Path.home() / raw_target)

        if not p.exists() or not p.is_file():
            return {"ok": False, "error": f"File '{raw_target}' not found on PC."}

        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > 49.5:
            return {"ok": False, "error": f"File is too large for Telegram ({size_mb:.1f} MB exceeds 50 MB limit)."}

        if chat_id:
            caption = f"📄 File from <b>{PC_NAME}</b>: <code>{p.name}</code> (<code>{size_mb:.2f} MB</code>)"
            ok = send_document_to_telegram(chat_id, p, caption)
            if ok:
                return {"ok": True, "direct_upload": True, "msg": f"File '{p.name}' uploaded to chat."}
            return {"ok": False, "error": "Telegram upload failed."}
        return {"ok": True, "path": str(p), "size": p.stat().st_size}

    # 14. CLEANUP
    elif cmd in ("clean_scan", "storage_scan"):
        candidates = SystemController.scan_storage_candidates(RECORDINGS_DIR, DOWNLOADS_DIR)
        return {"ok": True, "candidates": candidates, "pc_name": PC_NAME}

    elif cmd in ("clean_execute", "storage_clean"):
        cnt, freed = SystemController.cleanup_old_files(RECORDINGS_DIR, DOWNLOADS_DIR, max_age_days=0)
        return {"ok": True, "deleted_count": cnt, "freed_bytes": freed, "pc_name": PC_NAME}

    # 15. AUDIO & VOICE PLAYBACK
    elif cmd == "play_audio":
        import base64
        filename = params.get("filename", f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg")
        data_b64 = params.get("data_b64", "")
        if not data_b64:
            return {"ok": False, "error": "No audio data provided."}
        try:
            raw_bytes = base64.b64decode(data_b64)
            dest = DOWNLOADS_DIR / Path(filename).name
            with open(dest, "wb") as f:
                f.write(raw_bytes)
            ok, msg = SystemController.play_audio_file(dest)
            return {"ok": ok, "success": ok, "msg": msg, "path": str(dest)}
        except Exception as e:
            return {"ok": False, "error": f"Audio playback error: {e}"}

    elif cmd in ("file_upload", "upload"):
        import base64
        filename = params.get("filename", f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin")
        data_b64 = params.get("data_b64", "")
        if not data_b64:
            return {"ok": False, "error": "No file data provided."}
        try:
            raw_bytes = base64.b64decode(data_b64)
            dest = DOWNLOADS_DIR / Path(filename).name
            with open(dest, "wb") as f:
                f.write(raw_bytes)
            auto_played = False
            if dest.suffix.lower() in (".mp3", ".wav", ".ogg", ".aac", ".m4a"):
                try:
                    ok, _ = SystemController.play_audio_file(dest)
                    auto_played = ok
                except Exception:
                    pass
            return {"ok": True, "success": True, "path": str(dest), "auto_played": auto_played}
        except Exception as e:
            return {"ok": False, "error": f"File upload error: {e}"}

    # 15. TRACKING & GEOLOCATION
    elif cmd == "tracking":
        info = SystemController.get_tracking_info()
        info["pc_name"] = PC_NAME
        return {"ok": True, "tracking": info}

    # 16. EMERGENCY LOCKDOWN
    elif cmd in ("lockdown_enable", "lockdown"):
        silent = bool(params.get("silent", False))
        alarm = bool(params.get("alarm", not silent))
        chat_id = params.get("chat_id")

        LOCKDOWN_ACTIVE = True
        LOCKDOWN_CONFIG = {
            "silent": silent,
            "alarm": alarm,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
        }
        _lockdown_stop_event.clear()

        # Capture evidence before locking
        cam_ok = False
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_path = RECORDINGS_DIR / f"lockdown_face_{ts}.jpg"
        with hardware_lock:
            cam_ok, _ = SystemController.take_webcam_photo(photo_path)

        if chat_id and cam_ok and photo_path.exists():
            caption = (
                f"🚨 <b>EMERGENCY LOCKDOWN ENGAGED ON {PC_NAME}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Status:</b> Workstation Locked & Guard Active\n"
                f"• <b>Alarm Siren:</b> {'🔊 Sounding' if alarm else '🤫 Silent Mode'}\n"
                f"• <b>Display:</b> Blackout / Monitors Off\n"
                f"• <b>Intruder Trap:</b> Auto-relock active"
            )
            send_photo_to_telegram(chat_id, photo_path, caption)

        if alarm:
            SystemController.play_alert_siren("EMERGENCY LOCKDOWN")

        SystemController.lock_workstation()
        SystemController.turn_off_monitors()

        if not _lockdown_thread or not _lockdown_thread.is_alive():
            _lockdown_thread = threading.Thread(target=_lockdown_guard_worker, args=(chat_id,), daemon=True)
            _lockdown_thread.start()

        return {
            "ok": True,
            "active": True,
            "silent": silent,
            "alarm": alarm,
            "pc_name": PC_NAME,
            "photo_captured": cam_ok,
        }

    elif cmd in ("lockdown_disable", "unlockdown", "disarm"):
        LOCKDOWN_ACTIVE = False
        _lockdown_stop_event.set()
        SystemController.stop_alarm()
        SystemController.turn_on_monitors()
        return {"ok": True, "active": False, "msg": "Lockdown deactivated. PC returned to normal state."}

    elif cmd == "lockdown_status":
        return {"ok": True, "active": LOCKDOWN_ACTIVE, "config": LOCKDOWN_CONFIG, "pc_name": PC_NAME}

    # 17. OVER-THE-AIR (OTA) AGENT UPDATE
    elif cmd in ("agent_update", "update_agent", "ota_update"):
        zip_b64 = params.get("zip_b64")
        files_dict = params.get("files")
        res = apply_agent_update(zip_b64=zip_b64, files_dict=files_dict)
        return res

    elif cmd in ("agent_rollback", "update_rollback", "ota_rollback"):
        backup_id = params.get("backup_id")
        res = rollback_agent_update(backup_id=backup_id)
        return res

    elif cmd in ("agent_version", "update_version", "ota_version"):
        res = get_agent_version_info()
        return res

    return {"ok": False, "error": f"Unknown command: '{cmd}'"}


_pending_events = []

def _alarm_callback(label: str, time_str: str):
    """Callback when alarm fires on this PC — pushes alert to Central Bot."""
    global _pending_events
    _pending_events.append({
        "type": "alarm_triggered",
        "label": label,
        "time": time_str,
        "pc_name": PC_NAME,
    })
    if relay:
        relay.send_alert({
            "type": "alarm_triggered",
            "label": label,
            "time": time_str,
        })


# ═══════════════════════════════════════════════════════════════════════
#   LOCAL FASTAPI SERVER (For Direct LAN Access)
# ═══════════════════════════════════════════════════════════════════════

async def verify_secret(request: Request):
    """Validate shared secret header on local LAN requests."""
    if AGENT_SECRET:
        token = request.headers.get("X-Agent-Secret", "")
        if not hmac.compare_digest(token, AGENT_SECRET):
            raise HTTPException(status_code=403, detail="Invalid agent secret")


app = FastAPI(
    title=f"PC Sentinel Agent — {PC_NAME}",
    docs_url=None,
    redoc_url=None,
    dependencies=[Depends(verify_secret)],
)


@app.get("/health")
async def health():
    net = get_network_info()
    return {
        "status": "online",
        "pc_name": PC_NAME,
        "hostname": socket.gethostname(),
        "ip": net["ip"],
        "network": net["type"],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/memory")
async def api_memory():
    mem = await asyncio.to_thread(SystemController.get_memory_status)
    return mem


@app.get("/status")
async def get_status():
    stats = await asyncio.to_thread(SystemController.get_system_stats)
    stats["pc_name"] = PC_NAME
    stats["active_window"] = get_active_window_title()
    stats["network"] = get_network_info()
    return stats


@app.get("/screenshot")
async def take_screenshot():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"shot_{ts}.png"
    with hardware_lock:
        ok, msg = await asyncio.to_thread(SystemController.take_screenshot, path)
    if ok and path.exists():
        return FileResponse(str(path), media_type="image/png", filename=path.name)
    raise HTTPException(500, f"Screenshot failed: {msg}")


@app.get("/webcam")
async def take_webcam():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"webcam_{ts}.jpg"
    with hardware_lock:
        ok, msg = await asyncio.to_thread(SystemController.take_webcam_photo, path)
    if ok and path.exists():
        return FileResponse(str(path), media_type="image/jpeg", filename=path.name)
    raise HTTPException(500, f"Webcam failed: {msg}")


@app.post("/cast/web/start")
async def api_cast_web_start():
    res = screen_caster.start_web_cast(STREAM_PORT, enable_tunnel=True)
    return res


@app.post("/cast/web/stop")
async def api_cast_web_stop():
    screen_caster.stop_web_cast()
    return {"ok": True, "msg": "Live stream stopped."}


@app.post("/cast/rtmp/start")
async def api_cast_rtmp_start(request: Request):
    data = await request.form()
    url = data.get("url", "")
    ok, msg = screen_caster.start_rtmp_stream(url)
    return {"ok": ok, "msg": msg}


@app.post("/cast/rtmp/stop")
async def api_cast_rtmp_stop():
    ok, msg = screen_caster.stop_rtmp_stream()
    return {"ok": ok, "msg": msg}



@app.get("/cast/status")
async def api_cast_status():
    status = screen_caster.get_status()
    status["pc_name"] = PC_NAME
    return status


@app.get("/cast/frame")
async def api_cast_frame(quality: int = 60, max_width: int = 960):
    frame = screen_caster.capture_single_frame(quality=quality, max_w=max_width)
    return Response(content=frame, media_type="image/jpeg")


@app.post("/desktop/switch")
async def api_desktop_switch(action: str = "next"):
    ok, msg = SystemController.switch_virtual_desktop(action)
    return {
        "ok": ok,
        "msg": msg,
        "action": action,
        "active_window": get_active_window_title(),
        "pc_name": PC_NAME,
    }


@app.get("/windows")
async def api_windows_list(limit: int = 20):
    wins = SystemController.get_open_windows(limit=limit)
    return {"ok": True, "windows": wins, "active_window": get_active_window_title()}


@app.post("/windows/focus")
async def api_window_focus(target: str = ""):
    ok, msg = SystemController.focus_window(target)
    return {"ok": ok, "msg": msg, "active_window": get_active_window_title()}


@app.post("/windows/cycle")
async def api_window_cycle(direction: str = "next"):
    ok, msg = SystemController.cycle_window(direction)
    return {"ok": ok, "msg": msg, "direction": direction, "active_window": get_active_window_title()}


# ── Remote Mouse & Keyboard Routes ──────────────────────────────────

def _api_safe_int(v, d=0):
    try:
        return int(round(float(v))) if v is not None and v != "" else d
    except (ValueError, TypeError):
        return d

def _api_safe_float(v, d=0.0):
    try:
        return float(v) if v is not None and v != "" else d
    except (ValueError, TypeError):
        return d

async def _extract_request_data(request: Request) -> dict:
    data = {}
    if request.method == "POST":
        try:
            data = await request.json()
        except Exception:
            try:
                form = await request.form()
                data = dict(form)
            except Exception:
                data = {}
    if not data:
        data = dict(request.query_params)
    return data

@app.api_route("/input/mouse", methods=["GET", "POST"])
async def api_input_mouse(request: Request):
    data = await _extract_request_data(request)
    action = str(data.get("action", "move")).lower().strip()
    ok = False
    if action == "move":
        dx = _api_safe_int(data.get("dx", 0))
        dy = _api_safe_int(data.get("dy", 0))
        ok = SystemController.mouse_move(dx, dy)
    elif action == "move_abs":
        x = _api_safe_float(data.get("x", 0))
        y = _api_safe_float(data.get("y", 0))
        norm = data.get("norm", False) in (True, 1, "1", "true", "True", "yes")
        ok = SystemController.mouse_move_abs(x, y, normalized=norm)
    elif action in ("click", "down", "up", "double"):
        btn = str(data.get("btn", "left"))
        act = "click" if action == "click" else action
        if action == "double":
            btn = "double"
        ok = SystemController.mouse_click(button=btn, action=act)
    elif action == "scroll":
        delta = _api_safe_int(data.get("delta", 0))
        ok = SystemController.mouse_scroll(delta)
    elif action in ("scroll_h", "hscroll"):
        delta = _api_safe_int(data.get("delta", 0))
        ok = SystemController.mouse_scroll_h(delta)
    elif action == "gesture":
        gesture = str(data.get("gesture", ""))
        ok, msg = SystemController.execute_gesture(gesture)
        return {"ok": ok, "msg": msg, "cursor": SystemController.get_cursor_pos()}
    return {"ok": ok, "cursor": SystemController.get_cursor_pos()}


@app.api_route("/input/gesture", methods=["GET", "POST"])
async def api_input_gesture(request: Request):
    data = await _extract_request_data(request)
    gesture = str(data.get("gesture", ""))
    ok, msg = SystemController.execute_gesture(gesture)
    return {"ok": ok, "msg": msg, "cursor": SystemController.get_cursor_pos()}


@app.api_route("/input/type", methods=["GET", "POST"])
async def api_input_type(request: Request):
    data = await _extract_request_data(request)
    text = str(data.get("text", ""))
    ok, msg = SystemController.type_text(text)
    return {"ok": ok, "msg": msg}


@app.api_route("/input/key", methods=["GET", "POST"])
async def api_input_key(request: Request):
    data = await _extract_request_data(request)
    key = str(data.get("key", ""))
    ok, msg = SystemController.press_key(key)
    return {"ok": ok, "msg": msg}


@app.api_route("/input/cursor", methods=["GET", "POST"])
async def api_input_cursor():
    return {"ok": True, "cursor": SystemController.get_cursor_pos()}


@app.get("/browse")
async def api_browse(path: str = ""):
    data = await asyncio.to_thread(SystemController.browse_directory, path)
    data["pc_name"] = PC_NAME
    return data


@app.get("/file")
async def api_get_file(path: str):
    p = Path(path)
    if not p.is_absolute():
        p1 = RECORDINGS_DIR / path
        p2 = DOWNLOADS_DIR / path
        p = p1 if p1.exists() else (p2 if p2.exists() else Path.home() / path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, f"File not found: {path}")
    if p.stat().st_size > 50 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 50MB limit")
    return FileResponse(str(p), filename=p.name)


# ── Local LAN Power & Hardware Routes ────────────────────────────────

@app.get("/tracking")
async def api_tracking():
    info = await asyncio.to_thread(SystemController.get_tracking_info)
    info["pc_name"] = PC_NAME
    return {"ok": True, "tracking": info}


@app.post("/lockdown/enable")
async def api_lockdown_enable(request: Request):
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    silent = bool(data.get("silent", False))
    alarm = bool(data.get("alarm", not silent))
    chat_id = data.get("chat_id")

    global LOCKDOWN_ACTIVE, LOCKDOWN_CONFIG, _lockdown_thread
    LOCKDOWN_ACTIVE = True
    LOCKDOWN_CONFIG = {
        "silent": silent,
        "alarm": alarm,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
    }
    _lockdown_stop_event.clear()

    if alarm:
        SystemController.play_alert_siren("EMERGENCY LOCKDOWN")

    await asyncio.to_thread(SystemController.lock_workstation)
    await asyncio.to_thread(SystemController.turn_off_monitors)

    if not _lockdown_thread or not _lockdown_thread.is_alive():
        _lockdown_thread = threading.Thread(target=_lockdown_guard_worker, args=(chat_id,), daemon=True)
        _lockdown_thread.start()

    return {"ok": True, "active": True, "silent": silent, "alarm": alarm, "pc_name": PC_NAME}


@app.post("/lockdown/disable")
async def api_lockdown_disable():
    global LOCKDOWN_ACTIVE
    LOCKDOWN_ACTIVE = False
    _lockdown_stop_event.set()
    SystemController.stop_alarm()
    await asyncio.to_thread(SystemController.turn_on_monitors)
    return {"ok": True, "active": False, "msg": "Lockdown deactivated. PC returned to normal."}


@app.get("/lockdown/status")
async def api_lockdown_status():
    return {"ok": True, "active": LOCKDOWN_ACTIVE, "config": LOCKDOWN_CONFIG, "pc_name": PC_NAME}


@app.post("/agent/update")
async def api_agent_update(request: Request):
    data = await request.json()
    zip_b64 = data.get("zip_b64")
    files_dict = data.get("files")
    res = await asyncio.to_thread(apply_agent_update, zip_b64=zip_b64, files_dict=files_dict)
    return res


@app.post("/agent/update/rollback")
async def api_agent_rollback(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    backup_id = data.get("backup_id") if isinstance(data, dict) else None
    res = await asyncio.to_thread(rollback_agent_update, backup_id=backup_id)
    return res


@app.get("/agent/version")
async def api_agent_version():
    res = await asyncio.to_thread(get_agent_version_info)
    return res


@app.post("/power/lock")
async def api_power_lock():
    ok = await asyncio.to_thread(SystemController.lock_workstation)
    return {"ok": ok, "success": ok, "msg": "Workstation locked" if ok else "Lock failed"}


@app.post("/power/sleep")
async def api_power_sleep():
    ok = await asyncio.to_thread(SystemController.sleep_pc)
    return {"ok": ok, "success": ok, "msg": "PC entered sleep mode" if ok else "Sleep failed"}


@app.post("/power/shutdown")
async def api_power_shutdown(delay: int = 0):
    ok = await asyncio.to_thread(SystemController.shutdown_pc, delay)
    return {"ok": ok, "success": ok, "msg": f"Shutdown scheduled in {delay}s" if ok else "Shutdown failed"}


@app.post("/power/restart")
async def api_power_restart(delay: int = 5):
    ok = await asyncio.to_thread(SystemController.restart_pc, delay)
    return {"ok": ok, "success": ok, "msg": f"Restart scheduled in {delay}s" if ok else "Restart failed"}


@app.post("/power/cancel-shutdown")
async def api_power_cancel_shutdown():
    ok = await asyncio.to_thread(SystemController.cancel_shutdown)
    return {"ok": ok, "success": ok}


@app.post("/monitor/on")
async def api_monitor_on():
    ok = await asyncio.to_thread(SystemController.turn_on_monitors)
    return {"ok": ok, "success": ok}


@app.post("/monitor/off")
async def api_monitor_off():
    ok = await asyncio.to_thread(SystemController.turn_off_monitors)
    return {"ok": ok, "success": ok}


@app.post("/media/{action}")
async def api_media_action(action: str):
    ok, msg = await asyncio.to_thread(SystemController.press_media_key, action)
    return {"ok": ok, "msg": msg}


@app.get("/clipboard")
async def api_get_clipboard():
    text = await asyncio.to_thread(SystemController.get_clipboard)
    return {"ok": True, "content": text}


@app.post("/clipboard")
async def api_set_clipboard(request: Request):
    data = await request.form()
    text = data.get("text", "")
    ok = await asyncio.to_thread(SystemController.set_clipboard, text)
    return {"ok": ok, "success": ok}


@app.post("/tts")
async def api_tts(request: Request):
    data = await request.form()
    text = data.get("text", "")
    ok = await asyncio.to_thread(SystemController.speak_text, text)
    return {"ok": ok, "success": ok}


@app.get("/alarm/status")
async def api_alarm_status():
    st = await asyncio.to_thread(SystemController.get_alarm_status)
    return {"ok": True, "status": st}


@app.post("/alarm/set")
async def api_alarm_set(request: Request):
    data = await request.form()
    seconds = int(data.get("seconds", 30))
    label = data.get("label", "Timer Alarm")
    res = await asyncio.to_thread(SystemController.set_alarm, seconds, label, _alarm_callback)
    return res if isinstance(res, dict) else {"ok": True, "target_time_str": str(res)}


@app.post("/alarm/stop")
async def api_alarm_stop():
    ok = await asyncio.to_thread(SystemController.stop_alarm)
    return {"ok": ok, "success": ok}


@app.post("/alarm/cancel")
async def api_alarm_cancel():
    ok = await asyncio.to_thread(SystemController.cancel_alarm)
    return {"ok": ok, "success": ok}


@app.post("/alarm/trigger-now")
async def api_alarm_trigger_now(request: Request):
    data = await request.form()
    label = data.get("label", "Instant Alert")
    res = await asyncio.to_thread(SystemController.set_alarm, 1, label, _alarm_callback)
    return {"ok": True, "success": True, "message": "Alarm triggered"}


@app.post("/alarm/parse-time")
async def api_alarm_parse_time(request: Request):
    data = await request.form()
    raw_input = data.get("raw_input", "")
    seconds, label = SystemController.parse_alarm_time(raw_input)
    return {"seconds": seconds, "label": label}


@app.get("/events")
async def api_get_events():
    global _pending_events
    events = list(_pending_events)
    _pending_events.clear()
    return {"events": events}


@app.get("/clean/scan")
async def api_clean_scan():
    candidates = await asyncio.to_thread(SystemController.scan_storage_candidates, RECORDINGS_DIR, DOWNLOADS_DIR)
    return {"ok": True, "candidates": candidates, "pc_name": PC_NAME}


@app.post("/clean/execute")
async def api_clean_execute():
    cnt, freed = await asyncio.to_thread(SystemController.cleanup_old_files, RECORDINGS_DIR, DOWNLOADS_DIR, 0)
    return {"ok": True, "deleted_count": cnt, "freed_bytes": freed, "pc_name": PC_NAME}


# ── Audio & Voice Playback ───────────────────────────────────────────

@app.post("/play-audio")
async def api_play_audio(file: UploadFile = File(...)):
    filename = Path(file.filename or f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg").name
    dest = DOWNLOADS_DIR / filename
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    ok, msg = await asyncio.to_thread(SystemController.play_audio_file, dest)
    return {"success": ok, "ok": ok, "message": msg, "path": str(dest)}


@app.post("/upload")
async def api_upload(file: UploadFile = File(...)):
    filename = Path(file.filename or f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin").name
    dest = DOWNLOADS_DIR / filename
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    auto_played = False
    if dest.suffix.lower() in (".mp3", ".wav", ".ogg", ".aac", ".m4a"):
        try:
            ok, _ = await asyncio.to_thread(SystemController.play_audio_file, dest)
            auto_played = ok
        except Exception:
            pass

    return {"success": True, "ok": True, "path": str(dest), "auto_played": auto_played}


# ── System Processes & Terminal ──────────────────────────────────────

@app.get("/processes")
async def api_processes(count: int = 25):
    procs = await asyncio.to_thread(SystemController.list_top_processes, count)
    return {"ok": True, "processes": procs}


@app.post("/kill")
async def api_kill(request: Request):
    data = await request.form()
    target = data.get("target", "")
    ok, msg = await asyncio.to_thread(SystemController.kill_process, target)
    return {"ok": ok, "success": ok, "message": msg}


@app.post("/cmd")
async def api_cmd(request: Request):
    data = await request.form()
    command = data.get("command", "")
    rc, output = await asyncio.to_thread(SystemController.run_cmd, command)
    return {"ok": True, "output": output, "returncode": rc}


@app.post("/open")
async def api_open(request: Request):
    data = await request.form()
    target = data.get("target", "")
    ok = await asyncio.to_thread(SystemController.open_target, target)
    return {"ok": ok, "success": ok}


# ── Media Recording ──────────────────────────────────────────────────

@app.post("/record/screen")
async def api_record_screen(duration: int = 10):
    duration = min(max(duration, 3), 60)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"screen_{ts}_{duration}s.mp4"
    with hardware_lock:
        ok, msg = await asyncio.to_thread(SystemController.record_screen_video, path, duration)
    if ok and path.exists():
        return FileResponse(str(path), media_type="video/mp4", filename=path.name)
    raise HTTPException(500, f"Screen recording failed: {msg}")


@app.post("/record/webcam")
async def api_record_webcam(duration: int = 10):
    duration = min(max(duration, 3), 60)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"webcam_{ts}_{duration}s.mp4"
    with hardware_lock:
        ok, msg = await asyncio.to_thread(SystemController.record_webcam_video, path, duration)
    if ok and path.exists():
        return FileResponse(str(path), media_type="video/mp4", filename=path.name)
    raise HTTPException(500, f"Webcam recording failed: {msg}")




# ═══════════════════════════════════════════════════════════════════════
#   MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════

def ensure_single_agent_instance():
    """Terminate any stale older instances of this agent to free port 9010."""
    try:
        import psutil
        cur_pid = os.getpid()
        cur_dir = str(BASE_DIR).lower()
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                if p.pid == cur_pid:
                    continue
                cmdline = p.info.get('cmdline') or []
                cmd_str = " ".join(cmdline).lower()
                p_name = p.info.get('name', '').lower()
                exe_path = (p.info.get('exe') or '').lower()

                is_in_our_dir = (cur_dir in exe_path) or (cur_dir in cmd_str)
                is_our_agent = is_in_our_dir and (
                    "pc-sentinel-agent" in p_name
                    or ("agent.py" in cmd_str and "bot.py" not in cmd_str)
                )
                if is_our_agent:
                    logger.warning(f"Terminating older conflicting agent process (PID {p.pid})...")
                    p.terminate()
                    p.wait(timeout=2.0)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"ensure_single_agent_instance error: {e}")


def send_startup_announcement():
    """Notify Telegram chat that this PC has booted and is online, retrying until network is up."""
    global TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_IDS

    # Ensure tokens are loaded even if agent.env was generated with delays
    if not TELEGRAM_BOT_TOKEN or not AUTHORIZED_USER_IDS:
        for env_file in [BASE_DIR / "agent.env", BASE_DIR / ".env", BASE_DIR / "deploy_config.env"]:
            if env_file.exists():
                load_dotenv(env_file)
        TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or TELEGRAM_BOT_TOKEN
        AUTHORIZED_USER_IDS = os.getenv("AUTHORIZED_USER_IDS", "").strip() or AUTHORIZED_USER_IDS

    if not TELEGRAM_BOT_TOKEN or not AUTHORIZED_USER_IDS:
        logger.warning("Startup announcement skipped: TELEGRAM_BOT_TOKEN or AUTHORIZED_USER_IDS missing.")
        return

    net = get_network_info()
    text = (
        f"🟢 <b>PC Sentinel Agent Online!</b>\n\n"
        f"🖥️ <b>PC Name:</b> <code>{PC_NAME}</code>\n"
        f"🌐 <b>Network:</b> <code>{net.get('type', 'Unknown')}</code>\n"
        f"📡 <b>Cloud Relay:</b> <code>{MQTT_BROKER}:{MQTT_PORT}</code>\n"
        f"🕒 <b>Boot Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
        f"✨ <i>Send /pcs or /start to control this PC.</i>"
    )

    max_retries = 30  # Retry for up to 5 minutes (30 * 10s)
    for attempt in range(1, max_retries + 1):
        delivered = False
        for uid in AUTHORIZED_USER_IDS.split(","):
            uid = uid.strip()
            if not uid.isdigit():
                continue
            try:
                r = httpx.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": int(uid), "text": text, "parse_mode": "HTML"},
                    timeout=12.0,
                )
                if r.status_code == 200:
                    logger.info(f"Direct startup announcement sent to Telegram user {uid} (attempt {attempt})")
                    delivered = True
                else:
                    logger.debug(f"Telegram API returned status {r.status_code} for user {uid}")
            except Exception as e:
                logger.debug(f"Attempt {attempt}/{max_retries} could not send startup announcement to {uid}: {e}")

        if delivered:
            return
        time.sleep(10)


def main():
    global relay

    try:
        ensure_single_agent_instance()

        logger.info("=" * 55)
        logger.info(f"   PC REMOTE SENTINEL AGENT — {PC_NAME}")
        logger.info("=" * 55)
        net = get_network_info()
        logger.info(f"Local IP: {net['ip']} | Connection: {net['type']}")
        logger.info(f"Relay Broker: {MQTT_BROKER}:{MQTT_PORT} (TLS={MQTT_USE_TLS})")
        logger.info(f"Local LAN Port: {AGENT_PORT}")

        # 1. Start Cloud Relay (MQTT over TLS)
        relay = FleetAgentRelay(
            pc_name=PC_NAME,
            secret=FLEET_SECRET,
            broker=MQTT_BROKER,
            port=MQTT_PORT,
            use_tls=MQTT_USE_TLS,
            command_handler=handle_relay_command,
        )
        relay.start()

        # 2. Dispatch immediate startup Telegram notification
        threading.Thread(target=send_startup_announcement, daemon=True).start()

        # 3. Run local FastAPI server (keeps main thread alive)
        try:
            uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT, log_level="warning")
        except Exception as e:
            logger.error(f"Uvicorn server error: {e}")
        finally:
            if relay:
                relay.stop()
    except Exception as e:
        logger.exception(f"Fatal error running PC Sentinel Agent: {e}")
        time.sleep(2)
        sys.exit(1)


if __name__ == "__main__":
    main()
