# 🛡️ PC Remote Sentinel & Command Center

A secure, full-duplex remote control, system monitoring, and surveillance bot for your Windows PC via Telegram.

Control your PC from anywhere in the world: inspect diagnostics, capture instant high-resolution desktop screenshots, record 10-second screen clips, trigger webcam security snapshots, adjust audio, execute text-to-speech, manage power states (sleep, shutdown timers), and drop incoming files directly onto your hard drive.

---

## ✨ Features & Capabilities

- 📊 **Real-time Diagnostics (`/status`)**: CPU load, RAM utilization, C: drive disk capacity, battery status, and uptime.
- 📸 **Desktop Screenshots (`/shot`, `/screenshot`)**: High-res multi-monitor or desktop snapshots sent immediately to your chat.
- 📹 **Webcam Surveillance (`/webcam`, `/record_webcam`)**: Instant photo capture or security video clip (10s/30s) from connected webcams.
- 🎬 **Multi-Duration Screen Recorder (`/record_screen`)**: Interactive selector for 10s, 20s, 30s, 40s, 50s, 1 min, or 2 mins of on-screen desktop action into an MP4 video file.
- ⚡ **Power & Workstation Control**:
  - Sleep PC, Lock workstation, turn off monitors, shutdown timers (15m, 30m, 60m), and PC restart.
- 🎵 **Media Player & Volume Controls**:
  - Play/Pause, Next Track, Previous Track, Volume +/- 10%, and Mute (controls Spotify, YouTube, VLC, Netflix, etc.).
- 🔊 **Audio & Speaker Control**:
  - 🗣️ **Direct Type-to-Speak & TTS (`/say <text>`)**: Type any message directly into chat or use `/say` to speak aloud via PC speakers using Windows speech synthesis.
  - 🎙️ **Voice Note Speaker Playback**: Send any voice note or audio file (.ogg, .mp3, .wav) to play your actual voice directly through your laptop/PC speakers.
  - 🚨 `/siren` / Alert Alarm — Play loud emergency alert audio through speakers.
- 📋 **Process & Task Manager**:
  - `/top` — Interactive view of top memory & CPU consuming processes with live refresh.
  - `/kill <name_or_pid>` — Terminate frozen or unwanted processes.
- 📋 **Clipboard Manager**:
  - `/clip <text>` — Push and copy text from your phone directly to the Windows clipboard.
  - `/getclip` — Read and view the current PC clipboard text remotely.
- 📤 **Remote File Fetcher (`/get <path>`)**: Securely download any file from your PC directly to your Telegram chat (up to 50MB).
- 📥 **Remote File Drop**: Send any file, document, or photo to the bot to automatically save it in your PC's `downloads/` folder (with path-traversal protection).
- 🧹 **Storage Cleaner (`/clean`)**: Purge old recordings and temp files older than 3 days to reclaim disk space.
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
| `/clean` | Cleanup old recordings to free disk space |
| `/open <url>` | Open website or app on PC |
| `/cmd <command>` | Execute terminal command with token masking & security protection |

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
