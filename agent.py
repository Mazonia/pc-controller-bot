"""
PC Remote Sentinel — Agent
Dual-mode agent that runs on each monitored PC:
1. Connects to the Fleet Cloud Relay (MQTT over TLS) — works seamlessly across
   Wi-Fi, Ethernet, Mobile Hotspots, 4G/5G modems, and CGNAT.
2. Exposes a local FastAPI HTTP server on port 9010 for direct LAN access.
3. Uploads screenshots/videos directly to Telegram API for zero broker bandwidth.
"""

import ctypes

try:
    ctypes.windll.kernel32.SetConsoleTitleW('PC-Sentinel-Agent')
except Exception:
    pass

import os
import sys
import io
import hmac
import json
import time
import socket
import asyncio
import threading
from pathlib import Path
from datetime import datetime
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

PC_NAME = os.getenv("PC_NAME", "").strip() or os.environ.get("COMPUTERNAME", "Unknown-PC")
AGENT_PORT = int(os.getenv("AGENT_PORT", "9010"))
AGENT_SECRET = os.getenv("AGENT_SECRET", "").strip() or os.getenv("FLEET_SECRET", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
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


# ═══════════════════════════════════════════════════════════════════════
#   DIRECT TELEGRAM UPLOAD HELPERS
# ═══════════════════════════════════════════════════════════════════════

def send_photo_to_telegram(chat_id: int, photo_path: Path, caption: str = "") -> bool:
    """Upload photo directly to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Cannot upload to Telegram: TELEGRAM_BOT_TOKEN not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            r = httpx.post(url, data={"chat_id": chat_id, "caption": caption}, files={"photo": f}, timeout=25.0)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram photo upload error: {e}")
        return False


def send_video_to_telegram(chat_id: int, video_path: Path, caption: str = "") -> bool:
    """Upload video directly to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            r = httpx.post(url, data={"chat_id": chat_id, "caption": caption}, files={"video": f}, timeout=60.0)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram video upload error: {e}")
        return False


def send_document_to_telegram(chat_id: int, file_path: Path, caption: str = "") -> bool:
    """Upload document directly to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            r = httpx.post(url, data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=60.0)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram doc upload error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#   CLOUD RELAY COMMAND DISPATCHER
# ═══════════════════════════════════════════════════════════════════════

def handle_relay_command(data: dict) -> dict:
    """
    Handle commands received via MQTT Cloud Relay.
    Works over mobile hotspots, cellular modems, or local network.
    """
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

    # 2. SCREENSHOT
    elif cmd == "screenshot":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RECORDINGS_DIR / f"shot_{ts}.png"
        with hardware_lock:
            ok, msg = SystemController.take_screenshot(path)
        if ok and path.exists():
            if chat_id:
                caption = f"📸 Screenshot from <b>{PC_NAME}</b>\n⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                send_photo_to_telegram(chat_id, path, caption)
                return {"ok": True, "direct_upload": True, "msg": "Screenshot uploaded to chat."}
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
                send_photo_to_telegram(chat_id, path, caption)
                return {"ok": True, "direct_upload": True, "msg": "Webcam photo uploaded to chat."}
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
                send_video_to_telegram(chat_id, path, caption)
                return {"ok": True, "direct_upload": True, "msg": "Screen video uploaded to chat."}
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
                send_video_to_telegram(chat_id, path, caption)
                return {"ok": True, "direct_upload": True, "msg": "Webcam video uploaded to chat."}
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

    # 7. POWER & LOCK
    elif cmd == "lock":
        ok, msg = SystemController.lock_workstation()
        return {"ok": ok, "msg": msg}

    elif cmd == "reboot":
        delay = int(params.get("delay", 5))
        ok, msg = SystemController.reboot(delay_sec=delay)
        return {"ok": ok, "msg": msg}

    elif cmd == "shutdown":
        delay = int(params.get("delay", 5))
        ok, msg = SystemController.shutdown(delay_sec=delay)
        return {"ok": ok, "msg": msg}

    elif cmd == "cancel_shutdown":
        ok, msg = SystemController.cancel_shutdown()
        return {"ok": ok, "msg": msg}

    # 8. PROCESSES & TERMINAL
    elif cmd == "processes":
        procs = SystemController.get_running_processes(limit=int(params.get("limit", 25)))
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
        output = SystemController.execute_command(command_str)
        return {"ok": True, "output": output}

    # 9. VOLUME & MEDIA
    elif cmd == "volume_set":
        level = int(params.get("level", 50))
        ok, msg = SystemController.set_volume(level)
        return {"ok": ok, "msg": msg}

    elif cmd == "volume_mute":
        mute = bool(params.get("mute", True))
        ok, msg = SystemController.mute_volume(mute)
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
        ok, msg = SystemController.set_clipboard(text)
        return {"ok": ok, "msg": msg}

    # 11. ALARM
    elif cmd == "alarm_start":
        duration = int(params.get("duration", 30))
        label = params.get("label", "Manual Telegram Alarm")
        ok, msg = SystemController.trigger_alarm(duration_sec=duration, label=label, callback=_alarm_callback)
        return {"ok": ok, "msg": msg}

    elif cmd == "alarm_stop":
        ok, msg = SystemController.stop_alarm()
        return {"ok": ok, "msg": msg}

    # 12. TTS
    elif cmd == "tts":
        text = params.get("text", "")
        if not text:
            return {"ok": False, "error": "No text provided for TTS."}
        ok, msg = SystemController.speak_text(text)
        return {"ok": ok, "msg": msg}

    # 13. FILE OPERATIONS
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
        filename = params.get("name", "")
        p1 = RECORDINGS_DIR / filename
        p2 = DOWNLOADS_DIR / filename
        target_file = p1 if p1.exists() else (p2 if p2.exists() else None)
        if target_file and chat_id:
            caption = f"📄 File from <b>{PC_NAME}</b>: <code>{target_file.name}</code>"
            send_document_to_telegram(chat_id, target_file, caption)
            return {"ok": True, "direct_upload": True, "msg": "File uploaded to chat."}
        return {"ok": False, "error": f"File '{filename}' not found on PC."}

    return {"ok": False, "error": f"Unknown command: '{cmd}'"}


def _alarm_callback(label: str, time_str: str):
    """Callback when alarm fires on this PC — pushes alert to Central Bot."""
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


# ═══════════════════════════════════════════════════════════════════════
#   MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════

def main():
    global relay

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
        secret=AGENT_SECRET,
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        use_tls=MQTT_USE_TLS,
        command_handler=handle_relay_command,
    )
    relay.start()

    # 2. Run local FastAPI server (keeps main thread alive)
    try:
        uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT, log_level="warning")
    except Exception as e:
        logger.error(f"Uvicorn server error: {e}")
    finally:
        if relay:
            relay.stop()


if __name__ == "__main__":
    main()
