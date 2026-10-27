"""
Screen Caster Module for PC Remote Sentinel
Handles real-time desktop screen casting via:
1. High-performance Web MJPEG & HTML5 Player (mobile/desktop responsive, secure token, adjustable FPS/quality)
2. In-Chat Live Radar (rapid refreshing photo updates inside Telegram)
3. RTMP Live Stream (broadcasting to Telegram Channel / Group Video Chat or external RTMP endpoints)
"""

import os
import sys
import time
import io
import json
import socket
import secrets
import threading
import ctypes
import subprocess
import shutil
import re
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any, Tuple

from PIL import ImageGrab
from loguru import logger
import psutil

try:
    import win32gui
except ImportError:
    win32gui = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import av
except ImportError:
    av = None


def get_primary_lan_ip() -> str:
    """Detect primary local IPv4 address."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def find_available_port(start_port: int = 8585, max_attempts: int = 20) -> int:
    """Find an available port on the host."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return start_port


def ensure_desktop_access():
    """Ensure current thread is attached to the active Windows input desktop."""
    try:
        # DPI awareness
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception as e:
        logger.debug(f"Desktop attach notice: {e}")


def get_active_window_title() -> str:
    """Return title of current foreground window."""
    if not win32gui:
        return "Desktop"
    try:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd).strip()
            if title:
                return title
    except Exception:
        pass
    return "Desktop"


