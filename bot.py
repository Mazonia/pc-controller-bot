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
import html
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import httpx
from loguru import logger

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    BotCommand,
    InputMediaPhoto,
)
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


# ═══════════════════════════════════════════════════════════════════════
#   FLEET MANAGEMENT & CLOUD RELAY
# ═══════════════════════════════════════════════════════════════════════

FLEET_FILE = config.BASE_DIR / "fleet.json"
commander_relay: Optional[FleetCommanderRelay] = None


def load_fleet() -> dict:
    """Load fleet configuration from fleet.json."""
    if FLEET_FILE.exists():
        try:
            return json.loads(FLEET_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load fleet.json: {e}")
    return {"secret": "", "pcs": []}


def save_fleet(fleet: dict):
    """Save fleet configuration."""
    FLEET_FILE.write_text(json.dumps(fleet, indent=4), encoding="utf-8")


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

    def is_relay_online(self) -> bool:
        """Check if PC is connected to the Cloud Relay."""
        if commander_relay and commander_relay.is_connected:
            pcs = commander_relay.get_pc_list()
            return self.name in pcs and pcs[self.name].get("status") == "online"
        return False

    def _headers(self) -> dict:
        return {"X-Agent-Secret": self.secret}

    async def _get(self, path: str, timeout: float = 15.0, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(f"{self.base_url}{path}", headers=self._headers(), **kwargs)

    async def _post(self, path: str, timeout: float = 30.0, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(f"{self.base_url}{path}", headers=self._headers(), **kwargs)

    async def health(self) -> Optional[dict]:
        if self.is_relay_online():
            info = commander_relay.get_pc_list().get(self.name, {})
            return {"status": "online", "network": info.get("network", "Remote")}
        try:
            r = await self._get("/health", timeout=3.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def status(self) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "status", timeout=12.0)
            if res.get("ok") and "stats" in res:
                return res["stats"]
        r = await self._get("/status")
        r.raise_for_status()
        return r.json()

    async def screenshot(self, chat_id: Optional[int] = None) -> Any:
        if self.is_relay_online() and chat_id:
            res = await commander_relay.send_command(self.name, "screenshot", {"chat_id": chat_id}, timeout=25.0)
            if res.get("ok"):
                return {"direct_upload": True}
        r = await self._get("/screenshot", timeout=20.0)
        r.raise_for_status()
        return r.content

    async def webcam(self, chat_id: Optional[int] = None) -> Any:
        if self.is_relay_online() and chat_id:
            res = await commander_relay.send_command(self.name, "webcam", {"chat_id": chat_id}, timeout=25.0)
            if res.get("ok"):
                return {"direct_upload": True}
        r = await self._get("/webcam", timeout=20.0)
        r.raise_for_status()
        return r.content

    async def record_screen(self, duration: int, chat_id: Optional[int] = None) -> Any:
        if self.is_relay_online() and chat_id:
            res = await commander_relay.send_command(self.name, "record_screen", {"duration": duration, "chat_id": chat_id}, timeout=duration + 35.0)
            if res.get("ok"):
                return {"direct_upload": True}
        r = await self._post(f"/record/screen?duration={duration}", timeout=duration + 30)
        r.raise_for_status()
        return r.content

    async def record_webcam(self, duration: int, chat_id: Optional[int] = None) -> Any:
        if self.is_relay_online() and chat_id:
            res = await commander_relay.send_command(self.name, "record_webcam", {"duration": duration, "chat_id": chat_id}, timeout=duration + 35.0)
            if res.get("ok"):
                return {"direct_upload": True}
        r = await self._post(f"/record/webcam?duration={duration}", timeout=duration + 30)
        r.raise_for_status()
        return r.content

    async def cast_web_start(self) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "cast_start", timeout=25.0)
            if res.get("ok"):
                return res
        r = await self._post("/cast/web/start", timeout=30.0)
        r.raise_for_status()
        return r.json()

    async def cast_web_stop(self) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "cast_stop", timeout=10.0)
            if res.get("ok"):
                return res
        r = await self._post("/cast/web/stop")
        r.raise_for_status()
        return r.json()

    async def cast_status(self) -> dict:
        try:
            r = await self._get("/cast/status", timeout=5.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {"is_web_streaming": False, "is_rtmp_streaming": False}

    async def cast_frame(self, quality: int = 60, max_width: int = 960) -> bytes:
        r = await self._get(f"/cast/frame?quality={quality}&max_width={max_width}", timeout=10.0)
        r.raise_for_status()
        return r.content

    async def cast_rtmp_start(self, url: str) -> dict:
        r = await self._post("/cast/rtmp/start", data={"url": url})
        r.raise_for_status()
        return r.json()

    async def cast_rtmp_stop(self) -> dict:
        r = await self._post("/cast/rtmp/stop")
        r.raise_for_status()
        return r.json()

    async def processes(self, count: int = 15) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "processes", {"limit": count}, timeout=12.0)
            if res.get("ok"):
                return {"processes": res.get("processes", [])}
        r = await self._get(f"/processes?count={count}")
        r.raise_for_status()
        return r.json()

    async def kill_process(self, target: str) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "kill_process", {"target": target}, timeout=10.0)
            return {"success": res.get("ok", False), "message": res.get("msg", "")}
        r = await self._post("/kill", data={"target": target})
        r.raise_for_status()
        return r.json()

    async def run_cmd(self, command: str) -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "cmd", {"command": command}, timeout=40.0)
            return {"output": res.get("output", "")}
        r = await self._post("/cmd", data={"command": command}, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def open_target(self, target: str) -> dict:
        r = await self._post("/open", data={"target": target})
        r.raise_for_status()
        return r.json()

    async def get_file(self, path: str, chat_id: Optional[int] = None) -> Tuple[bytes, str]:
        if self.is_relay_online() and chat_id:
            res = await commander_relay.send_command(self.name, "file_download", {"name": path, "chat_id": chat_id}, timeout=30.0)
            if res.get("ok"):
                return b"", "direct_upload"
        r = await self._get(f"/file?path={path}", timeout=60.0)
        r.raise_for_status()
        filename = "file"
        cd = r.headers.get("content-disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"')
        return r.content, filename

    async def upload_file(self, filename: str, content: bytes) -> dict:
        files = {"file": (filename, content)}
        r = await self._post("/upload", files=files, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def get_clipboard(self) -> str:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "clipboard_get", timeout=10.0)
            return res.get("text", "")
        r = await self._get("/clipboard")
        r.raise_for_status()
        return r.json().get("content", "")

    async def set_clipboard(self, text: str) -> bool:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "clipboard_set", {"text": text}, timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/clipboard", data={"text": text})
        r.raise_for_status()
        return r.json().get("success", False)

    async def speak(self, text: str) -> bool:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "tts", {"text": text}, timeout=15.0)
            return res.get("ok", False)
        r = await self._post("/tts", data={"text": text})
        r.raise_for_status()
        return r.json().get("success", False)

    async def play_audio(self, filename: str, content: bytes) -> dict:
        files = {"file": (filename, content)}
        r = await self._post("/play-audio", files=files, timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def power_sleep(self):
        await self._post("/power/sleep")

    async def power_lock(self):
        if self.is_relay_online():
            await commander_relay.send_command(self.name, "lock", timeout=10.0)
            return
        await self._post("/power/lock")

    async def power_shutdown(self, delay: int = 0):
        if self.is_relay_online():
            await commander_relay.send_command(self.name, "shutdown", {"delay": delay}, timeout=10.0)
            return
        await self._post(f"/power/shutdown?delay={delay}")

    async def power_restart(self, delay: int = 5):
        if self.is_relay_online():
            await commander_relay.send_command(self.name, "reboot", {"delay": delay}, timeout=10.0)
            return
        await self._post(f"/power/restart?delay={delay}")

    async def power_cancel_shutdown(self) -> bool:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "cancel_shutdown", timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/power/cancel-shutdown")
        return r.json().get("success", False)

    async def monitor_on(self):
        await self._post("/monitor/on")

    async def monitor_off(self):
        await self._post("/monitor/off")

    async def media_control(self, action: str):
        if self.is_relay_online():
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
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "alarm_stop", timeout=10.0)
            return res.get("ok", False)
        r = await self._post("/alarm/stop")
        return r.json().get("success", False)

    async def alarm_cancel(self) -> bool:
        r = await self._post("/alarm/cancel")
        return r.json().get("success", False)

    async def alarm_trigger_now(self, label: str = "Instant Alert") -> dict:
        if self.is_relay_online():
            res = await commander_relay.send_command(self.name, "alarm_start", {"duration": 30, "label": label}, timeout=10.0)
            return {"success": res.get("ok", False), "message": res.get("msg", "")}
        r = await self._post("/alarm/trigger-now", data={"label": label})
        return r.json()

    async def alarm_parse_time(self, raw_input: str) -> dict:
        r = await self._post("/alarm/parse-time", data={"raw_input": raw_input})
        return r.json()

    async def clean_scan(self) -> dict:
        r = await self._get("/clean/scan")
        return r.json()

    async def clean_execute(self) -> dict:
        r = await self._post("/clean/execute")
        return r.json()

    async def get_events(self) -> list:
        try:
            r = await self._get("/events", timeout=3.0)
            r.raise_for_status()
            return r.json().get("events", [])
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════════════
#   SECURITY & LOCKS
# ═══════════════════════════════════════════════════════════════════════

unauthorized_alert_cooldown: dict[int, float] = {}
authenticated_sessions: dict[int, float] = {}
failed_login_attempts: dict[int, list[float]] = {}


def is_authorized(user_id: int) -> bool:
    if not config.AUTHORIZED_USER_IDS:
        return False
    return user_id in config.AUTHORIZED_USER_IDS


def is_authenticated(user_id: int) -> bool:
    if not config.BOT_PIN:
        return True
    expiry = authenticated_sessions.get(user_id, 0)
    return datetime.now().timestamp() < expiry


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or not is_authorized(user.id):
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

def get_selected_pc(context: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
    """Get the currently selected PC info from user session."""
    return context.user_data.get("selected_pc")


def get_agent(context: ContextTypes.DEFAULT_TYPE) -> Optional[AgentClient]:
    """Get AgentClient for currently selected PC."""
    pc = get_selected_pc(context)
    if not pc:
        return None
    fleet = load_fleet()
    return AgentClient(pc, fleet.get("secret", ""))


async def require_pc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[AgentClient]:
    """Require a PC to be selected. Returns agent or None (with user prompt)."""
    agent = get_agent(context)
    if not agent:
        await show_pc_picker(update, context, prompt="⚠️ <b>No PC selected!</b>\nPlease select a PC first:")
        return None
    return agent


# ═══════════════════════════════════════════════════════════════════════
#   PC PICKER KEYBOARD
# ═══════════════════════════════════════════════════════════════════════

async def check_fleet_health(fleet: dict) -> Dict[str, dict]:
    """Check which PCs are online via Cloud Relay or LAN."""
    results = {}
    secret = fleet.get("secret", "")

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


def get_pc_picker_keyboard(fleet: dict, health: Dict[str, dict]) -> InlineKeyboardMarkup:
    """Build PC selector keyboard with online/offline indicators."""
    buttons = []
    row = []
    for i, pc in enumerate(fleet["pcs"]):
        name = pc["name"]
        label = pc.get("label", name)
        h_info = health.get(name, {})
        is_online = h_info.get("online", False)
        emoji = "🟢" if is_online else "🔴"
        btn_text = f"{emoji} {label}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"pc_select_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("📊 Fleet Overview", callback_data="fleet_overview"),
        InlineKeyboardButton("🔄 Refresh", callback_data="fleet_refresh"),
    ])
    return InlineKeyboardMarkup(buttons)


