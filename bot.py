"""
PC Remote Sentinel — Fleet Commander Bot
Central Telegram bot that controls multiple Windows PCs through their remote agents.
"""

import ctypes

try:
    ctypes.windll.kernel32.SetConsoleTitleW('PC-Remote-Sentinel')
except Exception:
    pass

import os
import sys
import io
import time
import html
import json
import math
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import urllib.parse

import httpx
from loguru import logger

import telegram.error
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    BotCommand,
    BotCommandScopeChat,
    InputMediaPhoto,
)
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from fleet_relay import FleetCommanderRelay
from manager_auth import manager_auth, DEFAULT_ROLE_PERMISSIONS, PERMISSION_KEYS


# ═══════════════════════════════════════════════════════════════════════
#   FLEET MANAGEMENT & CLOUD RELAY
# ═══════════════════════════════════════════════════════════════════════

FLEET_FILE = config.BASE_DIR / "fleet.json"
commander_relay: Optional[FleetCommanderRelay] = None

# Core Agent files distributed during Over-The-Air (OTA) updates
CORE_AGENT_FILES = [
    "agent.py",
    "fleet_relay.py",
    "system_controller.py",
    "screen_caster.py",
    "diagnose_agent.py",
    "requirements_agent.txt",
    "start_agent.bat",
    "start_agent_hidden.vbs",
]


