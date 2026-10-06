# 🛡️ PC Remote Sentinel & Command Center

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API%20v21%2B-2CA5E0.svg?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Security](https://img.shields.io/badge/Security-Whitelist%20Locked-brightgreen.svg)](SECURITY.md)

> **A secure, full-duplex remote control, system monitoring, surveillance, and automation bot for Windows PC via Telegram.**  
> Remotely capture desktop screenshots, record screen videos (up to 2 minutes), capture webcam security feeds, control media and volume, play voice notes on laptop speakers, sync clipboards, and monitor system diagnostics from your phone anywhere in the world.

---

## ✨ Features & Capabilities

- 📊 **Real-time Diagnostics (`/status`)**: CPU load, RAM utilization, C: drive disk capacity, battery status, and uptime.
- 📸 **Desktop Screenshots (`/shot`, `/screenshot`)**: High-res multi-monitor or desktop snapshots sent immediately to your chat.
- 📹 **Webcam Surveillance (`/webcam`, `/record_webcam`)**: Instant photo capture or security video clip (10s/30s) from connected webcams.
- 🎬 **Multi-Duration Screen Recorder (`/record_screen`)**: Interactive selector for 10s, 20s, 30s, 40s, 50s, 1 min, or 2 mins of on-screen desktop action into an MP4 video file.
- ⚡ **Power & Workstation Control**:
  - Sleep PC, Lock workstation, turn off monitors, wake/turn on monitors (`/monitor on`), shutdown timers (15m, 30m, 60m), and PC restart.
- ⏰ **Customizable PC Alarm & Countdown Timers (`/alarm [time] [label]`)**:
  - Set relative countdown timers (e.g. `/alarm 10m`, `/alarm 45s Stretch`, `/alarm 1.5h Deep Work`).
  - Set specific clock-time alarms (e.g. `/alarm 07:30 Wake up workout`, `/alarm 18:30 Dinner`).
  - Sound audible sirens and speech synthesis voice announcements through PC speakers.
  - Interactive timer menu with 1m, 5m, 10m, 15m, 30m, and 1h quick presets.
  - Remote alarm silencing (`/stopalarm`) and cancellation (`/cancelalarm`).
- 🎵 **Media Player & Volume Controls**:
  - Play/Pause toggle, Stop playback, Next track, Previous track, Volume +/- 10%, and Mute (controls Spotify, YouTube, Chrome, VLC, Edge, etc.).
- 🔊 **Audio & Speaker Control**:
  - 🗣️ **Direct Type-to-Speak & TTS (`/say <text>`)**: Type any message directly into chat or use `/say` to speak aloud via PC speakers using Windows speech synthesis.
  - 🎙️ **Voice Note Speaker Playback**: Send any voice note or audio file (.ogg, .mp3, .wav) to play your actual voice directly through your laptop/PC speakers.
  - 🚨 Alert Siren — Play loud emergency alert audio through PC speakers.
- 📋 **Process & Task Manager**:
  - `/top` — Interactive view of top memory & CPU consuming processes with live refresh.
  - `/kill <name_or_pid>` — Terminate frozen or unwanted processes.
- 📋 **Clipboard Manager**:
  - `/clip <text>` — Push and copy text from your phone directly to the Windows clipboard.
  - `/getclip` — Read and view the current PC clipboard text remotely.
- 📤 **Remote File Fetcher (`/get <path>`)**: Securely download any file from your PC directly to your Telegram chat (up to 50MB).
- 📥 **Remote File Drop**: Send any file, document, or photo to the bot to automatically save it in your PC's `downloads/` folder (with path-traversal protection).
- 🧹 **Interactive Storage Cleaner (`/clean`)**: Audit cached recordings and downloads with file names, sizes, and ages, requiring explicit user approval before permanent deletion.
- 🌐 **Remote Web Launch (`/open <url>`)**: Launch any website or URL in your PC's default web browser.
- 🛡️ **Enterprise Security Architecture**:
  - **Intruder Detection & Instant Owner Alerting**: Unrecognized Telegram users are immediately blocked and owners receive an alert with the intruder's ID, username, and attempted action.
  - **Credential Leakage Prevention**: `/cmd` blocks access to `.env` files and masks your Telegram bot token if dumped in environment variables.
  - **Path Traversal Protection**: Uploaded files and file fetches are strictly sanitized against directory traversal attacks.
  - **Hardware Concurrency Locking**: Prevents overlapping camera/recording operations from overloading the CPU or crashing hardware devices.
- 🏷️ **Dedicated Windows Process Name**: Runs as `pc-sentinel.exe` with console title `PC-Remote-Sentinel` for instant Task Manager identification.
- ⚡ **Instant Startup Broadcast**: Automatically notifies authorized owners in Telegram with host info, IP, uptime, and the Command Center keyboard when `run.bat` starts.

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
   - Send `/start` or `/menu` to open the full interactive Command Center!

---

## 🕹️ Telegram Commands Reference

| Command | Description |
| :--- | :--- |
| `/start`, `/menu` | Open interactive Command Center dashboard |
| `/status` | View real-time CPU, RAM, Disk, Battery, and Uptime |
| `/shot`, `/screenshot` | Capture instant high-resolution desktop screenshot |
| `/webcam` | Capture webcam photo snapshot |
| `/record_webcam [s]` | Record 10s or custom webcam video clip |
| `/record_screen [s]` | Open duration selector or record screen video (10s-120s) |
| `/top` | Display top RAM & CPU consuming processes |
| `/kill <name_or_pid>` | Terminate running process (e.g., `/kill notepad.exe`) |
| `/say <text>` | Speak text aloud on PC speakers (or send any text directly) |
| `/clip <text>` | Copy text from phone directly onto Windows clipboard |
| `/getclip` | Read text currently on Windows clipboard |
| `/get <path>` | Securely download a file from PC to Telegram chat |
| `/alarm [time] [label]` | Set countdown timer (`10m`, `45s`, `1.5h`) or clock alarm (`18:30`, `7:00am`) |
| `/stopalarm`, `/silence` | Silence and stop currently ringing PC alarm |
| `/cancelalarm` | Cancel pending scheduled alarm countdown |
| `/monitor [on\|off]` | Turn PC monitors on/off or wake screens from sleep mode |
| `/clean` | Audit & cleanup cached recordings/downloads with user approval |
| `/open <url>` | Open website or app on PC |
| `/cmd <command>` | Execute terminal command with token masking & security protection |

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
