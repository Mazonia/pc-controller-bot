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


def is_authorized(user_id: int) -> bool:
    """Check if sender ID is in authorized whitelist."""
    if not config.AUTHORIZED_USER_IDS:
        return False
    return user_id in config.AUTHORIZED_USER_IDS


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Create the primary interactive Command Center keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 System Status", callback_data="cb_status"),
            InlineKeyboardButton("📸 Screenshot", callback_data="cb_shot"),
        ],
        [
            InlineKeyboardButton("📷 Webcam Selfie", callback_data="cb_webcam"),
            InlineKeyboardButton("🎥 Screen Video", callback_data="cb_screen_menu"),
        ],
        [
            InlineKeyboardButton("⚡ Power & Sleep", callback_data="cb_power_menu"),
            InlineKeyboardButton("🔊 Volume Control", callback_data="cb_volume_menu"),
        ],
        [
            InlineKeyboardButton("💻 Top Processes", callback_data="cb_top"),
            InlineKeyboardButton("🗣️ Speak / TTS", callback_data="cb_tts_info"),
        ],
        [
            InlineKeyboardButton("🚨 Play Alert Alarm", callback_data="cb_alarm"),
            InlineKeyboardButton("🔄 Refresh Menu", callback_data="cb_menu"),
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


def get_volume_keyboard() -> InlineKeyboardMarkup:
    """Create interactive volume controller keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔊 Volume +10%", callback_data="cb_vol_up"),
            InlineKeyboardButton("🔉 Volume -10%", callback_data="cb_vol_down"),
        ],
        [
            InlineKeyboardButton("🔇 Mute / Unmute", callback_data="cb_vol_mute"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu"),
        ]
    ])


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
        return
    msg = await (update.effective_message.reply_text("📸 <i>Capturing desktop screenshot...</i>", parse_mode="HTML"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shot_path = config.RECORDINGS_DIR / f"shot_{timestamp}.png"
    if SystemController.take_screenshot(shot_path):
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
        return
    msg = await (update.effective_message.reply_text("📷 <i>Accessing webcam sensor...</i>", parse_mode="HTML"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_path = config.RECORDINGS_DIR / f"webcam_{timestamp}.jpg"
    ok, status = SystemController.take_webcam_photo(photo_path)
    if ok:
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
        return
    duration = min(max(duration, 3), 120)
    msg = await update.effective_message.reply_text(
        f"🎥 <i>Recording {duration}s of desktop screen... (please wait)</i>",
        parse_mode="HTML"
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = config.RECORDINGS_DIR / f"screen_{timestamp}_{duration}s.mp4"

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


async def handle_record_webcam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /record_webcam [seconds] command."""
    if not is_authorized(update.effective_user.id):
        return
    duration = 10
    if context.args and context.args[0].isdigit():
        duration = min(max(int(context.args[0]), 3), 60)

    msg = await update.effective_message.reply_text(f"📹 <i>Recording {duration}s from webcam...</i>", parse_mode="HTML")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = config.RECORDINGS_DIR / f"webcam_video_{timestamp}.mp4"
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
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/cmd dir</code> or <code>/cmd ipconfig</code>", parse_mode="HTML")
        return
    command = " ".join(context.args)
    code, output = SystemController.run_cmd(command)
    emoji = "✅" if code == 0 else "⚠️"
    truncated = output[:3500] if len(output) > 3500 else output
    text = f"{emoji} <b>Command Output (Code {code}):</b>\n<pre>{html.escape(truncated)}</pre>"
    await update.message.reply_text(text, parse_mode="HTML")


async def handle_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save any received document/photo into downloads directory on PC and play if audio."""
    if not is_authorized(update.effective_user.id):
        return
    doc = update.message.document
    if not doc:
        return
    file_obj = await context.bot.get_file(doc.file_id)
    save_path = config.DOWNLOADS_DIR / doc.file_name
    await file_obj.download_to_drive(save_path)

    # If document is an audio file, also play it aloud
    if doc.file_name and Path(doc.file_name).suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
        await update.message.reply_text(f"🔊 <i>Playing audio document on PC speakers:</i> <code>{html.escape(doc.file_name)}</code>", parse_mode="HTML")
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
    elif data == "cb_webcam":
        await handle_webcam(update, context)
    elif data == "cb_screen_menu":
        await query.edit_message_text("🎥 <b>DESKTOP SCREEN RECORDING</b>\nSelect recording duration:", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data.startswith("cb_rec_screen_"):
        sec = int(data.split("_")[-1])
        await execute_screen_recording(update, context, duration=sec)
    elif data == "cb_record_screen":
        await query.edit_message_text("🎥 <b>DESKTOP SCREEN RECORDING</b>\nSelect recording duration:", reply_markup=get_screen_keyboard(), parse_mode="HTML")
    elif data == "cb_top":
        await handle_top(update, context)
    elif data == "cb_tts_info":
        await query.message.reply_text(
            "🗣️ <b>Speaker & Voice Playback:</b>\n\n"
            "• <b>Type to Speak:</b> Send any message directly or use <code>/say &lt;text&gt;</code> to speak aloud via PC speakers!\n"
            "• <b>Voice Notes:</b> Send a voice note or audio file to play your voice directly through the laptop speakers!",
            parse_mode="HTML"
        )
    elif data == "cb_alarm":
        SystemController.play_alert_siren()
        await query.message.reply_text("🚨 <b>Alert Siren Beep sounded on PC!</b>", parse_mode="HTML")
    elif data == "cb_power_menu":
        await query.edit_message_text("⚡ <b>PC POWER & SLEEP MANAGEMENT</b>", reply_markup=get_power_keyboard(), parse_mode="HTML")
    elif data == "cb_volume_menu":
        await query.edit_message_text("🔊 <b>SYSTEM AUDIO & VOLUME CONTROLS</b>", reply_markup=get_volume_keyboard(), parse_mode="HTML")
    elif data == "cb_vol_up":
        SystemController.change_volume("up")
        await query.answer("🔊 Volume +10%")
    elif data == "cb_vol_down":
        SystemController.change_volume("down")
        await query.answer("🔉 Volume -10%")
    elif data == "cb_vol_mute":
        SystemController.change_volume("mute")
        await query.answer("🔇 Mute toggled")
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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_incoming_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_incoming_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_text))
    app.add_handler(CallbackQueryHandler(callback_router))

    async def post_init(application):
        cmds = [
            BotCommand("start", "Command Center & Dashboard"),
            BotCommand("status", "CPU, RAM, Disk & Uptime Diagnostics"),
            BotCommand("shot", "Instant Desktop Screenshot"),
            BotCommand("webcam", "Capture Webcam Snapshot"),
            BotCommand("record_screen", "Record Desktop Screen (10s-120s)"),
            BotCommand("record_webcam", "Record Webcam Video Clip"),
            BotCommand("top", "List Top RAM & CPU Processes"),
            BotCommand("kill", "Kill Process (e.g. /kill notepad.exe)"),
            BotCommand("say", "Speak text aloud on PC speakers"),
            BotCommand("open", "Open URL or App (e.g. /open https://...)"),
            BotCommand("cmd", "Execute Terminal Command"),
        ]
        try:
            await application.bot.set_my_commands(cmds)
            logger.info("Registered Telegram menu commands.")
        except Exception as e:
            logger.warning(f"Could not register commands: {e}")

    app.post_init = post_init
    logger.info("🛡️ PC Remote Sentinel Bot is running and actively listening...")
    app.run_polling()


if __name__ == "__main__":
    main()