# Modern Dark Glass HTML5 Web Player with Cross-Network Auto-Reconnect & Virtual Desktop Controls
HTML_PLAYER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>PC Sentinel — Remote Ghost Mouse & Cast</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #070b14;
            --surface: rgba(15, 23, 42, 0.88);
            --surface-border: rgba(255, 255, 255, 0.12);
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.35);
            --accent-subtle: rgba(56, 189, 248, 0.15);
            --danger: #f43f5e;
            --success: #10b981;
            --warning: #f59e0b;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --dock-h: 155px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at 50% 0%, #0f1d3a 0%, var(--bg) 75%);
            color: var(--text-main);
            height: 100vh;
            height: 100dvh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            user-select: none;
            -webkit-user-select: none;
        }

        /* ── Top Bar ─────────────────────────────────────────────── */
        header {
            position: relative;
            z-index: 110;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            background: var(--surface);
            border-bottom: 1px solid var(--surface-border);
            padding: 8px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-shrink: 0;
        }

        .brand-group {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }

        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.4);
            color: #fda4af;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
        }

        .pulse-dot {
            width: 7px;
            height: 7px;
            background: var(--danger);
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.8; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 10px var(--danger); }
            100% { transform: scale(0.9); opacity: 0.8; }
        }

        .window-pill {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 3px 10px;
            border-radius: 8px;
            font-size: 0.75rem;
            color: #cbd5e1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 140px;
        }

        .mode-segmented {
            display: flex;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            padding: 2px;
            gap: 2px;
        }

        .mode-btn {
            background: transparent;
            border: none;
            color: var(--text-sub);
            padding: 5px 9px;
            border-radius: 8px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .mode-btn.active {
            background: var(--accent);
            color: #040812;
            box-shadow: 0 0 10px var(--accent-glow);
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .icon-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-main);
            padding: 6px 9px;
            border-radius: 8px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .icon-btn:active {
            transform: scale(0.95);
        }

        /* ── Main Viewport & Ghost Trackpad ───────────────────────── */
        main {
            position: relative;
            flex: 1;
            width: 100%;
            height: calc(100% - 50px);
            overflow: hidden;
            background: #020617;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .viewport-container {
            position: relative;
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #020617;
        }

        #stream-img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
            pointer-events: none;
            transition: opacity 0.2s ease;
            opacity: 0.35; /* default ghost opacity */
        }

        /* Full Screen Interactive Touch Trackpad Surface */
        #touch-surface {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            z-index: 40;
            touch-action: none;
            cursor: crosshair;
        }

        /* High-Contrast Floating Cursor Radar & Crosshair */
        #cursor-radar {
            position: absolute;
            top: 50%;
            left: 50%;
            width: 30px;
            height: 30px;
            margin-left: -15px;
            margin-top: -15px;
            border: 2px solid #38bdf8;
            border-radius: 50%;
            pointer-events: none;
            z-index: 50;
            box-shadow: 0 0 14px #38bdf8, inset 0 0 8px rgba(56, 189, 248, 0.4);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.04s ease-out;
            will-change: transform;
        }

        #cursor-radar::before {
            content: '';
            position: absolute;
            width: 44px;
            height: 1px;
            background: rgba(56, 189, 248, 0.4);
        }

        #cursor-radar::after {
            content: '';
            position: absolute;
            height: 44px;
            width: 1px;
            background: rgba(56, 189, 248, 0.4);
        }

        .cursor-center-dot {
            width: 7px;
            height: 7px;
            background: #ffffff;
            border-radius: 50%;
            box-shadow: 0 0 6px #ffffff;
            z-index: 2;
        }

        #cursor-radar.click-ripple {
            animation: radarPulse 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes radarPulse {
            0% { transform: scale(0.9); border-color: #f43f5e; box-shadow: 0 0 20px #f43f5e; }
            50% { transform: scale(1.6); border-color: #38bdf8; }
            100% { transform: scale(1); }
        }

        /* Right Edge Vertical Scroll Strip */
        #edge-scroll-strip {
            position: absolute;
            top: 15%;
            bottom: 25%;
            right: 6px;
            width: 32px;
            z-index: 45;
            background: rgba(15, 23, 42, 0.65);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 16px;
            backdrop-filter: blur(8px);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            padding: 8px 0;
            color: #94a3b8;
            font-size: 0.75rem;
            touch-action: none;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
            transition: all 0.2s;
        }

        #edge-scroll-strip.active {
            border-color: var(--accent);
            background: rgba(56, 189, 248, 0.25);
            color: #ffffff;
            box-shadow: 0 0 16px var(--accent-glow);
        }

        .scroll-icon {
            font-size: 0.75rem;
            opacity: 0.8;
        }

        /* ── Settings Drawer / Quick Bar ─────────────────────────── */
        .controls-overlay {
            position: absolute;
            top: 8px;
            left: 12px;
            z-index: 48;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            pointer-events: auto;
        }

        .hud-pill {
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid var(--surface-border);
            backdrop-filter: blur(8px);
            padding: 4px 10px;
            border-radius: 8px;
            font-size: 0.75rem;
            font-family: 'JetBrains Mono', monospace;
            color: #94a3b8;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .hud-pill span.val {
            color: var(--accent);
            font-weight: 600;
        }

        /* ── Floating Phone Input & Keyboard Dock ────────────────── */
        #keyboard-dock {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            z-index: 100;
            background: rgba(9, 14, 26, 0.94);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border-top: 1px solid rgba(255, 255, 255, 0.14);
            padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0px));
            display: flex;
            flex-direction: column;
            gap: 7px;
            box-shadow: 0 -12px 36px rgba(0, 0, 0, 0.7);
            transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
        }

        #keyboard-dock.dock-minimized {
            transform: translateY(calc(100% - 36px));
        }

        .dock-toggle-bar {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: space-between;
            cursor: pointer;
            padding: 0 4px 2px 4px;
        }

        .dock-handle {
            width: 36px;
            height: 4px;
            background: rgba(255, 255, 255, 0.25);
            border-radius: 999px;
            margin: 0 auto;
        }

        .dock-title {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-sub);
            display: flex;
            align-items: center;
            gap: 5px;
        }

        /* Row 1: Direct Text Input Bar */
        .type-input-row {
            display: flex;
            align-items: center;
            gap: 6px;
            width: 100%;
        }

        #phone-input {
            flex: 1;
            background: #0f172a;
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 10px;
            padding: 9px 12px;
            color: #f8fafc;
            font-size: 0.92rem;
            font-family: inherit;
            outline: none;
            transition: all 0.2s;
        }

        #phone-input:focus {
            border-color: var(--accent);
            box-shadow: 0 0 14px var(--accent-glow);
            background: #111c35;
        }

        .btn-send {
            background: var(--accent);
            color: #040812;
            border: none;
            border-radius: 9px;
            padding: 9px 14px;
            font-family: inherit;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s;
            display: flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
        }

        .btn-send:active {
            transform: scale(0.95);
        }

        .btn-live-toggle {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: var(--text-sub);
            border-radius: 9px;
            padding: 9px 11px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }

        .btn-live-toggle.active {
            background: rgba(16, 185, 129, 0.2);
            border-color: var(--success);
            color: #6ee7b7;
        }

        /* Row 2: Tactile Mouse Buttons Bar */
        .mouse-buttons-row {
            display: grid;
            grid-template-columns: 2fr 1.2fr 2fr;
            gap: 6px;
            width: 100%;
        }

        .mouse-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: var(--text-main);
            padding: 8px 10px;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            transition: all 0.15s;
        }

        .mouse-btn:active {
            background: var(--accent);
            color: #040812;
            transform: scale(0.97);
        }

        .mouse-btn.active-drag {
            background: rgba(244, 63, 94, 0.25);
            border-color: var(--danger);
            color: #fda4af;
        }

        /* Row 3: Special Keys Scrollable Ribbon */
        .keys-ribbon {
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding-bottom: 3px;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }

        .keys-ribbon::-webkit-scrollbar {
            display: none;
        }

        .key-pill {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.14);
            color: #f1f5f9;
            padding: 6px 11px;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.76rem;
            font-weight: 600;
            white-space: nowrap;
            cursor: pointer;
            touch-action: manipulation;
            transition: all 0.12s;
            flex-shrink: 0;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .key-pill:active {
            background: var(--accent);
            color: #040812;
            border-color: var(--accent);
            transform: scale(0.94);
        }

        .key-pill.pill-accent {
            background: rgba(56, 189, 248, 0.15);
            border-color: rgba(56, 189, 248, 0.35);
            color: #7dd3fc;
        }

        /* ── Expandable Modal / Controls Tray ─────────────────────── */
        #tray-modal {
            position: fixed;
            inset: 0;
            z-index: 150;
            background: rgba(4, 8, 18, 0.85);
            backdrop-filter: blur(12px);
            display: none;
            align-items: flex-end;
            justify-content: center;
        }

        #tray-modal.show {
            display: flex;
        }

        .tray-sheet {
            width: 100%;
            max-width: 600px;
            background: #0d1527;
            border-top: 1px solid var(--surface-border);
            border-radius: 20px 20px 0 0;
            padding: 16px 20px calc(20px + env(safe-area-inset-bottom, 0px));
            max-height: 85vh;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .sheet-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .sheet-title {
            font-size: 1rem;
            font-weight: 700;
        }

        .tray-section {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .tray-label {
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: var(--text-sub);
        }

        .tray-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .tray-btn {
            flex: 1;
            min-width: 90px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: var(--text-main);
            padding: 9px 12px;
            border-radius: 9px;
            font-family: inherit;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
        }

        .tray-btn:active {
            background: var(--accent);
            color: #040812;
        }

        select.tray-select {
            background: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #f8fafc;
            padding: 8px 12px;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.85rem;
            width: 100%;
        }

        /* Toast Notifications */
        .toast {
            position: fixed;
            top: 60px;
            left: 50%;
            transform: translateX(-50%) translateY(-30px);
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid var(--accent);
            color: #f8fafc;
            padding: 7px 16px;
            border-radius: 10px;
            font-size: 0.82rem;
            font-weight: 500;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
            opacity: 0;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 200;
            pointer-events: none;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .toast.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }
    </style>
</head>
<body>
    <header>
        <div class="brand-group">
            <span class="badge-live"><span class="pulse-dot"></span> LIVE</span>
            <div class="window-pill" id="window-pill" title="Active Window">
                <span id="window-title">PC Desktop</span>
            </div>
        </div>

        <!-- Mode Segmented Control: Ghost vs Desktop vs OLED -->
        <div class="mode-segmented">
            <button class="mode-btn active" id="btn-mode-ghost" onclick="setScreenViewMode('ghost')">👻 Ghost</button>
            <button class="mode-btn" id="btn-mode-desk" onclick="setScreenViewMode('desk')">🖥️ View</button>
            <button class="mode-btn" id="btn-mode-oled" onclick="setScreenViewMode('oled')">⬛ OLED</button>
        </div>

        <div class="header-actions">
            <button class="icon-btn" onclick="openTray()" title="PC Controls & Settings">⚙️</button>
        </div>
    </header>

    <main id="main-area">
        <div class="viewport-container" id="viewport">
            <!-- Screen Video Stream -->
            <img id="stream-img" src="/stream.mjpg?token={{TOKEN}}" alt="Desktop Stream" />

            <!-- Full-Screen Interactive Touch Surface -->
            <div id="touch-surface"></div>

            <!-- Floating High-Contrast Cursor Crosshair Radar -->
            <div id="cursor-radar">
                <div class="cursor-center-dot"></div>
            </div>

            <!-- Right Edge Touch Scroll Strip -->
            <div id="edge-scroll-strip" title="Slide thumb to scroll">
                <span class="scroll-icon">▲</span>
                <span style="font-size: 0.65rem; font-weight:700;">SCROLL</span>
                <span class="scroll-icon">▼</span>
            </div>

            <!-- Top HUD Diagnostics -->
            <div class="controls-overlay">
                <div class="hud-pill">FPS: <span class="val" id="stat-fps">--</span></div>
                <div class="hud-pill">Ping: <span class="val" id="stat-ping">-- ms</span></div>
                <div class="hud-pill">Pos: <span class="val" id="stat-pos">0, 0</span></div>
            </div>
        </div>
    </main>

    <!-- Bottom Phone Input & Remote Keyboard Dock -->
    <div id="keyboard-dock">
        <div class="dock-toggle-bar" onclick="toggleDock()">
            <div class="dock-title"><span>📱 Remote Keyboard & Input</span></div>
            <div class="dock-handle"></div>
            <span id="dock-chevron" style="color: var(--text-sub); font-size: 0.75rem;">▼</span>
        </div>

        <!-- Direct Text Injection Bar -->
        <div class="type-input-row">
            <input type="text" id="phone-input" placeholder="Type here (supports phone voice dictation)..." autocomplete="off" autocorrect="on" spellcheck="true" enterkeyhint="send" />
            <button class="btn-send" id="btn-send-text" onclick="sendInputText()">🚀 Send</button>
            <button class="btn-live-toggle" id="btn-live-type" onclick="toggleLiveType()" title="Stream keystrokes instantly">⚡ Live</button>
        </div>

        <!-- Tactile Mouse Buttons -->
        <div class="mouse-buttons-row">
            <button class="mouse-btn" onclick="sendMouseClick('left')">🖱️ Left Click</button>
            <button class="mouse-btn" id="btn-drag-lock" onclick="toggleDragLock()">🖲️ Drag: Off</button>
            <button class="mouse-btn" onclick="sendMouseClick('right')">🖱️ Right Click</button>
        </div>

        <!-- Special Keys Scrollable Ribbon -->
        <div class="keys-ribbon">
            <button class="key-pill pill-accent" onclick="sendKey('enter')">⏎ Enter</button>
            <button class="key-pill" onclick="sendKey('backspace')">⌫ Bksp</button>
            <button class="key-pill" onclick="sendKey('tab')">⇥ Tab</button>
            <button class="key-pill" onclick="sendKey('esc')">Esc</button>
            <button class="key-pill pill-accent" onclick="pasteClipboard()">📋 Paste</button>
            <button class="key-pill" onclick="sendKey('ctrl+c')">Copy</button>
            <button class="key-pill" onclick="sendKey('ctrl+a')">Sel All</button>
            <button class="key-pill" onclick="sendKey('ctrl+z')">Undo</button>
            <button class="key-pill" onclick="sendKey('delete')">Del</button>
            <button class="key-pill" onclick="sendKey('space')">Space</button>
            <button class="key-pill" onclick="sendKey('win')">⊞ Win</button>
            <button class="key-pill" onclick="sendKey('alt+tab')">Alt+Tab</button>
            <button class="key-pill" onclick="sendKey('win+d')">Win+D</button>
            <button class="key-pill" onclick="sendKey('up')">▲ Up</button>
            <button class="key-pill" onclick="sendKey('down')">▼ Down</button>
            <button class="key-pill" onclick="sendKey('left')">◄ Left</button>
            <button class="key-pill" onclick="sendKey('right')">► Right</button>
        </div>
    </div>

    <!-- PC Controls Tray / Settings Sheet -->
    <div id="tray-modal" onclick="closeTrayOnBackdrop(event)">
        <div class="tray-sheet">
            <div class="sheet-header">
                <span class="sheet-title">⚙️ PC Controls & Tuning</span>
                <button class="icon-btn" onclick="closeTray()">✕</button>
            </div>

            <!-- Ghost Opacity Slider -->
            <div class="tray-section">
                <div style="display:flex; justify-content:space-between;">
                    <span class="tray-label">👻 Ghost Desktop Opacity:</span>
                    <span id="label-opacity" style="font-size:0.75rem; color:var(--accent); font-weight:600;">35%</span>
                </div>
                <input type="range" id="slider-opacity" min="5" max="100" value="35" oninput="changeOpacity(this.value)" style="width:100%; accent-color:var(--accent);">
            </div>

            <!-- Trackpad Sensitivity Slider -->
            <div class="tray-section">
                <div style="display:flex; justify-content:space-between;">
                    <span class="tray-label">⚡ Trackpad Sensitivity:</span>
                    <span id="label-sens" style="font-size:0.75rem; color:var(--accent); font-weight:600;">1.4x</span>
                </div>
                <input type="range" id="slider-sens" min="5" max="30" value="14" oninput="changeSensitivity(this.value)" style="width:100%; accent-color:var(--accent);">
            </div>

            <!-- Virtual Desktops -->
            <div class="tray-section">
                <span class="tray-label">🪟 Virtual Desktops</span>
                <div class="tray-row">
                    <button class="tray-btn" onclick="switchDesktop('prev')">◀ Prev Desk</button>
                    <button class="tray-btn" onclick="switchDesktop('next')">Next Desk ▶</button>
                    <button class="tray-btn" onclick="switchDesktop('task_view')">🪟 Task View</button>
                    <button class="tray-btn" onclick="switchDesktop('new')">➕ New</button>
                </div>
            </div>

            <!-- Windows & Apps -->
            <div class="tray-section">
                <span class="tray-label">⚡ Switch Open App</span>
                <div class="tray-row">
                    <select id="sel-app" class="tray-select" onchange="focusSelectedApp()">
                        <option value="">🗂️ Focus Open App...</option>
                    </select>
                </div>
            </div>

            <!-- Stream Quality -->
            <div class="tray-section">
                <span class="tray-label">🎥 Stream Engine & Quality</span>
                <div class="tray-row">
                    <select id="sel-quality" class="tray-select" onchange="updateSettings()" style="flex:1;">
                        <option value="480">480p (Data Saver)</option>
                        <option value="720" selected>720p (Crisp)</option>
                        <option value="1080">1080p (Full HD)</option>
                    </select>
                    <select id="sel-fps" class="tray-select" onchange="updateSettings()" style="flex:1;">
                        <option value="10">10 FPS</option>
                        <option value="15" selected>15 FPS</option>
                        <option value="25">25 FPS</option>
                    </select>
                </div>
            </div>

            <!-- Utilities -->
            <div class="tray-section">
                <div class="tray-row">
                    <button class="tray-btn" onclick="toggleFullscreen()">⛶ Fullscreen</button>
                    <button class="tray-btn" onclick="forceReconnect()">🔄 Reconnect</button>
                    <button class="tray-btn" style="color:var(--danger); border-color:rgba(244,63,94,0.3);" onclick="stopStream()">⏹️ Stop</button>
                </div>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">Notice message</div>

    <script>
        const token = "{{TOKEN}}";
        let viewMode = 'ghost'; // 'ghost', 'desk', 'oled'
        let sensitivity = 1.4;
        let isDragLock = false;
        let liveTypeEnabled = false;

        const img = document.getElementById('stream-img');
        const touchSurface = document.getElementById('touch-surface');
        const radar = document.getElementById('cursor-radar');
        const phoneInput = document.getElementById('phone-input');

        // Toast feedback
        let toastTimer = null;
        function showToast(msg, isWarn = false) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.style.borderColor = isWarn ? '#f43f5e' : '#38bdf8';
            toast.classList.add('show');
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
        }

        // Haptic feedback helper
        function vibrate(ms = 35) {
            if (navigator.vibrate) {
                try { navigator.vibrate(ms); } catch (e) {}
            }
        }

        // Mode Switching
        function setScreenViewMode(mode) {
            viewMode = mode;
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            if (mode === 'ghost') {
                document.getElementById('btn-mode-ghost').classList.add('active');
                img.style.display = 'block';
                img.style.opacity = (document.getElementById('slider-opacity').value / 100);
                showToast('Ghost Mode: Faint Screen + Trackpad 👻');
            } else if (mode === 'desk') {
                document.getElementById('btn-mode-desk').classList.add('active');
                img.style.display = 'block';
                img.style.opacity = '1.0';
                showToast('View Mode: Full Desktop 🖥️');
            } else {
                document.getElementById('btn-mode-oled').classList.add('active');
                img.style.display = 'none';
                showToast('OLED Stealth Trackpad ⬛');
            }
        }

        function changeOpacity(val) {
            document.getElementById('label-opacity').textContent = val + '%';
            if (viewMode === 'ghost') {
                img.style.opacity = (val / 100);
            }
        }

        function changeSensitivity(val) {
            sensitivity = (val / 10);
            document.getElementById('label-sens').textContent = sensitivity.toFixed(1) + 'x';
        }

        // ── FULL-SCREEN TOUCH TRACKPAD GESTURES ──────────────────────────
        let lastTouchX = 0;
        let lastTouchY = 0;
        let touchStartX = 0;
        let touchStartY = 0;
        let touchStartTime = 0;
        let movedDist = 0;
        let longPressTimer = null;
        let pendingDx = 0;
        let pendingDy = 0;
        let moveRafId = null;

        // Virtual Radar cursor coordinates on screen
        let radarX = window.innerWidth / 2;
        let radarY = (window.innerHeight - 150) / 2;

        function updateRadarPos(x, y) {
            radarX = Math.max(10, Math.min(window.innerWidth - 10, x));
            radarY = Math.max(10, Math.min(window.innerHeight - 150, y));
            radar.style.left = radarX + 'px';
            radar.style.top = radarY + 'px';
        }
        updateRadarPos(radarX, radarY);

        function triggerRadarRipple() {
            radar.classList.remove('click-ripple');
            void radar.offsetWidth;
            radar.classList.add('click-ripple');
            vibrate(30);
        }

        function flushPendingMove() {
            if (pendingDx !== 0 || pendingDy !== 0) {
                const dx = Math.round(pendingDx);
                const dy = Math.round(pendingDy);
                pendingDx = 0;
                pendingDy = 0;
                fetch(`/input/mouse?token=${token}&action=move&dx=${dx}&dy=${dy}`, {
                    method: 'POST',
                    keepalive: true
                }).catch(() => {});
            }
            moveRafId = null;
        }

        touchSurface.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                const t = e.touches[0];
                lastTouchX = t.clientX;
                lastTouchY = t.clientY;
                touchStartX = t.clientX;
                touchStartY = t.clientY;
                touchStartTime = performance.now();
                movedDist = 0;

                // Long press for Right Click
                if (longPressTimer) clearTimeout(longPressTimer);
                longPressTimer = setTimeout(() => {
                    if (movedDist < 12) {
                        sendMouseClick('right');
                        showToast('Right Click 🖱️');
                        vibrate(55);
                    }
                }, 380);
            } else if (e.touches.length === 2) {
                // Two fingers: cancel long press
                if (longPressTimer) clearTimeout(longPressTimer);
                lastTouchY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            }
        }, { passive: false });

        touchSurface.addEventListener('touchmove', (e) => {
            e.preventDefault(); // prevent pull to refresh and scroll
            if (e.touches.length === 1) {
                const t = e.touches[0];
                const dx = (t.clientX - lastTouchX) * sensitivity;
                const dy = (t.clientY - lastTouchY) * sensitivity;
                lastTouchX = t.clientX;
                lastTouchY = t.clientY;

                movedDist += Math.hypot(dx, dy);
                if (movedDist > 10 && longPressTimer) {
                    clearTimeout(longPressTimer);
                    longPressTimer = null;
                }

                updateRadarPos(radarX + dx, radarY + dy);
                pendingDx += dx;
                pendingDy += dy;

                if (!moveRafId) {
                    moveRafId = requestAnimationFrame(flushPendingMove);
                }
            } else if (e.touches.length === 2) {
                // 2-finger scroll
                const curY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
                const dy = curY - lastTouchY;
                lastTouchY = curY;
                if (Math.abs(dy) > 3) {
                    const scrollDelta = Math.round(dy * 15);
                    fetch(`/input/mouse?token=${token}&action=scroll&delta=${scrollDelta}`, { method: 'POST', keepalive: true }).catch(() => {});
                }
            }
        }, { passive: false });

        touchSurface.addEventListener('touchend', (e) => {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }

            // Flush remaining move
            if (pendingDx !== 0 || pendingDy !== 0) {
                flushPendingMove();
            }

            const elapsed = performance.now() - touchStartTime;
            if (elapsed < 240 && movedDist < 10) {
                // Quick tap -> Left Click
                sendMouseClick('left');
                triggerRadarRipple();
            }
        });

        // Right Edge Scroll Strip logic
        const edgeStrip = document.getElementById('edge-scroll-strip');
        let edgeStartY = 0;

        edgeStrip.addEventListener('touchstart', (e) => {
            e.stopPropagation();
            edgeStrip.classList.add('active');
            edgeStartY = e.touches[0].clientY;
            vibrate(20);
        }, { passive: true });

        edgeStrip.addEventListener('touchmove', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const y = e.touches[0].clientY;
            const diff = y - edgeStartY;
            edgeStartY = y;
            if (Math.abs(diff) > 2) {
                const delta = Math.round(-diff * 35);
                fetch(`/input/mouse?token=${token}&action=scroll&delta=${delta}`, { method: 'POST', keepalive: true }).catch(() => {});
            }
        }, { passive: false });

        edgeStrip.addEventListener('touchend', (e) => {
            edgeStrip.classList.remove('active');
        }, { passive: true });

        // Mouse Click Sender
        async function sendMouseClick(btn) {
            triggerRadarRipple();
            try {
                await fetch(`/input/mouse?token=${token}&action=click&btn=${btn}`, { method: 'POST' });
            } catch (e) {}
        }

        // Drag Lock Toggle
        async function toggleDragLock() {
            isDragLock = !isDragLock;
            const btn = document.getElementById('btn-drag-lock');
            if (isDragLock) {
                btn.classList.add('active-drag');
                btn.textContent = '🖲️ Drag: LOCKED';
                await fetch(`/input/mouse?token=${token}&action=down&btn=left`, { method: 'POST' });
                showToast('Drag Locked: Left Button Down 🖲️');
                vibrate(60);
            } else {
                btn.classList.remove('active-drag');
                btn.textContent = '🖲️ Drag: Off';
                await fetch(`/input/mouse?token=${token}&action=up&btn=left`, { method: 'POST' });
                showToast('Drag Released');
                vibrate(30);
            }
        }

        // ── REMOTE KEYBOARD & DIRECT TYPING ──────────────────────────────
        async function sendInputText() {
            const text = phoneInput.value;
            if (!text) return;
            phoneInput.value = '';
            vibrate(25);
            try {
                const res = await fetch(`/input/type?token=${token}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast('Typed to PC 🚀');
                }
            } catch (e) {
                showToast('Typing error: ' + e.message, true);
            }
        }

        phoneInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                sendInputText();
                // Send Enter key on PC too
                sendKey('enter');
            }
        });

        // Real-time live keystroke streaming
        phoneInput.addEventListener('input', (e) => {
            if (liveTypeEnabled && e.data) {
                fetch(`/input/type?token=${token}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: e.data })
                }).catch(() => {});
            }
        });

        function toggleLiveType() {
            liveTypeEnabled = !liveTypeEnabled;
            const btn = document.getElementById('btn-live-type');
            if (liveTypeEnabled) {
                btn.classList.add('active');
                showToast('Live typing enabled ⚡');
            } else {
                btn.classList.remove('active');
                showToast('Live typing disabled');
            }
        }

        async function sendKey(keyName) {
            vibrate(25);
            try {
                await fetch(`/input/key?token=${token}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: keyName })
                });
                showToast(`Key: ${keyName.toUpperCase()}`);
            } catch (e) {}
        }

        async function pasteClipboard() {
            vibrate(30);
            if (navigator.clipboard && navigator.clipboard.readText) {
                try {
                    const text = await navigator.clipboard.readText();
                    if (text) {
                        await fetch(`/input/type?token=${token}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ text: text })
                        });
                        showToast(`Pasted ${text.length} chars from Phone 📋`);
                        return;
                    }
                } catch (e) {}
            }
            // Fallback: Send Ctrl+V to PC
            sendKey('ctrl+v');
        }

        // Toggle Keyboard Dock
        function toggleDock() {
            const dock = document.getElementById('keyboard-dock');
            dock.classList.toggle('dock-minimized');
            const chevron = document.getElementById('dock-chevron');
            chevron.textContent = dock.classList.contains('dock-minimized') ? '▲' : '▼';
        }

        // ── PC TRAY & VIRTUAL DESKTOPS ──────────────────────────────────
        function openTray() {
            document.getElementById('tray-modal').classList.add('show');
            refreshOpenWindows();
        }

        function closeTray() {
            document.getElementById('tray-modal').classList.remove('show');
        }

        function closeTrayOnBackdrop(e) {
            if (e.target.id === 'tray-modal') closeTray();
        }

        async function switchDesktop(action) {
            try {
                const res = await fetch(`/desktop/switch?token=${token}&action=${action}`, { method: 'POST' });
                const data = await res.json();
                showToast(data.msg || `Desktop: ${action}`);
                if (data.active_window) document.getElementById('window-title').textContent = data.active_window;
            } catch (e) {}
        }

        async function refreshOpenWindows() {
            try {
                const res = await fetch(`/windows?token=${token}`);
                if (res.ok) {
                    const data = await res.json();
                    const sel = document.getElementById('sel-app');
                    sel.innerHTML = '<option value="">🗂️ Focus Open App (' + (data.windows ? data.windows.length : 0) + ')...</option>';
                    if (data.windows && Array.isArray(data.windows)) {
                        data.windows.forEach(w => {
                            const opt = document.createElement('option');
                            opt.value = w.hwnd;
                            const title = w.title.length > 32 ? w.title.substring(0, 30) + '...' : w.title;
                            opt.textContent = `${title} [${w.process}]`;
                            sel.appendChild(opt);
                        });
                    }
                }
            } catch (e) {}
        }

        async function focusSelectedApp() {
            const sel = document.getElementById('sel-app');
            const val = sel.value;
            if (!val) return;
            try {
                const res = await fetch(`/windows/focus?token=${token}&target=${encodeURIComponent(val)}`, { method: 'POST' });
                const data = await res.json();
                showToast(data.msg || 'Focused Window');
                if (data.active_window) document.getElementById('window-title').textContent = data.active_window;
            } catch (e) {}
            closeTray();
        }

        async function updateSettings() {
            const quality = document.getElementById('sel-quality').value;
            const fps = document.getElementById('sel-fps').value;
            try {
                await fetch(`/config?token=${token}&res=${quality}&fps=${fps}`, { method: 'POST' });
                showToast(`Settings: ${quality}p @ ${fps} FPS`);
            } catch (e) {}
        }

        function toggleFullscreen() {
            const elem = document.documentElement;
            if (!document.fullscreenElement) {
                if (elem.requestFullscreen) elem.requestFullscreen();
                else if (elem.webkitRequestFullscreen) elem.webkitRequestFullscreen();
            } else {
                if (document.exitFullscreen) document.exitFullscreen();
            }
            closeTray();
        }

        function forceReconnect() {
            img.src = `/stream.mjpg?token=${token}&_t=${Date.now()}`;
            showToast('Stream reconnected 🔄');
            closeTray();
        }

        async function stopStream() {
            if (!confirm('Stop PC Screen Casting?')) return;
            try {
                await fetch(`/stop?token=${token}`, { method: 'POST' });
                document.body.innerHTML = '<div style="display:flex;height:100vh;align-items:center;justify-content:center;flex-direction:column;font-family:sans-serif;color:#94a3b8;"><h2>Stream Ended</h2><p style="margin-top:8px;">Screen casting was stopped by user.</p></div>';
            } catch (e) {}
        }

        // Diagnostics loop
        let frameCount = 0;
        let lastTime = performance.now();
        img.onload = () => {
            frameCount++;
            const now = performance.now();
            if (now - lastTime >= 1000) {
                const fps = Math.round((frameCount * 1000) / (now - lastTime));
                document.getElementById('stat-fps').textContent = fps;
                frameCount = 0;
                lastTime = now;
            }
        };

        async function fetchStatusAndPing() {
            const t0 = performance.now();
            try {
                const res = await fetch(`/status?token=${token}`);
                if (res.ok) {
                    const ping = Math.round(performance.now() - t0);
                    document.getElementById('stat-ping').textContent = ping + ' ms';
                    const data = await res.json();
                    if (data.active_window) document.getElementById('window-title').textContent = data.active_window;
                }
            } catch (e) {}

            try {
                const cRes = await fetch(`/input/cursor?token=${token}`);
                if (cRes.ok) {
                    const cData = await cRes.json();
                    if (cData.cursor) {
                        document.getElementById('stat-pos').textContent = `${cData.cursor.x}, ${cData.cursor.y}`;
                    }
                }
            } catch (e) {}
        }
        setInterval(fetchStatusAndPing, 3000);
        fetchStatusAndPing();
    </script>