async def show_pc_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str = None):
    """Show the PC selection menu."""
    fleet = load_fleet()
    health = await check_fleet_health(fleet)

    if not fleet["pcs"]:
        text = (
            "⚠️ <b>NO PCs REGISTERED</b>\n\n"
            "No PCs have been registered yet.\n"
            "Plug your USB pendrive into any PC and double-click <code>install.bat</code>.\n\n"
            "The PC will automatically register and appear here within seconds."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text, parse_mode="HTML")
        return

    online_count = sum(1 for v in health.values() if v.get("online"))

    header = prompt or (
        f"🛡️ <b>PC REMOTE SENTINEL — FLEET COMMAND CENTER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>Fleet Status:</b> <code>{online_count}/{len(fleet['pcs'])}</code> PCs online\n\n"
        f"<i>Select a PC to control:</i>"
    )
    keyboard = get_pc_picker_keyboard(fleet, health)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(header, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await update.effective_message.reply_text(header, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(header, reply_markup=keyboard, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════
#   COMMAND CENTER KEYBOARDS (same layout as before, with "Back to PCs")
# ═══════════════════════════════════════════════════════════════════════

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 System Status", callback_data="cb_status"),
            InlineKeyboardButton("📸 Screenshot", callback_data="cb_shot"),
        ],
        [
            InlineKeyboardButton("📺 Live Screen Cast", callback_data="cb_cast_menu"),
            InlineKeyboardButton("🎥 Screen Video", callback_data="cb_screen_menu"),
        ],
        [
            InlineKeyboardButton("📷 Webcam Menu", callback_data="cb_webcam_menu"),
            InlineKeyboardButton("⚡ Power & Sleep", callback_data="cb_power_menu"),
        ],
        [
            InlineKeyboardButton("🎵 Media & Volume", callback_data="cb_media_menu"),
            InlineKeyboardButton("💻 Top Processes", callback_data="cb_top"),
        ],
        [
            InlineKeyboardButton("📋 Clipboard Tools", callback_data="cb_clip_menu"),
            InlineKeyboardButton("🗣️ Speak / TTS", callback_data="cb_tts_info"),
        ],
        [
            InlineKeyboardButton("⏰ Alarm & Siren", callback_data="cb_alarm_menu"),
            InlineKeyboardButton("🧹 Clean Storage", callback_data="cb_clean"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="cb_menu"),
        ],
        [
            InlineKeyboardButton("🔙 Switch PC", callback_data="fleet_picker"),
        ],
    ])


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
    """Handle /start and /menu — show PC picker."""
    user = update.effective_user
    if not user:
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
    pc = get_selected_pc(context)
    if pc:
        agent = get_agent(context)
        try:
            stats = await agent.status()
            label = pc.get("label", pc["name"])
            text = (
                f"🛡️ <b>CONTROLLING: {html.escape(label)}</b> ⚡\n"
                f"<b>CPU:</b> <code>{stats['cpu_percent']:.1f}%</code> | "
                f"<b>RAM:</b> <code>{stats['memory_percent']:.1f}%</code> "
                f"({stats['memory_used_gb']} / {stats['memory_total_gb']} GB)\n"
                f"<b>Uptime:</b> <code>{stats['uptime']}</code>\n\n"
                f"<i>Tap below or send commands to control this PC:</i>"
            )
            await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        except Exception:
            context.user_data.pop("selected_pc", None)
            await show_pc_picker(update, context, prompt=f"⚠️ <b>{html.escape(label)} is offline.</b>\nSelect another PC:")
        return

    await show_pc_picker(update, context)


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


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    try:
        stats = await agent.status()
        cores_str = ", ".join([f"{c:.0f}%" for c in stats.get('per_core', [])[:8]])
        label = pc_label(context)
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
            await update.callback_query.edit_message_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        err = f"❌ Failed to reach <b>{html.escape(pc_label(context))}</b>: <code>{html.escape(str(e)[:200])}</code>"
        if update.callback_query:
            await update.callback_query.edit_message_text(err, reply_markup=get_main_keyboard(), parse_mode="HTML")
        else:
            await update.effective_message.reply_text(err, parse_mode="HTML")


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    chat_id = update.effective_chat.id
    msg = await update.effective_message.reply_text(f"📸 <i>Capturing screenshot from {html.escape(label)}...</i>", parse_mode="HTML")
    try:
        res = await agent.screenshot(chat_id=chat_id)
        if isinstance(res, bytes):
            await update.effective_chat.send_photo(
                photo=res,
                caption=f"🖥️ <b>Screenshot — {html.escape(label)}</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ Screenshot failed: {e}")


