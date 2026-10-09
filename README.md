# 🛡️ PC Remote Sentinel & Multi-PC Fleet Commander

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API%20v21%2B-2CA5E0.svg?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Security: AES-256-GCM](https://img.shields.io/badge/Security-AES--256--GCM%20Encrypted-success.svg)](SECURITY.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **A secure, cross-network multi-PC remote management, surveillance, and automation system controlled entirely through a single Telegram Bot.**  
> Monitor, control, diagnose, and automate any number of Windows computers (home desktop, work laptop, gaming rig, remote servers, or a fleet of workstations) from your phone anywhere in the world — across local LAN, mobile hotspots, 4G/5G tethering, or firewalled networks.

---

## 🌟 Why PC Remote Sentinel?

Traditional remote desktop tools require port forwarding, static public IPs, complex VPN setups, or expensive subscription licenses. **PC Remote Sentinel** solves this with a modern, serverless architecture:

1. **One Central Bot for All Your PCs (`/pcs`)**: Seamlessly switch between any registered computer with interactive Telegram inline buttons.
2. **Works Everywhere (Cross-Network Cloud Relay)**: Built-in MQTT over TLS with AES-256-GCM encryption punches through Carrier-Grade NAT (CGNAT), phone hotspots, hotel Wi-Fi, and corporate firewalls without configuring routers.
3. **Double-Click USB Pendrive Installer (`install.bat`)**: Plug a USB drive into any PC (even brand-new out of the box), double-click, and it automatically sets up Python, creates a silent boot task, and connects to your bot in under 15 seconds.
4. **Completely Silent & Background Operation**: Runs invisibly via Windows Task Scheduler. No command prompt windows, no taskbar icons, and no system tray clutter.
5. **Direct Media Transport**: High-resolution screenshots and video recordings upload directly to Telegram's cloud API, bypassing intermediary servers for lightning-fast delivery.

---

## 🏗️ Architecture

```
                       ┌────────────────────────┐
                       │   Owner's Telegram     │
                       │   (Phone or Desktop)   │
                       └───────────▲────────────┘
                                   │
                     Telegram API  │  Bot Commands
                     (Media & UI)  │  (/start, /pcs, etc.)
                                   ▼
                       ┌────────────────────────┐
                       │   Central Telegram Bot │
                       │    (Fleet Commander)   │
                       └───────────┬────────────┘
                                   │
              MQTT over TLS (Port 8883 / 443 WSS)
              AES-256-GCM Encrypted with FLEET_SECRET
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Primary Desktop  │     │ Work Laptop      │     │ Remote Server    │
│ Home Wi-Fi       │     │ Mobile Hotspot   │     │ 4G USB Modem     │
│ (Local Subnet)   │     │ (CGNAT / 4G / 5G)│     │ (CGNAT / Remote) │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                     Direct Telegram Bot API
                     (Screenshots, Videos, Audio)
```

---

## ✨ Features & Capabilities

### 🖥️ Fleet Management & Multi-PC Switching
- **Interactive PC Selector (`/pcs`, `/start`)**: View all registered machines with live online/offline indicators and connection badges (e.g. `🟢 Work-Laptop (Mobile Hotspot)` or `🟢 Home-PC (Wi-Fi)`).
- **Auto-Discovery**: Newly installed computers automatically appear in your Telegram menu the moment they boot.
- **Last Will & Testament (LWT)**: If a computer is unplugged or loses network connection, your bot immediately updates its status to `🔴 Offline`.

### 📊 System Diagnostics & Surveillance
- **Real-time Diagnostics (`/status`)**: CPU utilization, RAM usage, disk storage, battery state, active window title, and system uptime.
- **Desktop Screenshots (`/shot`, `/screenshot`)**: Instant high-resolution snapshot of active monitors sent directly to Telegram.
- **Webcam Surveillance (`/webcam`, `/record_webcam`)**: Instant photo snapshot or short security video clip (10s/30s) from connected webcams.
- **Multi-Duration Screen Recorder (`/record_screen`)**: Interactive duration picker for 10s, 20s, 30s, 40s, 50s, 1 min, or 2 mins of on-screen desktop action into an MP4 video file.
- **Global 30 FPS Live Screen Casting (`/cast`, `/stream`)**: Launches an on-demand Cloudflare Quick Tunnel (`cloudflared.exe`) and generates a secure public HTTPS link to stream the live desktop to your phone browser at 30 FPS.

### ⚡ Workstation & Power Controls
- **Instant Lock (`/lock` or buttons)**: Locks the Windows workstation session immediately.
- **Power Management**: Put PC to sleep, turn off monitors, turn on/wake monitors (`/monitor on`), reboot, or schedule shutdown timers (15m, 30m, 60m).

### 📋 Process Manager & Terminal
- **Process Viewer (`/top`)**: Interactive list of top CPU and memory consuming processes with live refresh.
- **Process Killer (`/kill <name_or_pid>`)**: Terminate frozen applications or games remotely.
- **Remote Terminal (`/cmd <command>`)**: Execute Windows shell commands remotely with automatic token masking.

### 🔊 Audio, TTS & Speaker Controls
- **Text-to-Speech (`/say <text>`)**: Speak any message aloud through PC speakers using native Windows speech synthesis.
- **Voice Note Speaker Playback**: Send any voice note or audio file (.ogg, .mp3, .wav) to play your actual voice directly through the PC speakers.
- **PC Alarms & Timers (`/alarm [time] [label]`)**: Set countdown timers or specific clock alarms with siren alerts and speech synthesis.
- **Media Player Controls**: Play, pause, skip tracks, volume up/down, and mute for Spotify, YouTube, Chrome, VLC, and media players.

### 📁 Remote Files & Clipboard
- **File Downloader (`/get <path>`)**: Fetch any file from the PC directly into Telegram (up to 50MB).
- **File Dropper**: Send any document, photo, or script to the bot to automatically save it in the PC's `downloads/` folder.
- **Clipboard Sync (`/clip <text>`, `/getclip`)**: Read or push text directly to and from the Windows clipboard.
- **Storage Cleaner (`/clean`)**: Audit and clean up cached recordings and downloads with explicit confirmation.

### 🔒 Enterprise Security Architecture
- **User Whitelist Enforcement**: Only numeric Telegram user IDs configured in `AUTHORIZED_USER_IDS` can communicate with the bot.
- **Intruder Alerts**: Unrecognized users are blocked immediately, and an alert with their Telegram ID and username is dispatched to the owner.
- **AES-256-GCM End-to-End Encryption**: All MQTT relay messages and command payloads are encrypted with your shared `FLEET_SECRET`.
- **Optional PIN Lock**: Require `/login <PIN>` with automatic session timeout and rate limiting.

---

## 🚀 Quick Start Guide

### Step 1: Set Up Your Telegram Bot
1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, choose a name and username, and copy your **Bot Token**.
3. Message **[@userinfobot](https://t.me/userinfobot)** in Telegram to find your numeric **User ID** (e.g. `6513180621`).

### Step 2: Configure Master Settings
1. Clone the repository:
   ```bash
   git clone https://github.com/Mazonia/pc-controller-bot.git
   cd pc-controller-bot
   ```
2. Copy the template and edit your `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in your values:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   AUTHORIZED_USER_IDS=6513180621
   ```
3. Copy the deploy template for your USB pendrive:
   ```bash
   cp deploy_config.env.example deploy_config.env
   ```
   Fill in your `FLEET_SECRET`, `TELEGRAM_BOT_TOKEN`, and `AUTHORIZED_USER_IDS`.

### Step 3: Run the Fleet Commander Bot (Your Main PC / Server)
Double-click **`run.bat`** (or run `python bot.py`).  
*(To run it completely hidden in the background, double-click `start_hidden.vbs`)*.

---

## 💾 Deploying on Target PCs (USB Pendrive Setup)

To monitor any PC (personal laptop, gaming PC, home workstation, office desktop, or brand-new unboxed PC):

1. **Copy the repository folder to your USB pendrive** (ensure `install.bat`, `python-installer.exe`, and `deploy_config.env` are present).
2. **Plug the USB pendrive into the target PC**.
3. **Double-click `install.bat`**.
   - Grants Windows UAC Administrator rights.
   - Automatically installs Python (using the bundled offline installer if not already installed).
   - Copies files to `C:\PCSentinel`.
   - Registers a silent Task Scheduler auto-start on Windows user logon.
   - Launches the background agent immediately.
4. **Unplug your USB drive.** The PC is now live in your Telegram bot!

---

## 🕹️ Telegram Commands Reference

| Command | Description |
| :--- | :--- |
| `/start`, `/pcs` | Open Fleet Command Center & switch between monitored PCs |
| `/status` | View CPU, RAM, Disk, Battery, Uptime, and Active Window |
| `/shot`, `/screenshot` | Capture high-resolution multi-monitor screenshot |
| `/cast`, `/stream` | Start global 30 FPS Live Screen Streaming |
| `/webcam` | Capture photo from connected webcam |
| `/record_webcam [s]` | Record 10s or custom webcam video clip |
| `/record_screen [s]` | Record 10s–120s of on-screen desktop video |
| `/lock` | Instantly lock the Windows workstation |
| `/top` | Display top RAM & CPU consuming processes |
| `/kill <name_or_pid>` | Terminate running process (e.g. `/kill notepad.exe`) |
| `/say <text>` | Speak text aloud on PC speakers |
| `/clip <text>` | Copy text from phone to PC clipboard |
| `/getclip` | Read text from PC clipboard |
| `/get <path>` | Download file from PC to Telegram chat |
| `/alarm [time] [label]` | Set countdown timer (`10m`, `45s`, `1.5h`) or clock alarm (`18:30`) |
| `/stopalarm`, `/silence` | Silence and stop ringing PC alarm |
| `/cancelalarm` | Cancel pending scheduled alarm countdown |
| `/monitor [on\|off]` | Turn PC monitors on/off or wake screens |
| `/clean` | Audit and clean cached recordings/downloads |
| `/open <url>` | Open website or app on PC |
| `/cmd <command>` | Execute terminal command with token masking |
| `/login <pin>` | Authenticate PIN to unlock Command Center |
| `/logout` | Lock bot session immediately |
| `/reload` | Reload registered fleet registry |

---

## 🧹 Clean Uninstallation

To completely remove the agent from any monitored PC:
1. Double-click **`uninstall.bat`**.
2. Click "Yes" on the UAC prompt.
3. All background tasks, services, and `C:\PCSentinel` files will be cleanly removed.

---

## 🔒 Security Policy

For security guidelines, vulnerability disclosure, and details on encryption protocols, please refer to [SECURITY.md](SECURITY.md).

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
