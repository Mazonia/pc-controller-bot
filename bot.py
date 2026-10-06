"""
Telegram Bot Application for PC Remote Sentinel
Complete interactive 2-way remote control for Windows PC.
"""

import ctypes

try:
    ctypes.windll.kernel32.SetConsoleTitleW('PC-Remote-Sentinel')
except Exception:
    pass

import os
import sys
import html
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    BotCommand,
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
from system_controller import SystemController


# ── Security & Locks ──────────────────────────────────────────────────

hardware_lock = asyncio.Lock()
unauthorized_alert_cooldown: dict[int, float] = {}


def is_authorized(user_id: int) -> bool:
    """Check if sender ID is in authorized whitelist."""
    if not config.AUTHORIZED_USER_IDS:
        return False
    return user_id in config.AUTHORIZED_USER_IDS


async def notify_unauthorized_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Notify authorized owners of unauthorized access attempts with rate-limiting."""
    user = update.effective_user
    user_id = user.id if user else 0
    username = f"@{user.username}" if user and user.username else f"User {user_id}"

    # 60s cooldown per user ID to prevent spam/flooding
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


# ── Interactive Keyboards ──────────────────────────────────────────────

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Create the primary interactive Command Center keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 System Status", callback_data="cb_status"),
            InlineKeyboardButton("📸 Screenshot", callback_data="cb_shot"),
        ],
        [
            InlineKeyboardButton("📷 Webcam Menu", callback_data="cb_webcam_menu"),
            InlineKeyboardButton("🎥 Screen Video", callback_data="cb_screen_menu"),
        ],
        [
            InlineKeyboardButton("⚡ Power & Sleep", callback_data="cb_power_menu"),
            InlineKeyboardButton("🎵 Media & Volume", callback_data="cb_media_menu"),
        ],
        [
            InlineKeyboardButton("💻 Top Processes", callback_data="cb_top"),
            InlineKeyboardButton("📋 Clipboard Tools", callback_data="cb_clip_menu"),
        ],
        [
            InlineKeyboardButton("🗣️ Speak / TTS", callback_data="cb_tts_info"),
            InlineKeyboardButton("⏰ Alarm & Siren", callback_data="cb_alarm_menu"),
        ],
        [
            InlineKeyboardButton("🧹 Clean Storage", callback_data="cb_clean"),
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="cb_menu"),
        ]
    ])


def get_screen_keyboard() -> InlineKeyboardMarkup:
    """Create screen recording duration selector."""
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
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_webcam_keyboard() -> InlineKeyboardMarkup:
    """Create webcam actions selector."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Snapshot Photo", callback_data="cb_webcam_shot"),
        ],
        [
            InlineKeyboardButton("📹 Record 10s Clip", callback_data="cb_rec_webcam_10"),
            InlineKeyboardButton("📹 Record 30s Clip", callback_data="cb_rec_webcam_30"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_media_keyboard() -> InlineKeyboardMarkup:
    """Create interactive media playback and volume controller keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔊 Volume +10%", callback_data="cb_vol_up"),
            InlineKeyboardButton("🔉 Volume -10%", callback_data="cb_vol_down"),
            InlineKeyboardButton("🔇 Mute", callback_data="cb_vol_mute"),
        ],
        [
            InlineKeyboardButton("⏮️ Previous", callback_data="cb_media_prev"),
            InlineKeyboardButton("⏯️ Play / Pause", callback_data="cb_media_play_pause"),
            InlineKeyboardButton("⏭️ Next", callback_data="cb_media_next"),
        ],
        [
            InlineKeyboardButton("⏹️ Stop Playback", callback_data="cb_media_stop"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_clipboard_keyboard() -> InlineKeyboardMarkup:
    """Create clipboard tools keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Read PC Clipboard", callback_data="cb_clip_read"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_top_keyboard() -> InlineKeyboardMarkup:
    """Create top processes control keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Processes", callback_data="cb_top"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_power_keyboard() -> InlineKeyboardMarkup:
    """Create interactive power controller keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💤 Sleep PC", callback_data="cb_pwr_sleep"),
            InlineKeyboardButton("🔒 Lock Workstation", callback_data="cb_pwr_lock"),
        ],
        [
            InlineKeyboardButton("🖥️ Turn Off Monitors", callback_data="cb_pwr_monitor_off"),
            InlineKeyboardButton("🛑 Shutdown Now", callback_data="cb_pwr_shutdown_now"),
        ],
        [
            InlineKeyboardButton("⏳ Shutdown in 15m", callback_data="cb_pwr_shut_15"),
            InlineKeyboardButton("⏳ Shutdown in 30m", callback_data="cb_pwr_shut_30"),
        ],
        [
            InlineKeyboardButton("⏳ Shutdown in 1h", callback_data="cb_pwr_shut_60"),
            InlineKeyboardButton("❌ Cancel Shutdown", callback_data="cb_pwr_shut_cancel"),
        ],
        [
            InlineKeyboardButton("🔄 Restart PC", callback_data="cb_pwr_restart"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


def get_alarm_keyboard(has_active: bool = False, is_ringing: bool = False) -> InlineKeyboardMarkup:
    """Create interactive Alarm and Timer management keyboard."""
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
        [
            InlineKeyboardButton("🚨 Sound Alarm Now", callback_data="cb_alarm_trigger_now"),
        ]
    ]

    action_row = []
    if is_ringing:
        action_row.append(InlineKeyboardButton("🔕 Silence Alarm", callback_data="cb_alarm_stop"))
    if has_active:
        action_row.append(InlineKeyboardButton("❌ Cancel Scheduled", callback_data="cb_alarm_cancel"))

    if action_row:
        buttons.append(action_row)

    buttons.append([
        InlineKeyboardButton("🔄 Refresh Status", callback_data="cb_alarm_menu"),
        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
    ])

    return InlineKeyboardMarkup(buttons)


def format_alarm_menu_text() -> Tuple[str, InlineKeyboardMarkup]:
    """Format real-time alarm dashboard text and control keyboard."""
    status_info = SystemController.get_alarm_status()
    st = status_info["status"]

    lines = ["⏰ <b>PC ALARM & COUNTDOWN TIMER</b>\n"]

    has_active = False
    is_ringing = False

    if st == "ringing":
        is_ringing = True
        lbl = html.escape(status_info.get("label", "Alarm"))
        lines.append(f"🚨 <b>STATUS: ALARM IS CURRENTLY RINGING ON PC!</b>")
        lines.append(f"• <b>Label:</b> <code>{lbl}</code>")
        lines.append(f"• <i>Siren & voice alert are active on PC speakers.</i>\n")
    elif st == "scheduled":
        has_active = True
        lbl = html.escape(status_info.get("label", "Scheduled Alarm"))
        rem_str = status_info.get("time_left_str", "soon")
        tgt_str = status_info.get("target_time_str", "")
        lines.append(f"⏳ <b>STATUS: COUNTDOWN TIMER ACTIVE</b>")
        lines.append(f"• <b>Target Time:</b> <code>{tgt_str}</code> (in <b>{rem_str}</b>)")
        lines.append(f"• <b>Label:</b> <code>{lbl}</code>\n")
    else:
        lines.append("💤 <b>STATUS: No alarm scheduled</b>\n")

    lines.append(
        "💡 <b>Set Custom Alarms & Labels:</b>\n"
        "Send anytime from chat:\n"
        "• <code>/alarm 20m Check dinner</code>\n"
        "• <code>/alarm 45s Stretch timer</code>\n"
        "• <code>/alarm 07:30 Wake up workout</code>\n"
        "• <code>/alarm cancel</code> or <code>/alarm stop</code>"
    )

    kb = get_alarm_keyboard(has_active=has_active, is_ringing=is_ringing)
    return "\n".join(lines), kb


# ── Command Handlers ───────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /menu commands."""
    user = update.effective_user
    if not user:
        return

    if not config.AUTHORIZED_USER_IDS:
        await update.message.reply_text(
            f"⚠️ <b>SETUP REQUIRED</b>\n\n"
            f"Your Telegram User ID is: <code>{user.id}</code>\n\n"
            f"Add this ID to your <code>.env</code> file:\n"
            f"<code>AUTHORIZED_USER_IDS={user.id}</code>\n\n"
            f"Then restart the bot to activate remote control.",
            parse_mode="HTML"
        )
        return

    if not is_authorized(user.id):
        await update.message.reply_text("⛔ <b>Access Denied:</b> This bot is locked to authorized PC owners.", parse_mode="HTML")
        return

    stats = SystemController.get_system_stats()
    text = (
        f"🛡️ <b>PC REMOTE SENTINEL — COMMAND CENTER</b> ⚡\n"
        f"<b>Machine:</b> Windows PC Online\n"
        f"<b>CPU Load:</b> <code>{stats['cpu_percent']:.1f}%</code>\n"
        f"<b>RAM Used:</b> <code>{stats['memory_percent']:.1f}%</code> ({stats['memory_used_gb']} / {stats['memory_total_gb']} GB)\n"
        f"<b>Uptime:</b> <code>{stats['uptime']}</code>\n\n"
        f"<i>Tap below or send commands to control your PC remotely:</i>"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if not is_authorized(update.effective_user.id):
        return
    stats = SystemController.get_system_stats()
    cores_str = ", ".join([f"{c:.0f}%" for c in stats['per_core'][:8]])
    text = (
        f"📊 <b>PC HARDWARE DIAGNOSTICS</b>\n"
        f"{'━' * 28}\n\n"
        f"🖥️ <b>CPU Total:</b> <code>{stats['cpu_percent']:.1f}%</code>\n"
        f"⚡ <b>Per Core:</b> <code>[{cores_str}]</code>\n"
        f"🧠 <b>RAM Memory:</b> <code>{stats['memory_percent']:.1f}%</code> ({stats['memory_used_gb']} GB / {stats['memory_total_gb']} GB)\n"
        f"💾 <b>C: Drive:</b> <code>{stats['disk_percent']:.1f}%</code> (Free: {stats['disk_free_gb']} GB / Total: {stats['disk_total_gb']} GB)\n"
        f"🔋 <b>Power/Battery:</b> <code>{stats['battery']}</code>\n"
        f"⏱️ <b>System Uptime:</b> <code>{stats['uptime']}</code>\n"
        f"📅 <b>Booted At:</b> <code>{stats['boot_time']}</code>"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /shot or /screenshot command."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    if hardware_lock.locked():
        await update.effective_message.reply_text("⏳ <i>Hardware device is currently in use. Please wait a moment.</i>", parse_mode="HTML")
        return

    async with hardware_lock:
        msg = await update.effective_message.reply_text("📸 <i>Capturing desktop screenshot...</i>", parse_mode="HTML")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_path = config.RECORDINGS_DIR / f"shot_{timestamp}.png"
        ok = await asyncio.to_thread(SystemController.take_screenshot, shot_path)
        if ok and shot_path.exists():
            with open(shot_path, "rb") as f:
                await update.effective_chat.send_photo(photo=f, caption=f"🖥️ <b>PC Desktop Screenshot</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", parse_mode="HTML")
            try:
                await msg.delete()
            except Exception:
                pass
        else:
            await msg.edit_text("❌ Failed to capture screenshot.")


async def handle_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /webcam snapshot command."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    if hardware_lock.locked():
        await update.effective_message.reply_text("⏳ <i>Camera device is currently busy. Please wait a moment.</i>", parse_mode="HTML")
        return

    async with hardware_lock:
        msg = await update.effective_message.reply_text("📷 <i>Accessing webcam sensor...</i>", parse_mode="HTML")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_path = config.RECORDINGS_DIR / f"webcam_{timestamp}.jpg"
        ok, status = await asyncio.to_thread(SystemController.take_webcam_photo, photo_path)
        if ok and photo_path.exists():
            with open(photo_path, "rb") as f:
                await update.effective_chat.send_photo(photo=f, caption=f"📷 <b>PC Webcam Snapshot</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", parse_mode="HTML")
            try:
                await msg.delete()
            except Exception:
                pass
        else:
            await msg.edit_text(f"❌ Webcam capture failed: {status}")


async def execute_screen_recording(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int = 10):
    """Execute desktop screen recording asynchronously and send video."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    if hardware_lock.locked():
        await update.effective_message.reply_text("⏳ <i>Recording device is currently busy. Please wait for previous job to finish.</i>", parse_mode="HTML")
        return

    duration = min(max(duration, 3), 120)
    msg = await update.effective_message.reply_text(
        f"🎥 <i>Recording {duration}s of desktop screen... (please wait)</i>",
        parse_mode="HTML"
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = config.RECORDINGS_DIR / f"screen_{timestamp}_{duration}s.mp4"

    async with hardware_lock:
        ok, status = await asyncio.to_thread(SystemController.record_screen_video, video_path, duration_sec=duration)
        if ok and video_path.exists():
            with open(video_path, "rb") as f:
                await update.effective_chat.send_video(
                    video=f,
                    caption=f"🎥 <b>Desktop Screen Recording ({duration}s)</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode="HTML"
                )
            try:
                await msg.delete()
            except Exception:
                pass
        else:
            await msg.edit_text(f"❌ Screen recording failed: {status}")


async def handle_record_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /record_screen [seconds] command or display duration menu."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if context.args and context.args[0].isdigit():
        duration = int(context.args[0])
        await execute_screen_recording(update, context, duration=duration)
    else:
        await update.effective_message.reply_text(
            "🎥 <b>DESKTOP SCREEN RECORDING</b>\nSelect recording duration:",
            reply_markup=get_screen_keyboard(),
            parse_mode="HTML"
        )


async def execute_webcam_recording(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int = 10):
    """Execute webcam clip recording asynchronously."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    if hardware_lock.locked():
        await update.effective_message.reply_text("⏳ <i>Camera device is currently busy. Please wait a moment.</i>", parse_mode="HTML")
        return

    duration = min(max(duration, 3), 60)
    msg = await update.effective_message.reply_text(f"📹 <i>Recording {duration}s from webcam... (please wait)</i>", parse_mode="HTML")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = config.RECORDINGS_DIR / f"webcam_video_{timestamp}_{duration}s.mp4"

    async with hardware_lock:
        ok, status = await asyncio.to_thread(SystemController.record_webcam_video, video_path, duration_sec=duration)
        if ok and video_path.exists():
            with open(video_path, "rb") as f:
                await update.effective_chat.send_video(video=f, caption=f"📹 <b>Webcam Video Clip ({duration}s)</b>", parse_mode="HTML")
            try:
                await msg.delete()
            except Exception:
                pass
        else:
            await msg.edit_text(f"❌ Webcam recording failed: {status}")


async def handle_record_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /record_webcam [seconds] command."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    duration = 10
    if context.args and context.args[0].isdigit():
        duration = int(context.args[0])
    await execute_webcam_recording(update, context, duration=duration)


async def handle_say(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Speak text aloud on PC speakers via TTS."""
    if not is_authorized(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/say Hello from my phone!</code>\n<i>Tip: You can also simply type any message directly to speak it aloud!</i>",
            parse_mode="HTML"
        )
        return
    text = " ".join(context.args)
    ok = await asyncio.to_thread(SystemController.speak_text, text)
    if ok:
        await update.message.reply_text(f"🗣️ <i>Spoken aloud on PC:</i> \"{html.escape(text)}\"", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Failed to trigger speech synthesis.")


async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display top CPU & Memory processes."""
    if not is_authorized(update.effective_user.id):
        return
    procs = await asyncio.to_thread(SystemController.list_top_processes, 10)
    lines = ["💻 <b>TOP PC PROCESSES (By RAM & CPU)</b>\n" + ("━" * 28)]
    for p in procs:
        safe_name = html.escape(str(p['name']))
        lines.append(f"• <code>{p['pid']}</code>: <b>{safe_name}</b> | RAM: <code>{p['mem']}%</code> | CPU: <code>{p['cpu']}%</code>")
    lines.append("\n<i>Kill any process via</i> <code>/kill &lt;name_or_pid&gt;</code>")
    text = "\n".join(lines)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" in str(e):
                await update.callback_query.answer("Processes list is up to date!")
            else:
                await update.effective_message.reply_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=get_top_keyboard(), parse_mode="HTML")


async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kill process by name or PID."""
    if not is_authorized(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/kill notepad.exe</code> or <code>/kill 1234</code>", parse_mode="HTML")
        return
    target = context.args[0]
    ok, res = SystemController.kill_process(target)
    emoji = "✅" if ok else "⚠️"
    await update.message.reply_text(f"{emoji} {res}", parse_mode="HTML")


async def handle_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open URL or file on PC."""
    if not is_authorized(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/open https://youtube.com</code>", parse_mode="HTML")
        return
    target = context.args[0]
    if SystemController.open_target(target):
        await update.message.reply_text(f"🌐 Opened: <code>{html.escape(target)}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Failed to open target.")


async def handle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute PowerShell/CMD command remotely."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/cmd dir</code> or <code>/cmd ipconfig</code>", parse_mode="HTML")
        return
    command = " ".join(context.args)
    code, output = SystemController.run_cmd(command, bot_token=config.BOT_TOKEN)
    emoji = "✅" if code == 0 else "⚠️"
    truncated = output[:3500] if len(output) > 3500 else output
    text = f"{emoji} <b>Command Output (Code {code}):</b>\n<pre>{html.escape(truncated)}</pre>"
    await update.message.reply_text(text, parse_mode="HTML")


async def handle_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Securely fetch and send a file from PC to Telegram chat."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/get C:\\path\\to\\file.txt</code>", parse_mode="HTML")
        return

    req_path = Path(" ".join(context.args))
    if not req_path.is_file():
        await update.message.reply_text("❌ File not found or is a directory.", parse_mode="HTML")
        return

    # Security blacklist check
    sensitive_blacklist = [".env", "id_rsa", "id_ed25519", "sam", "system", "security", ".git", ".ssh", "ntuser.dat"]
    resolved = req_path.resolve()
    for item in sensitive_blacklist:
        if item.lower() in resolved.name.lower() or item.lower() in [p.lower() for p in resolved.parts]:
            await update.message.reply_text("⛔ <b>Access Denied:</b> This file is protected by Sentinel security policy.", parse_mode="HTML")
            return

    # Check file size (Telegram limit: 50MB)
    size_mb = resolved.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        await update.message.reply_text(f"⚠️ File is too large ({size_mb:.1f} MB). Telegram upload limit is 50 MB.", parse_mode="HTML")
        return

    msg = await update.message.reply_text(f"📤 <i>Sending {html.escape(resolved.name)} ({size_mb:.2f} MB)...</i>", parse_mode="HTML")
    try:
        with open(resolved, "rb") as f:
            await update.effective_chat.send_document(
                document=f,
                caption=f"📄 <b>File from PC:</b> <code>{html.escape(resolved.name)}</code>\n💾 Size: <code>{size_mb:.2f} MB</code>",
                parse_mode="HTML"
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await msg.edit_text(f"❌ Failed to send file: {e}")


async def handle_clip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set PC clipboard text: /clip <text>"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/clip Text to copy onto PC clipboard</code>", parse_mode="HTML")
        return
    text = " ".join(context.args)
    ok = SystemController.set_clipboard(text)
    if ok:
        await update.message.reply_text(f"📋 <b>Copied to PC Clipboard!</b>\n<pre>{html.escape(text)}</pre>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Failed to set PC clipboard.")


async def handle_getclip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read PC clipboard text: /getclip"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    content = SystemController.get_clipboard()
    await update.message.reply_text(f"📋 <b>PC Clipboard Content:</b>\n<pre>{html.escape(content)}</pre>", parse_mode="HTML")


def format_cleanup_preview(candidates: List[Dict[str, Any]]) -> Tuple[str, InlineKeyboardMarkup]:
    """Format an informative storage scan preview and approval keyboard."""
    if not candidates:
        text = (
            "🧹 <b>STORAGE CLEANUP AUDIT</b>\n\n"
            "✨ <b>Storage is clean!</b>\n\n"
            "No temporary recordings or cached downloads found in:\n"
            "• <code>recordings/</code>\n"
            "• <code>downloads/</code>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")]
        ])
        return text, keyboard

    total_bytes = sum(c["size_bytes"] for c in candidates)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    count = len(candidates)

    rec_files = [c for c in candidates if c["folder"] == "recordings"]
    dl_files = [c for c in candidates if c["folder"] == "downloads"]

    lines = [
        "🧹 <b>STORAGE CLEANUP — APPROVAL REQUIRED</b>\n",
        f"Sentinel audited cache folders and found <b>{count} file(s)</b> ({total_mb} MB):\n"
    ]

    if rec_files:
        rec_mb = round(sum(c["size_bytes"] for c in rec_files) / (1024 * 1024), 2)
        lines.append(f"📁 <b>recordings/</b> ({len(rec_files)} files, {rec_mb} MB):")
        for f in rec_files[:6]:
            lines.append(f" • <code>{html.escape(f['name'])}</code> ({f['size_mb']} MB, {f['age_str']})")
        if len(rec_files) > 6:
            lines.append(f"   <i>...and {len(rec_files) - 6} more</i>")
        lines.append("")

    if dl_files:
        dl_mb = round(sum(c["size_bytes"] for c in dl_files) / (1024 * 1024), 2)
        lines.append(f"📁 <b>downloads/</b> ({len(dl_files)} files, {dl_mb} MB):")
        for f in dl_files[:6]:
            lines.append(f" • <code>{html.escape(f['name'])}</code> ({f['size_mb']} MB, {f['age_str']})")
        if len(dl_files) > 6:
            lines.append(f"   <i>...and {len(dl_files) - 6} more</i>")
        lines.append("")

    lines.append("⚠️ <b>Do you approve permanently deleting these files?</b>")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Confirm & Delete ({total_mb} MB)", callback_data="cb_clean_confirm"),
        ],
        [
            InlineKeyboardButton("❌ Cancel Cleanup", callback_data="cb_clean_cancel"),
            InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu"),
        ]
    ])

    return "\n".join(lines), keyboard


