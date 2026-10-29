# 🛡️ PC Remote Sentinel & Multi-PC Fleet Commander

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API%20v21%2B-2CA5E0.svg?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Security: AES-256-GCM](https://img.shields.io/badge/Security-AES--256--GCM%20Encrypted-success.svg)](SECURITY.md)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

> **A secure, cross-network multi-PC remote management, surveillance, and automation system controlled entirely through a single Telegram Bot.**  
> Monitor, control, diagnose, and automate any number of Windows computers (home desktop, work laptop, gaming rig, remote servers, or a fleet of workstations) from your phone anywhere in the world - across local LAN, mobile hotspots, 4G/5G tethering, or firewalled networks.

---

## 📑 Table of Contents
- [🌟 Why PC Remote Sentinel?](#why-pc-remote-sentinel)
- [🏗️ Architecture](#architecture)
- [✨ Features & Capabilities](#features-capabilities)
  - [🖥️ Fleet Management & Multi-PC Switching](#fleet-management-multi-pc-switching)
  - [📊 System Diagnostics & Surveillance](#system-diagnostics-surveillance)
  - [🖱️ Phone as a Mouse, Multi-Touch Windows Gestures & Typing](#phone-as-a-mouse-ghost-trackpad-direct-typing-mouse-type-key)
  - [🪟 Desktops & Windows Application Switching](#desktops-windows-application-switching)
  - [📋 Process Manager & Terminal](#process-manager-terminal)
  - [🔊 Audio, TTS & Speaker Controls](#audio-tts-speaker-controls)
  - [📁 Remote File Explorer & Clipboard](#remote-file-explorer-clipboard)
  - [🛡️ Anti-Timeout & Network Resilience Shield](#anti-timeout-network-resilience-shield)
  - [🔒 Enterprise Security Architecture](#enterprise-security-architecture)
- [🚀 Quick Start Guide](#quick-start-guide)
  - [Step 1: Set Up Your Telegram Bot](#step-1-set-up-your-telegram-bot)
  - [Step 2: Configure Master Settings](#step-2-configure-master-settings)
  - [Step 3: Run the Fleet Commander Bot](#step-3-run-the-fleet-commander-bot)
    - [📱 Option A: Android Phone (24/7 Always-On via Termux)](#option-a-android-phone-247-always-on-via-termux-recommended)
    - [☁️ Option B: Free 24/7 Cloud Server (Render / Railway / Docker)](#option-b-free-247-cloud-server-render-railway-docker-zero-phone-battery)
    - [💻 Option C: Windows Main PC / Laptop](#option-c-windows-main-pc-laptop-auto-start-on-boot)
- [🔄 Redundancy & Offline Self-Healing](#redundancy-offline-self-healing)
- [💾 Deploying on Target PCs (Two Effortless Methods)](#deploying-on-target-pcs-two-effortless-methods)
  - [🌐 Method 1: Over-the-Air Network Deployment](#method-1-over-the-air-network-deployment-recommended-for-1100-pcs)
  - [🔌 Method 2: Portable SSD & USB 1-Click Auto-Installer](#method-2-portable-ssd-usb-1-click-auto-installer-100-offline)
- [🕹️ Telegram Commands Reference](#telegram-commands-reference)
- [🧪 Test Suite & Quality Assurance](#test-suite-quality-assurance)
- [🧹 Clean Uninstallation (Zero Trace)](#clean-uninstallation-zero-trace)
  - [From Monitored Target PCs](#from-monitored-target-pcs)
  - [From Your Main Host PC](#from-your-main-host-pc)
- [🔒 Security Policy](#security-policy)
- [📄 License](#license)

---

## 🌟 Why PC Remote Sentinel? <a id="why-pc-remote-sentinel"></a>

Traditional remote desktop tools require port forwarding, static public IPs, complex VPN setups, or expensive subscription licenses. **PC Remote Sentinel** solves this with a modern, serverless architecture:

1. **One Central Bot for All Your PCs (`/pcs`)**: Seamlessly switch between any registered computer with interactive Telegram inline buttons.
2. **Works Everywhere (Cross-Network Cloud Relay)**: Built-in MQTT over TLS with AES-256-GCM encryption punches through Carrier-Grade NAT (CGNAT), phone hotspots, hotel Wi-Fi, and corporate firewalls without configuring routers.
3. **Double-Click USB Pendrive Installer (`install.bat`)**: Plug a USB drive into any PC (even brand-new out of the box), double-click, and it automatically sets up Python, creates a silent boot task, and connects to your bot in under 15 seconds.
4. **Completely Silent & Background Operation**: Runs invisibly via Windows Task Scheduler. No command prompt windows, no taskbar icons, and no system tray clutter.
5. **Direct Media Transport**: High-resolution screenshots and video recordings upload directly to Telegram's cloud API, bypassing intermediary servers for lightning-fast delivery.
6. **Anti-Timeout & Network Resilience Shield**: Engineered specifically for high-latency, unstable cellular hotspots, and packet-loss prone connections with automated retries, local loopback routing, dynamic JPEG compression, and live `/net` ping diagnostics.

---

## 🏗️ Architecture <a id="architecture"></a>

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

## ✨ Features & Capabilities <a id="features-capabilities"></a>

### 🖥️ Fleet Management & Multi-PC Switching <a id="fleet-management-multi-pc-switching"></a>
- **Interactive PC Selector (`/pcs`, `/start`)**: View all registered machines with live online/offline indicators and connection badges (e.g. `🟢 Work-Laptop (Mobile Hotspot)` or `🟢 Home-PC (Wi-Fi)`).
- **Auto-Discovery**: Newly installed computers automatically appear in your Telegram menu the moment they boot.
- **Last Will & Testament (LWT)**: If a computer is unplugged or loses network connection, your bot immediately updates its status to `🔴 Offline`.

### 📊 System Diagnostics & Surveillance <a id="system-diagnostics-surveillance"></a>
- **Real-time Diagnostics (`/status`)**: CPU utilization, RAM usage, disk storage, battery state, active window title, and system uptime.
- **Desktop Screenshots (`/shot`, `/screenshot`)**: Instant high-resolution snapshot of active monitors sent directly to Telegram.
- **Webcam Surveillance (`/webcam`, `/record_webcam`)**: Instant photo snapshot or short security video clip (10s/30s) from connected webcams.
- **Multi-Duration Screen Recorder (`/record_screen`)**: Interactive duration picker for 10s, 20s, 30s, 40s, 50s, 1 min, or 2 mins of on-screen desktop action into an MP4 video file.
- **Hardware-Accelerated 30 FPS Live Screen Casting (`/cast`, `/stream`)**:
  - **OpenCV Hardware Encoding Acceleration**: Converted frame resizing and compression from PIL down to high-performance C++ OpenCV (`cv2.cvtColor`, `cv2.resize`, `cv2.imencode`), reducing per-frame encode latency by 15x (from ~80-120ms to ~6ms) for butter-smooth 30+ FPS live desktop streaming.
  - **Zero-Stall Stream Pipeline**: Socket write buffer flushing prevents TCP frame buildup and eliminates jitter over both local Wi-Fi and mobile hotspots.
  - **Cross-Network Global Access**: Streams reliably across separate networks, cellular data (4G/5G), and CGNAT via automated Cloudflare Quick Tunnels (`https://*.trycloudflare.com`) with zero router port forwarding.
  - **Dual-Engine Web Player with Mobile Watchdog**: Smooth MJPEG video streaming + client-side watchdog that automatically re-syncs the stream if cellular signal dips.
  - **Interactive Remote Controls**: Control virtual desktops, inspect ping latency/FPS HUD, and capture high-res snapshots directly from your phone's browser.
  - **In-Chat Live Radar**: Rapid refreshing photo frames streamed directly inside your Telegram chat over the cloud relay.

### 🖱️ Phone as a Mouse (Ghost Trackpad), Multi-Touch Windows Gestures & Direct Typing (`/mouse`, `/type`, `/key`) <a id="phone-as-a-mouse-ghost-trackpad-direct-typing-mouse-type-key"></a>
- **Translucent "Ghost Trackpad"**: Turns your entire phone screen into a multi-touch mouse trackpad while faintly projecting the live PC desktop underneath so you can see exactly where you're pointing.
- **Adjustable Desktop Opacity**: Slide between **35% (faint ghost trackpad)**, **100% (vivid full desktop view)**, or **0% (OLED black stealth touchpad)**.
- **GPU-Accelerated Virtual Radar**: Hardware `translate3d` eliminates layout reflow for 120Hz butter-smooth cursor tracking with no transition lag.
- **Full Windows Multi-Touch Touchpad Gestures**:
  - **1-Finger Glide**: Smooth cursor gliding with non-linear velocity curve (precision dampening on micro-adjustments, smooth boost on fast flicks) and 3.0s input desktop throttling to eliminate micro-stutters.
  - **1-Finger Tap**: Left Click (with visual pulse indicator).
  - **1-Finger Double Tap**: Double Click (opens files and apps).
  - **1-Finger Tap-and-Drag**: Double-tap and hold to immediately grab windows, highlight text, or move desktop items.
  - **1-Finger Long Press (400ms)**: Right Click with phone haptic vibration feedback.
  - **2-Finger Tap**: Instant Right Click.
  - **2-Finger Pan (Vertical & Horizontal)**: Smooth vertical wheel scrolling and horizontal scrolling (`MOUSEEVENTF_HWHEEL`).
  - **2-Finger Pinch In / Pinch Out**: Hardware Zoom In / Zoom Out (`Ctrl + Wheel`).
  - **3-Finger Swipe Up**: Task View / Show All Windows (`Win + Tab`).
  - **3-Finger Swipe Down**: Show Desktop / Minimize All (`Win + D`).
  - **3-Finger Swipe Right**: Cycle to Next Application (`Alt + Tab`).
  - **3-Finger Swipe Left**: Cycle to Previous Application (`Alt + Shift + Tab`).
  - **3-Finger Tap**: Windows Search (`Win + S`).
  - **4-Finger Swipe Right**: Switch to Next Virtual Desktop (`Win + Ctrl + Right`).
  - **4-Finger Swipe Left**: Switch to Previous Virtual Desktop (`Win + Ctrl + Left`).
  - **4-Finger Swipe Up**: Windows Action Center / Notifications (`Win + A`).
  - **4-Finger Swipe Down**: Show Desktop (`Win + D`).
  - **4-Finger Tap**: Windows Settings (`Win + I`).
- **Visual Gesture HUD Badge**: Centered glass pill lights up dynamically with gesture icons and titles whenever any multi-finger gesture is triggered.
- **Quick-Action Gestures Ribbon**: 1-tap pills for Task View, Desktop, Alt+Tab, Search, Action Center, Settings, Clipboard History (`Win+V`), Snipping Tool (`Win+Shift+S`), and Zoom In/Out.
- **Right-Edge Scroll Strip**: Dedicated vertical strip for one-thumb fast scrolling.
- **🖲️ Drag Lock**: Toggle button locks left mouse down to easily drag windows, move files, or select text.
- **Phone-to-PC Direct Typing & Voice Dictation**:
  - Tap the floating input field on your phone to open your native smartphone keyboard.
  - Full support for **voice dictation / speech-to-text**, autocorrect, predictive typing, and swipe.
  - One-tap `[🚀 Send]` injects the text string into the active PC app using Win32 Unicode `SendInput` (emojis and international characters fully supported).
  - `[⚡ Live]` toggle for instant character-by-character keystroke streaming.
- **Special Keys Ribbon**: Floating scrollable quick pills for keys phone keyboards lack:
  `[⏎ Enter]`, `[⌫ Bksp]`, `[⇥ Tab]`, `[Esc]`, `[⊞ Win]`, `[📋 Paste]`, `[Copy]`, `[Cut]`, `[Sel All]`, `[Undo]`, `[Del]`, `[Space]`, `[▲]`, `[▼]`, `[◄]`, `[►]`, `[Alt+Tab]`, `[Win+D]`, `[Task View]`.
- **Telegram Mini App (TMA) Integration**:
  - Tap `🖱️ Open Ghost Mouse (TMA)` inside Telegram to open the trackpad right within your Telegram app!
- **In-Chat Quick Commands**:
  - `/type <message>` - Injects `<message>` directly into whatever app is focused on the PC.
  - `/key <key>` - Simulates keystrokes or hotkeys (e.g., `/key enter`, `/key ctrl+v`, `/key win+d`, `/key alt+f4`).
  - `/mouse` - Opens the mouse controller dashboard.

### 🪟 Desktops & Windows Application Switching <a id="desktops-windows-application-switching"></a>
- **Dedicated Remote Control (`/desktop`, `/windows`, `/switch`)**: Switch, create, or inspect Windows Virtual Desktops and cycle or focus active application windows with 1 tap from Telegram or the live web stream player.
- **Active Window Selection**: Tap any running application from the interactive Telegram keyboard or select it from the Live Stream dropdown to bring it directly to the front (even if minimized).
- **Fast Window Cycling**:
  - `[◀ Alt+Tab]` (Cycle forward)
  - `[Alt+Tab ▶]` (Cycle backward with Shift)
  - Direct Command: `/switch brave`, `/switch code`, `/switch spotify`
- **Virtual Desktop Navigation**:
  - `[◀ Prev Desktop]` (`Win + Ctrl + Left`)
  - `[Next Desktop ▶]` (`Win + Ctrl + Right`)
  - `[➕ New Desktop]` (`Win + Ctrl + D`)
  - `[🪟 Task View]` (`Win + Tab`)
  - `[❌ Close Desktop]` (`Win + Ctrl + F4`)
- **Safe Modifier Handling**: Fully isolated hardware scan-code events with guaranteed modifier key release in `finally` blocks to eliminate sticky keys.
- **Instant Lock (`/lock` or buttons)**: Locks the Windows workstation session immediately.
- **Power Management**: Put PC to sleep, turn off monitors, turn on/wake monitors (`/monitor on`), reboot, or schedule shutdown timers (15m, 30m, 60m).

### 📋 Process Manager & Terminal <a id="process-manager-terminal"></a>
- **Process Viewer (`/top`)**: Interactive list of top CPU and memory consuming processes with live refresh.
- **Process Killer (`/kill <name_or_pid>`)**: Terminate frozen applications or games remotely. Features a built-in **Process Safety Shield** that blocks blanket killing of `python.exe` by name (safeguarding your trading bots, background automation, and other Python tools) and prevents terminating critical Windows OS processes or Sentinel itself.
- **Remote Terminal (`/cmd <command>`)**: Execute Windows shell commands remotely with automatic token masking.

### 🔊 Audio, TTS & Speaker Controls <a id="audio-tts-speaker-controls"></a>
- **Text-to-Speech (`/say <text>`)**: Speak any message aloud through PC speakers using native Windows speech synthesis.
- **Voice Note Speaker Playback**: Send any voice note or audio file (.ogg, .mp3, .wav) to play your actual voice directly through the PC speakers.
- **PC Alarms & Timers (`/alarm [time] [label]`)**: Set countdown timers or specific clock alarms with siren alerts and speech synthesis.
- **Media Player Controls**: Play, pause, skip tracks, volume up/down, and mute for Spotify, YouTube, Chrome, VLC, and media players.

### 📁 Remote File Explorer & Clipboard <a id="remote-file-explorer-clipboard"></a>
- **Interactive File Explorer (`/get`, `/files`, `/browse`, `/explore`)**:
  - **No Need to Memorize Paths**: Sending `/get` or `/files` without arguments launches an interactive visual file browser right inside Telegram starting at your Desktop.
  - **Visual Directory Navigation**: Tap any folder button (`[📁 Folder Name]`) to navigate inside, tap `[⬆️ Up]` to go to the parent directory, or tap `[🔄 Refresh]` to re-scan.
  - **Smart File Identification**: Displays custom emojis for documents (`📄`), images (`🖼️`), videos (`🎥`), audio (`🎵`), archives (`📦`), executables (`💻`), and scripts (`⚙️`) with human-readable file sizes.
  - **1-Tap Direct Downloads**: Tap any file button (`[📄 document.pdf (2.4 MB) ⬇️]`) to instantly download and deliver the file directly to your Telegram chat (with 50MB safety check).
  - **Quick Access Shortcuts (`[🏠 Quick Access]`)**: 1-tap jump to system drive partitions (`💻 Drive (C:)`, `💻 Drive (D:)`) or core user folders (**Desktop**, **Downloads**, **Documents**, **Pictures**, **Sentinel Recordings**).
  - **Smart Path Support**: Send `/get C:\MyFolder` to open the explorer at that folder, or `/get C:\path\file.txt` to directly fetch the file.
- **File Dropper**: Send any document, photo, or script to the bot to automatically save it in the PC's `downloads/` folder.
- **Clipboard Sync (`/clip <text>`, `/getclip`)**: Read or push text directly to and from the Windows clipboard.
- **Storage Cleaner (`/clean`)**: Audit and clean up cached recordings and downloads with explicit confirmation.

### 🛡️ Anti-Timeout & Network Resilience Shield <a id="anti-timeout-network-resilience-shield"></a>
- **Engineered for High Latency & Unstable Connections**: Built specifically to survive bad internet, weak mobile hotspots, packet drop, 3G/4G/5G tethering, and cellular CGNAT environments where commands frequently time out.
- **Intelligent Telegram API Retries (`safe_telegram_call`)**: Automatically intercepts transient timeouts, connection resets, and Telegram flood limits (`RetryAfter`) with exponential backoff retry cycles and extended 60-second read/write timeouts.
- **Direct Local HTTP Loopback (`127.0.0.1`)**: Host PC commands automatically detect local residence and bypass cloud brokers and internet routing entirely, guaranteeing 0ms ping latency and zero cloud dependency.
- **Automatic JPEG Screenshot Compression**: High-resolution screenshots automatically compress oversized PNGs (>400KB) into optimized JPEG format (quality 85) on the agent before transmission, slashing upload sizes by 90-95% (e.g. from 4MB to ~200KB) for instantaneous mobile delivery.
- **Self-Healing Cloud Relay**: Commander Relay automatically buffers and waits up to 6.0 seconds for broker reconnection during transient network blips and automatically retries timed-out commands with QoS 1 confirmation.
- **Real-Time Network Diagnostics (`/net`, `/ping`)**: Tap the new **"🌐 Network Ping"** button or type `/net` to measure live roundtrip Telegram API latency in milliseconds, MQTT cloud broker connection health, and target PC reachability with color-coded connection ratings.
- **Immediate Typing Feedback**: Emits immediate `ChatAction.TYPING` and `ChatAction.UPLOAD_PHOTO` signals so you always know a command is being processed, even over high-latency connections.

### 🔒 Enterprise Security Architecture <a id="enterprise-security-architecture"></a>
- **User Whitelist Enforcement**: Only numeric Telegram user IDs configured in `AUTHORIZED_USER_IDS` can communicate with the bot.
- **Intruder Alerts**: Unrecognized users are blocked immediately, and an alert with their Telegram ID and username is dispatched to the owner.
- **Process Isolation & Trading Bot Protection**: Built-in safeguards strictly prevent accidental termination of user trading bots, other running Python applications, or critical Windows OS system services (`csrss.exe`, `lsass.exe`, `smss.exe`, etc.). Blanket termination of Python by process name is strictly blocked.
- **Strict Directory & Path Traversal Isolation**: File deletion (`/clean`) and file explorer operations strictly validate paths within whitelisted directories, preventing any access or modification to sensitive system directories or files used by other processes.
- **AES-256-GCM End-to-End Encryption**: All MQTT relay messages and command payloads are encrypted with your shared `FLEET_SECRET`.
- **Optional PIN Lock**: Require `/login <PIN>` with automatic session timeout and rate limiting.

---

## 🚀 Quick Start Guide <a id="quick-start-guide"></a>

### Step 1: Set Up Your Telegram Bot <a id="step-1-set-up-your-telegram-bot"></a>
1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, choose a name and username, and copy your **Bot Token**.
3. Message **[@userinfobot](https://t.me/userinfobot)** in Telegram to find your numeric **User ID** (e.g. `6513180621`).

### Step 2: Configure Master Settings <a id="step-2-configure-master-settings"></a>
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

### Step 3: Run the Fleet Commander Bot <a id="step-3-run-the-fleet-commander-bot"></a>

You have **three flexible ways** to run your Commander Bot 24/7:

#### 📱 Option A: Android Phone (24/7 Always-On via Termux) - Recommended <a id="option-a-android-phone-247-always-on-via-termux-recommended"></a>
Because smartphones stay powered and connected to Wi-Fi/4G 24/7, you can run the Commander Bot directly on your Android phone!
1. Install **[Termux](https://f-droid.org/en/packages/com.termux/)** (free from F-Droid or GitHub Releases).
2. Open Termux and clone the repo:
   ```bash
   pkg update -y && pkg install -y git python
   git clone https://github.com/Mazonia/pc-controller-bot.git
   cd pc-controller-bot
   ```
3. Run the automated setup script:
   ```bash
   bash termux_setup.sh
   ```
4. Enter your `.env` tokens (`nano .env`) and launch the bot:
   ```bash
   nohup python bot.py > bot.log 2>&1 &
   ```
   *The script activates `termux-wake-lock` so Android never suspends your bot when the phone screen is off!*

#### ☁️ Option B: Free 24/7 Cloud Server (Render / Railway / Docker) - Zero Phone Battery <a id="option-b-free-247-cloud-server-render-railway-docker-zero-phone-battery"></a>
Run the Commander Bot 24/7 in the cloud with zero hardware maintenance:

**Via Render.com (Free Tier):**
1. Sign up at [Render.com](https://render.com/) and click **New +** → **Blueprint**.
2. Connect your GitHub repository (`Mazonia/pc-controller-bot`). Render automatically detects `render.yaml`.
3. Enter your `TELEGRAM_BOT_TOKEN`, `AUTHORIZED_USER_IDS`, and `FLEET_SECRET` when prompted.
4. Click **Apply**. Render will build and run your bot 24/7 continuously.

**Via Docker / Home Server / VPS:**
```bash
docker compose up -d
```
*Zero phone battery drain, 99.99% uptime, and instant access from anywhere via your Telegram app.*

#### 💻 Option C: Windows Main PC / Laptop (Auto-Start on Boot) <a id="option-c-windows-main-pc-laptop-auto-start-on-boot"></a>
Run the Commander Bot on your local Windows PC:

1. **Auto-Start on Windows Boot/Logon (Recommended):**
   - Double-click **`setup_autostart.bat`**.
   - It automatically registers a silent Task Scheduler task and Startup shortcut.
   - The bot will now run invisibly in the background every time Windows boots!
   *(To disable later, double-click `remove_autostart.bat`)*.

2. **Run Manually:**
   - With visible terminal: Double-click **`run.bat`** (or `python bot.py`).
   - Hidden background mode: Double-click **`start_hidden.vbs`**.

---

## 🔄 Redundancy & Offline Self-Healing <a id="redundancy-offline-self-healing"></a>

What happens if your Main PC or Commander server goes offline?

- **100% Autonomous Monitored PCs**: Each target PC runs `agent.py` as an independent background process. They **never depend on the main PC being turned on**. Local timers, scheduled alarms, speakers, and security rules continue functioning normally on each target PC.
- **MQTT Retained Telemetry (`retain=True`)**: Target PCs publish heartbeats and system states with `retain=True` to the secure cloud broker.
- **Instant Synchronization on Boot**: The exact second your Main PC (or phone) powers on and connects to the internet:
  1. `bot.py` connects to the broker and subscribes to your fleet topic.
  2. The cloud broker **immediately flushes the retained status of all online PCs in <50 milliseconds**.
  3. You instantly receive a Telegram alert listing all online PCs with their live IP and network badges.
  4. You immediately regain full interactive control over your entire fleet.
- **Automatic Last Will & Testament (LWT)**: If any monitored PC loses power or drops offline while you are away, the broker immediately updates that PC's status to `🔴 Offline` so your bot never displays stale data.

## 💾 Deploying on Target PCs (Two Effortless Methods) <a id="deploying-on-target-pcs-two-effortless-methods"></a>

You can easily deploy PC-Remote-Sentinel to any number of target Windows PCs (personal laptops, office desktops, gaming rigs, or brand-new PCs) using either **WiFi Network Deployment** or a **Clean USB Pendrive**.

Target PCs only receive the lightweight agent runtime (~250 KB). Master bot code (`bot.py`), configurations, and credentials are never deployed to target machines.

### 🌐 Method 1: Over-the-Air Network Deployment (Recommended for 1-100+ PCs) <a id="method-1-over-the-air-network-deployment-recommended-for-1100-pcs"></a>

Deploy to any PC on your local Wi-Fi or LAN without touching a USB drive:

1. On your Main PC, double-click **`deploy_network.bat`** (Run as Administrator).
2. It launches the local deployment server and copies the install command to your clipboard.
3. On any target PC on the same Wi-Fi:
   - Press **`Win + R`** (Windows Run prompt).
   - Paste the one-liner command:
     ```powershell
     powershell -ep bypass -c "irm http://<YOUR_IP>:9090/install | iex"
     ```
   - Press **Enter** and walk away!
4. The target PC automatically elevates, installs the agent in `C:\PCSentinel`, sets up silent autostart on logon, and immediately connects to your Telegram Bot.

### 🔌 Method 2: Portable SSD & USB 1-Click Auto-Installer (100% Offline) <a id="method-2-portable-ssd-usb-1-click-auto-installer-100-offline"></a>

Deploy effortlessly to external PCs with zero internet dependency using your external SSD or USB flash drive:

1. **Prepare or Update Your SSD / USB Drive:**
   - Double-click **`UPDATE-SSD.bat`** (or `prepare_usb.bat`) on your main PC. It automatically scans for connected external drives and syncs all agent scripts, configurations, offline Python installer (`python-installer.exe`), and 33 pre-cached offline Python wheels.
2. **Install on Any Target PC in 10 Seconds:**
   - Plug your external SSD into the target Windows PC and open the drive in File Explorer.
   - Double-click **`1-CLICK-INSTALL.bat`** (it automatically requests UAC Administrator privileges).
   - In ~10-15 seconds, the automated installer:
     - **Silent Python Installation**: If Python is missing, silently installs the bundled official Python installer (`python-installer.exe`) into `C:\PCSentinel\Python` with `InstallAllUsers=1` and `SimpleInstall=1`.
     - **100% Offline Dependencies**: Installs all 15 pip requirements directly from the pre-cached `wheels/` folder (including `python-multipart`, `fastapi`, `uvicorn`, `cryptography`, `pillow`, `opencv-python`, `playsound3`, `av`, and `pywin32`).
     - **Agent Setup**: Installs minimal agent files into `C:\PCSentinel` (~250 KB footprint).
     - **Firewall Authorization**: Automatically creates Windows Defender Firewall allow rules for Agent port (`9010`) and Live Screen Streamer port (`8585`).
     - **Silent Auto-Start**: Registers a 24/7 battery-resilient Windows Task Scheduler background task on user logon, backed by Startup folder and Registry Run triple redundancy.
     - **Fleet Registration**: Automatically records the target PC's hostname and network IP into `fleet.json` on your SSD.
     - **Silent Background Launch**: Starts the agent immediately hidden in the background without any visible command window.
3. **Verify Connectivity:**
   - If the target PC has internet access, it immediately connects to your Telegram Bot and sends a startup ping.
   - Run **`DIAGNOSE-PC.bat`** at any time to run the live diagnostic inspector and verify agent port 9010, cloud relay, and logs.
4. **Sync Fleet to Main Bot:**
   - When you plug the SSD back into your main Host PC, run **`sync_fleet.bat`** to merge newly installed target PCs into your Master Fleet list!


---

## 🕹️ Telegram Commands Reference <a id="telegram-commands-reference"></a>

| Command | Description |
| :--- | :--- |
| `/start`, `/pcs` | Open Fleet Command Center & switch between monitored PCs |
| `/status` | View CPU, RAM, Disk, Battery, Uptime, and Active Window |
| `/shot`, `/screenshot` | Capture high-resolution multi-monitor screenshot |
| `/cast`, `/stream` | Start global 30 FPS Live Screen Streaming |
| `/desktop` | Desktops & Windows switcher menu (Alt+Tab, Virtual Desktops) |
| `/windows`, `/apps` | List open application windows with 1-tap focus buttons |
| `/switch <name>` | Instantly bring matching application window to the front |
| `/webcam` | Capture photo from connected webcam |
| `/record_webcam [s]` | Record 10s or custom webcam video clip |
| `/record_screen [s]` | Record 10s-120s of on-screen desktop video |
| `/lock` | Instantly lock the Windows workstation |
| `/top` | Display top RAM & CPU consuming processes |
| `/kill <name_or_pid>` | Terminate running process (e.g. `/kill notepad.exe`) |
| `/say <text>` | Speak text aloud on PC speakers |
| `/clip <text>` | Copy text from phone to PC clipboard |
| `/getclip` | Read text from PC clipboard |
| `/get [path]` | Open Remote File Explorer, browse directories, or download file |
| `/files`, `/browse`, `/explore` | Launch interactive Remote File Explorer menu |
| `/alarm [time] [label]` | Set countdown timer (`10m`, `45s`, `1.5h`) or clock alarm (`18:30`) |
| `/stopalarm`, `/silence` | Silence and stop ringing PC alarm |
| `/cancelalarm` | Cancel pending scheduled alarm countdown |
| `/monitor [on\|off]` | Turn PC monitors on/off or wake screens |
| `/clean` | Audit and clean cached recordings/downloads |
| `/net`, `/ping`, `/network` | Run network connectivity diagnostics (Telegram API latency ms, Cloud Relay broker, PC reachability) |
| `/open <url>` | Open website or app on PC |
| `/cmd <command>` | Execute terminal command with token masking |
| `/login <pin>` | Authenticate PIN to unlock Command Center |
| `/logout` | Lock bot session immediately |
| `/setpin <pin>` | Configure or change bot security PIN (4-8 digits) |
| `/removepin` | Disable PIN protection completely |
| `/rename [name]` | Rename a PC with a friendly custom label |
| `/removepc <name>` | Remove an uninstalled PC from the fleet list |
| `/reload` | Reload registered fleet registry |

---

## 🧪 Test Suite & Quality Assurance <a id="test-suite-quality-assurance"></a>

PC Remote Sentinel includes a comprehensive automated test suite verifying network resilience, retry mechanisms, encryption, and local routing:

```bash
# Run the complete test suite
python -m pytest tests/ -v
```

The test suite covers:
- **Telegram Resilience**: Safe API execution, exponential backoff retries on network drops, and error handling.
- **Agent Media Optimization**: Automatic JPEG compression, retry cycles on direct Telegram uploads, and failure reporting.
- **Fleet Relay Hardening**: Automatic wait-on-reconnect, command timeout retry over QoS 1, and offline PC staleness detection.
- **Zero-Latency Routing**: Host PC local loopback bypassing external networks.
- **Process Isolation & Non-Interference**: Strict safeguards preventing accidental termination of trading bots, other Python scripts, OS core services, or Sentinel itself, plus path traversal checks.
- **AES-256-GCM Cryptography**: Secure payload encryption, decryption, authentication, and nonce freshness.

---

## 🧹 Clean Uninstallation (Zero Trace) <a id="clean-uninstallation-zero-trace"></a>

Removing Sentinel from any PC is just as simple as installing it:

### From Monitored Target PCs <a id="from-monitored-target-pcs"></a>
1. Plug your USB pendrive into the target PC and double-click **`uninstall.bat`**.
2. Click **"Yes"** on the Windows UAC elevation prompt.
3. The script terminates all running agent processes, deletes the Task Scheduler task, removes startup hooks, deletes firewall rules, and wipes `C:\PCSentinel` completely.
4. In Telegram, the PC will show as `🔴 Offline`. Simply tap **"🗑️ Remove PC from Fleet"** (or send `/removepc <name>`) to clear it from your menu.

### From Your Main Host PC <a id="from-your-main-host-pc"></a>
- Double-click **`remove_autostart.bat`** to cleanly remove the startup task and background process.

---

## ❓ Frequently Asked Questions (FAQ)

### What is PC Remote Sentinel?
PC Remote Sentinel is an enterprise-grade multi-PC fleet management, surveillance, and automation system controlled entirely through a single Telegram Bot. It enables remote desktop monitoring, webcam capture, process management, mouse/keyboard simulation, and terminal execution on Windows 10 and 11.

### How does it connect to remote computers without port forwarding?
Sentinel uses outbound-only long-polling to the Telegram Bot API and optional MQTT over TLS (AES-256-GCM encrypted relay). This architecture punches through Carrier-Grade NAT (CGNAT), 4G/5G mobile hotspots, and corporate firewalls with zero router configuration.

### How does the bot prevent unauthorized access?
The bot enforces strict Telegram User ID authorization (`ADMIN_IDS`). Any interaction from unauthorized accounts is immediately blocked, logged, and alerted to the administrator. Additionally, optional PIN protection (`/setpin`) adds two-factor security for sensitive commands.

### Can I control multiple computers at once?
Yes. Using the `/pcs` command, administrators can list all registered workstations (home PC, work laptop, gaming rig, cloud VPS) and toggle active control between them in seconds.

---

## 🔒 Security Policy <a id="security-policy"></a>

For security guidelines, vulnerability disclosure, and details on encryption protocols, please refer to [SECURITY.md](SECURITY.md).

---

## 📄 License <a id="license"></a>

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