def create_agent_update_bundle() -> Tuple[bytes, List[str]]:
    """Package current workspace agent scripts into an in-memory zip bundle with manifest checksums."""
    import zipfile
    import hashlib
    import json
    buf = io.BytesIO()
    packaged = []
    file_hashes = {}

    for fname in CORE_AGENT_FILES:
        fpath = config.BASE_DIR / fname
        if fpath.exists():
            content = fpath.read_bytes()
            file_hashes[fname] = hashlib.sha256(content).hexdigest()
            packaged.append(fname)

    manifest = {
        "version": f"{int(time.time())}_{hashlib.sha256(''.join(file_hashes.values()).encode()).hexdigest()[:10]}",
        "timestamp": int(time.time()),
        "files": file_hashes,
        "count": len(packaged),
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for fname in packaged:
            fpath = config.BASE_DIR / fname
            zf.write(fpath, arcname=fname)

    return buf.getvalue(), packaged


def ensure_host_pc_registered(fleet: dict) -> bool:
    """Ensure Host PC is always registered in fleet if running on Windows."""
    if sys.platform != "win32":
        return False
    host_name = os.environ.get("COMPUTERNAME", "Host-PC")
    pcs = fleet.get("pcs", [])
    for pc in pcs:
        if pc.get("name") == host_name:
            pc["is_host"] = True
            return False
    pcs.insert(0, {
        "name": host_name,
        "label": f"🖥️ Host ({host_name})",
        "ip": "127.0.0.1",
        "port": int(os.getenv("AGENT_PORT", "9010")),
        "is_host": True,
    })
    fleet["pcs"] = pcs
    save_fleet(fleet)
    return True


def ensure_local_agent_running():
    """If running on Windows and local agent is not running or outdated on port 9010, launch it in background."""
    if sys.platform != "win32":
        return
    import socket
    import subprocess
    import urllib.request
    import urllib.error
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        is_open = sock.connect_ex(("127.0.0.1", 9010)) == 0
        sock.close()
        if is_open:
            # Check if running agent is up-to-date (responds to /input/cursor)
            is_outdated = False
            try:
                req = urllib.request.Request("http://127.0.0.1:9010/input/cursor")
                if config.AGENT_SECRET:
                    req.add_header("X-Agent-Secret", config.AGENT_SECRET)
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        logger.info("Local PC Agent is running and up-to-date on port 9010.")
                        return
            except urllib.error.HTTPError as he:
                if he.code == 404:
                    logger.warning("Local PC Agent on port 9010 is outdated (missing /input/cursor). Restarting...")
                    is_outdated = True
            except Exception:
                # If non-HTTP error (e.g. secret mismatch, timeout), keep existing process
                return

            if is_outdated:
                # Terminate stale agent process listening on port 9010
                try:
                    netstat_out = subprocess.check_output("netstat -ano", shell=True).decode()
                    for line in netstat_out.splitlines():
                        if ":9010" in line and "LISTENING" in line:
                            parts = line.strip().split()
                            pid = int(parts[-1])
                            if pid > 0 and pid != os.getpid():
                                subprocess.run(f"taskkill /f /pid {pid}", shell=True, capture_output=True)
                    time.sleep(1.0)
                except Exception as err:
                    logger.debug(f"Failed to kill outdated agent: {err}")

        agent_py = config.BASE_DIR / "agent.py"
        if not agent_py.exists():
            return

        agent_exe = config.BASE_DIR / "pc-sentinel-agent.exe"
        exe = str(agent_exe) if agent_exe.exists() else sys.executable
        extra_kwargs = {}
        if sys.platform == "win32":
            extra_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | 0x00000008
        logger.info(f"Auto-launching local PC Agent silently ({Path(exe).name})...")
        subprocess.Popen(
            [exe, str(agent_py)],
            cwd=str(config.BASE_DIR),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **extra_kwargs
        )
    except Exception as e:
        logger.error(f"Could not auto-start local agent: {e}")


def load_fleet() -> dict:
    """Load fleet configuration from fleet.json."""
    fleet = {"secret": os.getenv("FLEET_SECRET", "").strip(), "pcs": []}
    if FLEET_FILE.exists():
        try:
            fleet = json.loads(FLEET_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load fleet.json: {e}")
    ensure_host_pc_registered(fleet)
    return fleet


def save_fleet(fleet: dict):
    """Save fleet configuration."""
    try:
        FLEET_FILE.write_text(json.dumps(fleet, indent=4), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not persist fleet.json: {e}")


def get_fleet_secret(fleet: Optional[dict] = None) -> str:
    """Get the active fleet encryption secret from fleet.json or environment."""
    if fleet is None:
        fleet = load_fleet()
    return (fleet.get("secret", "") or "").strip() or os.getenv("FLEET_SECRET", "").strip() or "sentinel-fleet-secret-2026"


class AgentClient:
    """
    Hybrid client for communicating with a PC agent.
    Routes commands through Cloud Relay (MQTT over TLS) if PC is on Mobile Data / CGNAT,
    or directly via local HTTP if on local LAN.
    """

    def __init__(self, pc_info: dict, secret: str):
        self.name = pc_info["name"]
        self.label = pc_info.get("label", self.name)
        self.ip = pc_info.get("ip", "127.0.0.1")
        self.port = pc_info.get("port", 9010)
        self.base_url = f"http://{self.ip}:{self.port}"
        self.secret = secret

    @property
    def is_local(self) -> bool:
        """True if target PC is local host (127.0.0.1 or localhost) - bypasses internet/cloud entirely."""
        return self.ip in ("127.0.0.1", "localhost", "::1")

    @property
    def is_local(self) -> bool:
        """Check if PC agent is running locally on the same host machine."""
        return self.ip in ("127.0.0.1", "localhost", "::1")

    def is_relay_online(self) -> bool:
        """Check if PC is connected to the Cloud Relay."""
        if commander_relay and commander_relay.is_connected:
            pcs = commander_relay.get_pc_list()
            return self.name in pcs and pcs[self.name].get("status") == "online"
        return False

    def should_use_relay(self) -> bool:
        """
        Only route through Cloud Relay (MQTT) if the PC is truly remote.
        For local host PC (127.0.0.1), always use 0-latency direct local HTTP first.
        """
        if self.is_local:
            return False
        return self.is_relay_online()

    def _headers(self) -> dict:
        return {"X-Agent-Secret": self.secret}

    async def _get(self, path: str, timeout: float = 15.0, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(f"{self.base_url}{path}", headers=self._headers(), **kwargs)

    async def _post(self, path: str, timeout: float = 30.0, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(f"{self.base_url}{path}", headers=self._headers(), **kwargs)

    async def health(self) -> Optional[dict]:
        # For local PC, query direct loopback in milliseconds
        if self.is_local:
            try:
                r = await self._get("/health", timeout=2.0)
                r.raise_for_status()
                return r.json()
            except Exception:
                pass
        if self.should_use_relay():
            info = commander_relay.get_pc_list().get(self.name, {})
            return {"status": "online", "network": info.get("network", "Remote")}
        try:
            r = await self._get("/health", timeout=3.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def status(self) -> dict:
        # Prioritize local HTTP if on host PC for instant diagnostics without internet
        if self.is_local:
            try:
                r = await self._get("/status", timeout=5.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local status HTTP failed: {e}. Trying cloud relay...")
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "status", timeout=30.0)
            if res.get("ok") and "stats" in res:
                return res["stats"]
            elif "error" in res:
                raise Exception(res["error"])
        r = await self._get("/status", timeout=15.0)
        r.raise_for_status()
        return r.json()

    async def screenshot(self, chat_id: Optional[int] = None) -> Any:
        # If local host PC, capture screenshot directly via fast local loopback
        if self.is_local:
            try:
                r = await self._get("/screenshot", timeout=20.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.debug(f"Local screenshot HTTP failed: {e}. Trying relay...")
        if self.should_use_relay() and chat_id:
            res = await commander_relay.send_command(self.name, "screenshot", {"chat_id": chat_id}, timeout=50.0)
            if res.get("ok"):
                return {"direct_upload": True}
            raise Exception(res.get("error", "Remote screenshot failed"))
        r = await self._get("/screenshot", timeout=30.0)
        r.raise_for_status()
        return r.content

    async def webcam(self, chat_id: Optional[int] = None) -> Any:
        if self.is_local:
            try:
                r = await self._get("/webcam", timeout=20.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.debug(f"Local webcam HTTP failed: {e}. Trying relay...")
        if self.should_use_relay() and chat_id:
            res = await commander_relay.send_command(self.name, "webcam", {"chat_id": chat_id}, timeout=50.0)
            if res.get("ok"):
                return {"direct_upload": True}
            raise Exception(res.get("error", "Remote webcam failed"))
        r = await self._get("/webcam", timeout=30.0)
        r.raise_for_status()
        return r.content

    async def record_screen(self, duration: int, chat_id: Optional[int] = None) -> Any:
        if self.is_local:
            try:
                r = await self._post(f"/record/screen?duration={duration}", timeout=duration + 35.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.debug(f"Local screen record HTTP failed: {e}. Trying relay...")
        if self.should_use_relay() and chat_id:
            res = await commander_relay.send_command(self.name, "record_screen", {"duration": duration, "chat_id": chat_id}, timeout=duration + 60.0)
            if res.get("ok"):
                return {"direct_upload": True}
            raise Exception(res.get("error", "Remote screen recording failed"))
        r = await self._post(f"/record/screen?duration={duration}", timeout=duration + 45.0)
        r.raise_for_status()
        return r.content

    async def record_webcam(self, duration: int, chat_id: Optional[int] = None) -> Any:
        if self.is_local:
            try:
                r = await self._post(f"/record/webcam?duration={duration}", timeout=duration + 35.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.debug(f"Local webcam record HTTP failed: {e}. Trying relay...")
        if self.should_use_relay() and chat_id:
            res = await commander_relay.send_command(self.name, "record_webcam", {"duration": duration, "chat_id": chat_id}, timeout=duration + 60.0)
            if res.get("ok"):
                return {"direct_upload": True}
            raise Exception(res.get("error", "Remote webcam recording failed"))
        r = await self._post(f"/record/webcam?duration={duration}", timeout=duration + 45.0)
        r.raise_for_status()
        return r.content

    async def cast_web_start(self) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cast_start", timeout=25.0)
            if res.get("ok"):
                return res
        r = await self._post("/cast/web/start", timeout=30.0)
        r.raise_for_status()
        return r.json()

    async def cast_web_stop(self) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cast_stop", timeout=10.0)
            if res.get("ok"):
                return res
        r = await self._post("/cast/web/stop")
        r.raise_for_status()
        return r.json()

    async def cast_status(self) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cast_status", timeout=10.0)
            if res.get("ok"):
                return res.get("status", {})
        try:
            r = await self._get("/cast/status", timeout=5.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {"is_web_streaming": False, "is_rtmp_streaming": False}

    async def cast_frame(self, quality: int = 60, max_width: int = 960) -> bytes:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cast_frame", {"quality": quality, "max_width": max_width}, timeout=10.0)
            if res.get("ok") and "frame_b64" in res:
                import base64
                return base64.b64decode(res["frame_b64"])
        r = await self._get(f"/cast/frame?quality={quality}&max_width={max_width}", timeout=10.0)
        r.raise_for_status()
        return r.content

    async def switch_desktop(self, action: str = "next") -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "switch_desktop", {"action": action}, timeout=10.0)
        try:
            r = await self._post(f"/desktop/switch?action={action}", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"Desktop switch failed: {e}", "error": str(e)}

    async def get_open_windows(self, limit: int = 25) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "windows_list", {"limit": limit}, timeout=10.0)
        try:
            r = await self._get(f"/windows?limit={limit}", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "windows": [], "error": str(e)}

    async def focus_window(self, target: Any) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "window_focus", {"target": str(target)}, timeout=10.0)
        try:
            r = await self._post(f"/windows/focus?target={urllib.parse.quote(str(target))}", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"Focus failed: {e}", "error": str(e)}

    async def cycle_window(self, direction: str = "next") -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "window_cycle", {"direction": direction}, timeout=10.0)
        try:
            r = await self._post(f"/windows/cycle?direction={direction}", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"Cycle window failed: {e}", "error": str(e)}

    async def mouse_input(self, action: str = "move", **kwargs) -> dict:
        params = {"action": action, **kwargs}
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "mouse_input", params, timeout=10.0)
        try:
            r = await self._post("/input/mouse", json=params, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def type_text(self, text: str) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "type_text", {"text": text}, timeout=10.0)
        try:
            r = await self._post("/input/type", json={"text": text}, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": str(e), "error": str(e)}

    async def press_key(self, key: str) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "press_key", {"key": key}, timeout=10.0)
        try:
            r = await self._post("/input/key", json={"key": key}, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": str(e), "error": str(e)}

    async def get_cursor(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "get_cursor", timeout=10.0)
        try:
            r = await self._get("/input/cursor", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def cast_rtmp_start(self, url: str) -> dict:
        r = await self._post("/cast/rtmp/start", data={"url": url})
        r.raise_for_status()
        return r.json()

    async def cast_rtmp_stop(self) -> dict:
        r = await self._post("/cast/rtmp/stop")
        r.raise_for_status()
        return r.json()

    async def processes(self, count: int = 15) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "processes", {"limit": count}, timeout=12.0)
            if res.get("ok"):
                return {"processes": res.get("processes", [])}
        r = await self._get(f"/processes?count={count}")
        r.raise_for_status()
        return r.json()

    async def kill_process(self, target: str) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "kill_process", {"target": target}, timeout=10.0)
            return {"success": res.get("ok", False), "message": res.get("msg", "")}
        r = await self._post("/kill", data={"target": target})
        r.raise_for_status()
        return r.json()

    async def run_cmd(self, command: str) -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cmd", {"command": command}, timeout=40.0)
            return {"output": res.get("output", "")}
        r = await self._post("/cmd", data={"command": command}, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def open_target(self, target: str) -> dict:
        r = await self._post("/open", data={"target": target})
        r.raise_for_status()
        return r.json()

    async def browse_directory(self, path: str = "") -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "file_browse", {"path": path}, timeout=25.0)
            if res.get("ok") or "error" in res:
                return res
        try:
            r = await self._get(f"/browse?path={urllib.parse.quote(path)}", timeout=25.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e), "items": [], "current_path": path}

    async def get_file(self, path: str, chat_id: Optional[int] = None) -> Tuple[bytes, str]:
        if self.should_use_relay() and chat_id:
            res = await commander_relay.send_command(self.name, "file_download", {"path": path, "chat_id": chat_id}, timeout=60.0)
            if res.get("ok"):
                return b"", "direct_upload"
            else:
                raise Exception(res.get("error", "File download failed over relay"))
        r = await self._get(f"/file?path={urllib.parse.quote(path)}", timeout=60.0)
        r.raise_for_status()
        filename = Path(path).name or "file"
        cd = r.headers.get("content-disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"')
        return r.content, filename

    async def upload_file(self, filename: str, content: bytes) -> dict:
        import base64
        if self.is_local:
            try:
                files = {"file": (filename, content)}
                r = await self._post("/upload", files=files, timeout=60.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local upload_file HTTP failed: {e}. Trying relay...")

        if self.should_use_relay():
            if len(content) > 3 * 1024 * 1024:
                raise Exception("File too large for cloud relay (>3MB). Send smaller files or use local network.")
            b64 = base64.b64encode(content).decode("ascii")
            res = await commander_relay.send_command(self.name, "file_upload", {"filename": filename, "data_b64": b64}, timeout=30.0)
            if res.get("ok"):
                return {"success": True, "path": res.get("path", filename), "auto_played": res.get("auto_played", False)}
            raise Exception(res.get("error", "Remote upload failed"))

        files = {"file": (filename, content)}
        r = await self._post("/upload", files=files, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def get_clipboard(self) -> str:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "clipboard_get", timeout=10.0)
            return res.get("text", "")
        r = await self._get("/clipboard")
        r.raise_for_status()
        return r.json().get("content", "")

    async def set_clipboard(self, text: str) -> bool:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "clipboard_set", {"text": text}, timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/clipboard", data={"text": text})
        r.raise_for_status()
        return r.json().get("success", False)

    async def speak(self, text: str) -> bool:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "tts", {"text": text}, timeout=15.0)
            return res.get("ok", False)
        r = await self._post("/tts", data={"text": text})
        r.raise_for_status()
        return r.json().get("success", False)

    async def play_audio(self, filename: str, content: bytes) -> dict:
        import base64
        if self.is_local:
            try:
                files = {"file": (filename, content)}
                r = await self._post("/play-audio", files=files, timeout=60.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local play_audio HTTP failed: {e}. Trying relay...")

        if self.should_use_relay():
            if len(content) > 3 * 1024 * 1024:
                return {"success": False, "ok": False, "message": "Audio file too large for cloud relay (>3MB)."}
            b64 = base64.b64encode(content).decode("ascii")
            res = await commander_relay.send_command(self.name, "play_audio", {"filename": filename, "data_b64": b64}, timeout=30.0)
            return {"success": res.get("ok", False), "ok": res.get("ok", False), "message": res.get("msg", res.get("error", ""))}

        files = {"file": (filename, content)}
        r = await self._post("/play-audio", files=files, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def power_sleep(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "sleep", timeout=10.0)
        r = await self._post("/power/sleep")
        r.raise_for_status()
        return r.json()

    async def power_lock(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "lock", timeout=10.0)
        r = await self._post("/power/lock")
        r.raise_for_status()
        return r.json()

    async def power_shutdown(self, delay: int = 0) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "shutdown", {"delay": delay}, timeout=10.0)
        r = await self._post(f"/power/shutdown?delay={delay}")
        r.raise_for_status()
        return r.json()

    async def power_restart(self, delay: int = 5) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "restart", {"delay": delay}, timeout=10.0)
        r = await self._post(f"/power/restart?delay={delay}")
        r.raise_for_status()
        return r.json()

    async def power_cancel_shutdown(self) -> bool:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "cancel_shutdown", timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/power/cancel-shutdown")
        return r.json().get("success", False)

    async def monitor_on(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "monitor_on", timeout=10.0)
        r = await self._post("/monitor/on")
        r.raise_for_status()
        return r.json()

    async def monitor_off(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "monitor_off", timeout=10.0)
        r = await self._post("/monitor/off")
        r.raise_for_status()
        return r.json()

    async def media_control(self, action: str):
        if self.should_use_relay():
            await commander_relay.send_command(self.name, "media_key", {"action": action}, timeout=10.0)
            return
        await self._post(f"/media/{action}")

    async def alarm_status(self) -> dict:
        r = await self._get("/alarm/status")
        r.raise_for_status()
        return r.json()

    async def alarm_set(self, seconds: int, label: str) -> dict:
        r = await self._post("/alarm/set", data={"seconds": seconds, "label": label})
        r.raise_for_status()
        return r.json()

    async def alarm_stop(self) -> bool:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "alarm_stop", timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/alarm/stop")
        return r.json().get("success", False)

    async def alarm_cancel(self) -> bool:
        r = await self._post("/alarm/cancel")
        return r.json().get("success", False)

    async def alarm_trigger_now(self, label: str = "Instant Alert") -> dict:
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "alarm_start", {"duration": 30, "label": label}, timeout=10.0)
            return {"success": res.get("ok", False), "message": res.get("msg", "")}
        r = await self._post("/alarm/trigger-now", data={"label": label})
        return r.json()

    async def alarm_parse_time(self, raw_input: str) -> dict:
        r = await self._post("/alarm/parse-time", data={"raw_input": raw_input})
        return r.json()

    async def clean_scan(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "clean_scan", timeout=25.0)
        r = await self._get("/clean/scan")
        return r.json()

    async def clean_execute(self) -> dict:
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "clean_execute", timeout=25.0)
        r = await self._post("/clean/execute")
        return r.json()

    async def get_events(self) -> list:
        try:
            r = await self._get("/events", timeout=3.0)
            r.raise_for_status()
            return r.json().get("events", [])
        except Exception:
            return []

    async def get_tracking(self) -> dict:
        if self.is_local:
            try:
                r = await self._get("/tracking", timeout=10.0)
                r.raise_for_status()
                return r.json().get("tracking", {})
            except Exception as e:
                logger.debug(f"Local tracking HTTP failed: {e}. Trying relay...")
        if self.should_use_relay():
            res = await commander_relay.send_command(self.name, "tracking", timeout=20.0)
            if res.get("ok"):
                return res.get("tracking", {})
            raise Exception(res.get("error", "Failed to retrieve tracking over relay"))
        r = await self._get("/tracking", timeout=20.0)
        r.raise_for_status()
        return r.json().get("tracking", {})

    async def lockdown_enable(self, silent: bool = False, alarm: bool = True, chat_id: Optional[int] = None) -> dict:
        payload = {"silent": silent, "alarm": alarm, "chat_id": chat_id}
        if self.is_local:
            try:
                r = await self._post("/lockdown/enable", json=payload, timeout=15.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local lockdown_enable HTTP failed: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "lockdown_enable", payload, timeout=25.0)
        r = await self._post("/lockdown/enable", json=payload, timeout=25.0)
        r.raise_for_status()
        return r.json()

    async def lockdown_disable(self) -> dict:
        if self.is_local:
            try:
                r = await self._post("/lockdown/disable", timeout=15.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local lockdown_disable HTTP failed: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "lockdown_disable", timeout=15.0)
        r = await self._post("/lockdown/disable", timeout=15.0)
        r.raise_for_status()
        return r.json()

    async def lockdown_status(self) -> dict:
        if self.is_local:
            try:
                r = await self._get("/lockdown/status", timeout=10.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local lockdown_status HTTP failed: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "lockdown_status", timeout=10.0)
        r = await self._get("/lockdown/status", timeout=10.0)
        r.raise_for_status()
        return r.json()

    async def push_agent_update(self, zip_b64: Optional[str] = None, files_dict: Optional[dict] = None) -> dict:
        payload = {"zip_b64": zip_b64, "files": files_dict}
        if self.is_local:
            try:
                r = await self._post("/agent/update", json=payload, timeout=45.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local agent update failed: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "agent_update", payload, timeout=45.0)
        r = await self._post("/agent/update", json=payload, timeout=45.0)
        r.raise_for_status()
        return r.json()

    async def rollback_agent_update(self, backup_id: Optional[str] = None) -> dict:
        payload = {"backup_id": backup_id}
        if self.is_local:
            try:
                r = await self._post("/agent/update/rollback", json=payload, timeout=25.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local agent rollback notice: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "agent_rollback", payload, timeout=25.0)
        r = await self._post("/agent/update/rollback", json=payload, timeout=25.0)
        r.raise_for_status()
        return r.json()

    async def get_agent_version_info(self) -> dict:
        if self.is_local:
            try:
                r = await self._get("/agent/version", timeout=12.0)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.debug(f"Local agent version notice: {e}. Trying relay...")
        if self.should_use_relay():
            return await commander_relay.send_command(self.name, "agent_version", {}, timeout=15.0)
        r = await self._get("/agent/version", timeout=12.0)
        r.raise_for_status()
        return r.json()


# ═══════════════════════════════════════════════════════════════════════
#   SECURITY & LOCKS
# ═══════════════════════════════════════════════════════════════════════

unauthorized_alert_cooldown: dict[int, float] = {}
authenticated_sessions: dict[int, float] = {}
failed_login_attempts: dict[int, list[float]] = {}


def is_authorized(user_id: int) -> bool:
    return manager_auth.is_authorized(user_id)


def is_authenticated(user_id: int) -> bool:
    if not config.BOT_PIN:
        return True
    expiry = authenticated_sessions.get(user_id, 0)
    return datetime.now().timestamp() < expiry


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    # Check if user matches a pending @username authorization
    if not is_authorized(user.id) and user.username:
        claimed = manager_auth.claim_pending_username(
            user_id=user.id,
            username=user.username,
            display_name=user.full_name or user.first_name or "",
        )
        if claimed:
            logger.info(f"User {user.id} claimed pending username @{user.username}")

    if not is_authorized(user.id):
        await notify_unauthorized_access(update, context)
        return False

    if not is_authenticated(user.id):
        text = (
            "🔒 <b>COMMAND CENTER LOCKED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "PIN security is enabled on this Sentinel.\n"
            "Please authenticate to access commands:\n\n"
            "👉 <code>/login YOUR_PIN</code>"
        )
        if update.callback_query:
            await update.callback_query.answer("🔒 Bot is locked. Send /login <PIN> to unlock.", show_alert=True)
        else:
            await update.effective_message.reply_text(text, parse_mode="HTML")
        return False
    return True


async def check_permission(update: Update, context: ContextTypes.DEFAULT_TYPE, perm_key: str, action_name: str) -> bool:
    """Verify that user has required capability. Owner bypasses all checks."""
    user = update.effective_user
    if not user:
        return False
    if manager_auth.is_owner(user.id):
        return True
    if not manager_auth.has_permission(user.id, perm_key):
        msg = (
            f"⛔ <b>ACCESS DENIED: INSUFFICIENT PRIVILEGES</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Action: <b>{html.escape(action_name)}</b>\n"
            f"Required Permission: <code>{perm_key}</code>\n"
            f"Your Role: <code>{manager_auth.get_user_role(user.id).upper()}</code>\n\n"
            f"<i>Contact the fleet owner to request this capability.</i>"
        )
        if update.callback_query:
            await update.callback_query.answer(f"⛔ Denied: requires {perm_key}", show_alert=True)
        else:
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        manager_auth.record_audit(user.id, user.username or str(user.id), "PERMISSION_DENIED", "", f"{perm_key} for {action_name}")
        return False
    return True


async def check_owner_only(update: Update, context: ContextTypes.DEFAULT_TYPE, action_name: str) -> bool:
    """Verify that user is the primary Super Admin Owner."""
    user = update.effective_user
    if not user or not manager_auth.is_owner(user.id):
        msg = (
            f"⛔ <b>FLEET OWNER PRIVILEGE REQUIRED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{html.escape(action_name)}</b> is strictly restricted to the primary Fleet Owner."
        )
        if update.callback_query:
            await update.callback_query.answer("⛔ Restricted to Fleet Owner only.", show_alert=True)
        else:
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        if user:
            manager_auth.record_audit(user.id, user.username or str(user.id), "OWNER_ONLY_BLOCKED", "", f"Blocked: {action_name}")
        return False
    return True


async def execute_remove_manager(user_id: int, bot) -> bool:
    """Remove manager from storage and wipe all bot artifacts from their phone."""
    removed = manager_auth.remove_manager(user_id)
    authenticated_sessions.pop(user_id, None)
    try:
        await bot.delete_chat_menu_button(chat_id=user_id)
    except Exception as e:
        logger.debug(f"Could not delete chat menu button for {user_id}: {e}")
    try:
        await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=user_id))
    except Exception as e:
        logger.debug(f"Could not wipe commands for {user_id}: {e}")
    manager_auth.record_audit(user_id, str(user_id), "MANAGER_REVOKED", "", "Manager access revoked and Telegram UI wiped")
    return removed


async def notify_unauthorized_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else 0
    username = f"@{user.username}" if user and user.username else f"User {user_id}"
    now = datetime.now().timestamp()
    if now - unauthorized_alert_cooldown.get(user_id, 0) < 60:
        return
    unauthorized_alert_cooldown[user_id] = now
    action = update.message.text if update.message and update.message.text else (
        update.callback_query.data if update.callback_query else "Unknown"
    )
    logger.warning(f"🚨 UNAUTHORIZED ACCESS BLOCKED: {username} ({user_id}) -> {action}")
    alert_text = (
        f"🚨 <b>SECURITY ALERT: UNAUTHORIZED ACCESS BLOCKED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Attempted By:</b> {html.escape(username)} (ID: <code>{user_id}</code>)\n"
        f"🕒 <b>Timestamp:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"🎯 <b>Action:</b> <code>{html.escape(action[:120])}</code>\n\n"
        f"🛡️ <i>The request was immediately denied and blocked by Sentinel.</i>"
    )
    for owner_id in config.AUTHORIZED_USER_IDS:
        try:
            await context.bot.send_message(chat_id=owner_id, text=alert_text, parse_mode="HTML")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
#   PC SELECTION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_selected_pc(context: ContextTypes.DEFAULT_TYPE, user_id: int = 0) -> Optional[dict]:
    """Get the currently selected PC info from user session (defaults to Host PC or first available)."""
    pc = context.user_data.get("selected_pc")
    if pc:
        if not user_id or manager_auth.can_manage_pc(user_id, pc.get("name", "")):
            return pc
        context.user_data.pop("selected_pc", None)
    fleet = load_fleet()
    pcs = fleet.get("pcs", [])
    if user_id:
        pcs = manager_auth.get_allowed_pcs(user_id, pcs)
    if pcs:
        host_pc = next((p for p in pcs if p.get("is_host")), pcs[0])
        context.user_data["selected_pc"] = host_pc
        return host_pc
    return None


def get_agent(context: ContextTypes.DEFAULT_TYPE, user_id: int = 0) -> Optional[AgentClient]:
    """Get AgentClient for currently selected PC."""
    pc = get_selected_pc(context, user_id)
    if not pc:
        return None
    fleet = load_fleet()
    return AgentClient(pc, get_fleet_secret(fleet))


async def require_pc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[AgentClient]:
    """Require a PC to be selected. Returns agent or None (with user prompt)."""
    user = update.effective_user
    user_id = user.id if user else 0
    agent = get_agent(context, user_id)
    if not agent:
        await show_pc_picker(update, context, prompt="⚠️ <b>No accessible PC selected!</b>\nPlease select a PC:")
        return None
    return agent


# ═══════════════════════════════════════════════════════════════════════
#   PC PICKER KEYBOARD
# ═══════════════════════════════════════════════════════════════════════

async def check_fleet_health(fleet: dict) -> Dict[str, dict]:
    """Check which PCs are online via Cloud Relay or LAN."""
    results = {}
    secret = get_fleet_secret(fleet)

    relay_pcs = commander_relay.get_pc_list() if (commander_relay and commander_relay.is_connected) else {}

    # Auto-register any new PCs discovered over the relay into fleet['pcs']!
    known_names = {pc["name"] for pc in fleet.get("pcs", [])}
    changed = False
    for r_name, r_info in relay_pcs.items():
        if r_name not in known_names:
            fleet.setdefault("pcs", []).append({
                "name": r_name,
                "label": r_name,
                "ip": r_info.get("ip", "Unknown"),
                "network": r_info.get("network", "Remote"),
            })
            known_names.add(r_name)
            changed = True
    if changed:
        save_fleet(fleet)

    async def _check(pc):
        name = pc["name"]
        # 1. Check Cloud Relay
        if name in relay_pcs and relay_pcs[name].get("status") == "online":
            results[name] = {
                "online": True,
                "network": relay_pcs[name].get("network", "Online (Relay)"),
            }
            return

        # 2. Check local LAN HTTP
        client = AgentClient(pc, secret)
        health = await client.health()
        if health:
            results[name] = {
                "online": True,
                "network": health.get("network", f"LAN ({pc.get('ip', 'Local')})"),
            }
        else:
            results[name] = {
                "online": False,
                "network": "Offline",
            }

    await asyncio.gather(*[_check(pc) for pc in fleet["pcs"]], return_exceptions=True)
    return results


def get_pc_picker_keyboard(fleet: dict, health: Dict[str, dict], user_id: int = 0) -> InlineKeyboardMarkup:
    """Build PC selector keyboard with online/offline indicators and scoping."""
    buttons = []
    row = []
    all_pcs = fleet.get("pcs", [])
    if user_id and not manager_auth.is_owner(user_id):
        visible_pcs = manager_auth.get_allowed_pcs(user_id, all_pcs)
    else:
        visible_pcs = all_pcs

    for pc in visible_pcs:
        name = pc["name"]
        label = pc.get("label", name)
        h_info = health.get(name, {})
        is_online = h_info.get("online", False)
        emoji = "🟢" if is_online else "🔴"
        btn_text = f"{emoji} {label}"
        try:
            idx = all_pcs.index(pc)
        except ValueError:
            idx = 0
        row.append(InlineKeyboardButton(btn_text, callback_data=f"pc_select_{idx}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if not user_id or manager_auth.is_owner(user_id):
        buttons.append([
            InlineKeyboardButton("✏️ Rename PC", callback_data="fleet_rename_menu"),
            InlineKeyboardButton("📊 Overview", callback_data="fleet_overview"),
            InlineKeyboardButton("🔄 Refresh", callback_data="fleet_refresh"),
        ])
        buttons.append([
            InlineKeyboardButton("👥 Manage Managers", callback_data="cb_mgr_list"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="fleet_refresh"),
        ])
    return InlineKeyboardMarkup(buttons)


async def show_pc_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str = None):
    """Show the PC selection menu."""
    user = update.effective_user
    user_id = user.id if user else 0
    fleet = load_fleet()
    health = await check_fleet_health(fleet)

    all_pcs = fleet.get("pcs", [])
    if user_id and not manager_auth.is_owner(user_id):
        visible_pcs = manager_auth.get_allowed_pcs(user_id, all_pcs)
    else:
        visible_pcs = all_pcs

    if not visible_pcs:
        text = (
            "⚠️ <b>NO ACCESSIBLE PCs</b>\n\n"
            "There are currently no PCs assigned to your account or registered in the fleet.\n"
            "Please contact the fleet owner to assign devices to your profile."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text, parse_mode="HTML")
        return

    online_count = sum(1 for p in visible_pcs if health.get(p["name"], {}).get("online"))

    header = prompt or (
        f"🛡️ <b>PC REMOTE SENTINEL — FLEET COMMAND CENTER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>Fleet Status:</b> <code>{online_count}/{len(visible_pcs)}</code> PCs online\n"
        f"👤 <b>Role:</b> <code>{manager_auth.get_user_role(user_id).upper()}</code>\n\n"
        f"<i>Select a PC to control:</i>"
    )
    keyboard = get_pc_picker_keyboard(fleet, health, user_id)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(header, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await update.effective_message.reply_text(header, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(header, reply_markup=keyboard, parse_mode="HTML")


async def show_rename_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show PC rename selector or direct prompt."""
    fleet = load_fleet()
    pcs = fleet.get("pcs", [])
    if not pcs:
        await show_pc_picker(update, context)
        return

    if len(pcs) == 1:
        target_pc = pcs[0]
        context.user_data["awaiting_pc_rename"] = target_pc["name"]
        label = target_pc.get("label", target_pc["name"])
        prompt_text = (
            f"✏️ <b>RENAME PC: {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Hostname: <code>{html.escape(target_pc['name'])}</code>\n\n"
            f"Please <b>type and send the new name</b> for this PC in this chat:\n"
            f"<i>(e.g., 'Front Desk PC', 'Gaming Rig', 'Living Room Laptop')</i>\n\n"
            f"<i>Send /cancel to abort.</i>"
        )
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="fleet_picker")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(prompt_text, reply_markup=cancel_kb, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(prompt_text, reply_markup=cancel_kb, parse_mode="HTML")
        return

    buttons = []
    row = []
    for i, pc in enumerate(pcs):
        name = pc["name"]
        label = pc.get("label", name)
        btn_text = f"✏️ {label}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"cb_rename_pick_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🔙 Back to PC List", callback_data="fleet_picker")])
    menu_text = (
        "✏️ <b>SELECT A PC TO RENAME</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap the PC you want to give a friendly custom name:"
    )
    kb = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.edit_message_text(menu_text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(menu_text, reply_markup=kb, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════
#   COMMAND CENTER KEYBOARDS (same layout as before, with "Back to PCs")
# ═══════════════════════════════════════════════════════════════════════

def get_main_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    is_own = manager_auth.is_owner(user_id) if user_id else True
    buttons = []

    # Row 1: System Status & Screenshot
    r1 = [InlineKeyboardButton("📊 System Status", callback_data="cb_status")]
    if is_own or manager_auth.has_permission(user_id, "can_screen"):
        r1.append(InlineKeyboardButton("📸 Screenshot", callback_data="cb_shot"))
    buttons.append(r1)

    # Row 2: Track & Lockdown
    r2 = []
    if is_own or manager_auth.has_permission(user_id, "can_track"):
        r2.append(InlineKeyboardButton("📍 Track Laptop", callback_data="cb_track"))
    if is_own or manager_auth.has_permission(user_id, "can_lockdown"):
        r2.append(InlineKeyboardButton("🚨 Lockdown", callback_data="cb_lockdown_menu"))
    if r2:
        buttons.append(r2)

    # Row 3: Live Screen Cast & Mouse
    r3 = []
    if is_own or manager_auth.has_permission(user_id, "can_screen"):
        r3.append(InlineKeyboardButton("📺 Live Screen Cast", callback_data="cb_cast_menu"))
    if is_own or manager_auth.has_permission(user_id, "can_input"):
        r3.append(InlineKeyboardButton("🖱️ Remote Mouse & Type", callback_data="cb_mouse_menu"))
    if r3:
        buttons.append(r3)

    # Row 4: Desktops & Screen Video
    r4 = []
    if is_own or manager_auth.has_permission(user_id, "can_screen"):
        r4.append(InlineKeyboardButton("🪟 Desktops & Windows", callback_data="cb_desktop_menu"))
        r4.append(InlineKeyboardButton("🎥 Screen Video", callback_data="cb_screen_menu"))
    if r4:
        buttons.append(r4)

    # Row 5: Webcam & Media
    r5 = []
    if is_own or manager_auth.has_permission(user_id, "can_webcam"):
        r5.append(InlineKeyboardButton("📷 Webcam Menu", callback_data="cb_webcam_menu"))
    if is_own or manager_auth.has_permission(user_id, "can_media"):
        r5.append(InlineKeyboardButton("🎵 Media & Volume", callback_data="cb_media_menu"))
    if r5:
        buttons.append(r5)

    # Row 6: Power & Processes
    r6 = []
    if is_own or manager_auth.has_permission(user_id, "can_power"):
        r6.append(InlineKeyboardButton("⚡ Power & Sleep", callback_data="cb_power_menu"))
    r6.append(InlineKeyboardButton("💻 Top Processes", callback_data="cb_top"))
    buttons.append(r6)

    # Row 7: Clipboard & TTS
    r7 = []
    if is_own or manager_auth.has_permission(user_id, "can_input"):
        r7.append(InlineKeyboardButton("📋 Clipboard Tools", callback_data="cb_clip_menu"))
    if is_own or manager_auth.has_permission(user_id, "can_media"):
        r7.append(InlineKeyboardButton("🗣️ Speak / TTS", callback_data="cb_tts_info"))
    if r7:
        buttons.append(r7)

    # Row 8: Alarm & Update
    r8 = []
    if is_own or manager_auth.has_permission(user_id, "can_media"):
        r8.append(InlineKeyboardButton("⏰ Alarm & Siren", callback_data="cb_alarm_menu"))
    if is_own:
        r8.append(InlineKeyboardButton("🔄 Push Update", callback_data="cb_update_agent"))
    if r8:
        buttons.append(r8)

    # Row 9: File Explorer & Storage
    r9 = []
    if is_own or manager_auth.has_permission(user_id, "can_files"):
        r9.append(InlineKeyboardButton("📁 File Explorer", callback_data="cb_fs_menu"))
        r9.append(InlineKeyboardButton("🧹 Clean Storage", callback_data="cb_clean"))
    if r9:
        buttons.append(r9)

    # Row 10: Rename & Refresh
    r10 = []
    if is_own:
        r10.append(InlineKeyboardButton("✏️ Rename PC", callback_data="cb_rename_current"))
    r10.append(InlineKeyboardButton("🔄 Refresh", callback_data="cb_menu"))
    buttons.append(r10)

    # Bottom Row: Network & Switch PC
    buttons.append([
        InlineKeyboardButton("🌐 Network Ping", callback_data="cb_net_ping"),
        InlineKeyboardButton("🔙 Switch PC", callback_data="fleet_picker"),
    ])
    return InlineKeyboardMarkup(buttons)


def get_lockdown_keyboard(is_active: bool = False) -> InlineKeyboardMarkup:
    if is_active:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 Disarm / Release Lockdown", callback_data="cb_lockdown_disarm")],
            [
                InlineKeyboardButton("📍 Track Location", callback_data="cb_track"),
                InlineKeyboardButton("📸 Intruder Photo", callback_data="cb_webcam_shot"),
            ],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 Trigger Emergency Lockdown (Loud Siren)", callback_data="cb_lockdown_loud")],
        [InlineKeyboardButton("🤫 Silent Lockdown (Stealth Lock)", callback_data="cb_lockdown_silent")],
        [
            InlineKeyboardButton("📍 Track Location", callback_data="cb_track"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
        ],
    ])


def get_desktop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀ Prev Desktop", callback_data="cb_desktop_prev"),
            InlineKeyboardButton("Next Desktop ▶", callback_data="cb_desktop_next"),
        ],
        [
            InlineKeyboardButton("◀ Alt+Tab", callback_data="cb_win_cycle_prev"),
            InlineKeyboardButton("Alt+Tab ▶", callback_data="cb_win_cycle_next"),
        ],
        [
            InlineKeyboardButton("🗂️ Switch App / Window", callback_data="cb_win_list"),
            InlineKeyboardButton("🪟 Task View", callback_data="cb_desktop_task_view"),
        ],
        [
            InlineKeyboardButton("➕ New Desktop", callback_data="cb_desktop_new"),
            InlineKeyboardButton("❌ Close Desktop", callback_data="cb_desktop_close"),
        ],
        [
            InlineKeyboardButton("📸 Screenshot", callback_data="cb_desktop_snap"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
        ],
    ])


def get_windows_picker_keyboard(windows: list) -> InlineKeyboardMarkup:
    """Build interactive inline keyboard for choosing and focusing open application windows."""
    buttons = []
    for w in windows[:10]:
        title = w.get("title", "Window").strip()
        proc = w.get("process", "").strip()
        hwnd = w.get("hwnd", 0)
        label = title[:28] + ("…" if len(title) > 28 else "")
        if proc and not label.lower().endswith(proc.lower()):
            label = f"{label} ({proc})"
            if len(label) > 36:
                label = label[:33] + "…"
        buttons.append([InlineKeyboardButton(f"🪟 {label}", callback_data=f"cb_win_focus_{hwnd}")])

    buttons.append([
        InlineKeyboardButton("◀ Alt+Tab", callback_data="cb_win_cycle_prev"),
        InlineKeyboardButton("Alt+Tab ▶", callback_data="cb_win_cycle_next"),
        InlineKeyboardButton("🔄 Refresh", callback_data="cb_win_list"),
    ])
    buttons.append([
        InlineKeyboardButton("🪟 Desktops Menu", callback_data="cb_desktop_menu"),
        InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


def build_file_explorer_view(
    context: ContextTypes.DEFAULT_TYPE,
    data: dict,
    page: int = 0,
    label: str = "Host PC"
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Format remote file explorer message text and interactive navigation keyboard.
    Stores directory context into context.user_data for stateful button callbacks.
    """
    current_path = data.get("current_path", "Desktop")
    parent_path = data.get("parent_path")
    items = data.get("items", [])
    total_dirs = data.get("total_dirs", sum(1 for x in items if x.get("is_dir")))
    total_files = data.get("total_files", sum(1 for x in items if not x.get("is_dir")))
    drives = data.get("drives", ["C:\\"])
    quick_access = data.get("quick_access", {})

    # Persist in user session
    context.user_data["fs_current_path"] = current_path
    context.user_data["fs_parent_path"] = parent_path
    context.user_data["fs_items"] = items
    context.user_data["fs_drives"] = drives
    context.user_data["fs_quick"] = quick_access

    PAGE_SIZE = 8
    total_pages = max(1, math.ceil(len(items) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    context.user_data["fs_page"] = page

    start_idx = page * PAGE_SIZE
    page_items = items[start_idx : start_idx + PAGE_SIZE]

    # Build directory snippet lines
    lines = []
    for it in page_items:
        icon = it.get("icon", "📄")
        name = it.get("name", "")
        if it.get("is_dir"):
            lines.append(f"{icon} <code>{html.escape(name)}/</code>")
        else:
            lines.append(f"{icon} <code>{html.escape(name)}</code> ({html.escape(it.get('size_fmt', ''))})")

    if not data.get("ok", True) and data.get("error"):
        content_preview = f"⚠️ <b>Notice:</b> <code>{html.escape(str(data.get('error')))}</code>"
    else:
        content_preview = "\n".join(lines) if lines else "<i>(Empty directory)</i>"

    trunc_msg = f"\n⚡ <i>{html.escape(data.get('note', ''))}</i>" if data.get("truncated") and data.get("note") else ""

    text = (
        f"📁 <b>REMOTE FILE EXPLORER — {html.escape(label)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Path:</b> <code>{html.escape(current_path)}</code>\n\n"
        f"{content_preview}\n\n"
        f"📊 <b>Contents:</b> {total_dirs} folders, {total_files} files | 📄 <b>Page:</b> {page + 1}/{total_pages}{trunc_msg}\n"
        f"💡 <i>Tap a folder to open it, or tap any file to download it!</i>"
    )

    buttons = []
    # Item buttons
    for idx_offset, it in enumerate(page_items):
        global_idx = start_idx + idx_offset
        name = it.get("name", "item")
        icon = it.get("icon", "📄")
        if it.get("is_dir"):
            btn_title = f"{icon} {name}"
            if len(btn_title) > 36:
                btn_title = btn_title[:33] + "…"
            buttons.append([InlineKeyboardButton(btn_title, callback_data=f"cb_fs_open_{global_idx}")])
        else:
            size_fmt = it.get("size_fmt", "")
            btn_title = f"{icon} {name} ({size_fmt}) ⬇️"
            if len(btn_title) > 38:
                btn_title = f"{icon} {name[:20]}… ({size_fmt}) ⬇️"
            buttons.append([InlineKeyboardButton(btn_title, callback_data=f"cb_fs_get_{global_idx}")])

    # Directory Navigation Row
    nav_row = []
    if parent_path:
        nav_row.append(InlineKeyboardButton("⬆️ Up", callback_data="cb_fs_up"))
    nav_row.append(InlineKeyboardButton("🏠 Quick Access", callback_data="cb_fs_qa"))
    nav_row.append(InlineKeyboardButton("🔄 Refresh", callback_data="cb_fs_refresh"))
    buttons.append(nav_row)

    # Pagination Row (if more than 1 page)
    if total_pages > 1:
        pag_row = []
        if page > 0:
            pag_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"cb_fs_p_{page - 1}"))
        else:
            pag_row.append(InlineKeyboardButton("⏮️ First", callback_data="cb_fs_noop"))

        pag_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="cb_fs_noop"))

        if page < total_pages - 1:
            pag_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"cb_fs_p_{page + 1}"))
        else:
            pag_row.append(InlineKeyboardButton("⏭️ End", callback_data="cb_fs_noop"))
        buttons.append(pag_row)

    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")])

    return text, InlineKeyboardMarkup(buttons)


def build_quick_access_keyboard(context: ContextTypes.DEFAULT_TYPE, label: str = "Host PC") -> Tuple[str, InlineKeyboardMarkup]:
    """Build Quick Access keyboard with system drives and common user locations."""
    drives = context.user_data.get("fs_drives", ["C:\\"])
    current_path = context.user_data.get("fs_current_path", "Desktop")

    text = (
        f"🏠 <b>QUICK ACCESS LOCATIONS — {html.escape(label)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Jump directly to any disk drive or primary user folder:\n\n"
        f"📍 <b>Current:</b> <code>{html.escape(current_path)}</code>"
    )

    buttons = []

    # Drives row
    drive_btns = []
    for d_idx, d in enumerate(drives[:4]):
        if d == "/":
            display_name = "Root (/)"
        elif d.startswith("/Volumes/"):
            display_name = d.replace("/Volumes/", "")
        else:
            display_name = d.replace("\\", "")
        if len(display_name) > 12:
            display_name = display_name[:10] + "…"
        drive_btns.append(InlineKeyboardButton(f"💻 {display_name}", callback_data=f"cb_fs_drv_{d_idx}"))
    if drive_btns:
        buttons.append(drive_btns)

    # User folders
    buttons.append([
        InlineKeyboardButton("🖥️ Desktop", callback_data="cb_fs_qa_desktop"),
        InlineKeyboardButton("📥 Downloads", callback_data="cb_fs_qa_downloads"),
    ])
    buttons.append([
        InlineKeyboardButton("📄 Documents", callback_data="cb_fs_qa_documents"),
        InlineKeyboardButton("📸 Pictures", callback_data="cb_fs_qa_pictures"),
    ])
    buttons.append([
        InlineKeyboardButton("🔴 Sentinel Recordings", callback_data="cb_fs_qa_recordings"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Explorer", callback_data="cb_fs_refresh"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu"),
    ])

    return text, InlineKeyboardMarkup(buttons)


def get_screen_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱️ 10s", callback_data="cb_rec_screen_10"),
            InlineKeyboardButton("⏱️ 20s", callback_data="cb_rec_screen_20"),
            InlineKeyboardButton("⏱️ 30s", callback_data="cb_rec_screen_30"),
        ],
        [
            InlineKeyboardButton("⏱️ 40s", callback_data="cb_rec_screen_40"),
            InlineKeyboardButton("⏱️ 50s", callback_data="cb_rec_screen_50"),
        ],
        [
            InlineKeyboardButton("⏱️ 1 Min (60s)", callback_data="cb_rec_screen_60"),
            InlineKeyboardButton("⏱️ 2 Mins (120s)", callback_data="cb_rec_screen_120"),
        ],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")],
    ])


def get_webcam_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Snapshot Photo", callback_data="cb_webcam_shot")],
        [
            InlineKeyboardButton("📹 Record 10s Clip", callback_data="cb_rec_webcam_10"),
            InlineKeyboardButton("📹 Record 30s Clip", callback_data="cb_rec_webcam_30"),
        ],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")],
    ])


def get_media_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔊 Vol +10%", callback_data="cb_vol_up"),
            InlineKeyboardButton("🔉 Vol -10%", callback_data="cb_vol_down"),
            InlineKeyboardButton("🔇 Mute", callback_data="cb_vol_mute"),
        ],
        [
            InlineKeyboardButton("⏮️ Prev", callback_data="cb_media_prev"),
            InlineKeyboardButton("⏯️ Play/Pause", callback_data="cb_media_play_pause"),
            InlineKeyboardButton("⏭️ Next", callback_data="cb_media_next"),
        ],
        [
            InlineKeyboardButton("⏹️ Stop", callback_data="cb_media_stop"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
        ],
    ])