</body>
</html>
"""


class StreamHTTPHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for Web Screen Casting."""

    caster: 'ScreenCaster' = None

    def log_message(self, format, *args):
        # Silence default standard access logging to keep console clean
        return

    def send_unauthorized(self):
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"403 Forbidden: Invalid or missing token.")

    def authenticate(self) -> bool:
        query = parse_qs(urlparse(self.path).query)
        token_param = query.get("token", [""])[0]
        return bool(token_param and token_param == self.caster.auth_token)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.authenticate():
            self.send_unauthorized()
            return

        self.caster.record_viewer_activity()

        if path in ("/", "/index.html"):
            content = HTML_PLAYER_TEMPLATE.replace("{{TOKEN}}", self.caster.auth_token)
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        elif path == "/snapshot.jpg":
            query = parse_qs(parsed.query)
            q = int(query.get("q", ["80"])[0]) if query.get("q", ["80"])[0].isdigit() else 80
            w = int(query.get("w", [str(self.caster.target_width)])[0]) if query.get("w", [""])[0].isdigit() else self.caster.target_width
            img_bytes = self.caster.capture_single_frame(quality=min(max(q, 30), 95), max_w=w)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(img_bytes)

        elif path == "/status":
            try:
                stats = {
                    "cpu": psutil.cpu_percent(),
                    "ram": psutil.virtual_memory().percent,
                    "active_window": get_active_window_title(),
                    "fps": self.caster.target_fps,
                    "viewers": self.caster.active_viewers
                }
                body = json.dumps(stats).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_response(500)
                self.end_headers()

        elif path == "/windows":
            try:
                from system_controller import SystemController
                wins = SystemController.get_open_windows(limit=25)
            except Exception:
                wins = []
            resp = json.dumps({
                "ok": True,
                "windows": wins,
                "active_window": get_active_window_title()
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif path == "/stream.mjpg":
            # Multipart MJPEG stream
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "close")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            self.caster.active_viewers += 1
            try:
                while self.caster.is_web_streaming:
                    t_start = time.time()
                    frame_bytes = self.caster.get_latest_frame()
                    if frame_bytes:
                        header = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                        )
                        self.wfile.write(header + frame_bytes + b"\r\n")

                    # Regulate frame rate
                    target_delay = 1.0 / max(1, self.caster.target_fps)
                    elapsed = time.time() - t_start
                    if elapsed < target_delay:
                        time.sleep(target_delay - elapsed)

            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                logger.debug(f"Stream client disconnected: {e}")
            finally:
                self.caster.active_viewers = max(0, self.caster.active_viewers - 1)

        elif path in ("/input/cursor", "/input/mouse", "/input/type", "/input/key"):
            self.handle_input_endpoint(path, query=parse_qs(parsed.query), payload={})

        else:
            self.send_response(404)
            self.end_headers()

    def handle_input_endpoint(self, path: str, query: dict, payload: dict):
        def _safe_int(val, default=0):
            try:
                if val is None or val == "":
                    return default
                return int(round(float(val)))
            except (ValueError, TypeError):
                return default

        def _safe_float(val, default=0.0):
            try:
                if val is None or val == "":
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        from system_controller import SystemController
        if path == "/input/cursor":
            try:
                pos = SystemController.get_cursor_pos()
            except Exception:
                pos = {"x": 0, "y": 0, "screen_w": 1920, "screen_h": 1080}
            resp = json.dumps({"ok": True, "cursor": pos}).encode("utf-8")

        elif path == "/input/mouse":
            action = payload.get("action")
            if not action and "action" in query:
                action = query["action"][0]
            action = str(action or "move").lower().strip()

            try:
                ok = False
                if action == "move":
                    val_x = payload.get("dx") if payload.get("dx") is not None else query.get("dx", [0])[0]
                    val_y = payload.get("dy") if payload.get("dy") is not None else query.get("dy", [0])[0]
                    dx = _safe_int(val_x, 0)
                    dy = _safe_int(val_y, 0)
                    ok = SystemController.mouse_move(dx, dy)
                elif action == "move_abs":
                    val_x = payload.get("x") if payload.get("x") is not None else query.get("x", [0])[0]
                    val_y = payload.get("y") if payload.get("y") is not None else query.get("y", [0])[0]
                    x = _safe_float(val_x, 0.0)
                    y = _safe_float(val_y, 0.0)
                    norm_val = payload.get("norm") if payload.get("norm") is not None else query.get("norm", ["0"])[0]
                    norm = norm_val in (True, 1, "1", "true", "yes", "True")
                    ok = SystemController.mouse_move_abs(x, y, normalized=norm)
                elif action in ("click", "down", "up", "double"):
                    btn = payload.get("btn") if payload.get("btn") is not None else query.get("btn", ["left"])[0]
                    btn = str(btn or "left")
                    act = "click" if action == "click" else action
                    if action == "double":
                        btn = "double"
                    ok = SystemController.mouse_click(button=btn, action=act)
                elif action == "scroll":
                    val_delta = payload.get("delta") if payload.get("delta") is not None else query.get("delta", [0])[0]
                    delta = _safe_int(val_delta, 0)
                    ok = SystemController.mouse_scroll(delta)
                cur = SystemController.get_cursor_pos()
            except Exception as e:
                logger.error(f"Mouse input handling error: {e}")
                ok = False
                cur = {}
            resp = json.dumps({"ok": ok, "cursor": cur}).encode("utf-8")

        elif path == "/input/type":
            text = payload.get("text")
            if text is None and "text" in query:
                text = query["text"][0]
            text = str(text or "")
            try:
                ok, msg = SystemController.type_text(text)
            except Exception as e:
                ok, msg = False, str(e)
            resp = json.dumps({"ok": ok, "msg": msg}).encode("utf-8")

        elif path == "/input/key":
            key = payload.get("key")
            if key is None and "key" in query:
                key = query["key"][0]
            key = str(key or "")
            try:
                ok, msg = SystemController.press_key(key)
            except Exception as e:
                ok, msg = False, str(e)
            resp = json.dumps({"ok": ok, "msg": msg}).encode("utf-8")

        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(resp)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.authenticate():
            self.send_unauthorized()
            return

        def get_payload() -> dict:
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > 0:
                    raw = self.rfile.read(length)
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except Exception:
                        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
            except Exception:
                pass
            return {}

        if path == "/stop":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            threading.Thread(target=self.caster.stop_web_cast, daemon=True).start()

        elif path in ("/input/mouse", "/input/type", "/input/key", "/input/cursor"):
            self.handle_input_endpoint(path, query=parse_qs(parsed.query), payload=get_payload())

        elif path == "/desktop/switch":
            query = parse_qs(parsed.query)
            action = query.get("action", ["next"])[0]
            try:
                from system_controller import SystemController
                ok, msg = SystemController.switch_virtual_desktop(action)
            except Exception as e:
                ok, msg = False, str(e)
            resp = json.dumps({
                "ok": ok,
                "msg": msg,
                "action": action,
                "active_window": get_active_window_title()
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif path == "/windows/cycle":
            query = parse_qs(parsed.query)
            direction = query.get("dir", ["next"])[0]
            try:
                from system_controller import SystemController
                ok, msg = SystemController.cycle_window(direction)
            except Exception as e:
                ok, msg = False, str(e)
            resp = json.dumps({
                "ok": ok,
                "msg": msg,
                "direction": direction,
                "active_window": get_active_window_title()
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif path == "/windows/focus":
            query = parse_qs(parsed.query)
            target = query.get("target", [""])[0]
            try:
                from system_controller import SystemController
                ok, msg = SystemController.focus_window(target)
            except Exception as e:
                ok, msg = False, str(e)
            resp = json.dumps({
                "ok": ok,
                "msg": msg,
                "target": target,
                "active_window": get_active_window_title()
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif path == "/config":
            query = parse_qs(parsed.query)
            res = query.get("res", ["720"])[0]
            fps = query.get("fps", ["15"])[0]
            if fps.isdigit():
                self.caster.target_fps = min(max(int(fps), 5), 30)
            if res == "480":
                self.caster.target_width = 854
                self.caster.jpeg_quality = 55
            elif res == "1080":
                self.caster.target_width = 1920
                self.caster.jpeg_quality = 75
            else:
                self.caster.target_width = 1280
                self.caster.jpeg_quality = 65

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


class ScreenCaster:
    """Manages real-time desktop casting and streaming."""

    def __init__(self):
        self.is_web_streaming = False
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.capture_thread: Optional[threading.Thread] = None
        
        self.auth_token = ""
        self.port = 8585
        self.target_fps = 15
        self.target_width = 1280
        self.jpeg_quality = 65
        
        self.active_viewers = 0
        self.last_viewer_activity = 0.0
        self.current_frame: Optional[bytes] = None
        self.frame_lock = threading.Lock()
        
        # Public Internet Tunnel (Cloudflare Quick Tunnel)
        self.tunnel_process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.tunnel_thread: Optional[threading.Thread] = None
        
        # RTMP Streaming state
        self.is_rtmp_streaming = False
        self.rtmp_thread: Optional[threading.Thread] = None

    def record_viewer_activity(self):
        """Update timestamp of latest client request."""
        self.last_viewer_activity = time.time()

    def capture_single_frame(self, quality: int = 70, max_w: int = 1280) -> bytes:
        """Capture one instantaneous frame of Windows desktop."""
        ensure_desktop_access()
        try:
            img = ImageGrab.grab(all_screens=True)
            if img.width > max_w:
                ratio = max_w / float(img.width)
                new_h = int(float(img.height) * ratio)
                img = img.resize((max_w, new_h))
            
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Single frame capture failed: {e}")
            return b""

    def _frame_capture_worker(self):
        """Background worker continuously pulling frames into memory buffer."""
        ensure_desktop_access()
        logger.info("Screen caster background frame capture started.")
        
        while self.is_web_streaming:
            t0 = time.time()
            try:
                img = ImageGrab.grab(all_screens=True)
                if self.target_width and img.width > self.target_width:
                    ratio = self.target_width / float(img.width)
                    new_h = int(float(img.height) * ratio)
                    img = img.resize((self.target_width, new_h))

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.jpeg_quality)
                frame_data = buf.getvalue()

                with self.frame_lock:
                    self.current_frame = frame_data

            except Exception as e:
                logger.debug(f"Capture loop error: {e}")

            # Check idle timeout (stop if no viewer for 10 minutes)
            if self.active_viewers == 0 and (time.time() - self.last_viewer_activity > 600):
                logger.info("No active web viewers for 10 minutes. Stopping stream to conserve resources.")
                threading.Thread(target=self.stop_web_cast, daemon=True).start()
                break

            target_delay = 1.0 / max(1, self.target_fps)
            elapsed = time.time() - t0
            if elapsed < target_delay:
                time.sleep(target_delay - elapsed)

        logger.info("Screen caster background frame capture stopped.")

    def get_latest_frame(self) -> Optional[bytes]:
        """Fetch latest captured frame from buffer."""
        with self.frame_lock:
            return self.current_frame

    def _launch_tunnel_worker(self):
        """Worker executing cloudflared and parsing public HTTPS tunnel URL."""
        base_dir = Path(__file__).resolve().parent
        cf_bin = base_dir / "cloudflared.exe"
        if not cf_bin.exists():
            system_cf = shutil.which("cloudflared")
            if system_cf:
                cf_bin = Path(system_cf)
            else:
                logger.info("Downloading cloudflared.exe binary for global streaming...")
                try:
                    url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
                    urllib.request.urlretrieve(url, cf_bin)
                    logger.info("cloudflared.exe successfully downloaded!")
                except Exception as e:
                    logger.warning(f"Failed to auto-download cloudflared: {e}")
                    return

        try:
            logger.info("Launching Cloudflare Quick Tunnel for global streaming...")
            self.tunnel_process = subprocess.Popen(
                [str(cf_bin), "tunnel", "--url", f"http://127.0.0.1:{self.port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            t0 = time.time()
            while self.is_web_streaming and (time.time() - t0 < 30):
                line = self.tunnel_process.stdout.readline()
                if not line:
                    break
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    self.public_url = m.group(0)
                    logger.info(f"Cloudflare Tunnel online: {self.public_url}")
                    break

            while self.is_web_streaming and self.tunnel_process and self.tunnel_process.poll() is None:
                self.tunnel_process.stdout.readline()
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"Cloudflare tunnel error: {e}")
        finally:
            if self.tunnel_process:
                try:
                    self.tunnel_process.terminate()
                except Exception:
                    pass
                self.tunnel_process = None

    def start_web_cast(self, preferred_port: int = 8585, enable_tunnel: bool = True) -> Dict[str, Any]:
        """Start local HTTP streaming server and optional global Cloudflare tunnel."""
        lan_ip = get_primary_lan_ip()
        if self.is_web_streaming:
            return {
                "ok": True,
                "already_running": True,
                "port": self.port,
                "token": self.auth_token,
                "lan_url": f"http://{lan_ip}:{self.port}/?token={self.auth_token}",
                "public_url": f"{self.public_url}/?token={self.auth_token}" if self.public_url else None,
                "local_url": f"http://localhost:{self.port}/?token={self.auth_token}",
            }

        self.port = find_available_port(preferred_port)
        self.auth_token = secrets.token_urlsafe(12)
        self.is_web_streaming = True
        self.last_viewer_activity = time.time()
        self.active_viewers = 0
        self.public_url = None

        # Bind handler to this instance
        StreamHTTPHandler.caster = self

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), StreamHTTPHandler)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

        self.capture_thread = threading.Thread(target=self._frame_capture_worker, daemon=True)
        self.capture_thread.start()

        if enable_tunnel:
            self.tunnel_thread = threading.Thread(target=self._launch_tunnel_worker, daemon=True)
            self.tunnel_thread.start()
            # Wait up to 9 seconds for initial tunnel generation
            t_wait = time.time()
            while time.time() - t_wait < 9 and not self.public_url:
                time.sleep(0.3)

        logger.info(f"Screen cast active on port {self.port} with token {self.auth_token}")

        return {
            "ok": True,
            "already_running": False,
            "port": self.port,
            "token": self.auth_token,
            "lan_url": f"http://{lan_ip}:{self.port}/?token={self.auth_token}",
            "public_url": f"{self.public_url}/?token={self.auth_token}" if self.public_url else None,
            "local_url": f"http://localhost:{self.port}/?token={self.auth_token}",
        }

    def stop_web_cast(self) -> bool:
        """Stop HTTP streaming server, worker thread, and Cloudflare tunnel."""
        if not self.is_web_streaming:
            return False

        self.is_web_streaming = False
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception as e:
                logger.error(f"Error shutting down stream server: {e}")
            self.httpd = None

        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
            except Exception:
                pass
            self.tunnel_process = None
        self.public_url = None

        logger.info("Screen caster web stream and tunnel terminated.")
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get live streaming status."""
        lan_ip = get_primary_lan_ip()
        return {
            "is_web_streaming": self.is_web_streaming,
            "is_rtmp_streaming": self.is_rtmp_streaming,
            "port": self.port,
            "token": self.auth_token,
            "lan_url": f"http://{lan_ip}:{self.port}/?token={self.auth_token}" if self.is_web_streaming else None,
            "public_url": f"{self.public_url}/?token={self.auth_token}" if (self.is_web_streaming and self.public_url) else None,
            "active_viewers": self.active_viewers,
            "target_fps": self.target_fps,
            "active_window": get_active_window_title()
        }

    # ── RTMP Broadcast Engine ──────────────────────────────────────────

    def start_rtmp_stream(self, rtmp_url: str, duration_sec: int = 300) -> Tuple[bool, str]:
        """Broadcast live H.264 desktop stream to RTMP endpoint."""
        if av is None:
            return False, "PyAV (av) is not installed."
        
        if self.is_rtmp_streaming:
            return False, "RTMP broadcast is already active."

        self.is_rtmp_streaming = True
        self.rtmp_thread = threading.Thread(
            target=self._rtmp_broadcast_worker,
            args=(rtmp_url, duration_sec),
            daemon=True
        )
        self.rtmp_thread.start()
        return True, f"RTMP broadcast launched (duration up to {duration_sec}s)."

    def stop_rtmp_stream(self) -> bool:
        """Stop active RTMP broadcast."""
        if not self.is_rtmp_streaming:
            return False
        self.is_rtmp_streaming = False
        return True

    def _rtmp_broadcast_worker(self, rtmp_url: str, duration_sec: int):
        """Worker encoding desktop frames into H.264 FLV over RTMP."""
        ensure_desktop_access()
        logger.info(f"Starting RTMP broadcast to {rtmp_url[:25]}...")
        container = None
        try:
            fps = 15
            width, height = 1280, 720

            container = av.open(rtmp_url, mode="w", format="flv")
            stream = container.add_stream("h264", rate=fps)
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            stream.options = {"tune": "zerolatency", "preset": "ultrafast"}

            start_time = time.time()
            frame_delay = 1.0 / fps

            while self.is_rtmp_streaming and (time.time() - start_time < duration_sec):
                t0 = time.time()
                img = ImageGrab.grab(all_screens=True)
                if img.size != (width, height):
                    img = img.resize((width, height))

                frame = av.VideoFrame.from_image(img)
                for packet in stream.encode(frame):
                    container.mux(packet)

                elapsed = time.time() - t0
                if elapsed < frame_delay:
                    time.sleep(frame_delay - elapsed)

            # Flush encoder
            for packet in stream.encode():
                container.mux(packet)

            logger.info("RTMP broadcast finished.")
        except Exception as e:
            logger.error(f"RTMP streaming error: {e}")
        finally:
            self.is_rtmp_streaming = False
            if container:
                try:
                    container.close()
                except Exception:
                    pass


# Global singleton instance
screen_caster = ScreenCaster()