async def handle_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    label = pc_label(context)
    chat_id = update.effective_chat.id
    msg = await update.effective_message.reply_text(f"📷 <i>Accessing webcam on {html.escape(label)}...</i>", parse_mode="HTML")
    try:
        res = await agent.webcam(chat_id=chat_id)
        if isinstance(res, bytes):
            await update.effective_chat.send_photo(
                photo=res,
                caption=f"📷 <b>Webcam — {html.escape(label)}</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ Webcam failed: {e}")


async def execute_screen_recording(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int = 10):
    if not await check_access(update, context):
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
    duration = 10
    if context.args and context.args[0].isdigit():
        duration = int(context.args[0])
    await execute_webcam_recording(update, context, duration=duration)


# ── Screen Casting ────────────────────────────────────────────────────

active_radar_tasks: dict[int, asyncio.Task] = {}


async def handle_cast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
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
                InlineKeyboardButton("📡 RTMP Info", callback_data="cb_cast_rtmp_info"),
            ])
            rows.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")])
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


async def execute_cast_web_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return

    if update.callback_query:
        await update.callback_query.edit_message_text("⏳ <i>Starting web cast...</i>", parse_mode="HTML")
    else:
        init_msg = await update.effective_message.reply_text("⏳ <i>Starting web cast...</i>", parse_mode="HTML")

    try:
        res = await agent.cast_web_start()
        lan_url = res.get("lan_url", "")
        public_url = res.get("public_url", "")
        token = res.get("token", "")
        label = pc_label(context)

        url_section = ""
        buttons = []
        if public_url:
            url_section += f"🌍 <b>Global:</b>\n<code>{public_url}</code>\n\n"
            buttons.append([InlineKeyboardButton("🌍 Open Global Stream", url=public_url)])
        if lan_url:
            url_section += f"🏠 <b>Local:</b>\n<code>{lan_url}</code>\n\n"
            buttons.append([InlineKeyboardButton("🏠 Open Local Stream", url=lan_url)])

        msg_text = (
            f"📺 <b>WEB CAST ONLINE — {html.escape(label)}</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{url_section}"
            f"🔒 <b>Token:</b> <code>{token}</code>\n"
            f"⚡ <b>FPS:</b> <code>15-25</code>"
        )
        buttons.append([
            InlineKeyboardButton("⏹️ Stop", callback_data="cb_cast_web_stop"),
            InlineKeyboardButton("🔙 Cast Menu", callback_data="cb_cast_menu"),
        ])
        kb = InlineKeyboardMarkup(buttons)

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