def get_clipboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Read PC Clipboard", callback_data="cb_clip_read")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")],
    ])


def get_top_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Processes", callback_data="cb_top"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
        ],
    ])


def get_power_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💤 Sleep PC", callback_data="cb_pwr_sleep"),
            InlineKeyboardButton("🔒 Lock Workstation", callback_data="cb_pwr_lock"),
        ],
        [
            InlineKeyboardButton("🖥️ Turn Off Monitors", callback_data="cb_pwr_monitor_off"),
            InlineKeyboardButton("💡 Turn On Monitors", callback_data="cb_pwr_monitor_on"),
        ],
        [
            InlineKeyboardButton("⏳ Shutdown 15m", callback_data="cb_pwr_shut_15"),
            InlineKeyboardButton("⏳ Shutdown 30m", callback_data="cb_pwr_shut_30"),
        ],
        [
            InlineKeyboardButton("⏳ Shutdown 1h", callback_data="cb_pwr_shut_60"),
            InlineKeyboardButton("❌ Cancel Shutdown", callback_data="cb_pwr_shut_cancel"),
        ],
        [
            InlineKeyboardButton("🛑 Shutdown Now", callback_data="cb_pwr_shutdown_now"),
            InlineKeyboardButton("🔄 Restart PC", callback_data="cb_pwr_restart"),
        ],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")],
    ])


def get_alarm_keyboard(has_active: bool = False, is_ringing: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("⏱️ 1 Min", callback_data="cb_alarm_set_60"),
            InlineKeyboardButton("⏱️ 5 Mins", callback_data="cb_alarm_set_300"),
            InlineKeyboardButton("⏱️ 10 Mins", callback_data="cb_alarm_set_600"),
        ],
        [
            InlineKeyboardButton("⏱️ 15 Mins", callback_data="cb_alarm_set_900"),
            InlineKeyboardButton("⏱️ 30 Mins", callback_data="cb_alarm_set_1800"),
            InlineKeyboardButton("⏱️ 1 Hour", callback_data="cb_alarm_set_3600"),
        ],
        [InlineKeyboardButton("🚨 Sound Alarm Now", callback_data="cb_alarm_trigger_now")],
    ]
    action_row = []
    if is_ringing:
        action_row.append(InlineKeyboardButton("🔕 Silence Alarm", callback_data="cb_alarm_stop"))
    if has_active:
        action_row.append(InlineKeyboardButton("❌ Cancel Scheduled", callback_data="cb_alarm_cancel"))
    if action_row:
        buttons.append(action_row)
    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="cb_alarm_menu"),
        InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


def get_radar_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏹️ Stop Live View", callback_data="cb_cast_radar_stop"),
            InlineKeyboardButton("📸 High-Res Snap", callback_data="cb_shot"),
        ],
        [
            InlineKeyboardButton("🌐 Switch to Web Cast", callback_data="cb_cast_web_start"),
            InlineKeyboardButton("🔙 Cast Menu", callback_data="cb_cast_menu"),
        ],
    ])


# ═══════════════════════════════════════════════════════════════════════
#   HELPER: Current PC label for messages
# ═══════════════════════════════════════════════════════════════════════

def pc_label(context: ContextTypes.DEFAULT_TYPE) -> str:
    pc = get_selected_pc(context)
    if pc:
        return pc.get("label", pc.get("name", "Unknown"))
    return "No PC"


# ═══════════════════════════════════════════════════════════════════════
#   COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /menu — show PC picker or claim deep-link invite."""
    user = update.effective_user
    if not user:
        return

    # 1. Check for single-use invite token (/start inv_xxxx)
    if context.args and len(context.args) > 0:
        token = context.args[0].strip()
        if token.startswith("inv_"):
            success, msg, mgr_rec = manager_auth.claim_invite(
                token=token,
                user_id=user.id,
                username=user.username or "",
                display_name=user.full_name or user.first_name or "",
            )
            if success:
                role = mgr_rec.get("role", "manager")
                pcs = mgr_rec.get("allowed_pcs", ["*"])
                pc_str = "All PCs (*)" if "*" in pcs else ", ".join(pcs)
                manager_auth.record_audit(user.id, user.username or str(user.id), "INVITE_CLAIMED", pc_str, f"Role: {role}")
                welcome = (
                    f"🎉 <b>WELCOME TO PC REMOTE SENTINEL!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🛡️ <b>Access Granted:</b> <code>{role.upper()}</code>\n"
                    f"🖥️ <b>Scoped Devices:</b> <code>{html.escape(pc_str)}</code>\n\n"
                    f"You have been successfully onboarded as a fleet manager.\n"
                    f"Select an authorized device below to begin controlling:"
                )
                await update.message.reply_text(welcome, parse_mode="HTML")
                await show_pc_picker(update, context)
                return
            else:
                await update.message.reply_text(f"❌ <b>Invite Error:</b> {html.escape(msg)}", parse_mode="HTML")
                return

    # 2. Check for pending username pre-authorization
    if not is_authorized(user.id) and user.username:
        claimed = manager_auth.claim_pending_username(
            user_id=user.id,
            username=user.username,
            display_name=user.full_name or user.first_name or "",
        )
        if claimed:
            role = claimed.get("role", "manager")
            pcs = claimed.get("allowed_pcs", ["*"])
            pc_str = "All PCs (*)" if "*" in pcs else ", ".join(pcs)
            manager_auth.record_audit(user.id, user.username, "USERNAME_CLAIMED", pc_str, f"Role: {role}")
            welcome = (
                f"🎉 <b>WELCOME TO PC REMOTE SENTINEL!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ <b>Access Granted:</b> <code>{role.upper()}</code>\n"
                f"🖥️ <b>Scoped Devices:</b> <code>{html.escape(pc_str)}</code>\n\n"
                f"Your Telegram account (@{html.escape(user.username)}) was pre-authorized by the fleet owner.\n"
                f"Select an authorized device below to begin controlling:"
            )
            await update.message.reply_text(welcome, parse_mode="HTML")
            await show_pc_picker(update, context)
            return

    if not config.AUTHORIZED_USER_IDS:
        await update.message.reply_text(
            f"⚠️ <b>SETUP REQUIRED</b>\n\n"
            f"Your Telegram User ID is: <code>{user.id}</code>\n\n"
            f"Add this ID to your <code>.env</code> file:\n"
            f"<code>AUTHORIZED_USER_IDS={user.id}</code>\n\n"
            f"Then restart the bot.",
            parse_mode="HTML"
        )
        return

    if not is_authorized(user.id):
        await update.message.reply_text("⛔ <b>Access Denied.</b>", parse_mode="HTML")
        return

    if config.BOT_PIN and not is_authenticated(user.id):
        text = (
            f"🔒 <b>PC REMOTE SENTINEL — LOCKED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Security Mode:</b> PIN Protected\n\n"
            f"<i>Please enter your PIN to unlock the Fleet Command Center:</i>\n"
            f"👉 <code>/login YOUR_PIN</code>"
        )
        await update.message.reply_text(text, parse_mode="HTML")
        return

    # If a PC is already selected, show its command center
    pc = get_selected_pc(context, user.id)
    if pc:
        label = pc.get("label", pc.get("name", "Host PC"))
        agent = get_agent(context, user.id)
        try:
            # If target PC is local host and agent is offline, revive it silently
            if agent and agent.is_local:
                ensure_local_agent_running()
            stats = await agent.status()
            text = (
                f"🛡️ <b>CONTROLLING: {html.escape(label)}</b> ⚡\n"
                f"<b>CPU:</b> <code>{stats['cpu_percent']:.1f}%</code> | "
                f"<b>RAM:</b> <code>{stats['memory_percent']:.1f}%</code> "
                f"({stats['memory_used_gb']} / {stats['memory_total_gb']} GB)\n"
                f"<b>Uptime:</b> <code>{stats['uptime']}</code>\n\n"
                f"<i>Tap below or send commands to control this PC:</i>"
            )
            await update.message.reply_text(text, reply_markup=get_main_keyboard(user.id), parse_mode="HTML")
        except Exception:
            # Auto-revive local host agent if down
            if pc.get("is_host") or pc.get("ip") in ("127.0.0.1", "localhost"):
                ensure_local_agent_running()
            context.user_data.pop("selected_pc", None)
            await show_pc_picker(update, context, prompt=f"⚠️ <b>{html.escape(label)} is offline.</b>\nSelect another PC:")
        return

    await show_pc_picker(update, context)


# ═══════════════════════════════════════════════════════════════════════
#   DELEGATED MANAGERS & ACCESS CONTROL HANDLERS
# ═══════════════════════════════════════════════════════════════════════

def get_managers_overview_keyboard() -> InlineKeyboardMarkup:
    """Build manager list with management action buttons."""
    buttons = []
    managers = manager_auth.list_managers()
    for mgr in managers:
        uid = mgr.get("user_id")
        name = mgr.get("display_name") or mgr.get("username") or str(uid)
        role = mgr.get("role", "manager")
        btn_text = f"👤 {name} ({role.upper()})"
        buttons.append([
            InlineKeyboardButton(btn_text, callback_data=f"cb_mgr_view_{uid}"),
            InlineKeyboardButton("🗑️ Revoke", callback_data=f"cb_mgr_del_{uid}"),
        ])
    buttons.append([
        InlineKeyboardButton("➕ Create Invite Link", callback_data="cb_mgr_invite_quick"),
        InlineKeyboardButton("📜 Audit Log", callback_data="cb_mgr_audit"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Fleet", callback_data="fleet_picker"),
    ])
    return InlineKeyboardMarkup(buttons)


def get_manager_detail_keyboard(mgr_uid: int) -> InlineKeyboardMarkup:
    """Build granular permissions toggle keyboard for a specific manager."""
    mgr = manager_auth.get_manager(mgr_uid)
    if not mgr:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Managers", callback_data="cb_mgr_list")]])

    perms = mgr.get("permissions", {})
    labels = {
        "can_power": "⚡ Power",
        "can_screen": "📸 Screen",
        "can_input": "🖱️ Input",
        "can_media": "🎵 Media",
        "can_webcam": "📷 Webcam",
        "can_files": "📁 Files",
        "can_terminal": "💻 Terminal",
        "can_track": "📍 Track",
        "can_lockdown": "🚨 Lockdown",
    }
    buttons = []
    row = []
    for p_key, p_label in labels.items():
        enabled = perms.get(p_key, False)
        status_emoji = "✅" if enabled else "❌"
        row.append(InlineKeyboardButton(f"{status_emoji} {p_label}", callback_data=f"cb_mgr_tog_{mgr_uid}_{p_key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🗑️ Revoke Access", callback_data=f"cb_mgr_del_{mgr_uid}"),
        InlineKeyboardButton("🔙 Back to Managers", callback_data="cb_mgr_list"),
    ])
    return InlineKeyboardMarkup(buttons)


async def handle_managers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /managers — manage delegated fleet managers."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Manager Administration (/managers)"):
        return

    managers = manager_auth.list_managers()
    invites = manager_auth.list_pending_invites()
    pending_u = manager_auth.data.get("pending_by_username", {})

    lines = [
        "👥 <b>FLEET DELEGATION & MANAGER ACCESS CONTROL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"👑 <b>Super Admin (Owner):</b> <code>{len(config.AUTHORIZED_USER_IDS)}</code>",
        f"👤 <b>Active Managers:</b> <code>{len(managers)}</code>",
        f"🎟️ <b>Active Invites:</b> <code>{len(invites)}</code>",
        f"⏳ <b>Pending Usernames:</b> <code>{len(pending_u)}</code>\n",
    ]

    if managers:
        lines.append("<b>Registered Managers:</b>")
        for m in managers:
            uid = m.get("user_id")
            uname = f"@{m.get('username')}" if m.get("username") else f"ID: {uid}"
            role = m.get("role", "manager").upper()
            pcs = m.get("allowed_pcs", ["*"])
            pc_str = "All PCs" if "*" in pcs else ", ".join(pcs)
            lines.append(f"• <b>{html.escape(m.get('display_name', ''))}</b> ({html.escape(uname)}) — <code>{role}</code>\n  └ Devices: <code>{html.escape(pc_str)}</code>")
        lines.append("")

    if invites:
        lines.append("<b>Pending Invite Links:</b>")
        for inv in invites:
            tok = inv.get("token")
            role = inv.get("role", "manager").upper()
            lines.append(f"• Token: <code>{tok}</code> ({role})")
        lines.append("")

    if pending_u:
        lines.append("<b>Pre-authorized Usernames:</b>")
        for uname, udata in pending_u.items():
            lines.append(f"• @{html.escape(uname)} ({udata.get('role', 'manager').upper()})")
        lines.append("")

    lines.append("<i>Commands:</i>\n• <code>/invite [role] [pcs]</code> — Generate deep-link\n• <code>/addmanager @user [role] [pcs]</code> — Pre-authorize user\n• <code>/removemanager &lt;id|@user&gt;</code> — Revoke & wipe manager\n• <code>/audit</code> — View security logs")

    text = "\n".join(lines)
    kb = get_managers_overview_keyboard()

    if update.callback_query:
        await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def handle_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /invite [role] [pc1,pc2] — Generate single-use onboarding deep-link."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Invite Creation (/invite)"):
        return

    role = "manager"
    allowed_pcs = ["*"]
    if context.args:
        arg_role = context.args[0].lower()
        if arg_role in DEFAULT_ROLE_PERMISSIONS:
            role = arg_role
        if len(context.args) > 1:
            allowed_pcs = [p.strip() for p in context.args[1].split(",") if p.strip()]

    user = update.effective_user
    token = manager_auth.create_invite(
        role=role,
        allowed_pcs=allowed_pcs,
        expires_hours=72,
        created_by=user.id if user else 0,
    )

    bot_info = await context.bot.get_me()
    invite_url = f"https://t.me/{bot_info.username}?start={token}"
    pc_str = "All PCs (*)" if "*" in allowed_pcs else ", ".join(allowed_pcs)

    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "INVITE_CREATED", pc_str, f"Role: {role}, Token: {token}")

    text = (
        f"🎟️ <b>SINGLE-USE MANAGER INVITE CREATED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Role:</b> <code>{role.upper()}</code>\n"
        f"🖥️ <b>Allowed PCs:</b> <code>{html.escape(pc_str)}</code>\n"
        f"⏳ <b>Validity:</b> 72 hours (Single use)\n\n"
        f"🔗 <b>Onboarding Link:</b>\n"
        f"<code>{invite_url}</code>\n\n"
        f"👉 <i>Forward this link to your manager. As soon as they open the link in Telegram and tap Start, they will automatically gain scoped access to the bot on their phone.</i>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def handle_add_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addmanager <@username> [role] [pc1,pc2] — Pre-authorize manager by Telegram username."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Add Manager (/addmanager)"):
        return

    if not context.args:
        usage = (
            "⚠️ <b>Usage:</b>\n"
            "<code>/addmanager @username [role] [pc1,pc2]</code>\n\n"
            "<b>Roles:</b> <code>admin</code>, <code>manager</code>, <code>operator</code>, <code>viewer</code>\n"
            "<b>Example:</b> <code>/addmanager @JohnDoe operator Laptop-Office</code>"
        )
        await update.effective_message.reply_text(usage, parse_mode="HTML")
        return

    username = context.args[0].lstrip("@").strip()
    role = "manager"
    allowed_pcs = ["*"]
    if len(context.args) > 1:
        r = context.args[1].lower()
        if r in DEFAULT_ROLE_PERMISSIONS:
            role = r
    if len(context.args) > 2:
        allowed_pcs = [p.strip() for p in context.args[2].split(",") if p.strip()]

    user = update.effective_user
    manager_auth.add_pending_by_username(
        username=username,
        role=role,
        allowed_pcs=allowed_pcs,
        added_by=user.id if user else 0,
    )
    pc_str = "All PCs (*)" if "*" in allowed_pcs else ", ".join(allowed_pcs)
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "PREAUTH_ADDED", pc_str, f"User: @{username}, Role: {role}")

    bot_info = await context.bot.get_me()
    text = (
        f"✅ <b>PRE-AUTHORIZATION CONFIGURED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Username:</b> <code>@{html.escape(username)}</code>\n"
        f"🛡️ <b>Role:</b> <code>{role.upper()}</code>\n"
        f"🖥️ <b>Allowed PCs:</b> <code>{html.escape(pc_str)}</code>\n\n"
        f"✨ When <b>@{html.escape(username)}</b> opens <b>@{bot_info.username}</b> and taps <b>/start</b>, "
        f"Sentinel will immediately recognize their account, grant them access, and show their scoped PCs."
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def handle_remove_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removemanager <user_id or @username> — Revoke manager and scrub bot artifacts from their phone."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Remove Manager (/removemanager)"):
        return

    if not context.args:
        await update.effective_message.reply_text("⚠️ <b>Usage:</b> <code>/removemanager &lt;user_id or @username&gt;</code>", parse_mode="HTML")
        return

    target = context.args[0].strip()
    bot = context.bot

    # If numeric user_id
    if target.isdigit():
        target_uid = int(target)
        if target_uid in config.AUTHORIZED_USER_IDS:
            await update.effective_message.reply_text("⛔ Cannot remove Primary Fleet Owner.", parse_mode="HTML")
            return
        removed = await execute_remove_manager(target_uid, bot)
        if removed:
            await update.effective_message.reply_text(
                f"🗑️ <b>MANAGER ACCESS REVOKED</b>\n\n"
                f"User ID <code>{target_uid}</code> has been completely removed.\n"
                f"• Access permissions wiped.\n"
                f"• Telegram Chat Menu Button deleted from their device.\n"
                f"• Command suggestions erased from their app.\n"
                f"• Any future messages from them will be immediately rejected.",
                parse_mode="HTML"
            )
        else:
            await update.effective_message.reply_text(f"⚠️ Manager with User ID <code>{target_uid}</code> was not found.", parse_mode="HTML")
        return

    # If @username
    uname = target.lstrip("@").lower()
    found_uid = None
    for uid_str, m_data in manager_auth.data.get("managers", {}).items():
        if m_data.get("username", "").lower() == uname:
            found_uid = int(uid_str)
            break

    if found_uid:
        await execute_remove_manager(found_uid, bot)
        await update.effective_message.reply_text(
            f"🗑️ <b>MANAGER @{html.escape(uname)} REVOKED</b>\n\n"
            f"Manager removed and Telegram bot commands/menu wiped from their phone.",
            parse_mode="HTML"
        )
    else:
        pending_removed = manager_auth.remove_by_username(uname)
        if pending_removed:
            await update.effective_message.reply_text(f"🗑️ Removed pending pre-authorization for <b>@{html.escape(uname)}</b>.", parse_mode="HTML")
        else:
            await update.effective_message.reply_text(f"⚠️ No active or pending manager found for <b>@{html.escape(uname)}</b>.", parse_mode="HTML")


async def handle_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /audit — view security audit trail."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Audit Log Access (/audit)"):
        return

    logs = manager_auth.get_audit_log(15)
    if not logs:
        text = "📜 <b>SECURITY AUDIT LOG</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>No security events recorded yet.</i>"
    else:
        items = []
        for entry in reversed(logs):
            ts = entry.get("timestamp", "")[:19].replace("T", " ")
            u = entry.get("username") or str(entry.get("user_id"))
            act = entry.get("action", "")
            target = entry.get("target_pc") or "Fleet"
            det = entry.get("details", "")
            det_str = f" ({html.escape(det[:50])})" if det else ""
            items.append(f"• <code>[{ts}]</code> <b>{html.escape(act)}</b> by <b>{html.escape(u)}</b> on <code>{html.escape(target)}</code>{det_str}")
        text = "📜 <b>SECURITY AUDIT LOG (Latest 15 Events)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(items)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Log", callback_data="cb_mgr_audit")],
        [InlineKeyboardButton("👥 Back to Managers", callback_data="cb_mgr_list")],
    ])
    if update.callback_query:
        await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def handle_pcs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pcs — switch to PC picker."""
    if not await check_access(update, context):
        return
    context.user_data.pop("selected_pc", None)
    await show_pc_picker(update, context)


async def handle_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reload — reload fleet.json."""
    if not await check_access(update, context):
        return
    fleet = load_fleet()
    await update.message.reply_text(
        f"🔄 <b>Fleet reloaded!</b>\n"
        f"Found <code>{len(fleet['pcs'])}</code> registered PC(s).",
        parse_mode="HTML"
    )


async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Authenticate user with PIN."""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        await notify_unauthorized_access(update, context)
        return

    if not config.BOT_PIN:
        await update.effective_message.reply_text("ℹ️ PIN security is not enabled.", parse_mode="HTML")
        return

    now = datetime.now().timestamp()
    attempts = [t for t in failed_login_attempts.get(user.id, []) if now - t < 300]
    if len(attempts) >= 5:
        await update.effective_message.reply_text("⛔ <b>Too many failed attempts.</b> Locked for 5 minutes.", parse_mode="HTML")
        return

    if not context.args:
        await update.effective_message.reply_text("Usage: <code>/login 1234</code>", parse_mode="HTML")
        return

    pin_input = context.args[0].strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    if pin_input == config.BOT_PIN:
        authenticated_sessions[user.id] = now + (config.SESSION_TIMEOUT_MINS * 60)
        failed_login_attempts.pop(user.id, None)
        await update.effective_chat.send_message(
            f"🔓 <b>ACCESS GRANTED</b> ✅\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Session unlocked for <b>{config.SESSION_TIMEOUT_MINS} minutes</b>.\n"
            f"Send <code>/logout</code> to re-lock.",
            parse_mode="HTML"
        )
        await show_pc_picker(update, context)
    else:
        attempts.append(now)
        failed_login_attempts[user.id] = attempts
        remaining = 5 - len(attempts)
        await update.effective_chat.send_message(
            f"❌ <b>Incorrect PIN!</b> ({remaining} attempts remaining).",
            parse_mode="HTML"
        )


async def handle_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        authenticated_sessions.pop(user.id, None)
        context.user_data.pop("selected_pc", None)
    await update.effective_message.reply_text(
        "🔒 <b>Session Locked</b> ✅\nSend <code>/login &lt;PIN&gt;</code> to re-authenticate.",
        parse_mode="HTML"
    )


async def handle_setpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or change the bot PIN: /setpin <4-8 digit PIN>"""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        await notify_unauthorized_access(update, context)
        return
    if not await check_owner_only(update, context, "PIN Management (/setpin)"):
        return

    # If PIN currently active and user is not authenticated, require login first
    if config.BOT_PIN and not is_authenticated(user.id):
        await update.effective_message.reply_text(
            "⛔ <b>Authentication Required</b>\nPlease log in first with <code>/login &lt;current_pin&gt;</code> before setting a new PIN.",
            parse_mode="HTML"
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: <code>/setpin 1234</code> to set, or <code>/setpin off</code> to disable.",
            parse_mode="HTML"
        )
        return

    new_pin = context.args[0].strip()
    if new_pin.lower() in ("off", "remove", "disable", "del", "unset", "clear"):
        return await handle_removepin(update, context)

    if not new_pin.isdigit() or len(new_pin) < 4 or len(new_pin) > 8:
        await update.effective_message.reply_text(
            "❌ <b>Invalid PIN:</b> PIN must be 4 to 8 digits (e.g. <code>/setpin 2580</code>).",
            parse_mode="HTML"
        )
        return

    # Delete message with the PIN for privacy
    try:
        await update.message.delete()
    except Exception:
        pass

    if config.update_pin(new_pin):
        now = datetime.now().timestamp()
        authenticated_sessions[user.id] = now + (config.SESSION_TIMEOUT_MINS * 60)
        failed_login_attempts.pop(user.id, None)
        await update.effective_chat.send_message(
            f"🔐 <b>PIN CONFIGURED SUCCESSFULLY</b> ✅\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• PIN set to: <code>{'*' * len(new_pin)}</code>\n"
            f"• Session timeout: <b>{config.SESSION_TIMEOUT_MINS} minutes</b>\n"
            f"• To lock bot immediately: <code>/logout</code>\n"
            f"• To remove PIN: <code>/removepin</code>",
            parse_mode="HTML"
        )
    else:
        await update.effective_chat.send_message("❌ Failed to save PIN to configuration.", parse_mode="HTML")


async def handle_removepin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove PIN protection: /removepin"""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        await notify_unauthorized_access(update, context)
        return
    if not await check_owner_only(update, context, "PIN Removal (/removepin)"):
        return

    if not config.BOT_PIN:
        await update.effective_message.reply_text("ℹ️ No PIN is currently set.", parse_mode="HTML")
        return

    if not is_authenticated(user.id):
        await update.effective_message.reply_text(
            "⛔ <b>Authentication Required</b>\nPlease log in first with <code>/login &lt;PIN&gt;</code> before removing your PIN.",
            parse_mode="HTML"
        )
        return

    if config.update_pin(""):
        authenticated_sessions.pop(user.id, None)
        await update.effective_message.reply_text(
            f"🔓 <b>PIN SECURITY REMOVED</b> ✅\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"PIN protection has been disabled.\n"
            f"The bot is now directly accessible to authorized users without a PIN.\n\n"
            f"<i>You can set a new PIN anytime with <code>/setpin &lt;digits&gt;</code>.</i>",
            parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text("❌ Failed to update configuration.", parse_mode="HTML")


async def handle_remove_pc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a PC from the fleet registry: /removepc <pc_name>"""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Remove PC (/removepc)"):
        return
    fleet = load_fleet()
    pcs = fleet.get("pcs", [])

    if not context.args:
        names = [f"• <code>{p['name']}</code> {'<i>(Host)</i>' if p.get('is_host') else ''}" for p in pcs]
        names_str = "\n".join(names) if names else "None"
        await update.effective_message.reply_text(
            f"Usage: <code>/removepc &lt;pc_name&gt;</code>\n\n"
            f"<b>Registered PCs:</b>\n{names_str}",
            parse_mode="HTML"
        )
        return

    target_name = context.args[0].strip()
    found = None
    for p in pcs:
        if p["name"].lower() == target_name.lower():
            found = p
            break

    if not found:
        await update.effective_message.reply_text(f"❌ PC '<code>{html.escape(target_name)}</code>' not found in fleet.", parse_mode="HTML")
        return

    if found.get("is_host"):
        await update.effective_message.reply_text("⚠️ Cannot remove the Host PC.", parse_mode="HTML")
        return

    fleet["pcs"] = [p for p in pcs if p["name"].lower() != target_name.lower()]
    save_fleet(fleet)

    # Clear from session if active
    if context.user_data.get("selected_pc", {}).get("name", "").lower() == target_name.lower():
        context.user_data.pop("selected_pc", None)

    await update.effective_message.reply_text(
        f"🗑️ <b>PC REMOVED</b> ✅\n\nPC '<code>{html.escape(found['name'])}</code>' has been removed from your fleet registry.",
        parse_mode="HTML"
    )


