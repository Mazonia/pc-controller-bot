# 🛡️ PC Remote Sentinel & Command Center

A secure, full-duplex remote control, system monitoring, and surveillance bot for your Windows PC via Telegram.

Control your PC from anywhere in the world: inspect diagnostics, capture instant high-resolution desktop screenshots, record 10-second screen clips, trigger webcam security snapshots, adjust audio, execute text-to-speech, manage power states (sleep, shutdown timers), and drop incoming files directly onto your hard drive.

---

## ✨ Features & Capabilities

- 📊 **Real-time Diagnostics (`/status`)**: CPU load, RAM utilization, C: drive disk capacity, battery status, and uptime.
- 📸 **Desktop Screenshots (`/shot`, `/screenshot`)**: High-res multi-monitor or desktop snapshots sent immediately to your chat.
- 📹 **Webcam Surveillance (`/webcam`, `/record_webcam`)**: Instant photo capture or security video clip from connected webcams.
- 🎬 **Multi-Duration Screen Recorder (`/record_screen`)**: Interactive selector for 10s, 20s, 30s, 40s, 50s, 1 min, or 2 mins of on-screen desktop action into an MP4 video file.
- ⚡ **Power & Workstation Control**:
  - Sleep PC, Lock workstation, turn off monitors, shutdown timers (15m, 30m, 60m), and PC restart.
- 🔊 **Audio & Speaker Control**:
  - `/mute`, volume up, volume down master audio controls.
  - 🗣️ **Direct Type-to-Speak & TTS (`/say <text>`)**: Type any message directly into chat or use `/say` to speak aloud via PC speakers using Windows speech synthesis.
  - 🎙️ **Voice Note Speaker Playback**: Send any voice note or audio file (.ogg, .mp3, .wav) to play your actual voice directly through your laptop/PC speakers.
  - `/siren` / Alert Alarm — Play loud emergency alert audio through speakers.
- 📋 **Process & Task Manager**:
  - `/top` — Interactive view of top memory & CPU consuming processes with live refresh.
  - `/kill <name_or_pid>` — Terminate frozen or unwanted processes.
- 📥 **Remote File Drop**: Send any file, document, or photo to the bot to automatically save it in your PC's `downloads/` folder.
- 🌐 **Remote Web Launch (`/open <url>`)**: Launch any website or URL in your PC's default web browser.
- 🛡️ **Strict Whitelist Security**: Ignores all messages from unauthorized Telegram users. Only IDs listed in `AUTHORIZED_USER_IDS` can interact.
- 🏷️ **Dedicated Windows Process Name**: Runs as `pc-sentinel.exe` with console title `PC-Remote-Sentinel` for instant Task Manager identification.

---

## 📋 Prerequisites & Setup Guide

### 1. Getting a Telegram Bot Token
1. Open Telegram and search for the official **[@BotFather](https://t.me/BotFather)**.
2. Send `/start` and then `/newbot`.
3. Choose a name (e.g. `My PC Sentinel`) and username (e.g. `john_pc_sentinel_bot`).
4. Copy the HTTP API token provided by BotFather:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

### 2. Getting Your Numeric Telegram User ID (Critical Security Step)
To ensure only **you** can control your PC, you must configure your Telegram numeric User ID:
1. Search for **[@userinfobot](https://t.me/userinfobot)** in Telegram.
2. Press `/start`.
3. Copy your numeric **Id** (e.g., `987654321`).
4. Set this in `.env` as `AUTHORIZED_USER_IDS=987654321`.
   *(Multiple IDs can be comma-separated: `AUTHORIZED_USER_IDS=987654321,11223344`)*

### 3. Optional Hardware & Permissions
- **Webcam access**: Requires a functional USB or built-in webcam.
- **Administrator rights**: While basic monitoring and media controls work under standard permissions, power actions (like shutdown or sleep) may require running PowerShell/command prompt as Administrator on certain Windows editions.

---

## 🚀 Installation & Running

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Mazonia/pc-controller-bot.git
   cd pc-controller-bot
   ```

2. **Configure your `.env` file**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in your tokens:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   AUTHORIZED_USER_IDS=987654321
   RECORDINGS_DIR=./recordings
   DOWNLOADS_DIR=./downloads
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the Sentinel**:
   - **Option A (Recommended)**: Double-click `run.bat` or run:
     ```powershell
     .\run.bat
     ```
     *(Runs as `pc-sentinel.exe` in Windows Task Manager)*
   - **Option B**:
     ```powershell
     python bot.py
     ```

5. **Interact in Telegram**:
   - Send `/start` or `/help` to see the full interactive menu with inline buttons!

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