async def handle_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Audit storage and seek explicit approval before deleting files: /clean"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    candidates = SystemController.scan_storage_candidates(config.RECORDINGS_DIR, config.DOWNLOADS_DIR)
    context.user_data["pending_cleanup"] = [c["path"] for c in candidates]
    text, keyboard = format_cleanup_preview(candidates)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


_bot_app = None
_bot_loop = None


def _alarm_trigger_dispatcher(label: str, time_str: str):
    """Callback fired by AlarmManager when a timer triggers on PC."""
    global _bot_app, _bot_loop
    if _bot_app and _bot_loop and _bot_loop.is_running():
        async def _notify():
            alert_text = (
                "🚨 <b>ALARM TRIGGERED ON PC!</b> 🚨\n\n"
                f"• <b>Label:</b> <code>{html.escape(label)}</code>\n"
                f"• <b>Trigger Time:</b> <code>{time_str}</code>\n\n"
                "🔊 <i>Alarm siren and voice alert are actively ringing on your PC speakers!</i>"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔕 Silence Alarm", callback_data="cb_alarm_stop")],
                [InlineKeyboardButton("⏰ Alarm Menu", callback_data="cb_alarm_menu")],
            ])
            for owner_id in config.AUTHORIZED_USER_IDS:
                try:
                    await _bot_app.bot.send_message(chat_id=owner_id, text=alert_text, reply_markup=kb, parse_mode="HTML")
                except Exception as err:
                    logger.error(f"Failed to send alarm alert to {owner_id}: {err}")

        asyncio.run_coroutine_threadsafe(_notify(), _bot_loop)