async def handle_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rename <new_name> or /rename to open rename picker."""
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Rename PC (/rename)"):
        return

    if not context.args:
        await show_rename_menu(update, context)
        return

    new_label = " ".join(context.args).strip()
    if len(new_label) > 40:
        await update.message.reply_text("⚠️ Name too long (max 40 characters).", parse_mode="HTML")
        return

    target_pc = get_selected_pc(context)
    if not target_pc:
        await update.message.reply_text("⚠️ No PC selected. Use <code>/pcs</code> first.", parse_mode="HTML")
        return

    target_name = target_pc["name"]
    fleet = load_fleet()
    for pc in fleet.get("pcs", []):
        if pc["name"].lower() == target_name.lower():
            pc["label"] = new_label
            break
    save_fleet(fleet)

    if context.user_data.get("selected_pc", {}).get("name", "").lower() == target_name.lower():
        context.user_data["selected_pc"]["label"] = new_label

    await update.message.reply_text(
        f"✨ <b>PC RENAMED SUCCESSFULLY</b> ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• PC (<code>{html.escape(target_name)}</code>) is now labeled:\n"
        f"👉 <b>{html.escape(new_label)}</b>",
        parse_mode="HTML"
    )


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any pending operation."""
    if "awaiting_pc_rename" in context.user_data:
        context.user_data.pop("awaiting_pc_rename", None)
        await update.message.reply_text("❌ Renaming cancelled.", parse_mode="HTML")
        await show_pc_picker(update, context)
        return
    await update.message.reply_text("ℹ️ No active operation to cancel.", parse_mode="HTML")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    chat_id = update.effective_chat.id
    label = pc_label(context)
    await safe_send_chat_action(context.bot, chat_id, ChatAction.TYPING)

    status_msg = None
    if not update.callback_query:
        status_msg = await safe_reply(update, f"📊 <i>Querying hardware diagnostics from {html.escape(label)}...</i>", parse_mode="HTML")
    else:
        try:
            await update.callback_query.edit_message_text(f"📊 <i>Querying hardware diagnostics from {html.escape(label)}...</i>", parse_mode="HTML")
        except Exception:
            pass

    try:
        stats = await agent.status()
        cores_str = ", ".join([f"{c:.0f}%" for c in stats.get('per_core', [])[:8]])
        text = (
            f"📊 <b>PC HARDWARE DIAGNOSTICS — {html.escape(label)}</b>\n"
            f"{'━' * 28}\n\n"
            f"🖥️ <b>CPU Total:</b> <code>{stats['cpu_percent']:.1f}%</code>\n"
            f"⚡ <b>Per Core:</b> <code>[{cores_str}]</code>\n"
            f"🧠 <b>RAM:</b> <code>{stats['memory_percent']:.1f}%</code> ({stats['memory_used_gb']} / {stats['memory_total_gb']} GB)\n"
            f"💾 <b>Disk C:</b> <code>{stats['disk_percent']:.1f}%</code> (Free: {stats['disk_free_gb']} GB)\n"
            f"🔋 <b>Power:</b> <code>{stats['battery']}</code>\n"
            f"🪟 <b>Session:</b> <code>{stats.get('session_state', 'Normal')}</code>\n"
            f"⏱️ <b>Uptime:</b> <code>{stats['uptime']}</code>\n"
            f"📅 <b>Boot:</b> <code>{stats['boot_time']}</code>"
        )
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        elif status_msg:
            await safe_edit_text(status_msg, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await safe_reply(update, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        err = f"❌ Failed to reach <b>{html.escape(label)}</b>: <code>{html.escape(str(e)[:250])}</code>\n\n💡 <i>Internet connection may be unstable. Try /net to check latency.</i>"
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, err, reply_markup=get_main_keyboard(), parse_mode="HTML")
        elif status_msg:
            await safe_edit_text(status_msg, err, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await safe_reply(update, err, parse_mode="HTML")


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_screen", "Screenshot (/shot)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    chat_id = update.effective_chat.id

    await safe_send_chat_action(context.bot, chat_id, ChatAction.UPLOAD_PHOTO)
    msg = await safe_reply(
        update,
        f"📸 <i>Capturing screenshot from {html.escape(label)}...</i>\n<small>⏳ Connecting over network...</small>",
        parse_mode="HTML"
    )
    try:
        res = await agent.screenshot(chat_id=chat_id)
        if isinstance(res, bytes):
            await safe_send_photo(
                context.bot,
                chat_id=chat_id,
                photo=res,
                caption=f"🖥️ <b>Screenshot — {html.escape(label)}</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception as e:
        err_text = f"❌ <b>Screenshot failed:</b> <code>{html.escape(str(e))}</code>\n\n💡 <i>Tip: Send /net to test connection ping.</i>"
        if msg:
            await safe_edit_text(msg, err_text, parse_mode="HTML")
        else:
            await safe_reply(update, err_text, parse_mode="HTML")


async def handle_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_webcam", "Webcam Snapshot (/webcam)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    chat_id = update.effective_chat.id

    await safe_send_chat_action(context.bot, chat_id, ChatAction.UPLOAD_PHOTO)
    msg = await safe_reply(
        update,
        f"📷 <i>Accessing webcam on {html.escape(label)}...</i>\n<small>⏳ Connecting over network...</small>",
        parse_mode="HTML"
    )
    try:
        res = await agent.webcam(chat_id=chat_id)
        if isinstance(res, bytes):
            await safe_send_photo(
                context.bot,
                chat_id=chat_id,
                photo=res,
                caption=f"📷 <b>Webcam — {html.escape(label)}</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception as e:
        err_text = f"❌ <b>Webcam failed:</b> <code>{html.escape(str(e))}</code>\n\n💡 <i>Tip: Send /net to test connection ping.</i>"
        if msg:
            await safe_edit_text(msg, err_text, parse_mode="HTML")
        else:
            await safe_reply(update, err_text, parse_mode="HTML")


async def execute_screen_recording(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int = 10):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_screen", "Screen Video Recording"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    duration = min(max(duration, 3), 120)
    label = pc_label(context)
    chat_id = update.effective_chat.id
    msg = await update.effective_message.reply_text(
        f"🎥 <i>Recording {duration}s of {html.escape(label)} desktop...</i>", parse_mode="HTML"
    )
    try:
        res = await agent.record_screen(duration, chat_id=chat_id)
        if isinstance(res, bytes):
            await update.effective_chat.send_video(
                video=res,
                caption=f"🎥 <b>Screen Recording ({duration}s) — {html.escape(label)}</b>",
                parse_mode="HTML"
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ Recording failed: {e}")


async def handle_record_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_screen", "Screen Video Recording"):
        return
    if context.args and context.args[0].isdigit():
        await execute_screen_recording(update, context, duration=int(context.args[0]))
    else:
        label = pc_label(context)
        await update.effective_message.reply_text(
            f"🎥 <b>SCREEN RECORDING — {html.escape(label)}</b>\nSelect duration:",
            reply_markup=get_screen_keyboard(), parse_mode="HTML"
        )


async def execute_webcam_recording(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int = 10):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_webcam", "Webcam Video Recording"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    duration = min(max(duration, 3), 60)
    label = pc_label(context)
    chat_id = update.effective_chat.id
    msg = await update.effective_message.reply_text(
        f"📹 <i>Recording {duration}s from webcam on {html.escape(label)}...</i>", parse_mode="HTML"
    )
    try:
        res = await agent.record_webcam(duration, chat_id=chat_id)
        if isinstance(res, bytes):
            await update.effective_chat.send_video(
                video=res,
                caption=f"📹 <b>Webcam ({duration}s) — {html.escape(label)}</b>",
                parse_mode="HTML"
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ Webcam recording failed: {e}")


async def handle_record_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_webcam", "Webcam Video Recording"):
        return
    duration = 10
    if context.args and context.args[0].isdigit():
        duration = int(context.args[0])
    await execute_webcam_recording(update, context, duration=duration)


# ── Screen Casting ────────────────────────────────────────────────────

active_radar_tasks: dict[int, asyncio.Task] = {}


async def handle_cast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_screen", "Live Screen Cast (/cast)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    args = context.args or []
    if not args:
        try:
            status = await agent.cast_status()
            is_web = status.get("is_web_streaming", False)
            is_rtmp = status.get("is_rtmp_streaming", False)
            web_state = "🟢 <b>ACTIVE</b>" if is_web else "⚪ <i>Inactive</i>"
            rtmp_state = "🟢 <b>ACTIVE</b>" if is_rtmp else "⚪ <i>Inactive</i>"
            win = html.escape(status.get("active_window", "Desktop")[:45])
            label = pc_label(context)
            text = (
                f"📺 <b>LIVE SCREEN CASTING — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Web Stream:</b> {web_state}\n"
                f"• <b>RTMP:</b> {rtmp_state}\n"
                f"• <b>Window:</b> <code>{win}</code>"
            )
            rows = []
            if is_web:
                rows.append([
                    InlineKeyboardButton("⏹️ Stop Web Stream", callback_data="cb_cast_web_stop"),
                ])
            else:
                rows.append([
                    InlineKeyboardButton("🌐 Start Web Cast", callback_data="cb_cast_web_start"),
                ])
            rows.append([
                InlineKeyboardButton("⚡ In-Chat Live View", callback_data="cb_cast_radar_start"),
                InlineKeyboardButton("🪟 Switch Desktops", callback_data="cb_desktop_menu"),
            ])
            rows.append([
                InlineKeyboardButton("📡 RTMP Info", callback_data="cb_cast_rtmp_info"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
            ])
            await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Cast status failed: {e}")
        return

    subcmd = args[0].lower()
    if subcmd in ("web", "start"):
        await execute_cast_web_start(update, context)
    elif subcmd in ("stop", "off"):
        if update.effective_chat.id in active_radar_tasks:
            active_radar_tasks.pop(update.effective_chat.id).cancel()
        try:
            await agent.cast_web_stop()
            await agent.cast_rtmp_stop()
        except Exception:
            pass
        await update.effective_message.reply_text("⏹️ <b>All casts stopped.</b>", parse_mode="HTML")
    elif subcmd in ("live", "radar"):
        await execute_cast_radar_start(update, context)
    elif subcmd == "rtmp":
        if len(args) < 2:
            await update.effective_message.reply_text(
                "📡 <b>RTMP Usage:</b>\n<code>/cast rtmp rtmps://dc4-1.rtmp.t.me/s/YOUR_KEY</code>",
                parse_mode="HTML"
            )
            return
        try:
            result = await agent.cast_rtmp_start(args[1])
            await update.effective_message.reply_text(f"📡 RTMP: {result.get('message', 'Started')}")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ RTMP failed: {e}")


async def handle_desktop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    label = pc_label(context)

    # If user provided action argument: /desktop next, /desktop prev, /desktop new, /desktop close, /desktop task_view
    if context.args:
        sub_arg = context.args[0].lower().strip()
        action_map = {
            "next": "next", "right": "next",
            "prev": "prev", "previous": "prev", "left": "prev",
            "new": "new", "create": "new", "add": "new",
            "close": "close", "remove": "close", "del": "close",
            "task_view": "task_view", "overview": "task_view", "tab": "task_view",
            "show_desktop": "show_desktop", "desktop": "show_desktop", "min": "show_desktop",
        }
        action = action_map.get(sub_arg)
        if action:
            try:
                res = await agent.switch_desktop(action)
                ok = res.get("ok", False)
                msg = res.get("msg", "Action completed")
                active = res.get("active_window", "")
                icon = "✅" if ok else "❌"
                await update.effective_message.reply_text(
                    f"{icon} <b>Virtual Desktop — {html.escape(label)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Status: <code>{html.escape(msg)}</code>\n"
                    f"🖥️ <b>Active Window:</b> <code>{html.escape(active[:50])}</code>",
                    reply_markup=get_desktop_keyboard(),
                    parse_mode="HTML"
                )
                return
            except Exception as e:
                await update.effective_message.reply_text(f"❌ Error switching desktop: {e}")
                return

    try:
        st = await agent.status()
        win = html.escape(st.get("active_window", "Desktop")[:50])
    except Exception:
        win = "Active Desktop"

    text = (
        f"🪟 <b>DESKTOPS &amp; WINDOWS — {html.escape(label)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Switch virtual desktops or jump directly between open windows.\n\n"
        f"🖥️ <b>Active Window:</b> <code>{win}</code>\n"
        f"⌨️ <i>Hardware Shortcuts: Alt+Tab, Win+Ctrl+Arrows, Win+Tab</i>"
    )
    await update.effective_message.reply_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")


async def handle_windows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List open application windows or switch directly to a target window (/windows, /apps, /switch)."""
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    label = pc_label(context)

    # If user provided a window name or query: /switch brave, /window code, /apps spotify
    if context.args:
        target = " ".join(context.args).strip()
        try:
            res = await agent.focus_window(target)
            ok = res.get("ok", False)
            msg = res.get("msg", "Window focus requested")
            active = res.get("active_window", "")
            if ok:
                await update.effective_message.reply_text(
                    f"✅ <b>Window Switched!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 <b>Target:</b> <code>{html.escape(msg)}</code>\n"
                    f"🖥️ <b>Foreground:</b> <code>{html.escape(active[:50])}</code>",
                    parse_mode="HTML"
                )
            else:
                await update.effective_message.reply_text(
                    f"⚠️ <b>Window Not Found:</b> {html.escape(msg)}\n"
                    f"Send <code>/windows</code> without arguments to see all active open applications.",
                    parse_mode="HTML"
                )
            return
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error switching window: {e}")
            return

    # No argument: Fetch open windows list and display keyboard
    try:
        data = await agent.get_open_windows(limit=15)
        if not data.get("ok", True) and "error" in data:
            await update.effective_message.reply_text(
                f"❌ <b>Error Fetching Windows — {html.escape(label)}</b>\n\n"
                f"<code>{html.escape(str(data.get('error', 'Could not reach agent')))}</code>",
                reply_markup=get_desktop_keyboard(),
                parse_mode="HTML"
            )
            return

        wins = data.get("windows", [])
        active = data.get("active_window", "Desktop")
        if not wins:
            await update.effective_message.reply_text(
                f"🪟 <b>NO OPEN WINDOWS FOUND — {html.escape(label)}</b>\n\n"
                f"All application windows may be minimized or hidden.",
                reply_markup=get_desktop_keyboard(),
                parse_mode="HTML"
            )
            return

        text = (
            f"🗂️ <b>OPEN APPLICATIONS — {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Tap any window below to bring it directly to the foreground:\n\n"
            f"🖥️ <b>Active Window:</b> <code>{html.escape(active[:50])}</code>\n"
            f"📊 <b>Total Visible Windows:</b> {len(wins)}"
        )
        await update.effective_message.reply_text(
            text,
            reply_markup=get_windows_picker_keyboard(wins),
            parse_mode="HTML"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error listing open windows: {e}")


async def execute_cast_web_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    label = pc_label(context)
    if update.callback_query:
        sent_msg = await update.callback_query.edit_message_text(
            f"⏳ <i>Starting web cast & securing Cloudflare global tunnel for <b>{html.escape(label)}</b>...</i>",
            parse_mode="HTML"
        )
    else:
        sent_msg = await update.effective_message.reply_text(
            f"⏳ <i>Starting web cast & securing Cloudflare global tunnel for <b>{html.escape(label)}</b>...</i>",
            parse_mode="HTML"
        )

    try:
        res = await agent.cast_web_start()
        lan_url = res.get("lan_url", "")
        public_url = res.get("public_url", "")
        token = res.get("token", "")

        # If Cloudflare tunnel handshake is still in progress, poll for up to 8s
        if not public_url:
            for _ in range(5):
                await asyncio.sleep(1.5)
                st = await agent.cast_status()
                if st.get("public_url"):
                    public_url = st.get("public_url")
                    break

        url_section = ""
        buttons = []
        if public_url:
            url_section += f"🌍 <b>Global Stream & Ghost Trackpad:</b>\n<code>{public_url}</code>\n\n"
            from telegram import WebAppInfo
            buttons.append([
                InlineKeyboardButton("🖱️ Open Ghost Mouse (TMA)", web_app=WebAppInfo(url=public_url)),
                InlineKeyboardButton("🌍 Open in Browser", url=public_url),
            ])
        else:
            url_section += (
                "⚠️ <b>Global Tunnel:</b> <i>Establishing Cloudflare edge connection...</i>\n"
                "<i>Click '🔄 Refresh Link' below in a few seconds or use local link.</i>\n\n"
            )

        if lan_url:
            url_section += f"🏠 <b>Local LAN Stream:</b>\n<code>{lan_url}</code>\n\n"
            buttons.append([InlineKeyboardButton("🏠 Open Local Stream", url=lan_url)])

        buttons.append([
            InlineKeyboardButton("🪟 Switch Desktops", callback_data="cb_desktop_menu"),
            InlineKeyboardButton("🔄 Refresh Link", callback_data="cb_cast_web_start"),
        ])
        buttons.append([
            InlineKeyboardButton("⏹️ Stop Stream", callback_data="cb_cast_web_stop"),
            InlineKeyboardButton("🔙 Cast Menu", callback_data="cb_cast_menu"),
        ])
        kb = InlineKeyboardMarkup(buttons)

        msg_text = (
            f"📺 <b>WEB CAST ONLINE — {html.escape(label)}</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{url_section}"
            f"🔒 <b>Token:</b> <code>{token}</code>\n"
            f"⚡ <b>Engine:</b> <code>MJPEG + Turbo Snapshot</code>\n"
            f"🪟 <b>Features:</b> Ghost Mouse Trackpad, Phone Direct Typing, Desktops"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(msg_text, reply_markup=kb, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(msg_text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        err = f"❌ Web cast failed: {e}"
        if update.callback_query:
            await update.callback_query.edit_message_text(err)
        else:
            await update.effective_message.reply_text(err)


async def execute_cast_radar_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    chat_id = update.effective_chat.id
    if chat_id in active_radar_tasks:
        active_radar_tasks.pop(chat_id).cancel()

    try:
        frame_bytes = await agent.cast_frame(65, 960)
        stats = await agent.status()
        label = pc_label(context)
        win = html.escape(stats.get("active_window", "Desktop")[:45])
        now_str = datetime.now().strftime("%H:%M:%S")

        caption = (
            f"🔴 <b>LIVE RADAR — {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪟 <b>Window:</b> <code>{win}</code>\n"
            f"🕒 <code>{now_str}</code> | Frame <code>1/30</code>\n"
            f"💻 CPU <code>{stats['cpu_percent']}%</code> | RAM <code>{stats['memory_percent']}%</code>\n\n"
            f"📡 <i>Updating every 2s...</i>"
        )
        msg = await update.effective_chat.send_photo(
            photo=frame_bytes, caption=caption,
            reply_markup=get_radar_keyboard(), parse_mode="HTML"
        )
        task = asyncio.create_task(_run_radar_loop(chat_id, msg.message_id, context, agent))
        active_radar_tasks[chat_id] = task
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Radar failed: {e}")


async def _run_radar_loop(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE, agent: AgentClient, max_frames: int = 30):
    label = pc_label(context)
    try:
        for frame_num in range(2, max_frames + 1):
            await asyncio.sleep(2.0)
            try:
                frame_bytes = await agent.cast_frame(60, 960)
                stats = await agent.status()
                win = html.escape(stats.get("active_window", "Desktop")[:45])
                now_str = datetime.now().strftime("%H:%M:%S")
                caption = (
                    f"🔴 <b>LIVE RADAR — {html.escape(label)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪟 <b>Window:</b> <code>{win}</code>\n"
                    f"🕒 <code>{now_str}</code> | Frame <code>{frame_num}/{max_frames}</code>\n"
                    f"💻 CPU <code>{stats['cpu_percent']}%</code> | RAM <code>{stats['memory_percent']}%</code>\n\n"
                    f"📡 <i>Updating every 2s...</i>"
                )
                await context.bot.edit_message_media(
                    chat_id=chat_id, message_id=message_id,
                    media=InputMediaPhoto(media=frame_bytes, caption=caption, parse_mode="HTML"),
                    reply_markup=get_radar_keyboard()
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_str = str(e)
                if "Message is not modified" in err_str:
                    pass
                elif "Flood control" in err_str or "retry after" in err_str.lower():
                    await asyncio.sleep(3.0)
                else:
                    logger.debug(f"Radar error: {e}")

        await context.bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption=f"✅ <b>Radar for {html.escape(label)} completed.</b> (30 frames)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Restart", callback_data="cb_cast_radar_start")],
                [InlineKeyboardButton("📺 Cast Menu", callback_data="cb_cast_menu")],
            ]),
            parse_mode="HTML"
        )
    except asyncio.CancelledError:
        try:
            await context.bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id,
                caption=f"⏹️ <b>Radar for {html.escape(label)} stopped.</b>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Restart", callback_data="cb_cast_radar_start")],
                    [InlineKeyboardButton("📺 Cast Menu", callback_data="cb_cast_menu")],
                ]),
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        active_radar_tasks.pop(chat_id, None)


# ── Remote Mouse, Trackpad & Direct Phone Typing ────────────────────────

async def handle_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Type text directly into the focused PC application window."""
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_input", "Remote Typing (/type)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.effective_message.reply_text(
            "⌨️ <b>Type into PC Active Window:</b>\n"
            "Usage: <code>/type Hello from my phone!</code>\n\n"
            "<i>Whatever you type will be injected immediately into the active app, search bar, document, or terminal on your PC.</i>",
            parse_mode="HTML"
        )
        return
    text = " ".join(context.args)
    try:
        res = await agent.type_text(text)
        if res.get("ok", True):
            win = res.get("active_window", "")
            win_txt = f" into <b>{html.escape(win)}</b>" if win else ""
            await update.effective_message.reply_text(
                f"⌨️ <b>Typed{win_txt}:</b>\n<code>{html.escape(text)}</code>",
                parse_mode="HTML"
            )
        else:
            await update.effective_message.reply_text(f"❌ Typing failed: {res.get('msg', 'Unknown error')}")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Typing error: {e}")


async def handle_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simulate keypress or keyboard shortcut on PC."""
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_input", "Key Simulation (/key)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.effective_message.reply_text(
            "⌨️ <b>Send PC Key / Shortcut:</b>\n"
            "Usage: <code>/key enter</code> or <code>/key ctrl+v</code>\n\n"
            "<b>Common Keys:</b>\n"
            "• <code>/key enter</code>, <code>/key backspace</code>, <code>/key tab</code>, <code>/key esc</code>\n"
            "• <code>/key win+d</code> (Show Desktop), <code>/key win</code> (Start Menu)\n"
            "• <code>/key alt+tab</code> (Switch Window), <code>/key alt+f4</code> (Close App)\n"
            "• <code>/key ctrl+c</code>, <code>/key ctrl+v</code>, <code>/key ctrl+z</code>\n"
            "• <code>/key up</code>, <code>/key down</code>, <code>/key left</code>, <code>/key right</code>",
            parse_mode="HTML"
        )
        return
    key = context.args[0].lower().strip()
    try:
        res = await agent.press_key(key)
        if res.get("ok", True):
            await update.effective_message.reply_text(f"⌨️ <b>Key pressed:</b> <code>{html.escape(key.upper())}</code>", parse_mode="HTML")
        else:
            await update.effective_message.reply_text(f"❌ Key press failed: {res.get('msg', 'Unknown key')}")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Key press error: {e}")


async def handle_mouse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mouse control menu, quick clicks, and Ghost Trackpad launcher."""
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_input", "Remote Mouse & Touchpad (/mouse)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    label = pc_label(context)
    try:
        status = await agent.cast_status()
    except Exception:
        status = {}
    public_url = status.get("public_url", "")
    lan_url = status.get("lan_url", "")

    rows = []
    from telegram import WebAppInfo
    if public_url:
        rows.append([InlineKeyboardButton("🖱️ Open Ghost Mouse Trackpad", web_app=WebAppInfo(url=public_url))])
        rows.append([InlineKeyboardButton("🌍 Open Trackpad in Browser", url=public_url)])
        if lan_url:
            rows.append([InlineKeyboardButton("🏠 Open Local Stream (LAN)", url=lan_url)])
    elif lan_url:
        rows.append([InlineKeyboardButton("🌐 Launch Global Tunnel Stream", callback_data="cb_cast_web_start")])
        rows.append([InlineKeyboardButton("🏠 Open Local Trackpad (LAN)", url=lan_url)])
    else:
        rows.append([InlineKeyboardButton("🌐 Launch Ghost Trackpad Stream", callback_data="cb_cast_web_start")])

    rows.append([
        InlineKeyboardButton("🖱️ Left Click", callback_data="cb_mouse_click_left"),
        InlineKeyboardButton("🖱️ Right Click", callback_data="cb_mouse_click_right"),
        InlineKeyboardButton("🖱️ Double Click", callback_data="cb_mouse_click_double"),
    ])
    rows.append([
        InlineKeyboardButton("🔼 Scroll Up", callback_data="cb_mouse_scroll_up"),
        InlineKeyboardButton("🔽 Scroll Down", callback_data="cb_mouse_scroll_down"),
    ])
    rows.append([
        InlineKeyboardButton("🔙 Menu", callback_data="cb_menu"),
    ])

    status_note = ""
    if public_url:
        status_note = f"\n🟢 <b>Active Trackpad Link:</b>\n<code>{public_url}</code>\n"
    elif lan_url:
        status_note = f"\n🟡 <b>LAN Active:</b> <code>{lan_url}</code>\n"
    else:
        status_note = "\n⚪ <i>Tap 'Launch Ghost Trackpad Stream' below to activate web surface.</i>\n"

    text = (
        f"🖱️ <b>REMOTE MOUSE &amp; TOUCHPAD — {html.escape(label)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Use your phone as a full-screen trackpad with translucent desktop view.{status_note}\n"
        f"• <b>Ghost Trackpad:</b> Gliding thumb moves PC cursor over faint desktop.\n"
        f"• <b>Direct Phone Typing:</b> Tap phone input field to type with voice &amp; autocorrect.\n"
        f"• <b>In-Chat Quick Typing:</b> <code>/type &lt;message&gt;</code>\n"
        f"• <b>In-Chat Hotkeys:</b> <code>/key &lt;enter|ctrl+v|win+d&gt;</code>"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")


# ── TTS, Processes, Kill, Open, CMD, Files, Clipboard ──────────────────

async def handle_say(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_media", "Text-to-Speech (/say)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/say Hello!</code>", parse_mode="HTML")
        return
    text = " ".join(context.args)
    try:
        ok = await agent.speak(text)
        if ok:
            await update.message.reply_text(f"🗣️ <i>Spoken on {html.escape(pc_label(context))}:</i> \"{html.escape(text)}\"", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ TTS failed.")
    except Exception as e:
        await update.message.reply_text(f"❌ TTS error: {e}")


async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    try:
        result = await agent.processes(10)
        procs = result.get("processes", [])
        label = pc_label(context)
        lines = [f"💻 <b>TOP PROCESSES — {html.escape(label)}</b>\n" + ("━" * 28)]
        for p in procs:
            safe_name = html.escape(str(p['name']))
            lines.append(f"• <code>{p['pid']}</code>: <b>{safe_name}</b> | RAM: <code>{p['mem']}%</code> | CPU: <code>{p['cpu']}%</code>")
        lines.append("\n<i>Kill via</i> <code>/kill &lt;name_or_pid&gt;</code>")
        text = "\n".join(lines)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" in str(e):
                    await update.callback_query.answer("Up to date!")
                else:
                    await update.effective_message.reply_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Process list failed: {e}")


async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/kill notepad.exe</code>", parse_mode="HTML")
        return
    try:
        result = await agent.kill_process(context.args[0])
        emoji = "✅" if result.get("success") else "⚠️"
        await update.message.reply_text(f"{emoji} {result.get('message', 'Done')}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Kill failed: {e}")


async def handle_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/open https://youtube.com</code>", parse_mode="HTML")
        return
    try:
        target = context.args[0]
        result = await agent.open_target(target)
        if result.get("success"):
            await update.message.reply_text(f"🌐 Opened on {html.escape(pc_label(context))}: <code>{html.escape(target)}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Failed to open target.")
    except Exception as e:
        await update.message.reply_text(f"❌ Open failed: {e}")


async def handle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_terminal", "Shell Execution (/cmd)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await safe_reply(update, "Usage: <code>/cmd ipconfig</code>", parse_mode="HTML")
        return
    command = " ".join(context.args)
    label = pc_label(context)
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "EXEC_CMD", label, command[:100])
    chat_id = update.effective_chat.id

    await safe_send_chat_action(context.bot, chat_id, ChatAction.TYPING)
    status_msg = await safe_reply(
        update,
        f"⚡ <i>Executing command on {html.escape(label)}...</i>\n<code>{html.escape(command[:80])}</code>",
        parse_mode="HTML"
    )
    try:
        result = await agent.run_cmd(command)
        code = result.get("exit_code", -1)
        output = result.get("output", "")
        emoji = "✅" if code == 0 else "⚠️"
        truncated = output[:3500] if len(output) > 3500 else output
        text = f"{emoji} <b>{html.escape(label)} — Code {code}:</b>\n<pre>{html.escape(truncated or '(No output)')}</pre>"
        if status_msg:
            await safe_edit_text(status_msg, text, parse_mode="HTML")
        else:
            await safe_reply(update, text, parse_mode="HTML")
    except Exception as e:
        err_text = f"❌ Command execution failed on <b>{html.escape(label)}</b>: <code>{html.escape(str(e))}</code>\n\n💡 <i>Try /net to check connectivity.</i>"
        if status_msg:
            await safe_edit_text(status_msg, err_text, parse_mode="HTML")
        else:
            await safe_reply(update, err_text, parse_mode="HTML")


async def handle_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_files", "File Access (/get)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    label = pc_label(context)
    chat_id = update.effective_chat.id
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "FILE_ACCESS", label, (context.args[0] if context.args else "browse")[:100])

    # If no path specified: open interactive remote File Explorer!
    if not context.args:
        status_msg = await update.message.reply_text("📁 <i>Opening File Explorer...</i>", parse_mode="HTML")
        try:
            data = await agent.browse_directory()
            if not data.get("ok", True) and "error" in data:
                await status_msg.edit_text(f"❌ Could not open File Explorer: {data.get('error')}")
                return
            text, reply_markup = build_file_explorer_view(context, data, page=0, label=label)
            await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            await status_msg.edit_text(f"❌ Error accessing filesystem: {e}")
        return

    target_path = " ".join(context.args).strip().strip('"').strip("'")
    status_msg = await update.message.reply_text(f"🔍 <i>Inspecting <code>{html.escape(target_path)}</code>...</i>", parse_mode="HTML")

    try:
        browse_res = await agent.browse_directory(target_path)
        # If it's a directory, open it in the interactive File Explorer!
        if browse_res.get("ok") and not browse_res.get("is_file"):
            text, reply_markup = build_file_explorer_view(context, browse_res, page=0, label=label)
            await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return

        # It's a file or direct download:
        await status_msg.edit_text(f"📤 <i>Fetching file from {html.escape(label)}...</i>", parse_mode="HTML")
        content, filename = await agent.get_file(target_path, chat_id=chat_id)
        if filename == "direct_upload":
            try:
                await status_msg.delete()
            except Exception:
                pass
            return

        size_mb = len(content) / (1024 * 1024)
        await update.effective_chat.send_document(
            document=content,
            filename=filename,
            caption=f"📄 <b>File from {html.escape(label)}:</b> <code>{html.escape(filename)}</code>\n💾 <code>{size_mb:.2f} MB</code>",
            parse_mode="HTML"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        err_msg = str(e)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Open File Explorer", callback_data="cb_fs_menu")],
            [InlineKeyboardButton("🏠 Quick Access", callback_data="cb_fs_qa")],
        ])
        await status_msg.edit_text(
            f"❌ <b>File Explorer Error — {html.escape(label)}</b>\n\n"
            f"Could not open or download <code>{html.escape(target_path)}</code>:\n"
            f"<i>{html.escape(err_msg)}</i>\n\n"
            f"💡 <i>Tip: Send <code>/get</code> or <code>/files</code> without arguments to explore folders interactively!</i>",
            reply_markup=kb,
            parse_mode="HTML"
        )


async def handle_clip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        return await handle_getclip(update, context)
    text = " ".join(context.args)
    try:
        ok = await agent.set_clipboard(text)
        if ok:
            await update.message.reply_text(f"📋 <b>Copied to {html.escape(pc_label(context))}!</b>\n<pre>{html.escape(text)}</pre>", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Clipboard set failed.")
    except Exception as e:
        await update.message.reply_text(f"❌ Clipboard error: {e}")


async def handle_getclip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    try:
        content = await agent.get_clipboard()
        label = pc_label(context)
        await update.message.reply_text(f"📋 <b>{html.escape(label)} Clipboard:</b>\n<pre>{html.escape(content)}</pre>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Clipboard read failed: {e}")


async def handle_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    chat_id = update.effective_chat.id
    await safe_send_chat_action(context.bot, chat_id, ChatAction.TYPING)

    status_msg = None
    if not update.callback_query:
        status_msg = await safe_reply(update, f"🧹 <i>Scanning storage on {html.escape(label)}...</i>", parse_mode="HTML")

    try:
        result = await agent.clean_scan()
        candidates = result.get("candidates", [])
        if not candidates:
            text = f"🧹 <b>STORAGE CLEAN — {html.escape(label)}</b>\n\n✨ <b>Already clean! No temporary or old files found.</b>"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]])
        else:
            total_mb = round(sum(c.get("size_bytes", 0) for c in candidates) / (1024 * 1024), 2)
            count = len(candidates)
            text = (
                f"🧹 <b>STORAGE CLEANUP — {html.escape(label)}</b>\n\n"
                f"Found <b>{count}</b> file(s) ({total_mb} MB).\n\n"
                f"⚠️ <b>Delete all?</b>"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Delete ({total_mb} MB)", callback_data="cb_clean_confirm")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cb_clean_cancel"),
                 InlineKeyboardButton("🔙 Menu", callback_data="cb_menu")],
            ])
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=kb, parse_mode="HTML")
        elif status_msg:
            await safe_edit_text(status_msg, text, reply_markup=kb, parse_mode="HTML")
        else:
            await safe_reply(update, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        err = f"❌ Storage scan failed on <b>{html.escape(label)}</b>: <code>{html.escape(str(e))}</code>"
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, err, parse_mode="HTML")
        elif status_msg:
            await safe_edit_text(status_msg, err, parse_mode="HTML")
        else:
            await safe_reply(update, err, parse_mode="HTML")


async def handle_alarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_media", "Alarm Siren (/alarm)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    args = context.args
    if not args:
        try:
            info = await agent.alarm_status()
            label = pc_label(context)
            text, kb = format_alarm_text(info, label)
            await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Alarm status failed: {e}")
        return

    first_arg = args[0].lower().strip()
    if first_arg in ("cancel", "clear"):
        try:
            ok = await agent.alarm_cancel()
            await update.message.reply_text("✅ <b>Alarm cancelled.</b>" if ok else "ℹ️ No active alarm.", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
        return
    elif first_arg in ("stop", "silence", "mute"):
        try:
            ok = await agent.alarm_stop()
            await update.message.reply_text("🔕 <b>Alarm silenced.</b>" if ok else "ℹ️ No alarm ringing.", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
        return
    elif first_arg in ("now", "siren"):
        alarm_label = " ".join(args[1:]) if len(args) > 1 else "Instant Alarm"
        try:
            await agent.alarm_trigger_now(alarm_label)
            await update.message.reply_text(
                f"🚨 <b>Siren on {html.escape(pc_label(context))}!</b>\n• <code>{html.escape(alarm_label)}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔕 Silence", callback_data="cb_alarm_stop")]]),
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
        return

    raw_input = " ".join(args)
    try:
        parsed = await agent.alarm_parse_time(raw_input)
        seconds = parsed.get("seconds")
        alarm_label = parsed.get("label", "Timer")
        if not seconds or seconds <= 0:
            await update.message.reply_text("⚠️ <b>Invalid time format.</b>\nExamples: <code>/alarm 10m</code>, <code>/alarm 18:30 Dinner</code>", parse_mode="HTML")
            return
        info = await agent.alarm_set(seconds, alarm_label)
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        dur_str = f"{hours}h {mins}m {secs}s" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")
        await update.message.reply_text(
            f"⏰ <b>Alarm set on {html.escape(pc_label(context))}!</b>\n\n"
            f"• <b>Duration:</b> <code>{dur_str}</code>\n"
            f"• <b>Target:</b> <code>{info.get('target_time_str', 'N/A')}</code>\n"
            f"• <b>Label:</b> <code>{html.escape(alarm_label)}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cb_alarm_cancel")],
                [InlineKeyboardButton("⏰ Alarm Menu", callback_data="cb_alarm_menu")],
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Alarm failed: {e}")