# ── TTS, Processes, Kill, Open, CMD, Files, Clipboard ──────────────────

async def handle_say(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
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
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/cmd ipconfig</code>", parse_mode="HTML")
        return
    command = " ".join(context.args)
    try:
        result = await agent.run_cmd(command)
        code = result.get("exit_code", -1)
        output = result.get("output", "")
        emoji = "✅" if code == 0 else "⚠️"
        truncated = output[:3500] if len(output) > 3500 else output
        label = pc_label(context)
        text = f"{emoji} <b>{html.escape(label)} — Code {code}:</b>\n<pre>{html.escape(truncated)}</pre>"
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Command failed: {e}")


async def handle_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/get C:\\path\\to\\file.txt</code>", parse_mode="HTML")
        return
    file_path = " ".join(context.args)
    msg = await update.message.reply_text(f"📤 <i>Fetching file...</i>", parse_mode="HTML")
    try:
        content, filename = await agent.get_file(file_path)
        size_mb = len(content) / (1024 * 1024)
        label = pc_label(context)
        await update.effective_chat.send_document(
            document=content,
            filename=filename,
            caption=f"📄 <b>File from {html.escape(label)}:</b> <code>{html.escape(filename)}</code>\n💾 <code>{size_mb:.2f} MB</code>",
            parse_mode="HTML"
        )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ File fetch failed: {e}")


async def handle_clip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    agent = await require_pc(update, context)
    if not agent:
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/clip text to copy</code>", parse_mode="HTML")
        return
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
    try:
        result = await agent.clean_scan()
        candidates = result.get("candidates", [])
        label = pc_label(context)
        if not candidates:
            text = f"🧹 <b>STORAGE CLEAN — {html.escape(label)}</b>\n\n✨ <b>Already clean!</b>"
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
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Storage scan failed: {e}")


async def handle_alarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
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
        ok = await agent.alarm_stop()
        await update.message.reply_text("🔕 <b>Silenced.</b>" if ok else "ℹ️ No alarm ringing.", parse_mode="HTML")
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
        if result.get("success"):
            await msg.edit_text(f"🔊 <b>Voice played on {html.escape(pc_label(context))}!</b> ({duration}s)", parse_mode="HTML")
        else:
            await msg.edit_text(f"⚠️ Playback issue: {result.get('message', 'Unknown')}")
    except Exception as e:
        await msg.edit_text(f"❌ Voice playback failed: {e}")


async def handle_incoming_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    agent = get_agent(context)
    if not agent:
        # No PC selected — don't prompt, just ignore plain text
        return
    text = update.message.text
    if not text:
        return
    try:
        ok = await agent.speak(text)
        if ok:
            await update.message.reply_text(f"🗣️ <i>Spoken on {html.escape(pc_label(context))}:</i>\n\"{html.escape(text)}\"", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ TTS failed.")
    except Exception as e:
        await update.message.reply_text(f"❌ TTS error: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling update: {context.error}")
    if isinstance(update, Update):
        if update.callback_query:
            try:
                await update.callback_query.answer("⚠️ Error occurred.")
            except Exception:
                pass
        if update.effective_message:
            try:
                err_msg = str(context.error)
                if "Message is not modified" not in err_msg:
                    await update.effective_message.reply_text(f"⚠️ <code>{html.escape(err_msg[:300])}</code>", parse_mode="HTML")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#   CALLBACK QUERY ROUTER
# ═══════════════════════════════════════════════════════════════════════

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("⛔ Unauthorized.")
        return

    # Allow fleet picker without PIN (but not PC commands)
    data = query.data

    if config.BOT_PIN and not is_authenticated(query.from_user.id):
        # Allow fleet navigation even when locked
        if data not in ("fleet_picker", "fleet_refresh", "fleet_overview") and not data.startswith("pc_select_"):
            await query.answer("🔒 Locked. Send /login <PIN>", show_alert=True)
            return

    # ── Fleet Navigation ──────────────────────────────────────────
    if data == "fleet_picker":
        context.user_data.pop("selected_pc", None)
        await show_pc_picker(update, context)
        return

    if data == "fleet_refresh":
        await show_pc_picker(update, context)
        return

    if data == "fleet_overview":
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
            context.user_data["selected_pc"] = pc
            label = pc.get("label", pc["name"])

            # Check if online
            agent = AgentClient(pc, fleet.get("secret", ""))
            health = await agent.health()
            if not health:
                await query.edit_message_text(
                    f"🔴 <b>{html.escape(label)} is OFFLINE</b>\n\n"
                    f"Cannot connect to <code>{pc['ip']}:{pc.get('port', 9010)}</code>.\n"
                    f"Make sure the PC is on and the agent is running.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Retry", callback_data=data)],
                        [InlineKeyboardButton("🔙 Back to PC List", callback_data="fleet_picker")],
                    ]),
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
            await query.edit_message_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        return

    # ── PC Commands (require selected PC) ─────────────────────────

    if data == "cb_menu":
        pc = get_selected_pc(context)
        if pc:
            label = pc.get("label", pc["name"])
            await query.edit_message_text(
                f"🛡️ <b>CONTROLLING: {html.escape(label)}</b>",
                reply_markup=get_main_keyboard(), parse_mode="HTML"
            )
        else:
            await show_pc_picker(update, context)
    elif data == "cb_status":
        await handle_status(update, context)
    elif data == "cb_shot":
        await handle_screenshot(update, context)
    elif data in ("cb_webcam", "cb_webcam_menu"):
        label = pc_label(context)
        await query.edit_message_text(f"📷 <b>WEBCAM — {html.escape(label)}</b>", reply_markup=get_webcam_keyboard(), parse_mode="HTML")
    elif data == "cb_webcam_shot":
        await handle_webcam(update, context)
    elif data == "cb_rec_webcam_10":
        await execute_webcam_recording(update, context, duration=10)
    elif data == "cb_rec_webcam_30":
        await execute_webcam_recording(update, context, duration=30)
    elif data == "cb_screen_menu":
        label = pc_label(context)
        await query.edit_message_text(f"🎥 <b>SCREEN RECORDING — {html.escape(label)}</b>", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data.startswith("cb_rec_screen_"):
        sec = int(data.split("_")[-1])
        await execute_screen_recording(update, context, duration=sec)
    elif data == "cb_cast_menu":
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
                InlineKeyboardButton("📡 RTMP Info", callback_data="cb_cast_rtmp_info"),
            ])
            rows.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")])
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
        if agent:
            try:
                await agent.power_sleep()
            except Exception:
                pass
        await query.message.reply_text(f"💤 {html.escape(pc_label(context))} going to sleep...")
    elif data == "cb_pwr_lock":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_lock()
            except Exception:
                pass
        await query.message.reply_text(f"🔒 {html.escape(pc_label(context))} locked.")
    elif data == "cb_pwr_monitor_off":
        agent = get_agent(context)
        if agent:
            try:
                await agent.monitor_off()
            except Exception:
                pass
        await query.message.reply_text(f"🖥️ {html.escape(pc_label(context))} monitors off.")
    elif data == "cb_pwr_monitor_on":
        agent = get_agent(context)
        if agent:
            try:
                await agent.monitor_on()
            except Exception:
                pass
        await query.message.reply_text(f"💡 {html.escape(pc_label(context))} monitors on.")
    elif data == "cb_pwr_shutdown_now":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_shutdown(0)
            except Exception:
                pass
        await query.message.reply_text(f"🛑 {html.escape(pc_label(context))} shutting down...")
    elif data == "cb_pwr_shut_15":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_shutdown(900)
            except Exception:
                pass
        await query.message.reply_text(f"⏳ {html.escape(pc_label(context))} shutdown in 15 min.")
    elif data == "cb_pwr_shut_30":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_shutdown(1800)
            except Exception:
                pass
        await query.message.reply_text(f"⏳ {html.escape(pc_label(context))} shutdown in 30 min.")
    elif data == "cb_pwr_shut_60":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_shutdown(3600)
            except Exception:
                pass
        await query.message.reply_text(f"⏳ {html.escape(pc_label(context))} shutdown in 1 hour.")
    elif data == "cb_pwr_shut_cancel":
        agent = get_agent(context)
        if agent:
            try:
                ok = await agent.power_cancel_shutdown()
                if ok:
                    await query.message.reply_text(f"✅ {html.escape(pc_label(context))} shutdown cancelled.")
                else:
                    await query.message.reply_text("ℹ️ No scheduled shutdown.")
            except Exception:
                pass
    elif data == "cb_pwr_restart":
        agent = get_agent(context)
        if agent:
            try:
                await agent.power_restart(5)
            except Exception:
                pass
        await query.message.reply_text(f"🔄 {html.escape(pc_label(context))} restarting in 5s...")


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


