# 🛡️ PC Remote Sentinel & Command Center

A complete 2-way remote control and surveillance system for your Windows PC via Telegram.

## 🚀 Features
- **📊 Real-time Diagnostics**: CPU load, per-core load, RAM usage, C: disk space, battery status, and uptime.
- **📸 Desktop Screenshots**: Instant high-res capture of your desktop screen.
- **📷 Webcam Surveillance**: Snapshot photos and 10s video clips directly from your PC webcam.
- **🎥 Screen Recording**: Record 10-second desktop screen videos sent directly to Telegram.
- **⚡ Advanced Power Controller**: Sleep, Lock Workstation, Turn Off Monitors, Instant Shutdown, Timed Shutdown (15m, 30m, 1h), and Cancel Shutdown.
- **🔊 Audio & Speech**: Remote volume up/down/mute, text-to-speech `/say <message>` on PC speakers, and alert siren sound.
- **💻 Task Manager**: Top processes view and kill frozen tasks `/kill <name_or_pid>`.
- **📁 File Drop**: Forward files to the bot to automatically save them into your PC's `downloads/` folder.
- **🌐 Open Links & Apps**: `/open https://youtube.com` opens in default browser.
- **🔒 Whitelist Security**: Restricts control to authorized Telegram user IDs only.

## 🛠️ Quick Setup
1. Create a bot using [@BotFather](https://t.me/BotFather) on Telegram and copy the API token.
2. Get your Telegram User ID by sending `/start` to [@userinfobot](https://t.me/userinfobot).
3. Copy `.env.example` to `.env` and fill in:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   AUTHORIZED_USER_IDS=123456789
   ```
4. Double-click `run.bat` or run `python bot.py`.