def format_alarm_text(info: dict, label: str) -> Tuple[str, InlineKeyboardMarkup]:
    st = info.get("status", "idle")
    lines = [f"⏰ <b>ALARM — {html.escape(label)}</b>\n"]
    has_active = False
    is_ringing = False

    if st == "ringing":
        is_ringing = True
        lbl = html.escape(info.get("label", "Alarm"))
        lines.append(f"🚨 <b>RINGING!</b> Label: <code>{lbl}</code>\n")
    elif st == "scheduled":
        has_active = True
        lbl = html.escape(info.get("label", "Timer"))
        rem = info.get("time_left_str", "soon")
        tgt = info.get("target_time_str", "")
        lines.append(f"⏳ <b>ACTIVE</b> — <code>{tgt}</code> (in <b>{rem}</b>)\n• <code>{lbl}</code>\n")
    else:
        lines.append("💤 <b>No alarm scheduled</b>\n")

    lines.append(
        "💡 <code>/alarm 20m Label</code>\n"
        "• <code>/alarm 07:30 Wake up</code>"
    )
    kb = get_alarm_keyboard(has_active=has_active, is_ringing=is_ringing)
    return "\n".join(lines), kb


async def handle_stopalarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    try:
        ok_stop = await agent.alarm_stop()
        if ok_stop:
            await update.message.reply_text("🔕 <b>Alarm Silenced.</b>", parse_mode="HTML")
            return
        ok_cancel = await agent.alarm_cancel()
        if ok_cancel:
            await update.message.reply_text("✅ <b>Scheduled Alarm Cancelled.</b>", parse_mode="HTML")
            return
        await update.message.reply_text("ℹ️ No alarm ringing or active.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def handle_cancelalarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    try:
        ok = await agent.alarm_cancel()
        await update.message.reply_text("✅ <b>Cancelled.</b>" if ok else "ℹ️ No active alarm.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def handle_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    action = "on"
    if context.args:
        arg = context.args[0].lower().strip()
        if arg in ("off", "sleep", "down"):
            action = "off"
    try:
        if action == "on":
            await agent.monitor_on()
            await update.message.reply_text(f"💡 <b>Monitors on — {html.escape(pc_label(context))}</b>", parse_mode="HTML")
        else:
            await agent.monitor_off()
            await update.message.reply_text(f"🖥️ <b>Monitors off — {html.escape(pc_label(context))}</b>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Monitor control failed: {e}")


async def handle_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_power", "Workstation Lock (/lock)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    try:
        res = await agent.power_lock()
        ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
        msg = res.get("msg", "Workstation locked.") if isinstance(res, dict) else "Workstation locked."
        if ok:
            await update.message.reply_text(f"🔒 <b>{html.escape(label)} Workstation Locked</b> ✅\n<i>{html.escape(msg)}</i>", parse_mode="HTML")
        else:
            err = res.get("error", msg)
            await update.message.reply_text(f"❌ <b>Lock failed on {html.escape(label)}:</b> {html.escape(err)}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Lock error on {html.escape(label)}: {e}")


async def handle_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_power", "Put PC to Sleep (/sleep)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    try:
        res = await agent.power_sleep()
        ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
        msg = res.get("msg", "PC entering sleep mode.") if isinstance(res, dict) else "PC entering sleep mode."
        if ok:
            await update.message.reply_text(f"💤 <b>{html.escape(label)} entering sleep mode...</b>\n<i>{html.escape(msg)}</i>", parse_mode="HTML")
        else:
            err = res.get("error", msg)
            await update.message.reply_text(f"❌ <b>Sleep failed on {html.escape(label)}:</b> {html.escape(err)}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Sleep error on {html.escape(label)}: {e}")


# ── Tracking & Geolocation Dossier ─────────────────────────────────────

async def handle_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_track", "Laptop Geolocation & Wi-Fi Tracking"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    chat_id = update.effective_chat.id
    label = pc_label(context)
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "TRACK_LAPTOP", label)
    await safe_send_chat_action(context.bot, chat_id, ChatAction.FIND_LOCATION)

    loading_msg = None
    if not update.callback_query:
        loading_msg = await safe_reply(update, f"📍 <i>Acquiring real-time tracking dossier from {html.escape(label)}...</i>", parse_mode="HTML")
    else:
        try:
            await update.callback_query.edit_message_text(f"📍 <i>Acquiring real-time tracking dossier from {html.escape(label)}...</i>", parse_mode="HTML")
        except Exception:
            pass

    try:
        data = await agent.get_tracking()
        geo = data.get("geo", {})
        battery = data.get("battery", {})
        wifi = data.get("wifi", {})
        session = data.get("session_state", "Normal")
        vpn = data.get("vpn", {})
        hw_gw = data.get("hardware_gateway", {})

        lat = float(geo.get("lat", 0.0) or 0.0)
        lon = float(geo.get("lon", 0.0) or 0.0)

        city = geo.get("city") or "Unknown City"
        region = geo.get("region") or "Unknown Region"
        country = geo.get("country") or "Unknown Country"
        isp = geo.get("isp") or "Unknown ISP"
        pub_ip = geo.get("ip") or "Unknown"

        vpn_active = vpn.get("active", False)
        tunnels = vpn.get("tunnels", [])
        if vpn_active:
            vpn_str = f"• <b>VPN Status:</b> ⚠️ <b>ACTIVE TUNNEL</b> (<code>{', '.join(tunnels)}</code>)\n  └ <i>Public IP reflects VPN exit node; physical router anchor below:</i>\n"
        else:
            vpn_str = "• <b>VPN Status:</b> 🟢 Direct Connection (No VPN tunnel active)\n"

        hw_gw_mac = hw_gw.get("gateway_mac") or "N/A"
        hw_gw_ip = hw_gw.get("gateway_ip") or "N/A"
        hw_gw_iface = hw_gw.get("physical_interface") or "Default Gateway"
        hw_str = f"• <b>Router Hardware Anchor:</b> MAC <code>{hw_gw_mac}</code> (GW IP: <code>{hw_gw_ip}</code> via <code>{hw_gw_iface}</code>)\n"

        wifi_connected = wifi.get("connected", False)
        wifi_ssid = wifi.get("ssid") or ("Connected" if wifi_connected else "Ethernet / Cellular")
        wifi_bssid = wifi.get("bssid") or "N/A"
        wifi_sig = wifi.get("signal") or "N/A"
        wifi_chan = wifi.get("channel") or "N/A"

        visible = wifi.get("visible_networks", [])
        visible_str = ""
        if visible:
            v_items = [f"• <code>{v.get('ssid', 'Hidden')}</code> ({v.get('bssid', '')}) [{v.get('signal', '')}]" for v in visible[:3]]
            visible_str = "\n📶 <b>Nearby Visible Wi-Fi APs:</b>\n" + "\n".join(v_items) + "\n"

        map_links = ""
        if lat != 0.0 or lon != 0.0:
            map_links = f"• <b>Map Links:</b> <a href=\"{geo.get('google_maps', '')}\">Google Maps</a> | <a href=\"{geo.get('osm_maps', '')}\">OpenStreetMap</a>\n"

        phys_bssid_loc = geo.get("physical_bssid_location")
        phys_loc_str = ""
        pin_lat = lat
        pin_lon = lon
        if phys_bssid_loc and isinstance(phys_bssid_loc, dict):
            p_lat = float(phys_bssid_loc.get("lat", 0.0) or 0.0)
            p_lon = float(phys_bssid_loc.get("lon", 0.0) or 0.0)
            if p_lat != 0.0 or p_lon != 0.0:
                pin_lat = p_lat
                pin_lon = p_lon
                source = phys_bssid_loc.get("source", "Wi-Fi BSSID Triangulation")
                phys_loc_str = (
                    f"\n🎯 <b>HARDWARE BSSID POSITION (Anti-VPN Anchor):</b>\n"
                    f"• <b>Physical Pin:</b> <code>{p_lat:.5f}, {p_lon:.5f}</code> (<i>{source}</i>)\n"
                    f"• <b>Hardware Map:</b> <a href=\"https://www.google.com/maps?q={p_lat},{p_lon}\">Google Maps</a>\n"
                )

        text = (
            f"📍 <b>LAPTOP TRACKING DOSSIER — {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💻 <b>Device:</b> <code>{html.escape(data.get('hostname', ''))}</code> (User: <code>{html.escape(data.get('user', ''))}</code>)\n"
            f"🔋 <b>Battery:</b> <code>{html.escape(battery.get('status_str', 'N/A'))}</code>\n"
            f"🪟 <b>Session:</b> <code>{html.escape(session)}</code>\n"
            f"⏱️ <b>Uptime:</b> <code>{data.get('uptime', 'N/A')}</code>\n\n"
            f"🌐 <b>NETWORK & ROUTER ANCHORS:</b>\n"
            f"{vpn_str}"
            f"{hw_str}"
            f"• <b>Active Wi-Fi:</b> <code>{html.escape(wifi_ssid)}</code> (BSSID: <code>{html.escape(wifi_bssid)}</code>)\n"
            f"• <b>Signal / Channel:</b> <code>{html.escape(wifi_sig)}</code> (Ch: <code>{html.escape(wifi_chan)}</code>)\n"
            f"• <b>Public IP:</b> <code>{html.escape(pub_ip)}</code> (<i>{html.escape(isp)}</i>)\n\n"
            f"🗺️ <b>GEOLOCATION:</b>\n"
            f"• <b>Location:</b> <b>{html.escape(city)}, {html.escape(region)}, {html.escape(country)}</b>\n"
            f"• <b>Coordinates:</b> <code>{lat:.4f}, {lon:.4f}</code>\n"
            f"{map_links}"
            f"{phys_loc_str}"
            f"{visible_str}"
        )

        buttons = [
            [
                InlineKeyboardButton("🔄 Refresh Location", callback_data="cb_track"),
                InlineKeyboardButton("📸 Instant Photo", callback_data="cb_webcam_shot"),
            ],
            [
                InlineKeyboardButton("🚨 Emergency Lockdown", callback_data="cb_lockdown_menu"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
            ],
        ]
        track_kb = InlineKeyboardMarkup(buttons)

        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=track_kb, parse_mode="HTML")
        elif loading_msg:
            await safe_edit_text(loading_msg, text, reply_markup=track_kb, parse_mode="HTML")
        else:
            await safe_reply(update, text, reply_markup=track_kb, parse_mode="HTML")

        # Native Telegram interactive location pin (physical BSSID pin prioritised over VPN IP)
        if pin_lat != 0.0 or pin_lon != 0.0:
            try:
                await context.bot.send_location(chat_id=chat_id, latitude=pin_lat, longitude=pin_lon)
            except Exception as le:
                logger.debug(f"Could not send native Telegram map pin: {le}")

    except Exception as e:
        err_text = f"❌ Failed to track <b>{html.escape(label)}</b>: <code>{html.escape(str(e)[:250])}</code>"
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, err_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        elif loading_msg:
            await safe_edit_text(loading_msg, err_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await safe_reply(update, err_text, parse_mode="HTML")


# ── Laptop Emergency Lockdown ──────────────────────────────────────────

async def handle_lockdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_lockdown", "Emergency Anti-Theft Lockdown"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "LOCKDOWN_VIEW", label)

    if context.args:
        sub_arg = context.args[0].lower().strip()
        if sub_arg in ("off", "stop", "disarm", "disable", "cancel"):
            return await handle_unlockdown(update, context)
        elif sub_arg in ("loud", "alarm", "siren"):
            try:
                await agent.lockdown_enable(silent=False, alarm=True)
                manager_auth.record_audit(user.id if user else 0, user.username if user else "", "LOCKDOWN_ENGAGE_LOUD", label)
                await update.effective_message.reply_text(
                    f"🚨 <b>LOUD LOCKDOWN ENGAGED ON {html.escape(label)}!</b> 🚨\n"
                    f"• Workstation locked & screens blacked out.\n"
                    f"• Emergency deterrent siren active.\n"
                    f"• Intruder webcam guard armed.",
                    reply_markup=get_lockdown_keyboard(is_active=True),
                    parse_mode="HTML"
                )
                return
            except Exception as le:
                await update.effective_message.reply_text(f"❌ Lockdown failed: {le}")
                return
        elif sub_arg in ("silent", "stealth"):
            try:
                await agent.lockdown_enable(silent=True, alarm=False)
                manager_auth.record_audit(user.id if user else 0, user.username if user else "", "LOCKDOWN_ENGAGE_SILENT", label)
                await update.effective_message.reply_text(
                    f"🥷 <b>SILENT STEALTH LOCKDOWN ENGAGED ON {html.escape(label)}!</b>\n"
                    f"• Workstation locked & screens blacked out.\n"
                    f"• Silent stealth guard active (intruder photos will be captured upon breach).",
                    reply_markup=get_lockdown_keyboard(is_active=True),
                    parse_mode="HTML"
                )
                return
            except Exception as le:
                await update.effective_message.reply_text(f"❌ Lockdown failed: {le}")
                return
    try:
        st = await agent.lockdown_status()
        is_active = st.get("active", False)
        status_banner = "🚨 <b>LOCKDOWN ENGAGED & GUARD ACTIVE</b> 🚨" if is_active else "🛡️ <b>STANDBY / NORMAL OPERATION</b>"
        text = (
            f"🚨 <b>EMERGENCY LOCKDOWN CONTROL — {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Current State: {status_banner}\n\n"
            f"• <b>Loud Lockdown:</b> Instantly locks workstation, blacks out screen, sounds loud siren on PC speakers, and arms background guard to automatically re-lock and take webcam photo if unlocked.\n\n"
            f"• <b>Silent Lockdown:</b> Stealth anti-theft lockdown (no siren). Workstation is locked, screen blacked out, and guard auto-relocks on any unlock attempts while snapping intruder photos.\n\n"
            f"• <b>Disarm:</b> Unlocks guard mode, silences siren, and restores normal PC use."
        )
        kb = get_lockdown_keyboard(is_active=is_active)
        if update.callback_query:
            await safe_telegram_call(update.callback_query.edit_message_text, text, reply_markup=kb, parse_mode="HTML")
        else:
            await safe_reply(update, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lockdown status error on {html.escape(label)}: {e}")


async def handle_unlockdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_permission(update, context, "can_lockdown", "Disarm Lockdown"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "LOCKDOWN_DISARM", label)
    try:
        await agent.lockdown_disable()
        await update.effective_message.reply_text(
            f"🛡️ <b>Lockdown Disarmed on {html.escape(label)}!</b> ✅\n"
            f"• PC returned to normal operation.\n"
            f"• Alarm siren silenced and monitors restored.",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Failed to disarm lockdown on {html.escape(label)}: {e}")


# ── Over-The-Air (OTA) Remote Agent Update ─────────────────────────────

async def verify_agent_reconnect(
    agent: "AgentClient",
    chat_id: int,
    label: str,
    status_msg_id: Optional[int],
    bot_instance,
    max_wait_seconds: float = 16.0,
):
    """Asynchronously monitor agent restart and verify when it reports back online."""
    import time
    start_t = time.time()
    await asyncio.sleep(2.0)
    while (time.time() - start_t) < max_wait_seconds:
        try:
            st = await agent.status()
            if st and isinstance(st, dict) and "cpu_percent" in st:
                elapsed = time.time() - start_t
                cpu = st.get("cpu_percent", 0.0)
                ram = st.get("memory_percent", 0.0)
                confirm_text = (
                    f"✅ <b>OTA UPDATE CONFIRMED — {html.escape(label)} IS BACK ONLINE!</b> 🚀\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <b>Restart Latency:</b> <code>{elapsed:.1f}s</code>\n"
                    f"💻 <b>Live Health:</b> CPU <code>{cpu:.1f}%</code> | RAM <code>{ram:.1f}%</code>\n"
                    f"🟢 <b>Status:</b> Running updated codebase with zero errors."
                )
                if status_msg_id:
                    try:
                        await bot_instance.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_msg_id,
                            text=confirm_text,
                            parse_mode="HTML",
                        )
                        return
                    except Exception:
                        pass
                await bot_instance.send_message(chat_id=chat_id, text=confirm_text, parse_mode="HTML")
                return
        except Exception:
            pass
        await asyncio.sleep(1.5)

    timeout_text = (
        f"⏳ <b>Update Delivered to {html.escape(label)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"The agent was instructed to restart. If it hasn't reconnected yet:\n"
        f"• Check connection: <code>/net</code>\n"
        f"• To revert: <code>/update rollback</code>"
    )
    if status_msg_id:
        try:
            await bot_instance.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=timeout_text,
                parse_mode="HTML",
            )
        except Exception:
            pass


async def handle_update_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "OTA Agent Update (/update)"):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    user = update.effective_user
    chat_id = update.effective_chat.id
    import base64
    import hashlib

    # 1. Parse subcommands: /update all, /update rollback [backup_id], /update status
    if context.args:
        sub = context.args[0].lower().strip()
        if sub in ("all", "fleet", "broadcast"):
            return await handle_update_all_fleet(update, context)
        elif sub in ("rollback", "undo", "revert"):
            backup_id = context.args[1].strip() if len(context.args) > 1 else None
            manager_auth.record_audit(user.id if user else 0, user.username if user else "", "OTA_ROLLBACK", label, f"Backup: {backup_id or 'latest'}")
            rb_msg = await safe_reply(update, f"⏪ <i>Requesting code rollback on {html.escape(label)}...</i>", parse_mode="HTML")
            try:
                res = await agent.rollback_agent_update(backup_id=backup_id)
                if res.get("ok"):
                    used_b = res.get("backup_id", "previous backup")
                    restored = res.get("restored_files", [])
                    txt = (
                        f"⏪ <b>ROLLBACK INITIATED ON {html.escape(label)}!</b> ✅\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Restored From:</b> <code>{html.escape(used_b)}</code>\n"
                        f"📂 <b>Restored Files ({len(restored)}):</b> <code>{', '.join(restored)}</code>\n"
                        f"⚡ <b>Status:</b> Agent process is restarting to restored version...\n\n"
                        f"📡 <i>Verifying live reconnection...</i>"
                    )
                    await safe_edit_text(rb_msg, txt, parse_mode="HTML")
                    asyncio.create_task(
                        verify_agent_reconnect(
                            agent=agent,
                            chat_id=chat_id,
                            label=label,
                            status_msg_id=rb_msg.message_id if rb_msg else None,
                            bot_instance=context.bot,
                        )
                    )
                else:
                    err = res.get("error", "Rollback rejected")
                    await safe_edit_text(rb_msg, f"❌ <b>Rollback failed on {html.escape(label)}:</b>\n<code>{html.escape(err)}</code>", parse_mode="HTML")
            except Exception as e:
                await safe_edit_text(rb_msg, f"❌ Rollback error: {e}")
            return
        elif sub in ("status", "check", "version", "diff"):
            chk_msg = await safe_reply(update, f"🔍 <i>Inspecting codebase version on {html.escape(label)}...</i>", parse_mode="HTML")
            try:
                ver_info = await agent.get_agent_version_info()
                remote_hashes = ver_info.get("hashes", {})
                backups = ver_info.get("backups", [])

                rows = []
                diff_count = 0
                for fname in CORE_AGENT_FILES:
                    fpath = config.BASE_DIR / fname
                    if not fpath.exists():
                        continue
                    local_h = hashlib.sha256(fpath.read_bytes()).hexdigest()[:16]
                    remote_h = remote_hashes.get(fname, "missing")
                    if local_h == remote_h:
                        rows.append(f"🟢 <code>{fname}</code>: Match")
                    else:
                        diff_count += 1
                        rows.append(f"🟡 <code>{fname}</code>: Differ ({remote_h} vs local {local_h[:8]})")

                ver_status = "🟢 <b>Agent is completely UP TO DATE!</b>" if diff_count == 0 else f"🟡 <b>{diff_count} file(s) differ from Host</b> (update available)"
                bk_str = ", ".join(backups) if backups else "None"
                txt = (
                    f"🔍 <b>AGENT CODE VERSION — {html.escape(label)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{ver_status}\n\n"
                    + "\n".join(rows) + "\n\n"
                    f"💾 <b>Available Backups:</b> <code>{html.escape(bk_str)}</code>"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Push Update Now", callback_data="cb_update_agent")],
                    [InlineKeyboardButton("⏪ Rollback", callback_data="cb_update_rollback")],
                ])
                await safe_edit_text(chk_msg, txt, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                await safe_edit_text(chk_msg, f"❌ Version inspection failed: {e}")
            return

    # Standard /update execution
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "OTA_UPDATE_START", label)
    status_msg = None
    if not update.callback_query:
        status_msg = await safe_reply(update, f"📦 <i>Packaging latest core agent files for {html.escape(label)}...</i>", parse_mode="HTML")
    else:
        try:
            await update.callback_query.edit_message_text(f"📦 <i>Packaging latest core agent files for {html.escape(label)}...</i>", parse_mode="HTML")
            status_msg = update.callback_query.message
        except Exception:
            pass

    try:
        zip_bytes, packaged_files = create_agent_update_bundle()
        if not packaged_files:
            err = "❌ No update files found in project directory."
            if status_msg:
                await safe_edit_text(status_msg, err)
            else:
                await update.effective_message.reply_text(err)
            return

        b64_zip = base64.b64encode(zip_bytes).decode("ascii")
        res = await agent.push_agent_update(zip_b64=b64_zip)

        if res.get("ok"):
            text = (
                f"🔄 <b>OTA UPDATE DELIVERED TO {html.escape(label)}!</b> ✅\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Files Updated ({len(packaged_files)}):</b> <code>{', '.join(packaged_files)}</code>\n"
                f"📊 <b>Package Size:</b> <code>{len(zip_bytes) / 1024:.1f} KB</code> (Manifest & SHA-256 Verified)\n"
                f"⚡ <b>Status:</b> Zero syntax errors. Agent restarting...\n\n"
                f"📡 <i>Verifying live reconnection...</i>"
            )
            if status_msg:
                await safe_edit_text(status_msg, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
            else:
                status_msg = await safe_reply(update, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

            # Launch background verification watchdog
            asyncio.create_task(
                verify_agent_reconnect(
                    agent=agent,
                    chat_id=chat_id,
                    label=label,
                    status_msg_id=status_msg.message_id if status_msg else None,
                    bot_instance=context.bot,
                )
            )
        else:
            err_msg = res.get("error", "Update rejected")
            text = f"❌ <b>OTA update rejected by {html.escape(label)}:</b>\n<code>{html.escape(err_msg)}</code>"
            if status_msg:
                await safe_edit_text(status_msg, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
            else:
                await safe_reply(update, text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        err = f"❌ Failed to push update to <b>{html.escape(label)}</b>: <code>{html.escape(str(e)[:250])}</code>"
        if status_msg:
            await safe_edit_text(status_msg, err, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await safe_reply(update, err, parse_mode="HTML")


async def handle_update_all_fleet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not await check_owner_only(update, context, "Fleet-Wide OTA Update (/update_all)"):
        return
    user = update.effective_user
    manager_auth.record_audit(user.id if user else 0, user.username if user else "", "OTA_UPDATE_ALL_FLEET", "ALL_PCS")
    import base64
    fleet = load_fleet()
    pcs = fleet.get("pcs", [])
    if not pcs:
        await update.effective_message.reply_text("⚠️ No PCs registered in fleet.")
        return

    status_msg = await safe_reply(update, "🚀 <b>FLEET OTA BROADCAST UPDATE</b>\nPackaging files...", parse_mode="HTML")
    zip_bytes, packaged_files = create_agent_update_bundle()
    b64_zip = base64.b64encode(zip_bytes).decode("ascii")

    results = []
    for pc in pcs:
        name = pc.get("name")
        label = pc.get("label", name)
        agent = AgentClient(pc, fleet.get("secret", ""))
        try:
            res = await agent.push_agent_update(zip_b64=b64_zip)
            if res.get("ok"):
                results.append(f"• <b>{html.escape(label)}</b>: ✅ Updated & Restarting")
            else:
                results.append(f"• <b>{html.escape(label)}</b>: ❌ {html.escape(res.get('error', 'Failed'))}")
        except Exception as e:
            results.append(f"• <b>{html.escape(label)}</b>: 🔴 Offline / Failed")

    summary = (
        f"🚀 <b>FLEET OTA BROADCAST COMPLETE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Updated Files:</b> <code>{', '.join(packaged_files)}</code>\n\n"
        + "\n".join(results) + "\n\n"
        f"📡 <i>Online agents are restarting and will reconnect shortly.</i>"
    )
    await safe_edit_text(status_msg, summary, parse_mode="HTML")


# ── Incoming Files, Voice, Text ────────────────────────────────────────


async def handle_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    doc = update.message.document
    if not doc:
        return

    file_obj = await context.bot.get_file(doc.file_id)
    file_bytes = await file_obj.download_as_bytearray()
    filename = doc.file_name or "file.bin"

    caption = (update.message.caption or "").lower().strip()
    # Check if user sent a file as an OTA update
    if "/update" in caption or caption == "update":
        label = pc_label(context)
        import base64
        await update.message.reply_text(f"📦 <i>Processing OTA update file '{html.escape(filename)}' for {html.escape(label)}...</i>", parse_mode="HTML")
        if filename.endswith(".zip"):
            b64_zip = base64.b64encode(bytes(file_bytes)).decode("ascii")
            res = await agent.push_agent_update(zip_b64=b64_zip)
        elif filename.endswith(".py"):
            b64_py = base64.b64encode(bytes(file_bytes)).decode("ascii")
            res = await agent.push_agent_update(files_dict={filename: b64_py})
        else:
            await update.message.reply_text("❌ Update file must be a .py script or a .zip archive.")
            return

        if res.get("ok"):
            success_msg = await update.message.reply_text(
                f"✅ <b>OTA Update Applied on {html.escape(label)}!</b>\n"
                f"• <b>Payload:</b> <code>{html.escape(filename)}</code>\n"
                f"• <b>Status:</b> Files verified and agent process is restarting...\n\n"
                f"📡 <i>Verifying live reconnection...</i>",
                parse_mode="HTML"
            )
            chat_id = update.effective_chat.id
            asyncio.create_task(
                verify_agent_reconnect(
                    agent=agent,
                    chat_id=chat_id,
                    label=label,
                    status_msg_id=success_msg.message_id if success_msg else None,
                    bot_instance=context.bot,
                )
            )
        else:
            await update.message.reply_text(f"❌ <b>Update rejected by {html.escape(label)}:</b>\n<code>{html.escape(res.get('error', 'Unknown error'))}</code>", parse_mode="HTML")
        return

    try:
        result = await agent.upload_file(filename, bytes(file_bytes))
        label = pc_label(context)
        played_note = " 🔊 <i>Audio auto-played!</i>" if result.get("auto_played") else ""
        await update.message.reply_text(
            f"📥 <b>Saved to {html.escape(label)}!</b>\n"
            f"<b>File:</b> <code>{html.escape(filename)}</code>\n"
            f"<b>Path:</b> <code>{html.escape(result.get('path', ''))}</code>{played_note}",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Upload failed: {e}")


async def handle_incoming_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    duration = getattr(voice, 'duration', 0)
    msg = await update.message.reply_text(f"🔊 <i>Playing voice on {html.escape(pc_label(context))}...</i>", parse_mode="HTML")

    try:
        file_obj = await context.bot.get_file(voice.file_id)
        file_bytes = await file_obj.download_as_bytearray()
        ext = ".ogg" if update.message.voice else (Path(getattr(voice, 'file_name', 'audio.mp3')).suffix or ".mp3")
        filename = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"

        result = await agent.play_audio(filename, bytes(file_bytes))
        dur_label = f" ({duration}s)" if duration else ""
        if result.get("success") or result.get("ok"):
            await msg.edit_text(f"🔊 <b>Voice played on {html.escape(pc_label(context))}!</b>{dur_label}", parse_mode="HTML")
        else:
            err_msg = result.get("message") or result.get("msg") or result.get("error", "Unknown error")
            await msg.edit_text(f"⚠️ Playback issue: {html.escape(str(err_msg))}")
    except Exception as e:
        await msg.edit_text(f"❌ Voice playback failed: {e}")


async def handle_incoming_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    text = update.message.text
    if not text:
        return

    # ── Check for Pending PC Rename ──
    rename_target = context.user_data.get("awaiting_pc_rename")
    if rename_target:
        new_label = text.strip()
        if new_label.lower() in ("/cancel", "cancel"):
            context.user_data.pop("awaiting_pc_rename", None)
            await update.message.reply_text("❌ PC renaming cancelled.", parse_mode="HTML")
            await show_pc_picker(update, context)
            return

        if len(new_label) > 40:
            await update.message.reply_text("⚠️ Name too long (max 40 characters). Please send a shorter name:", parse_mode="HTML")
            return

        fleet = load_fleet()
        updated = False
        for pc in fleet.get("pcs", []):
            if pc["name"].lower() == rename_target.lower():
                pc["label"] = new_label
                updated = True
                break

        if updated:
            save_fleet(fleet)
            context.user_data.pop("awaiting_pc_rename", None)
            if context.user_data.get("selected_pc", {}).get("name", "").lower() == rename_target.lower():
                context.user_data["selected_pc"]["label"] = new_label

            await update.message.reply_text(
                f"✨ <b>PC RENAMED SUCCESSFULLY</b> ✅\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• PC (<code>{rename_target}</code>) is now labeled:\n"
                f"👉 <b>{html.escape(new_label)}</b>\n\n"
                f"<i>This custom name will now appear on all buttons and menus.</i>",
                parse_mode="HTML"
            )
            await show_pc_picker(update, context)
            return
        else:
            context.user_data.pop("awaiting_pc_rename", None)
            await update.message.reply_text(f"❌ PC '<code>{html.escape(rename_target)}</code>' was not found in fleet.", parse_mode="HTML")
            return

    agent = get_agent(context)
    if not agent:
        return
    try:
        ok = await agent.speak(text)
        if ok:
            await update.message.reply_text(f"🗣️ <i>Spoken on {html.escape(pc_label(context))}:</i>\n\"{html.escape(text)}\"", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ TTS failed.")
    except Exception as e:
        await update.message.reply_text(f"❌ TTS error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#   RESILIENT TELEGRAM CALLS & NETWORK SHIELD
# ═══════════════════════════════════════════════════════════════════════

async def safe_telegram_call(coro_fn, *args, retries: int = 3, **kwargs) -> Any:
    """
    Execute a Telegram API coroutine with automatic retry and backoff
    for transient network errors (TimedOut, NetworkError, RetryAfter).
    Prevents bot from failing to respond under bad/unstable internet conditions.
    """
    for attempt in range(1, retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except telegram.error.RetryAfter as e:
            wait_time = max(float(e.retry_after), 1.0) + 0.5
            logger.warning(f"Telegram flood control: waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                return None
            raise
        except (telegram.error.TimedOut, telegram.error.NetworkError) as e:
            if attempt == retries:
                logger.error(f"Telegram API call failed after {retries} retries: {e}")
                raise
            backoff = 1.0 * (1.5 ** (attempt - 1))
            logger.warning(f"Telegram network glitch ({e}). Retrying in {backoff:.1f}s (attempt {attempt}/{retries})...")
            await asyncio.sleep(backoff)
        except Exception:
            raise


async def safe_reply(update: Update, text: str, **kwargs) -> Optional[Any]:
    """Safely reply to an update message with retries."""
    if not update or not update.effective_message:
        return None
    try:
        return await safe_telegram_call(update.effective_message.reply_text, text, **kwargs)
    except Exception as e:
        logger.error(f"safe_reply failed: {e}")
        return None


async def safe_edit_text(message: Any, text: str, **kwargs) -> Optional[Any]:
    """Safely edit a message with retries."""
    if not message:
        return None
    try:
        return await safe_telegram_call(message.edit_text, text, **kwargs)
    except Exception as e:
        logger.error(f"safe_edit_text failed: {e}")
        return None


async def safe_send_photo(bot, chat_id: int, photo: Any, **kwargs) -> Optional[Any]:
    """Safely send photo with retries."""
    try:
        return await safe_telegram_call(bot.send_photo, chat_id=chat_id, photo=photo, **kwargs)
    except Exception as e:
        logger.error(f"safe_send_photo failed: {e}")
        return None


async def safe_send_message(bot, chat_id: int, text: str, **kwargs) -> Optional[Any]:
    """Safely send message with retries."""
    try:
        return await safe_telegram_call(bot.send_message, chat_id=chat_id, text=text, **kwargs)
    except Exception as e:
        logger.error(f"safe_send_message failed: {e}")
        return None


async def safe_send_chat_action(bot, chat_id: int, action: str):
    """Safely send chat action without raising on network glitches."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action=action)
    except Exception:
        pass


async def handle_net(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Network connection diagnostics: checks latency, broker, and local agent."""
    if not await check_access(update, context):
        return

    chat_id = update.effective_chat.id
    await safe_send_chat_action(context.bot, chat_id, ChatAction.TYPING)
    status_msg = await safe_reply(update, "📡 <i>Running network diagnostics...</i>", parse_mode="HTML")

    # 1. Measure Telegram API roundtrip latency
    t0 = time.time()
    tg_ok = False
    tg_ms = 0
    try:
        await context.bot.get_me()
        tg_ms = int((time.time() - t0) * 1000)
        tg_ok = True
    except Exception:
        tg_ms = int((time.time() - t0) * 1000)

    # 2. Check Cloud Relay (MQTT) status
    relay_status = "Disconnected 🔴"
    broker_info = "N/A"
    online_pcs = 0
    if commander_relay:
        broker_info = f"{commander_relay.broker}:{commander_relay.port}"
        if commander_relay.is_connected:
            relay_status = "Connected 🟢"
            pcs = commander_relay.get_pc_list()
            online_pcs = sum(1 for p in pcs.values() if p.get("status") == "online")
        else:
            relay_status = "Reconnecting 🟡"

    # 3. Check selected PC / Local Agent latency
    agent = get_agent(context)
    pc_name = pc_label(context)
    agent_status = "Unknown ⚪"
    agent_ms = 0
    if agent:
        t_agent = time.time()
        try:
            h = await agent.health()
            agent_ms = int((time.time() - t_agent) * 1000)
            if h:
                net_type = h.get("network", "Online")
                agent_status = f"Online 🟢 ({agent_ms}ms) [{net_type}]"
            else:
                agent_status = "Offline / Unreachable 🔴"
        except Exception as e:
            agent_status = f"Error 🔴 ({e})"

    # Rating
    if tg_ok and tg_ms < 250:
        overall = "🟢 <b>Optimal Connection</b>"
    elif tg_ok and tg_ms < 700:
        overall = "🟡 <b>Moderate Latency (Jitter / Mobile Data)</b>"
    elif tg_ok:
        overall = "🟠 <b>High Latency / Slow Connection</b>"
    else:
        overall = "🔴 <b>Severely Degraded Connection</b>"

    text = (
        f"🌐 <b>NETWORK CONNECTIVITY DIAGNOSTICS</b>\n"
        f"{'━' * 32}\n\n"
        f"📊 <b>Connection Health:</b> {overall}\n\n"
        f"✈️ <b>Telegram API Ping:</b> <code>{tg_ms} ms</code> {'🟢' if tg_ok and tg_ms < 300 else ('🟡' if tg_ok else '🔴')}\n"
        f"☁️ <b>Cloud Relay:</b> {relay_status}\n"
        f"   • <b>Broker:</b> <code>{broker_info}</code>\n"
        f"   • <b>Fleet PCs Online:</b> <code>{online_pcs}</code>\n\n"
        f"🖥️ <b>Target PC ({html.escape(pc_name)}):</b>\n"
        f"   • <b>Status:</b> {agent_status}\n\n"
        f"🛡️ <i>Sentinel Anti-Timeout Shield is Active:</i>\n"
        f"• Auto-retry on packet loss (up to 3x)\n"
        f"• HTTP timeouts extended to 60s\n"
        f"• Direct local HTTP routing prioritized\n"
        f"• Automatic screenshot JPEG compression"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Re-test Ping", callback_data="cb_net_ping")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
    ])

    if status_msg:
        await safe_edit_text(status_msg, text, reply_markup=kb, parse_mode="HTML")
    else:
        await safe_reply(update, text, reply_markup=kb, parse_mode="HTML")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if not err:
        return
    err_str = str(err)
    err_type = type(err).__name__

    # Network hiccups on unstable internet — log gently and avoid crashing/spamming
    if "TimedOut" in err_type or "NetworkError" in err_type or "ConnectError" in err_str:
        logger.warning(f"Telegram network latency hiccup (auto-retrying): {err}")
        return

    logger.error(f"Exception while handling update: {err}")
    if isinstance(update, Update):
        if update.callback_query:
            try:
                await update.callback_query.answer("⚠️ Request delayed by network.")
            except Exception:
                pass
        if update.effective_message:
            try:
                if "Message is not modified" not in err_str:
                    await update.effective_message.reply_text(f"⚠️ <code>{html.escape(err_str[:300])}</code>", parse_mode="HTML")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#   CALLBACK QUERY ROUTER
# ═══════════════════════════════════════════════════════════════════════

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer()
    except Exception:
        pass

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("⛔ Unauthorized.")
        return

    # Allow fleet picker without PIN (but not PC commands)
    data = query.data

    if data == "cb_net_ping":
        await handle_net(update, context)
        return

    if config.BOT_PIN and not is_authenticated(query.from_user.id):
        # Allow fleet navigation even when locked
        if data not in ("fleet_picker", "fleet_refresh", "fleet_overview", "fleet_rename_menu") and not data.startswith("pc_select_") and not data.startswith("cb_rename_pick_"):
            await query.answer("🔒 Locked. Send /login <PIN>", show_alert=True)
            return

    # ── Manager Delegation Callbacks ──────────────────────────────
    if data == "cb_mgr_list":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        await handle_managers(update, context)
        return

    if data == "cb_mgr_audit":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        await handle_audit(update, context)
        return

    if data == "cb_mgr_invite_quick":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        token = manager_auth.create_invite(role="manager", allowed_pcs=["*"], created_by=query.from_user.id)
        bot_info = await context.bot.get_me()
        inv_url = f"https://t.me/{bot_info.username}?start={token}"
        msg = (
            f"🎟️ <b>SINGLE-USE MANAGER INVITE CREATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Link:</b> <code>{inv_url}</code>\n\n"
            f"Forward this link to the manager you want to onboard."
        )
        await query.message.reply_text(msg, parse_mode="HTML")
        return

    if data.startswith("cb_mgr_view_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        mgr_uid = int(data.split("_")[-1])
        mgr = manager_auth.get_manager(mgr_uid)
        if not mgr:
            await query.answer("Manager not found", show_alert=True)
            return
        name = mgr.get("display_name") or mgr.get("username") or str(mgr_uid)
        role = mgr.get("role", "manager").upper()
        pcs = mgr.get("allowed_pcs", ["*"])
        pc_str = "All PCs (*)" if "*" in pcs else ", ".join(pcs)
        added_at = mgr.get("added_at", "Unknown")[:10]
        text = (
            f"👤 <b>MANAGER PROFILE: {html.escape(name)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Telegram ID:</b> <code>{mgr_uid}</code>\n"
            f"🛡️ <b>Role:</b> <code>{role}</code>\n"
            f"🖥️ <b>Allowed Devices:</b> <code>{html.escape(pc_str)}</code>\n"
            f"📅 <b>Added:</b> <code>{added_at}</code>\n\n"
            f"<i>Tap below to toggle granular capabilities:</i>"
        )
        kb = get_manager_detail_keyboard(mgr_uid)
        await safe_telegram_call(query.edit_message_text, text, reply_markup=kb, parse_mode="HTML")
        return

    if data.startswith("cb_mgr_tog_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        parts = data.split("_")
        mgr_uid = int(parts[3])
        perm_key = "_".join(parts[4:])
        new_val = manager_auth.toggle_permission(mgr_uid, perm_key)
        await query.answer(f"{perm_key}: {'Enabled' if new_val else 'Disabled'}")
        kb = get_manager_detail_keyboard(mgr_uid)
        await safe_telegram_call(query.edit_message_reply_markup, reply_markup=kb)
        return

    if data.startswith("cb_mgr_del_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        mgr_uid = int(data.split("_")[-1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ Yes, Revoke and Wipe", callback_data=f"cb_mgr_delyes_{mgr_uid}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cb_mgr_list")],
        ])
        await safe_telegram_call(query.edit_message_text, f"⚠️ <b>Are you sure you want to revoke Manager ID {mgr_uid}?</b>\n\nThis will revoke their access, delete the bot menu button, and wipe commands on their device.", reply_markup=kb, parse_mode="HTML")
        return

    if data.startswith("cb_mgr_delyes_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        mgr_uid = int(data.split("_")[-1])
        await execute_remove_manager(mgr_uid, context.bot)
        await query.answer("Manager revoked successfully!", show_alert=True)
        await handle_managers(update, context)
        return

    # ── Fleet Navigation ──────────────────────────────────────────
    if data == "fleet_picker":
        context.user_data.pop("selected_pc", None)
        await show_pc_picker(update, context)
        return

    if data == "fleet_refresh":
        await show_pc_picker(update, context)
        return

    if data == "fleet_rename_menu":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        await show_rename_menu(update, context)
        return

    if data.startswith("cb_rename_pick_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        idx = int(data.split("_")[-1])
        fleet = load_fleet()
        if idx < len(fleet["pcs"]):
            target_pc = fleet["pcs"][idx]
            context.user_data["awaiting_pc_rename"] = target_pc["name"]
            label = target_pc.get("label", target_pc["name"])
            prompt_text = (
                f"✏️ <b>RENAME PC: {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Hostname: <code>{html.escape(target_pc['name'])}</code>\n\n"
                f"Please <b>type and send the new name</b> for this PC in this chat:\n"
                f"<i>(e.g., 'Front Desk PC', 'Gaming Rig', 'Living Room Laptop')</i>\n\n"
                f"<i>Send /cancel to abort.</i>"
            )
            cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="fleet_picker")]])
            await query.edit_message_text(prompt_text, reply_markup=cancel_kb, parse_mode="HTML")
        return

    if data == "cb_rename_current":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        pc = get_selected_pc(context)
        if pc:
            context.user_data["awaiting_pc_rename"] = pc["name"]
            label = pc.get("label", pc["name"])
            prompt_text = (
                f"✏️ <b>RENAME PC: {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Hostname: <code>{html.escape(pc['name'])}</code>\n\n"
                f"Please <b>type and send the new name</b> for this PC in this chat:\n"
                f"<i>(e.g., 'Office Workstation', 'Gaming Rig')</i>\n\n"
                f"<i>Send /cancel to abort.</i>"
            )
            cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cb_menu")]])
            await query.edit_message_text(prompt_text, reply_markup=cancel_kb, parse_mode="HTML")
        else:
            await show_pc_picker(update, context)
        return

    if data == "fleet_overview":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        fleet = load_fleet()
        health = await check_fleet_health(fleet)
        lines = ["📊 <b>FLEET OVERVIEW</b>\n" + "━" * 28]
        for pc in fleet["pcs"]:
            name = pc["name"]
            label = pc.get("label", name)
            online = health.get(name, False)
            status_emoji = "🟢 Online" if online else "🔴 Offline"
            lines.append(f"• <b>{html.escape(label)}</b>: {status_emoji} (<code>{pc['ip']}:{pc.get('port', 9010)}</code>)")
        text = "\n".join(lines)
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to PC List", callback_data="fleet_picker")],
            ]),
            parse_mode="HTML"
        )
        return

    if data.startswith("pc_select_"):
        idx = int(data.split("_")[-1])
        fleet = load_fleet()
        if idx < len(fleet["pcs"]):
            pc = fleet["pcs"][idx]
            if not manager_auth.can_manage_pc(query.from_user.id, pc["name"]):
                await query.answer("⛔ Access to this device is restricted for your account.", show_alert=True)
                return
            context.user_data["selected_pc"] = pc
            label = pc.get("label", pc["name"])

            # Check if online
            agent = AgentClient(pc, fleet.get("secret", ""))
            health = await agent.health()
            if not health:
                offline_buttons = [
                    [InlineKeyboardButton("🔄 Retry", callback_data=data)],
                    [InlineKeyboardButton("🔙 Back to PC List", callback_data="fleet_picker")],
                ]
                if not pc.get("is_host") and manager_auth.is_owner(query.from_user.id):
                    offline_buttons.insert(1, [InlineKeyboardButton("🗑️ Remove PC from Fleet", callback_data=f"cb_del_pc_{pc['name']}")])

                await query.edit_message_text(
                    f"🔴 <b>{html.escape(label)} is OFFLINE</b>\n\n"
                    f"Cannot connect to <code>{pc['ip']}:{pc.get('port', 9010)}</code>.\n"
                    f"Make sure the PC is on and the agent is running.\n\n"
                    f"<i>If you uninstalled Sentinel from this PC, tap below to remove it:</i>",
                    reply_markup=InlineKeyboardMarkup(offline_buttons),
                    parse_mode="HTML"
                )
                return

            try:
                stats = await agent.status()
                text = (
                    f"🛡️ <b>CONTROLLING: {html.escape(label)}</b> ⚡\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💻 <b>CPU:</b> <code>{stats['cpu_percent']:.1f}%</code>\n"
                    f"🧠 <b>RAM:</b> <code>{stats['memory_percent']:.1f}%</code> "
                    f"({stats['memory_used_gb']} / {stats['memory_total_gb']} GB)\n"
                    f"⏱️ <b>Uptime:</b> <code>{stats['uptime']}</code>\n"
                    f"🪟 <b>Session:</b> <code>{stats.get('session_state', 'Normal')}</code>\n\n"
                    f"<i>Tap below to control this PC:</i>"
                )
            except Exception:
                text = (
                    f"🛡️ <b>CONTROLLING: {html.escape(label)}</b>\n\n"
                    f"<i>Connected. Tap below to control:</i>"
                )
            await query.edit_message_text(text, reply_markup=get_main_keyboard(query.from_user.id), parse_mode="HTML")
        return

    if data.startswith("cb_del_pc_"):
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        target_name = data.replace("cb_del_pc_", "")
        fleet = load_fleet()
        fleet["pcs"] = [p for p in fleet.get("pcs", []) if p["name"].lower() != target_name.lower()]
        save_fleet(fleet)
        if context.user_data.get("selected_pc", {}).get("name", "").lower() == target_name.lower():
            context.user_data.pop("selected_pc", None)
        await query.answer(f"Removed {target_name} from fleet.")
        await show_pc_picker(update, context, prompt=f"🗑️ PC '<b>{html.escape(target_name)}</b>' was removed from fleet.")
        return

    # ── PC Commands (require selected PC) ─────────────────────────

    if data == "cb_menu":
        pc = get_selected_pc(context, query.from_user.id)
        if pc:
            label = pc.get("label", pc["name"])
            await query.edit_message_text(
                f"🛡️ <b>CONTROLLING: {html.escape(label)}</b>",
                reply_markup=get_main_keyboard(query.from_user.id), parse_mode="HTML"
            )
        else:
            await show_pc_picker(update, context)
    elif data == "cb_status":
        await handle_status(update, context)
    elif data == "cb_track":
        await handle_track(update, context)
    elif data == "cb_lockdown_menu":
        await handle_lockdown(update, context)
    elif data == "cb_lockdown_loud":
        if not manager_auth.has_permission(query.from_user.id, "can_lockdown"):
            await query.answer("⛔ Permission denied: can_lockdown required", show_alert=True)
            return
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            chat_id = query.message.chat_id if query.message else None
            res = await agent.lockdown_enable(silent=False, alarm=True, chat_id=chat_id)
            await query.message.reply_text(
                f"🚨 <b>EMERGENCY LOCKDOWN ENGAGED ON {html.escape(label)}!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔒 Workstation Locked\n"
                f"🔊 Deterrent Siren Sounding\n"
                f"🖥️ Monitors Off (Blackout)\n"
                f"🛡️ Guard Worker Active (Auto-relocks & snaps intruder on unlock attempt)",
                reply_markup=get_lockdown_keyboard(is_active=True),
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Lockdown activation error: {e}")
    elif data == "cb_lockdown_silent":
        if not manager_auth.has_permission(query.from_user.id, "can_lockdown"):
            await query.answer("⛔ Permission denied: can_lockdown required", show_alert=True)
            return
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            chat_id = query.message.chat_id if query.message else None
            res = await agent.lockdown_enable(silent=True, alarm=False, chat_id=chat_id)
            await query.message.reply_text(
                f"🤫 <b>SILENT LOCKDOWN ENGAGED ON {html.escape(label)}!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔒 Workstation Locked\n"
                f"🔇 Silent Mode (No Siren)\n"
                f"🖥️ Monitors Off\n"
                f"🛡️ Guard Worker Active (Auto-relocks & snaps intruder on unlock attempt)",
                reply_markup=get_lockdown_keyboard(is_active=True),
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Lockdown activation error: {e}")
    elif data == "cb_lockdown_disarm":
        if not manager_auth.has_permission(query.from_user.id, "can_lockdown"):
            await query.answer("⛔ Permission denied: can_lockdown required", show_alert=True)
            return
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            await agent.lockdown_disable()
            await query.message.reply_text(
                f"🛡️ <b>Lockdown Disarmed on {html.escape(label)}!</b> ✅\n"
                f"• PC returned to normal operation.\n"
                f"• Siren silenced and monitors restored.",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Failed to disarm lockdown: {e}")
    elif data == "cb_update_agent":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        await handle_update_agent(update, context)
    elif data == "cb_update_rollback":
        if not manager_auth.is_owner(query.from_user.id):
            await query.answer("⛔ Restricted to Primary Fleet Owner", show_alert=True)
            return
        context.args = ["rollback"]
        await handle_update_agent(update, context)
    elif data == "cb_shot":
        if not manager_auth.has_permission(query.from_user.id, "can_screen"):
            await query.answer("⛔ Permission denied: can_screen required", show_alert=True)
            return
        await handle_screenshot(update, context)
    elif data in ("cb_webcam", "cb_webcam_menu"):
        if not manager_auth.has_permission(query.from_user.id, "can_webcam"):
            await query.answer("⛔ Permission denied: can_webcam required", show_alert=True)
            return
        label = pc_label(context)
        await query.edit_message_text(f"📷 <b>WEBCAM — {html.escape(label)}</b>", reply_markup=get_webcam_keyboard(), parse_mode="HTML")
    elif data == "cb_webcam_shot":
        if not manager_auth.has_permission(query.from_user.id, "can_webcam"):
            await query.answer("⛔ Permission denied: can_webcam required", show_alert=True)
            return
        await handle_webcam(update, context)
    elif data == "cb_rec_webcam_10":
        if not manager_auth.has_permission(query.from_user.id, "can_webcam"):
            await query.answer("⛔ Permission denied: can_webcam required", show_alert=True)
            return
        await execute_webcam_recording(update, context, duration=10)
    elif data == "cb_rec_webcam_30":
        if not manager_auth.has_permission(query.from_user.id, "can_webcam"):
            await query.answer("⛔ Permission denied: can_webcam required", show_alert=True)
            return
        await execute_webcam_recording(update, context, duration=30)
    elif data == "cb_screen_menu":
        if not manager_auth.has_permission(query.from_user.id, "can_screen"):
            await query.answer("⛔ Permission denied: can_screen required", show_alert=True)
            return
        label = pc_label(context)
        await query.edit_message_text(f"🎥 <b>SCREEN RECORDING — {html.escape(label)}</b>", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data.startswith("cb_rec_screen_"):
        if not manager_auth.has_permission(query.from_user.id, "can_screen"):
            await query.answer("⛔ Permission denied: can_screen required", show_alert=True)
            return
        sec = int(data.split("_")[-1])
        await execute_screen_recording(update, context, duration=sec)
    elif data == "cb_cast_menu":
        if not manager_auth.has_permission(query.from_user.id, "can_screen"):
            await query.answer("⛔ Permission denied: can_screen required", show_alert=True)
            return
        agent = get_agent(context)
        if not agent:
            await show_pc_picker(update, context)
            return
        try:
            status = await agent.cast_status()
            is_web = status.get("is_web_streaming", False)
            web_state = "🟢 <b>ACTIVE</b>" if is_web else "⚪ <i>Inactive</i>"
            label = pc_label(context)
            text = (
                f"📺 <b>LIVE CASTING — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Web:</b> {web_state}\n"
                f"• <b>Window:</b> <code>{html.escape(status.get('active_window', 'Desktop')[:45])}</code>"
            )
            rows = []
            if is_web:
                rows.append([InlineKeyboardButton("⏹️ Stop Web Stream", callback_data="cb_cast_web_stop")])
            else:
                rows.append([InlineKeyboardButton("🌐 Start Web Cast", callback_data="cb_cast_web_start")])
            rows.append([
                InlineKeyboardButton("⚡ In-Chat Live View", callback_data="cb_cast_radar_start"),
                InlineKeyboardButton("🪟 Switch Desktops", callback_data="cb_desktop_menu"),
            ])
            rows.append([
                InlineKeyboardButton("📡 RTMP Info", callback_data="cb_cast_rtmp_info"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
            ])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ Cast status error: {e}")
    elif data == "cb_cast_web_start":
        await execute_cast_web_start(update, context)
    elif data == "cb_cast_web_stop":
        agent = get_agent(context)
        if agent:
            try:
                await agent.cast_web_stop()
            except Exception:
                pass
        label = pc_label(context)
        await query.edit_message_text(
            f"⏹️ <b>Web Cast Stopped — {html.escape(label)}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Restart", callback_data="cb_cast_web_start"),
                 InlineKeyboardButton("🔙 Cast Menu", callback_data="cb_cast_menu")],
            ]),
            parse_mode="HTML"
        )
    elif data == "cb_cast_radar_start":
        await execute_cast_radar_start(update, context)
    elif data == "cb_cast_radar_stop":
        chat_id = update.effective_chat.id
        if chat_id in active_radar_tasks:
            active_radar_tasks.pop(chat_id).cancel()
        await query.answer("⏹️ Radar stopped.")
    elif data == "cb_cast_rtmp_info":
        await query.edit_message_text(
            "📡 <b>RTMP BROADCAST</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Stream your PC desktop to a Telegram Channel Video Chat!\n\n"
            "<code>/cast rtmp rtmps://dc4-1.rtmp.t.me/s/YOUR_KEY</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cast Menu", callback_data="cb_cast_menu")]]),
            parse_mode="HTML"
        )
    elif data == "cb_mouse_menu":
        await handle_mouse(update, context)
    elif data.startswith("cb_mouse_click_"):
        btn = data.replace("cb_mouse_click_", "")
        agent = get_agent(context)
        if agent:
            await agent.mouse_input(action="click", btn=btn)
            await query.answer(f"🖱️ {btn.capitalize()} Click")
    elif data == "cb_mouse_scroll_up":
        agent = get_agent(context)
        if agent:
            await agent.mouse_input(action="scroll", delta=120)
            await query.answer("🔼 Scrolled Up")
    elif data == "cb_mouse_scroll_down":
        agent = get_agent(context)
        if agent:
            await agent.mouse_input(action="scroll", delta=-120)
            await query.answer("🔽 Scrolled Down")
    elif data == "cb_desktop_menu":
        agent = get_agent(context)
        if not agent:
            await show_pc_picker(update, context)
            return
        label = pc_label(context)
        try:
            st = await agent.status()
            win = html.escape(st.get("active_window", "Desktop")[:50])
        except Exception:
            win = "Active Desktop"
        now_str = datetime.now().strftime("%H:%M:%S")
        text = (
            f"🪟 <b>DESKTOPS &amp; WINDOWS — {html.escape(label)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Switch virtual desktops or jump directly between open windows.\n\n"
            f"🖥️ <b>Active Window:</b> <code>{win}</code>\n"
            f"⌨️ <i>Hardware Shortcuts: Alt+Tab, Win+Ctrl+Arrows, Win+Tab</i>\n"
            f"⏱️ <i>Refreshed: {now_str}</i>"
        )
        try:
            await query.edit_message_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.debug(f"cb_desktop_menu edit error: {e}")
    elif data.startswith("cb_desktop_"):
        sub = data.replace("cb_desktop_", "")
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return

        if sub == "snap":
            await query.answer("📸 Capturing screenshot...")
            await handle_screenshot(update, context)
            return

        action_map = {
            "prev": "prev",
            "next": "next",
            "new": "new",
            "close": "close",
            "task_view": "task_view",
            "show_desktop": "show_desktop",
        }
        action = action_map.get(sub, "next")
        answered = False
        try:
            res = await agent.switch_desktop(action)
            ok = res.get("ok", False)
            msg = res.get("msg", "Desktop action triggered")
            win = res.get("active_window", "")
            toast = f"✅ {msg}" if ok else f"❌ {msg}"
            await query.answer(toast, show_alert=False)
            answered = True

            label = pc_label(context)
            if not win:
                try:
                    st = await agent.status()
                    win = st.get("active_window", "Desktop")
                except Exception:
                    win = "Active Desktop"

            now_str = datetime.now().strftime("%H:%M:%S")
            text = (
                f"🪟 <b>DESKTOPS &amp; WINDOWS — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Status: <code>{html.escape(msg)}</code>\n\n"
                f"🖥️ <b>Active Window:</b> <code>{html.escape(win[:50])}</code>\n"
                f"⌨️ <i>Hardware Shortcuts: Alt+Tab, Win+Ctrl+Arrows, Win+Tab</i>\n"
                f"⏱️ <i>Updated: {now_str}</i>"
            )
            try:
                await query.edit_message_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.debug(f"cb_desktop_ edit error: {e}")
        except Exception as e:
            if not answered:
                try:
                    await query.answer(f"❌ Error: {e}", show_alert=True)
                except Exception:
                    pass
            logger.error(f"Desktop switch callback error: {e}")
    elif data.startswith("cb_win_cycle_"):
        direction = data.replace("cb_win_cycle_", "")
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        answered = False
        try:
            res = await agent.cycle_window(direction)
            ok = res.get("ok", False)
            msg = res.get("msg", "Window cycled")
            win = res.get("active_window", "")
            toast = f"✅ {msg}" if ok else f"❌ {msg}"
            await query.answer(toast, show_alert=False)
            answered = True

            label = pc_label(context)
            if not win:
                try:
                    st = await agent.status()
                    win = st.get("active_window", "Desktop")
                except Exception:
                    win = "Active Desktop"

            now_str = datetime.now().strftime("%H:%M:%S")
            text = (
                f"🪟 <b>DESKTOPS &amp; WINDOWS — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Action: <code>{html.escape(msg)}</code>\n\n"
                f"🖥️ <b>Active Window:</b> <code>{html.escape(win[:50])}</code>\n"
                f"⌨️ <i>Hardware Shortcuts: Alt+Tab, Win+Ctrl+Arrows, Win+Tab</i>\n"
                f"⏱️ <i>Updated: {now_str}</i>"
            )
            try:
                await query.edit_message_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.debug(f"cb_win_cycle_ edit error: {e}")
        except Exception as e:
            if not answered:
                try:
                    await query.answer(f"❌ Error: {e}", show_alert=True)
                except Exception:
                    pass
            logger.error(f"Win cycle callback error: {e}")
    elif data == "cb_win_list":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        try:
            data_wins = await agent.get_open_windows(limit=15)
            await query.answer("Open windows updated 🔄", show_alert=False)
            wins = data_wins.get("windows", [])
            active = data_wins.get("active_window", "Desktop")
            label = pc_label(context)
            if not data_wins.get("ok", True) and "error" in data_wins:
                text = (
                    f"❌ <b>ERROR FETCHING WINDOWS — {html.escape(label)}</b>\n\n"
                    f"<code>{html.escape(str(data_wins.get('error')))}</code>"
                )
                try:
                    await query.edit_message_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")
                except Exception:
                    pass
                return

            if not wins:
                text = (
                    f"🪟 <b>NO OPEN WINDOWS FOUND — {html.escape(label)}</b>\n\n"
                    f"All application windows may be minimized or hidden."
                )
                try:
                    await query.edit_message_text(text, reply_markup=get_desktop_keyboard(), parse_mode="HTML")
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        logger.debug(f"cb_win_list edit error: {e}")
                return

            now_str = datetime.now().strftime("%H:%M:%S")
            text = (
                f"🗂️ <b>OPEN APPLICATIONS — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Tap any window below to bring it directly to the foreground:\n\n"
                f"🖥️ <b>Active Window:</b> <code>{html.escape(active[:50])}</code>\n"
                f"📊 <b>Total Visible Windows:</b> {len(wins)} | ⏱️ <i>{now_str}</i>"
            )
            try:
                await query.edit_message_text(text, reply_markup=get_windows_picker_keyboard(wins), parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.debug(f"cb_win_list edit error: {e}")
        except Exception as e:
            try:
                await query.answer(f"❌ Error: {e}", show_alert=True)
            except Exception:
                pass
            logger.error(f"Win list callback error: {e}")
    elif data.startswith("cb_win_focus_"):
        target_hwnd = data.replace("cb_win_focus_", "")
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        answered = False
        try:
            res = await agent.focus_window(target_hwnd)
            ok = res.get("ok", False)
            msg = res.get("msg", "Window focused")
            active = res.get("active_window", "")
            toast = f"✅ {msg}" if ok else f"❌ {msg}"
            await query.answer(toast, show_alert=False)
            answered = True

            label = pc_label(context)
            data_wins = await agent.get_open_windows(limit=15)
            wins = data_wins.get("windows", [])
            if not active:
                active = data_wins.get("active_window", "Desktop")

            now_str = datetime.now().strftime("%H:%M:%S")
            text = (
                f"🗂️ <b>OPEN APPLICATIONS — {html.escape(label)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Status: <code>{html.escape(msg)}</code>\n\n"
                f"🖥️ <b>Active Window:</b> <code>{html.escape(active[:50])}</code>\n"
                f"Tap any window below to switch to it | ⏱️ <i>{now_str}</i>:"
            )
            try:
                await query.edit_message_text(text, reply_markup=get_windows_picker_keyboard(wins), parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.debug(f"cb_win_focus_ edit error: {e}")
        except Exception as e:
            if not answered:
                try:
                    await query.answer(f"❌ Error: {e}", show_alert=True)
                except Exception:
                    pass
            logger.error(f"Win focus callback error: {e}")
    elif data == "cb_top":
        await handle_top(update, context)
    elif data == "cb_clip_menu":
        agent = get_agent(context)
        if agent:
            try:
                content = await agent.get_clipboard()
                truncated = content[:250] + ("..." if len(content) > 250 else "")
                label = pc_label(context)
                await query.edit_message_text(
                    f"📋 <b>CLIPBOARD — {html.escape(label)}</b>\n\n"
                    f"<pre>{html.escape(truncated)}</pre>\n\n"
                    f"<i>Set via:</i> <code>/clip text</code>",
                    reply_markup=get_clipboard_keyboard(), parse_mode="HTML"
                )
            except Exception:
                await query.edit_message_text("📋 <b>CLIPBOARD</b>", reply_markup=get_clipboard_keyboard(), parse_mode="HTML")
    elif data == "cb_clip_read":
        agent = get_agent(context)
        if agent:
            try:
                content = await agent.get_clipboard()
                label = pc_label(context)
                await query.message.reply_text(f"📋 <b>{html.escape(label)} Clipboard:</b>\n<pre>{html.escape(content)}</pre>", parse_mode="HTML")
            except Exception as e:
                await query.message.reply_text(f"❌ {e}")
    elif data == "cb_clean":
        await handle_clean(update, context)
    elif data == "cb_clean_confirm":
        agent = get_agent(context)
        if agent:
            try:
                result = await agent.clean_execute()
                count = result.get("deleted_count", 0)
                freed = result.get("freed_bytes", 0)
                mb = round(freed / (1024 * 1024), 2)
                label = pc_label(context)
                await query.edit_message_text(
                    f"🧹 <b>CLEANUP DONE — {html.escape(label)}</b> ✅\n\n"
                    f"• <b>Deleted:</b> <code>{count}</code> files\n"
                    f"• <b>Freed:</b> <code>{mb} MB</code>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="cb_menu")]]),
                    parse_mode="HTML"
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Cleanup failed: {e}")
    elif data == "cb_clean_cancel":
        await query.edit_message_text(
            "❌ <b>Cleanup Cancelled</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="cb_menu")]]),
            parse_mode="HTML"
        )
    elif data == "cb_tts_info":
        label = pc_label(context)
        await query.message.reply_text(
            f"🗣️ <b>TTS — {html.escape(label)}</b>\n\n"
            f"• Type any message to speak it aloud\n"
            f"• <code>/say text</code> to speak specific text\n"
            f"• Send voice notes to play through speakers",
            parse_mode="HTML"
        )
    elif data in ("cb_alarm", "cb_alarm_menu"):
        agent = get_agent(context)
        if agent:
            try:
                info = await agent.alarm_status()
                label = pc_label(context)
                text, kb = format_alarm_text(info, label)
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                await query.edit_message_text(f"❌ Alarm error: {e}")
    elif data == "cb_alarm_trigger_now":
        agent = get_agent(context)
        if agent:
            try:
                await agent.alarm_trigger_now("Instant Alert")
                await query.answer("🚨 Siren sounding!")
                info = await agent.alarm_status()
                label = pc_label(context)
                text, kb = format_alarm_text(info, label)
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
    elif data == "cb_alarm_stop":
        agent = get_agent(context)
        if agent:
            try:
                await agent.alarm_stop()
                await query.answer("🔕 Silenced!")
                info = await agent.alarm_status()
                label = pc_label(context)
                text, kb = format_alarm_text(info, label)
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
    elif data == "cb_alarm_cancel":
        agent = get_agent(context)
        if agent:
            try:
                ok = await agent.alarm_cancel()
                await query.answer("❌ Cancelled!" if ok else "ℹ️ No active alarm.")
                info = await agent.alarm_status()
                label = pc_label(context)
                text, kb = format_alarm_text(info, label)
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
    elif data.startswith("cb_alarm_set_"):
        agent = get_agent(context)
        if agent:
            secs = int(data.split("_")[-1])
            alarm_label = f"{secs // 60}m Timer" if secs >= 60 else f"{secs}s Timer"
            try:
                await agent.alarm_set(secs, alarm_label)
                await query.answer(f"⏰ Set for {alarm_label}!")
                info = await agent.alarm_status()
                label = pc_label(context)
                text, kb = format_alarm_text(info, label)
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
    elif data == "cb_power_menu":
        label = pc_label(context)
        await query.edit_message_text(f"⚡ <b>POWER — {html.escape(label)}</b>", reply_markup=get_power_keyboard(), parse_mode="HTML")
    elif data == "cb_media_menu":
        label = pc_label(context)
        await query.edit_message_text(f"🎵 <b>MEDIA — {html.escape(label)}</b>", reply_markup=get_media_keyboard(), parse_mode="HTML")
    elif data == "cb_vol_up":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("up")
            except Exception:
                pass
        await query.answer("🔊 +10%")
    elif data == "cb_vol_down":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("down")
            except Exception:
                pass
        await query.answer("🔉 -10%")
    elif data == "cb_vol_mute":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("mute")
            except Exception:
                pass
        await query.answer("🔇 Mute toggled")
    elif data == "cb_media_play_pause":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("play_pause")
            except Exception:
                pass
        await query.answer("⏯️ Play/Pause")
    elif data == "cb_media_next":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("next")
            except Exception:
                pass
        await query.answer("⏭️ Next")
    elif data == "cb_media_prev":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("prev")
            except Exception:
                pass
        await query.answer("⏮️ Prev")
    elif data == "cb_media_stop":
        agent = get_agent(context)
        if agent:
            try:
                await agent.media_control("stop")
            except Exception:
                pass
        await query.answer("⏹️ Stopped")
    elif data == "cb_pwr_sleep":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_sleep()
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            msg = res.get("msg", "PC entering sleep mode.") if isinstance(res, dict) else "PC entering sleep mode."
            if ok:
                await query.message.reply_text(f"💤 <b>{html.escape(label)} sleep mode triggered!</b>\n<i>{html.escape(msg)}</i>", parse_mode="HTML")
            else:
                err = res.get("error", msg)
                await query.message.reply_text(f"❌ <b>Sleep failed on {html.escape(label)}:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Sleep error on {html.escape(label)}: {e}")

    elif data == "cb_pwr_lock":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_lock()
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            msg = res.get("msg", "Workstation locked.") if isinstance(res, dict) else "Workstation locked."
            if ok:
                await query.message.reply_text(f"🔒 <b>{html.escape(label)} Workstation Locked</b> ✅\n<i>{html.escape(msg)}</i>", parse_mode="HTML")
            else:
                err = res.get("error", msg)
                await query.message.reply_text(f"❌ <b>Lock failed on {html.escape(label)}:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Lock error on {html.escape(label)}: {e}")

    elif data == "cb_pwr_monitor_off":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.monitor_off()
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"🖥️ <b>{html.escape(label)} monitors turned off.</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Failed to turn off monitors.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Monitor off failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Monitor off error: {e}")

    elif data == "cb_pwr_monitor_on":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.monitor_on()
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"💡 <b>{html.escape(label)} monitors powered on.</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Failed to turn on monitors.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Monitor on failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Monitor on error: {e}")

    elif data == "cb_pwr_shutdown_now":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_shutdown(0)
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"🛑 <b>{html.escape(label)} shutting down immediately...</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Shutdown failed.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Shutdown failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Shutdown error: {e}")

    elif data == "cb_pwr_shut_15":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_shutdown(900)
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"⏳ <b>{html.escape(label)} shutdown scheduled in 15 min.</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Schedule failed.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Schedule failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Shutdown schedule error: {e}")

    elif data == "cb_pwr_shut_30":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_shutdown(1800)
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"⏳ <b>{html.escape(label)} shutdown scheduled in 30 min.</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Schedule failed.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Schedule failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Shutdown schedule error: {e}")

    elif data == "cb_pwr_shut_60":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_shutdown(3600)
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"⏳ <b>{html.escape(label)} shutdown scheduled in 1 hour.</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Schedule failed.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Schedule failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Shutdown schedule error: {e}")

    elif data == "cb_pwr_shut_cancel":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            ok = await agent.power_cancel_shutdown()
            if ok:
                await query.message.reply_text(f"✅ <b>{html.escape(label)} scheduled shutdown cancelled.</b>", parse_mode="HTML")
            else:
                await query.message.reply_text("ℹ️ No scheduled shutdown active.")
        except Exception as e:
            await query.message.reply_text(f"❌ Cancel error: {e}")

    elif data == "cb_pwr_restart":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        label = pc_label(context)
        try:
            res = await agent.power_restart(5)
            ok = res.get("ok", True) if isinstance(res, dict) else bool(res)
            if ok:
                await query.message.reply_text(f"🔄 <b>{html.escape(label)} restarting in 5s...</b>", parse_mode="HTML")
            else:
                err = res.get("error", "Restart failed.") if isinstance(res, dict) else "Failed"
                await query.message.reply_text(f"❌ <b>Restart failed:</b> {html.escape(err)}", parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Restart error: {e}")


    # ── Remote File Explorer ──────────────────────────────────────
    elif data == "cb_fs_menu":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        curr_path = context.user_data.get("fs_current_path", "")
        label = pc_label(context)
        try:
            res = await agent.browse_directory(curr_path)
            if not res.get("ok", True) and "error" in res:
                res = await agent.browse_directory("")
            text, kb = build_file_explorer_view(context, res, page=0, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ Failed to open File Explorer: {e}"[:180], show_alert=True)

    elif data.startswith("cb_fs_open_"):
        idx = int(data.split("_")[-1])
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        items = context.user_data.get("fs_items", [])
        if idx >= len(items):
            await query.answer("Folder item expired. Refreshing...", show_alert=False)
            curr = context.user_data.get("fs_current_path", "")
            res = await agent.browse_directory(curr)
            text, kb = build_file_explorer_view(context, res, page=0, label=pc_label(context))
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            return

        target_item = items[idx]
        target_path = target_item.get("path")
        label = pc_label(context)
        try:
            res = await agent.browse_directory(target_path)
            if not res.get("ok", True) and "error" in res:
                await query.answer(f"❌ Cannot open folder: {res.get('error')}"[:180], show_alert=True)
                return
            text, kb = build_file_explorer_view(context, res, page=0, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ Navigation error: {e}"[:180], show_alert=True)

    elif data.startswith("cb_fs_get_"):
        idx = int(data.split("_")[-1])
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        items = context.user_data.get("fs_items", [])
        if idx >= len(items):
            await query.answer("File item expired. Please refresh.", show_alert=True)
            return
        target_item = items[idx]
        file_path = target_item.get("path", "")
        file_name = target_item.get("name", "file")
        size = target_item.get("size", 0)
        size_fmt = target_item.get("size_fmt", "")

        if size > 49.5 * 1024 * 1024:
            await query.answer(f"⚠️ {file_name} is too large ({size_fmt} exceeds 50 MB limit).", show_alert=True)
            return

        await query.answer(f"⏳ Downloading {file_name}...", show_alert=False)
        label = pc_label(context)
        status_msg = await query.message.reply_text(
            f"📤 <i>Fetching <code>{html.escape(file_name)}</code> ({size_fmt}) from {html.escape(label)}...</i>",
            parse_mode="HTML"
        )
        try:
            content, name = await agent.get_file(file_path, chat_id=query.message.chat_id)
            if name != "direct_upload":
                size_mb = len(content) / (1024 * 1024)
                await query.message.chat.send_document(
                    document=content,
                    filename=name or file_name,
                    caption=f"📄 <b>File from {html.escape(label)}:</b> <code>{html.escape(name or file_name)}</code>\n💾 <code>{size_mb:.2f} MB</code>",
                    parse_mode="HTML"
                )
            try:
                await status_msg.delete()
            except Exception:
                pass
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to download <code>{html.escape(file_name)}</code>: {e}", parse_mode="HTML")

    elif data == "cb_fs_up":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        parent_path = context.user_data.get("fs_parent_path")
        if not parent_path:
            await query.answer("Already at drive root 🔝", show_alert=False)
            return
        label = pc_label(context)
        try:
            res = await agent.browse_directory(parent_path)
            text, kb = build_file_explorer_view(context, res, page=0, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ Error moving up: {e}"[:180], show_alert=True)

    elif data.startswith("cb_fs_p_"):
        target_page = int(data.replace("cb_fs_p_", ""))
        label = pc_label(context)
        fs_data = {
            "current_path": context.user_data.get("fs_current_path", "Desktop"),
            "parent_path": context.user_data.get("fs_parent_path"),
            "items": context.user_data.get("fs_items", []),
            "drives": context.user_data.get("fs_drives", ["C:\\"]),
            "quick_access": context.user_data.get("fs_quick", {}),
        }
        text, kb = build_file_explorer_view(context, fs_data, page=target_page, label=label)
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.debug(f"cb_fs_p_ edit error: {e}")

    elif data == "cb_fs_refresh":
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        curr_path = context.user_data.get("fs_current_path", "")
        page = context.user_data.get("fs_page", 0)
        label = pc_label(context)
        try:
            res = await agent.browse_directory(curr_path)
            text, kb = build_file_explorer_view(context, res, page=page, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            await query.answer("Directory refreshed 🔄", show_alert=False)
        except Exception as e:
            await query.answer(f"❌ Refresh failed: {e}"[:180], show_alert=True)

    elif data == "cb_fs_qa":
        label = pc_label(context)
        text, kb = build_quick_access_keyboard(context, label=label)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data.startswith("cb_fs_qa_"):
        key = data.replace("cb_fs_qa_", "")
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        qa = context.user_data.get("fs_quick", {})
        target = qa.get(key)
        if key == "recordings":
            target = str(config.RECORDINGS_DIR)
        if not target:
            target = key

        label = pc_label(context)
        try:
            res = await agent.browse_directory(target)
            text, kb = build_file_explorer_view(context, res, page=0, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ Location not found: {e}"[:180], show_alert=True)

    elif data.startswith("cb_fs_drv_"):
        idx = int(data.replace("cb_fs_drv_", ""))
        agent = get_agent(context)
        if not agent:
            await query.answer("No PC selected.", show_alert=True)
            return
        drives = context.user_data.get("fs_drives", ["C:\\"])
        if idx >= len(drives):
            idx = 0
        drv = drives[idx]
        label = pc_label(context)
        try:
            res = await agent.browse_directory(drv)
            text, kb = build_file_explorer_view(context, res, page=0, label=label)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ Drive error: {e}", show_alert=True)

    elif data == "cb_fs_noop":
        await query.answer()



# ═══════════════════════════════════════════════════════════════════════
#   EVENT POLLING (alarm notifications from agents)
# ═══════════════════════════════════════════════════════════════════════

async def poll_agent_events(app: Application):
    """Periodically poll all agents for events (alarm triggers, etc.)."""
    while True:
        try:
            await asyncio.sleep(30)
            fleet = load_fleet()
            secret = fleet.get("secret", "")
            for pc in fleet["pcs"]:
                client = AgentClient(pc, secret)
                events = await client.get_events()
                for event in events:
                    if event.get("type") == "alarm_triggered":
                        pc_name = event.get("pc_name", pc["name"])
                        label = event.get("label", "Alarm")
                        time_str = event.get("time", "")
                        alert_text = (
                            f"🚨 <b>ALARM on {html.escape(pc_name)}!</b> 🚨\n\n"
                            f"• <b>Label:</b> <code>{html.escape(label)}</code>\n"
                            f"• <b>Time:</b> <code>{time_str}</code>\n\n"
                            f"🔊 <i>Siren is ringing on PC speakers!</i>"
                        )
                        for uid in config.AUTHORIZED_USER_IDS:
                            try:
                                await app.bot.send_message(chat_id=uid, text=alert_text, parse_mode="HTML")
                            except Exception:
                                pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Event poll error: {e}")


async def local_agent_watchdog():
    """Background watchdog to ensure local Host PC agent stays alive across sleep/wake."""
    if sys.platform != "win32":
        return
    while True:
        try:
            await asyncio.sleep(15)
            await asyncio.to_thread(ensure_local_agent_running)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Local agent watchdog error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════════════════════

def ensure_single_bot_instance():
    """Terminate any stale older instances of THIS bot to prevent Telegram polling conflicts."""
    import psutil
    cur_pid = os.getpid()
    cur_dir = str(config.BASE_DIR).lower()
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
        try:
            if p.pid == cur_pid or p.pid == os.getppid():
                continue
            cmdline = p.info.get('cmdline') or []
            cmd_str = " ".join(cmdline).lower()
            p_name = p.info.get('name', '').lower()
            exe_path = (p.info.get('exe') or '').lower()

            is_in_our_dir = (cur_dir in exe_path) or (cur_dir in cmd_str)
            is_our_commander = is_in_our_dir and (
                ("pc-sentinel" in p_name and "agent" not in p_name and not any("test" in a for a in cmdline))
                or any(a.lower().endswith("bot.py") for a in cmdline)
            )
            if is_our_commander:
                logger.warning(f"Terminating older conflicting bot process (PID {p.pid})...")
                p.terminate()
                p.wait(timeout=2.0)
        except Exception:
            pass


def main():
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        print("\n⚠️ Error: TELEGRAM_BOT_TOKEN is not set in .env file!")
        return

    # Terminate any duplicate bot instance to avoid Telegram Conflict errors
    ensure_single_bot_instance()

    # Auto-spawn local agent on Windows so Host PC is active immediately
    ensure_local_agent_running()

    request = HTTPXRequest(
        connection_pool_size=32,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=30.0,
    )
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )
    app.add_error_handler(error_handler)

    # Register handlers
    app.add_handler(CommandHandler(["start", "menu"], handle_start))
    app.add_handler(CommandHandler(["net", "ping", "network"], handle_net))
    app.add_handler(CommandHandler("pcs", handle_pcs))
    app.add_handler(CommandHandler("reload", handle_reload))
    app.add_handler(CommandHandler(["managers", "delegation"], handle_managers))
    app.add_handler(CommandHandler(["invite", "inv"], handle_invite))
    app.add_handler(CommandHandler(["addmanager", "addmgr"], handle_add_manager))
    app.add_handler(CommandHandler(["removemanager", "delmanager", "revokemanager"], handle_remove_manager))
    app.add_handler(CommandHandler(["audit", "auditlog"], handle_audit))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler(["shot", "screenshot"], handle_screenshot))
    app.add_handler(CommandHandler("webcam", handle_webcam))
    app.add_handler(CommandHandler("record_screen", handle_record_screen))
    app.add_handler(CommandHandler("record_webcam", handle_record_webcam))
    app.add_handler(CommandHandler(["cast", "stream"], handle_cast))
    app.add_handler(CommandHandler(["desktop", "desktops"], handle_desktop))
    app.add_handler(CommandHandler(["windows", "window", "apps", "switch"], handle_windows))
    app.add_handler(CommandHandler("login", handle_login))
    app.add_handler(CommandHandler("logout", handle_logout))
    app.add_handler(CommandHandler(["setpin", "pin"], handle_setpin))
    app.add_handler(CommandHandler(["removepin", "unsetpin", "delpin"], handle_removepin))
    app.add_handler(CommandHandler(["removepc", "deletepc", "delpc"], handle_remove_pc))
    app.add_handler(CommandHandler(["rename", "renamepc"], handle_rename))
    app.add_handler(CommandHandler(["cancel", "abort"], handle_cancel))
    app.add_handler(CommandHandler("top", handle_top))
    app.add_handler(CommandHandler("kill", handle_kill))
    app.add_handler(CommandHandler("say", handle_say))
    app.add_handler(CommandHandler("open", handle_open))
    app.add_handler(CommandHandler("cmd", handle_cmd))
    app.add_handler(CommandHandler(["get", "files", "browse", "explore"], handle_get_file))
    app.add_handler(CommandHandler("clip", handle_clip))
    app.add_handler(CommandHandler("getclip", handle_getclip))
    app.add_handler(CommandHandler("clean", handle_clean))
    app.add_handler(CommandHandler(["alarm", "timer"], handle_alarm))
    app.add_handler(CommandHandler(["stopalarm", "silence"], handle_stopalarm))
    app.add_handler(CommandHandler(["cancelalarm"], handle_cancelalarm))
    app.add_handler(CommandHandler(["lock", "lockpc"], handle_lock))
    app.add_handler(CommandHandler(["sleep", "sleeppc"], handle_sleep))
    app.add_handler(CommandHandler(["track", "locate", "gps"], handle_track))
    app.add_handler(CommandHandler(["lockdown", "panic"], handle_lockdown))
    app.add_handler(CommandHandler(["unlockdown", "disarm"], handle_unlockdown))
    app.add_handler(CommandHandler(["update", "updatepc", "ota"], handle_update_agent))
    app.add_handler(CommandHandler(["updateall", "update_all"], handle_update_all_fleet))
    app.add_handler(CommandHandler("monitor", handle_monitor))
    app.add_handler(CommandHandler(["mouse", "touchpad", "trackpad"], handle_mouse))
    app.add_handler(CommandHandler(["type", "typing", "sendtext"], handle_type))
    app.add_handler(CommandHandler(["key", "press"], handle_key))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_incoming_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_incoming_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_text))
    app.add_handler(CallbackQueryHandler(callback_router))

    async def post_init(application):
        # Initialize and start Fleet Cloud Relay
        global commander_relay
        fleet = load_fleet()
        secret = get_fleet_secret(fleet)
        broker = os.getenv("MQTT_BROKER", "broker.emqx.io").strip()
        port = int(os.getenv("MQTT_PORT", "8883"))
        use_tls = os.getenv("MQTT_USE_TLS", "true").strip().lower() in ("1", "true", "yes")

        def on_fleet_alert(alert_data: dict):
            pc_name = alert_data.get("pc_name", "Unknown PC")
            alert_type = alert_data.get("type", "")
            time_str = alert_data.get("time", "")

            if alert_type == "lockdown_breach":
                alert_text = (
                    f"🚨🚨 <b>CRITICAL SECURITY ALERT: LOCKDOWN BREACH!</b> 🚨🚨\n\n"
                    f"🖥️ <b>PC:</b> <code>{html.escape(pc_name)}</code>\n"
                    f"⏱️ <b>Time:</b> <code>{time_str}</code>\n\n"
                    f"⚠️ <i>Workstation was unlocked while under LOCKDOWN!</i>\n"
                    f"🛡️ <b>Sentinel Action:</b> Workstation was IMMEDIATELY re-locked and intruder photo captured!"
                )
            else:
                label = alert_data.get("label", "Alarm")
                alert_text = (
                    f"🚨 <b>ALARM on {html.escape(pc_name)}!</b> 🚨\n\n"
                    f"• <b>Label:</b> <code>{html.escape(label)}</code>\n"
                    f"• <b>Time:</b> <code>{time_str}</code>\n\n"
                    f"🔊 <i>Siren is ringing on PC speakers!</i>"
                )
            for uid in config.AUTHORIZED_USER_IDS:
                try:
                    asyncio.create_task(application.bot.send_message(chat_id=uid, text=alert_text, parse_mode="HTML"))
                except Exception:
                    pass

        def on_fleet_status(pc_name: str, status_data: dict, is_new: bool):
            fleet_data = load_fleet()
            known_names = {pc.get("name") for pc in fleet_data.get("pcs", [])}
            is_truly_new = pc_name not in known_names
            if is_truly_new:
                fleet_data.setdefault("pcs", []).append({
                    "name": pc_name,
                    "label": pc_name,
                    "ip": status_data.get("ip", "Unknown"),
                    "network": status_data.get("network", "Remote (Relay)"),
                })
                save_fleet(fleet_data)
                logger.info(f"Auto-registered new PC '{pc_name}' into fleet.json")

            net_desc = status_data.get("network", "Remote")
            banner = "🎉 <b>New PC Discovered!</b>" if is_truly_new else "🟢 <b>PC Reconnected!</b>"
            notice_text = (
                f"{banner}\n\n"
                f"🖥️ <b>PC Name:</b> <code>{html.escape(pc_name)}</code>\n"
                f"🌐 <b>Network:</b> <code>{html.escape(net_desc)}</code>\n"
                f"📡 <b>Status:</b> Online via Cloud Relay\n"
                f"🕒 <b>Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
                f"✨ <i>Ready to control! Send /pcs or /start to switch to this PC.</i>"
            )
            for uid in config.AUTHORIZED_USER_IDS:
                try:
                    asyncio.create_task(application.bot.send_message(chat_id=uid, text=notice_text, parse_mode="HTML"))
                except Exception as e:
                    logger.debug(f"Could not send fleet notice to {uid}: {e}")

        commander_relay = FleetCommanderRelay(
            secret=secret,
            broker=broker,
            port=port,
            use_tls=use_tls,
            on_alert_callback=on_fleet_alert,
            on_status_callback=on_fleet_status,
        )
        commander_relay.start(asyncio.get_running_loop())
        # Allow relay a brief moment to connect and ingest retained status
        await asyncio.sleep(1.2)

        cmds = [
            BotCommand("status", "System Diagnostics (CPU, RAM, Uptime)"),
            BotCommand("pcs", "Fleet Command Center & PC Switcher"),
            BotCommand("shot", "Desktop Screenshot"),
            BotCommand("cast", "Live 30 FPS Screen Stream"),
            BotCommand("mouse", "Remote Ghost Mouse & Touchpad"),
            BotCommand("type", "Type text into PC: /type [text]"),
            BotCommand("key", "Press PC key: /key [enter|ctrl+v]"),
            BotCommand("desktop", "Virtual Desktops & Task View"),
            BotCommand("windows", "Switch Open Apps: /windows [name]"),
            BotCommand("files", "Remote File Explorer & Downloads: /files [path]"),
            BotCommand("clip", "Read or Copy PC Clipboard: /clip [text]"),
            BotCommand("say", "Speak text on PC speakers: /say [text]"),
            BotCommand("webcam", "Webcam Snapshot"),
            BotCommand("record_screen", "Record Desktop Video (10s-120s)"),
            BotCommand("record_webcam", "Record Webcam Video"),
            BotCommand("alarm", "PC Alarm & Timer: /alarm [time|stop]"),
            BotCommand("track", "Anti-VPN Geolocation & Wi-Fi Tracking"),
            BotCommand("lockdown", "Emergency Laptop Lockdown: /lockdown [loud|silent|off]"),
            BotCommand("update", "OTA Code Update: /update [all|rollback|status]"),
            BotCommand("lock", "Lock Windows workstation"),
            BotCommand("sleep", "Put PC to sleep"),
            BotCommand("monitor", "Turn monitors on/off: /monitor [on|off]"),
            BotCommand("top", "Top CPU & Memory Processes"),
            BotCommand("kill", "Terminate Process: /kill [name|pid]"),
            BotCommand("clean", "Cleanup cache & temporary recordings"),
            BotCommand("open", "Open URL or App on PC: /open [url]"),
            BotCommand("cmd", "Execute Terminal Command: /cmd [command]"),
            BotCommand("net", "Network Latency & Ping Diagnostics"),
            BotCommand("managers", "Delegated Managers & Role Permissions"),
            BotCommand("invite", "Generate Manager Single-Use Invite Link"),
            BotCommand("audit", "Security Audit Trail & Manager Actions"),
            BotCommand("setpin", "Configure or Remove Security PIN: /setpin [pin|off]"),
            BotCommand("login", "Unlock Bot with PIN: /login [pin]"),
            BotCommand("logout", "Lock Bot Session"),
            BotCommand("rename", "Rename PC: /rename [new_label]"),
            BotCommand("removepc", "Remove PC from Fleet: /removepc [name]"),
            BotCommand("reload", "Reload Fleet Registry"),
        ]
        try:
            await application.bot.set_my_commands(cmds)
        except Exception:
            pass

        # Startup notification
        health = await check_fleet_health(fleet)
        online_count = sum(1 for v in health.values() if v.get("online"))

        lines = []
        for pc in fleet.get("pcs", []):
            name = pc["name"]
            label = pc.get("label", name)
            h_info = health.get(name, {})
            online = h_info.get("online", False)
            net_str = h_info.get("network", "")
            badge = f" <i>({net_str})</i>" if online and net_str else ""
            lines.append(f"{'🟢' if online else '🔴'} {html.escape(label)}{badge}")
        fleet_list = "\n".join(lines) if lines else "<i>No PCs registered yet (plug pendrive into PC to auto-add)</i>"

        startup_msg = (
            f"🛡️ <b>FLEET COMMAND CENTER ONLINE</b> ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Fleet:</b> <code>{online_count}/{len(fleet.get('pcs', []))}</code> PCs online\n"
            f"☁️ <b>Cloud Relay:</b> <code>{'Connected' if commander_relay.is_connected else 'Connecting...'}</code>\n\n"
            f"{fleet_list}\n\n"
            f"<i>Send /start to begin controlling your PCs.</i>"
        )
        for uid in config.AUTHORIZED_USER_IDS:
            try:
                await application.bot.send_message(chat_id=uid, text=startup_msg, parse_mode="HTML")
            except Exception:
                pass

        # Start event polling background task (LAN fallback)
        asyncio.create_task(poll_agent_events(application))

        # Start watchdog to keep local host agent alive across sleep/wake
        asyncio.create_task(local_agent_watchdog())

    app.post_init = post_init
    logger.info("🛡️ Fleet Commander Bot is running...")
    app.run_polling(
        poll_interval=0.5,
        timeout=30,
        bootstrap_retries=-1,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