# ═══════════════════════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        print("\n⚠️ Error: TELEGRAM_BOT_TOKEN is not set in .env file!")
        return

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    # Register handlers
    app.add_handler(CommandHandler(["start", "menu"], handle_start))
    app.add_handler(CommandHandler("pcs", handle_pcs))
    app.add_handler(CommandHandler("reload", handle_reload))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler(["shot", "screenshot"], handle_screenshot))
    app.add_handler(CommandHandler("webcam", handle_webcam))
    app.add_handler(CommandHandler("record_screen", handle_record_screen))
    app.add_handler(CommandHandler("record_webcam", handle_record_webcam))
    app.add_handler(CommandHandler(["cast", "stream"], handle_cast))
    app.add_handler(CommandHandler("login", handle_login))
    app.add_handler(CommandHandler("logout", handle_logout))
    app.add_handler(CommandHandler("top", handle_top))
    app.add_handler(CommandHandler("kill", handle_kill))
    app.add_handler(CommandHandler("say", handle_say))
    app.add_handler(CommandHandler("open", handle_open))
    app.add_handler(CommandHandler("cmd", handle_cmd))
    app.add_handler(CommandHandler("get", handle_get_file))
    app.add_handler(CommandHandler("clip", handle_clip))
    app.add_handler(CommandHandler("getclip", handle_getclip))
    app.add_handler(CommandHandler("clean", handle_clean))
    app.add_handler(CommandHandler(["alarm", "timer"], handle_alarm))
    app.add_handler(CommandHandler(["stopalarm", "silence"], handle_stopalarm))
    app.add_handler(CommandHandler(["cancelalarm"], handle_cancelalarm))
    app.add_handler(CommandHandler("monitor", handle_monitor))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_incoming_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_incoming_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_text))
    app.add_handler(CallbackQueryHandler(callback_router))

    async def post_init(application):
        # Initialize and start Fleet Cloud Relay
        global commander_relay
        fleet = load_fleet()
        secret = fleet.get("secret", "") or os.getenv("FLEET_SECRET", "sentinel-fleet-secret-2026")
        broker = os.getenv("MQTT_BROKER", "broker.emqx.io").strip()
        port = int(os.getenv("MQTT_PORT", "8883"))
        use_tls = os.getenv("MQTT_USE_TLS", "true").strip().lower() in ("1", "true", "yes")

        def on_fleet_alert(alert_data: dict):
            pc_name = alert_data.get("pc_name", "Unknown PC")
            label = alert_data.get("label", "Alarm")
            time_str = alert_data.get("time", "")
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

        commander_relay = FleetCommanderRelay(
            secret=secret,
            broker=broker,
            port=port,
            use_tls=use_tls,
            on_alert_callback=on_fleet_alert,
        )
        commander_relay.start(asyncio.get_running_loop())
        # Allow relay a brief moment to connect and ingest retained status
        await asyncio.sleep(1.2)

        cmds = [
            BotCommand("start", "Fleet Command Center"),
            BotCommand("pcs", "Switch PC / View fleet"),
            BotCommand("reload", "Reload fleet.json"),
            BotCommand("login", "Authenticate with PIN"),
            BotCommand("logout", "Lock session"),
            BotCommand("status", "System Diagnostics"),
            BotCommand("shot", "Desktop Screenshot"),
            BotCommand("cast", "Live Screen Cast"),
            BotCommand("webcam", "Webcam Snapshot"),
            BotCommand("record_screen", "Record Desktop (10s-120s)"),
            BotCommand("record_webcam", "Record Webcam"),
            BotCommand("alarm", "PC Alarm & Timer"),
            BotCommand("stopalarm", "Silence alarm"),
            BotCommand("cancelalarm", "Cancel alarm"),
            BotCommand("monitor", "Monitors on/off"),
            BotCommand("top", "Top Processes"),
            BotCommand("kill", "Kill Process"),
            BotCommand("say", "Speak text on PC"),
            BotCommand("clip", "Copy to PC clipboard"),
            BotCommand("getclip", "Read PC clipboard"),
            BotCommand("get", "Fetch file from PC"),
            BotCommand("clean", "Cleanup storage"),
            BotCommand("open", "Open URL/App on PC"),
            BotCommand("cmd", "Execute command"),
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

    app.post_init = post_init
    logger.info("🛡️ Fleet Commander Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
