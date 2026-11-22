# 🍏 PC Remote Sentinel — macOS Edition

Comprehensive guide for deploying and operating the **PC Remote Sentinel Agent** on Apple MacBooks and Macs (macOS Monterey, Ventura, Sonoma, and Sequoia on both **Apple Silicon M1/M2/M3/M4** and **Intel x86_64**).

---

## 🚀 Key Highlights on macOS

- **Unified Fleet**: Your MacBook appears alongside your Windows PCs in the same Telegram Bot (`/pcs`). You can switch between your Windows desktop and MacBook instantly.
- **Native OS Acceleration**:
  - **Screen Capture**: Uses `/usr/sbin/screencapture` and macOS Quartz CoreGraphics with zero lag.
  - **Speech Synthesis (TTS)**: Built-in `/usr/bin/say` produces crisp, natural spoken announcements with zero extra dependencies.
  - **Audio Playback**: Built-in `/usr/bin/afplay` plays voice messages and alert sirens directly on MacBook speakers.
  - **Clipboard**: Seamlessly syncs with native macOS `pbcopy` and `pbpaste`.
  - **Synthetic Input**: Uses AppleScript and CoreGraphics event taps for smooth remote mouse movement, clicks, scrolling, gestures, and unicode typing.
- **Persistent LaunchAgent**: Runs silently in the user GUI session via `launchd`, automatically restarting across reboots and network switches.

---

## 📦 Quick Installation (1 Step)

From your MacBook terminal inside the repository folder, run:

```bash
chmod +x install_mac.sh
./install_mac.sh
```

The installer will:
1. Detect your macOS architecture (Apple Silicon ARM64 or Intel).
2. Validate Python 3.9+.
3. Create an isolated virtual environment in `~/Library/Application Support/PCSentinel/venv`.
4. Install all required dependencies cleanly without bloat.
5. Configure `agent.env` with your Telegram Bot Token and fleet secret.
6. Install and activate the LaunchAgent daemon (`com.sentinel.agent.plist`).

---

## 🛡️ macOS Security & TCC Permissions Guide

macOS features strict Privacy and Security controls (TCC - Transparency, Consent, and Control). To allow Sentinel to capture screens and accept synthetic mouse/keyboard input from your Telegram Bot, grant permissions once:

### 1. Screen Recording (Required for screenshots and live stream)
1. Open **System Settings** → **Privacy & Security** → **Screen Recording**.
2. Click the **+** button or toggle ON for:
   - **Terminal** (or **iTerm2** if you use it).
   - **Python** (if prompted).

### 2. Accessibility (Required for remote mouse movement & typing)
1. Open **System Settings** → **Privacy & Security** → **Accessibility**.
2. Click the **+** button or toggle ON for:
   - **Terminal** (or **iTerm2**).
   - **Python**.

> [!TIP]
> You can open the Privacy settings directly from Terminal with:
> ```bash
> open "x-apple.systempreferences:com.apple.preference.security?Privacy"
> ```

---

## ⚙️ Service Management

The Sentinel agent runs as a user LaunchAgent in `~/Library/LaunchAgents/com.sentinel.agent.plist`.

| Action | Command |
|---|---|
| **Check Status** | `launchctl list com.sentinel.agent` |
| **Stop Agent** | `launchctl unload ~/Library/LaunchAgents/com.sentinel.agent.plist` |
| **Start Agent** | `launchctl load ~/Library/LaunchAgents/com.sentinel.agent.plist` |
| **View Live Logs** | `tail -f ~/Library/Application\ Support/PCSentinel/agent.log` |
| **Foreground Test** | `~/Library/Application\ Support/PCSentinel/start_agent.sh` |

---

## 🗑️ Uninstallation

To cleanly remove the agent and LaunchAgent service:

```bash
chmod +x uninstall_mac.sh
./uninstall_mac.sh
```