async def handle_alarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage customizable PC alarms: /alarm [time] [label]"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return

    args = context.args
    if not args:
        text, kb = format_alarm_menu_text()
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
        return

    first_arg = args[0].lower().strip()
    if first_arg in ("cancel", "clear"):
        if SystemController.cancel_alarm():
            await update.message.reply_text("✅ <b>Scheduled alarm cancelled.</b>", parse_mode="HTML")
        else:
            await update.message.reply_text("ℹ️ No active scheduled alarm found to cancel.")
        return
    elif first_arg in ("stop", "silence", "mute"):
        if SystemController.stop_alarm():
            await update.message.reply_text("🔕 <b>Alarm silenced successfully.</b>", parse_mode="HTML")
        else:
            await update.message.reply_text("ℹ️ No alarm is currently ringing.")
        return
    elif first_arg in ("now", "siren"):
        label = " ".join(args[1:]) if len(args) > 1 else "Instant Alarm"
        SystemController.play_alert_siren(label)
        await update.message.reply_text(
            f"🚨 <b>Alert Siren sounding on PC!</b>\n• <b>Label:</b> <code>{html.escape(label)}</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔕 Silence Alarm", callback_data="cb_alarm_stop")]]),
            parse_mode="HTML"
        )
        return

    raw_input = " ".join(args)
    seconds, label = SystemController.parse_alarm_time(raw_input)
    if seconds is None or seconds <= 0:
        await update.message.reply_text(
            "⚠️ <b>Invalid alarm time format.</b>\n\n"
            "<b>Supported Examples:</b>\n"
            "• <code>/alarm 10m</code> <i>(in 10 minutes)</i>\n"
            "• <code>/alarm 45s Stretch</code> <i>(in 45 seconds with label)</i>\n"
            "• <code>/alarm 1.5h Deep Work</code> <i>(in 90 minutes)</i>\n"
            "• <code>/alarm 18:30 Dinner</code> <i>(at 18:30 clock time)</i>\n"
            "• <code>/alarm 7:00am Wake up</code> <i>(at 07:00 tomorrow)</i>",
            parse_mode="HTML"
        )
        return

    alarm_info = SystemController.set_alarm(seconds, label, callback=_alarm_trigger_dispatcher)
    mins = seconds // 60
    secs = seconds % 60
    hours = mins // 60
    mins = mins % 60
    dur_str = f"{hours}h {mins}m {secs}s" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel This Alarm", callback_data="cb_alarm_cancel")],
        [InlineKeyboardButton("⏰ Alarm Menu", callback_data="cb_alarm_menu")],
    ])

    await update.message.reply_text(
        f"⏰ <b>PC Alarm Scheduled!</b>\n\n"
        f"• <b>Duration:</b> <code>{dur_str}</code>\n"
        f"• <b>Trigger Time:</b> <code>{alarm_info['target_time_str']}</code>\n"
        f"• <b>Label:</b> <code>{html.escape(label)}</code>\n\n"
        f"🔊 <i>When the time arrives, PC speakers will announce the label and sound the alarm siren.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )


async def handle_stopalarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Silence any active alarm: /stopalarm"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if SystemController.stop_alarm():
        await update.message.reply_text("🔕 <b>Alarm silenced.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ No alarm is currently ringing.")


async def handle_cancelalarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel scheduled alarm: /cancelalarm"""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    if SystemController.cancel_alarm():
        await update.message.reply_text("✅ <b>Scheduled alarm cancelled.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ No active scheduled alarm found to cancel.")


async def handle_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save any received document/photo into downloads directory on PC and play if audio."""
    if not is_authorized(update.effective_user.id):
        await notify_unauthorized_access(update, context)
        return
    doc = update.message.document
    if not doc:
        return

    raw_name = Path(doc.file_name or "downloaded_file").name
    safe_name = "".join(c for c in raw_name if c.isalnum() or c in "._- ") or "file.bin"
    save_path = (config.DOWNLOADS_DIR / safe_name).resolve()

    # Path traversal protection
    if not str(save_path).startswith(str(config.DOWNLOADS_DIR.resolve())):
        await update.message.reply_text("⛔ Security Violation: Invalid path.", parse_mode="HTML")
        return

    file_obj = await context.bot.get_file(doc.file_id)
    await file_obj.download_to_drive(save_path)

    # If document is an audio file, also play it aloud
    if save_path.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
        await update.message.reply_text(f"🔊 <i>Playing audio document on PC speakers:</i> <code>{html.escape(save_path.name)}</code>", parse_mode="HTML")
        await asyncio.to_thread(SystemController.play_audio_file, save_path)

    await update.message.reply_text(
        f"📥 <b>File Saved to PC!</b>\n\n"
        f"<b>Filename:</b> <code>{html.escape(doc.file_name)}</code>\n"
        f"<b>Saved Path:</b> <code>{save_path}</code>",
        parse_mode="HTML"
    )


async def handle_incoming_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive voice notes or audio files and play them aloud through laptop speakers."""
    if not is_authorized(update.effective_user.id):
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    duration = getattr(voice, 'duration', 0)
    dur_str = f" ({duration}s)" if duration else ""
    msg = await update.message.reply_text(
        f"🔊 <i>Downloading voice note{dur_str} & routing to PC speakers...</i>",
        parse_mode="HTML"
    )

    try:
        file_obj = await context.bot.get_file(voice.file_id)
        ext = ".ogg" if update.message.voice else (Path(getattr(voice, 'file_name', 'audio.mp3')).suffix or ".mp3")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_path = config.DOWNLOADS_DIR / f"voice_{timestamp}{ext}"
        await file_obj.download_to_drive(saved_path)

        ok, res = await asyncio.to_thread(SystemController.play_audio_file, saved_path)
        if ok:
            await msg.edit_text(
                f"🔊 <b>Voice note played successfully through PC speakers!</b>\n⏱️ Duration: <code>{duration}s</code>",
                parse_mode="HTML"
            )
        else:
            await msg.edit_text(f"⚠️ Could not play audio through PC speakers: {res}")
    except Exception as e:
        logger.error(f"Voice playback error: {e}")
        await msg.edit_text(f"❌ Failed to process voice note: {e}")


async def handle_incoming_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When user types any direct message, speak it aloud through PC speakers via TTS."""
    if not is_authorized(update.effective_user.id):
        return
    text = update.message.text
    if not text:
        return

    ok = await asyncio.to_thread(SystemController.speak_text, text)
    if ok:
        await update.message.reply_text(
            f"🗣️ <i>Spoken aloud on PC speakers:</i>\n\"{html.escape(text)}\"",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Failed to synthesize speech on PC.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates and notify user."""
    logger.error(f"Exception while handling an update: {context.error}")
    if isinstance(update, Update):
        if update.callback_query:
            try:
                await update.callback_query.answer("⚠️ Processing error occurred.")
            except Exception:
                pass
        if update.effective_message:
            try:
                err_msg = str(context.error)
                if "Message is not modified" not in err_msg:
                    await update.effective_message.reply_text(f"⚠️ <b>Error:</b> <code>{html.escape(err_msg)}</code>", parse_mode="HTML")
            except Exception:
                pass


# ── Callback Query Router ──────────────────────────────────────────────

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route interactive button clicks."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("⛔ Unauthorized.")
        return

    data = query.data

    if data == "cb_menu":
        await query.edit_message_text("🛡️ <b>PC REMOTE SENTINEL — COMMAND CENTER</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
    elif data == "cb_status":
        await handle_status(update, context)
    elif data == "cb_shot":
        await handle_screenshot(update, context)
    elif data in ("cb_webcam", "cb_webcam_menu"):
        await query.edit_message_text("📷 <b>WEBCAM SURVEILLANCE MENU</b>\nSelect an action:", reply_markup=get_webcam_keyboard(), parse_mode="HTML")
    elif data == "cb_webcam_shot":
        await handle_webcam(update, context)
    elif data == "cb_rec_webcam_10":
        await execute_webcam_recording(update, context, duration=10)
    elif data == "cb_rec_webcam_30":
        await execute_webcam_recording(update, context, duration=30)
    elif data == "cb_screen_menu":
        await query.edit_message_text("🎥 <b>DESKTOP SCREEN RECORDING</b>\nSelect recording duration:", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data.startswith("cb_rec_screen_"):
        sec = int(data.split("_")[-1])
        await execute_screen_recording(update, context, duration=sec)
    elif data == "cb_record_screen":
        await query.edit_message_text("🎥 <b>DESKTOP SCREEN RECORDING</b>\nSelect recording duration:", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data == "cb_top":
        await handle_top(update, context)
    elif data == "cb_clip_menu":
        clip_preview = SystemController.get_clipboard()
        truncated = clip_preview[:250] + ("..." if len(clip_preview) > 250 else "")
        await query.edit_message_text(
            f"📋 <b>PC CLIPBOARD MANAGER</b>\n\n"
            f"<b>Current Clipboard:</b>\n<pre>{html.escape(truncated)}</pre>\n\n"
            f"<i>To copy text to PC from your phone, send:</i>\n<code>/clip Your text here</code>",
            reply_markup=get_clipboard_keyboard(),
            parse_mode="HTML"
        )
    elif data == "cb_clip_read":
        clip_full = SystemController.get_clipboard()
        await query.message.reply_text(f"📋 <b>PC Clipboard Content:</b>\n<pre>{html.escape(clip_full)}</pre>", parse_mode="HTML")
    elif data == "cb_clean":
        candidates = SystemController.scan_storage_candidates(config.RECORDINGS_DIR, config.DOWNLOADS_DIR)
        context.user_data["pending_cleanup"] = [c["path"] for c in candidates]
        text, keyboard = format_cleanup_preview(candidates)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif data == "cb_clean_confirm":
        pending = context.user_data.pop("pending_cleanup", None)
        if pending is None:
            candidates = SystemController.scan_storage_candidates(config.RECORDINGS_DIR, config.DOWNLOADS_DIR)
            pending = [c["path"] for c in candidates]

        if not pending:
            await query.edit_message_text(
                "✨ <b>Storage is clean!</b> No files found to delete.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")]]),
                parse_mode="HTML"
            )
            return

        count, freed = SystemController.delete_storage_files(pending, [config.RECORDINGS_DIR, config.DOWNLOADS_DIR])
        mb = round(freed / (1024 * 1024), 2)
        await query.edit_message_text(
            f"🧹 <b>STORAGE CLEANUP COMPLETED</b> ✅\n\n"
            f"• <b>Files Deleted:</b> <code>{count}</code>\n"
            f"• <b>Disk Space Freed:</b> <code>{mb} MB</code>\n\n"
            f"Scanned & cleared: <code>recordings/</code>, <code>downloads/</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")]]),
            parse_mode="HTML"
        )
    elif data == "cb_clean_cancel":
        context.user_data.pop("pending_cleanup", None)
        await query.edit_message_text(
            "❌ <b>Storage Cleanup Cancelled</b>\n\n"
            "No files were deleted. Your recordings and downloads remain intact.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")]]),
            parse_mode="HTML"
        )
    elif data == "cb_tts_info":
        await query.message.reply_text(
            "🗣️ <b>Speaker & Voice Playback:</b>\n\n"
            "• <b>Type to Speak:</b> Send any message directly or use <code>/say &lt;text&gt;</code> to speak aloud via PC speakers!\n"
            "• <b>Voice Notes:</b> Send a voice note or audio file to play your voice directly through the laptop speakers!",
            parse_mode="HTML"
        )
    elif data in ("cb_alarm", "cb_alarm_menu"):
        text, kb = format_alarm_menu_text()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "cb_alarm_trigger_now":
        SystemController.play_alert_siren("Instant Alert")
        await query.answer("🚨 Siren sounding on PC!")
        text, kb = format_alarm_menu_text()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "cb_alarm_stop":
        SystemController.stop_alarm()
        await query.answer("🔕 Alarm silenced!")
        text, kb = format_alarm_menu_text()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "cb_alarm_cancel":
        if SystemController.cancel_alarm():
            await query.answer("❌ Scheduled alarm cancelled!")
        else:
            await query.answer("ℹ️ No scheduled alarm active.")
        text, kb = format_alarm_menu_text()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data.startswith("cb_alarm_set_"):
        secs = int(data.split("_")[-1])
        label = f"{secs // 60}m Timer" if secs >= 60 else f"{secs}s Timer"
        SystemController.set_alarm(secs, label, callback=_alarm_trigger_dispatcher)
        await query.answer(f"⏰ Alarm set for {label}!")
        text, kb = format_alarm_menu_text()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "cb_power_menu":
        await query.edit_message_text("⚡ <b>PC POWER & SLEEP MANAGEMENT</b>", reply_markup=get_power_keyboard(), parse_mode="HTML")
    elif data == "cb_media_menu":
        await query.edit_message_text("🎵 <b>MEDIA PLAYBACK & SYSTEM VOLUME</b>", reply_markup=get_media_keyboard(), parse_mode="HTML")
    elif data == "cb_vol_up":
        SystemController.control_media("up")
        await query.answer("🔊 Volume +10%")
    elif data == "cb_vol_down":
        SystemController.control_media("down")
        await query.answer("🔉 Volume -10%")
    elif data == "cb_vol_mute":
        SystemController.control_media("mute")
        await query.answer("🔇 Mute toggled")
    elif data == "cb_media_play_pause":
        SystemController.control_media("play_pause")
        await query.answer("⏯️ Play / Pause toggled")
    elif data == "cb_media_next":
        SystemController.control_media("next")
        await query.answer("⏭️ Next Track")
    elif data == "cb_media_prev":
        SystemController.control_media("prev")
        await query.answer("⏮️ Previous Track")
    elif data == "cb_media_stop":
        SystemController.control_media("stop")
        await query.answer("⏹️ Playback Stopped")
    elif data == "cb_pwr_sleep":
        await query.message.reply_text("💤 Putting PC to sleep...")
        SystemController.sleep_pc()
    elif data == "cb_pwr_lock":
        SystemController.lock_workstation()
        await query.message.reply_text("🔒 Workstation locked.")
    elif data == "cb_pwr_monitor_off":
        SystemController.turn_off_monitors()
        await query.message.reply_text("🖥️ Monitors put to sleep.")
    elif data == "cb_pwr_shutdown_now":
        await query.message.reply_text("🛑 Shutting down PC immediately...")
        SystemController.shutdown_pc(0)
    elif data == "cb_pwr_shut_15":
        SystemController.shutdown_pc(900)
        await query.message.reply_text("⏳ Shutdown scheduled in 15 minutes! Use Cancel button to abort.")
    elif data == "cb_pwr_shut_30":
        SystemController.shutdown_pc(1800)
        await query.message.reply_text("⏳ Shutdown scheduled in 30 minutes! Use Cancel button to abort.")
    elif data == "cb_pwr_shut_60":
        SystemController.shutdown_pc(3600)
        await query.message.reply_text("⏳ Shutdown scheduled in 1 hour! Use Cancel button to abort.")
    elif data == "cb_pwr_shut_cancel":
        if SystemController.cancel_shutdown():
            await query.message.reply_text("✅ Scheduled shutdown aborted successfully.")
        else:
            await query.message.reply_text("ℹ️ No active scheduled shutdown found.")
    elif data == "cb_pwr_restart":
        await query.message.reply_text("🔄 Restarting PC in 5 seconds...")
        SystemController.restart_pc(5)


def main():
    """Start PC Remote Sentinel Bot."""
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing! Set it in .env file.")
        print("\n⚠️ Error: TELEGRAM_BOT_TOKEN is not set in .env file!")
        print("Please edit C:\\Users\\Mazonia\\Desktop\\PC-Remote-Sentinel\\.env and add your bot token.\n")
        return

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Global error handler
    app.add_error_handler(error_handler)

    # Register handlers
    app.add_handler(CommandHandler(["start", "menu"], handle_start))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler(["shot", "screenshot"], handle_screenshot))
    app.add_handler(CommandHandler("webcam", handle_webcam))
    app.add_handler(CommandHandler("record_screen", handle_record_screen))
    app.add_handler(CommandHandler("record_webcam", handle_record_webcam))
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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_incoming_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_incoming_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_text))
    app.add_handler(CallbackQueryHandler(callback_router))

    async def post_init(application):
        global _bot_app, _bot_loop
        _bot_app = application
        _bot_loop = asyncio.get_running_loop()

        cmds = [
            BotCommand("start", "Command Center Dashboard"),
            BotCommand("status", "System Diagnostics (CPU, RAM, Uptime)"),
            BotCommand("shot", "Instant Desktop Screenshot"),
            BotCommand("webcam", "Capture Webcam Snapshot"),
            BotCommand("record_screen", "Record Desktop Screen (10s-120s)"),
            BotCommand("record_webcam", "Record Webcam Video Clip"),
            BotCommand("alarm", "PC Alarm & Timer (/alarm 20m Label)"),
            BotCommand("stopalarm", "Silence ringing alarm"),
            BotCommand("cancelalarm", "Cancel pending scheduled alarm"),
            BotCommand("top", "List Top RAM & CPU Processes"),
            BotCommand("kill", "Kill Process (/kill notepad.exe)"),
            BotCommand("say", "Speak text aloud on PC speakers"),
            BotCommand("clip", "Copy text to PC clipboard"),
            BotCommand("getclip", "Read PC clipboard content"),
            BotCommand("get", "Securely fetch file from PC"),
            BotCommand("clean", "Free disk space (cleanup old recordings)"),
            BotCommand("open", "Open URL or App on PC"),
            BotCommand("cmd", "Execute Terminal Command"),
        ]
        try:
            await application.bot.set_my_commands(cmds)
            logger.info("Registered Telegram menu commands.")
        except Exception as e:
            logger.warning(f"Could not register commands: {e}")

        # Broadcast Sentinel Online status to authorized owners
        import socket
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            hostname = "Windows PC"
            local_ip = "127.0.0.1"

        stats = SystemController.get_system_stats()
        startup_msg = (
            f"🛡️ <b>PC REMOTE SENTINEL ONLINE</b> ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💻 <b>Host:</b> <code>{html.escape(hostname)}</code> (<code>{local_ip}</code>)\n"
            f"⏱️ <b>Uptime:</b> <code>{stats['uptime']}</code>\n"
            f"🔋 <b>Battery:</b> <code>{stats['battery']}</code>\n"
            f"🧠 <b>RAM Used:</b> <code>{stats['memory_percent']}%</code>\n\n"
            f"<i>Sentinel is active and monitoring for commands.</i>"
        )
        for uid in config.AUTHORIZED_USER_IDS:
            try:
                await application.bot.send_message(chat_id=uid, text=startup_msg, reply_markup=get_main_keyboard(), parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Could not deliver startup message to {uid}: {e}")

    app.post_init = post_init
    logger.info("🛡️ PC Remote Sentinel Bot is running and actively listening...")
    app.run_polling()


if __name__ == "__main__":
    main()
