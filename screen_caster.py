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


# Modern Dark Glass HTML5 Web Player
HTML_PLAYER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
    <title>PC Sentinel — Live Screen Cast</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --surface: rgba(18, 24, 38, 0.75);
            --surface-border: rgba(255, 255, 255, 0.08);
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.25);
            --danger: #f43f5e;
            --success: #10b981;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at 50% 0%, #172554 0%, var(--bg) 60%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
        }

        header {
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            background: var(--surface);
            border-bottom: 1px solid var(--surface-border);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.4);
            color: #fda4af;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background: var(--danger);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--danger);
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 14px var(--danger); }
            100% { transform: scale(0.95); opacity: 0.8; }
        }

        .header-title {
            font-size: 1rem;
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        .meta-stats {
            display: flex;
            align-items: center;
            gap: 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: var(--text-sub);
        }

        .stat-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .stat-val {
            color: var(--accent);
            font-weight: 500;
        }

        main {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 16px;
            gap: 16px;
            width: 100%;
            max-width: 1400px;
            margin: 0 auto;
        }

        .stream-viewport-wrapper {
            position: relative;
            width: 100%;
            max-width: 1280px;
            background: #020617;
            border-radius: 16px;
            border: 1px solid var(--surface-border);
            overflow: hidden;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 20px var(--accent-glow);
            aspect-ratio: 16 / 9;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        #stream-img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
            user-select: none;
            -webkit-user-drag: none;
        }

        .active-window-pill {
            position: absolute;
            top: 14px;
            left: 14px;
            z-index: 10;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 0.8rem;
            color: #cbd5e1;
            display: flex;
            align-items: center;
            gap: 8px;
            max-width: 80%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .toolbar {
            width: 100%;
            max-width: 1280px;
            background: var(--surface);
            backdrop-filter: blur(12px);
            border: 1px solid var(--surface-border);
            border-radius: 14px;
            padding: 12px 18px;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .control-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-main);
            padding: 8px 14px;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .btn:hover {
            background: rgba(255, 255, 255, 0.12);
            border-color: rgba(255, 255, 255, 0.25);
            transform: translateY(-1px);
        }

        .btn-accent {
            background: rgba(56, 189, 248, 0.15);
            border-color: rgba(56, 189, 248, 0.4);
            color: #7dd3fc;
        }

        .btn-accent:hover {
            background: rgba(56, 189, 248, 0.25);
            border-color: #38bdf8;
        }

        .btn-danger {
            background: rgba(244, 63, 94, 0.15);
            border-color: rgba(244, 63, 94, 0.35);
            color: #fda4af;
        }

        .btn-danger:hover {
            background: rgba(244, 63, 94, 0.3);
            border-color: var(--danger);
        }

        select {
            background: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: var(--text-main);
            padding: 8px 12px;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.85rem;
            outline: none;
            cursor: pointer;
        }

        select:focus {
            border-color: var(--accent);
        }

        .label-text {
            font-size: 0.8rem;
            color: var(--text-sub);
            font-weight: 500;
        }

        @media (max-width: 768px) {
            header {
                padding: 10px 14px;
            }
            .meta-stats {
                display: none;
            }
            .toolbar {
                flex-direction: column;
                align-items: stretch;
            }
            .control-group {
                justify-content: space-between;
                width: 100%;
            }
            .stream-viewport-wrapper {
                border-radius: 10px;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <span class="badge-live"><span class="pulse-dot"></span> LIVE</span>
            <span class="header-title">PC Sentinel Stream</span>
        </div>
        <div class="meta-stats">
            <div class="stat-item"><span>FPS:</span> <span class="stat-val" id="stat-fps">--</span></div>
            <div class="stat-item"><span>CPU:</span> <span class="stat-val" id="stat-cpu">--%</span></div>
            <div class="stat-item"><span>RAM:</span> <span class="stat-val" id="stat-ram">--%</span></div>
        </div>
    </header>

    <main>
        <div class="stream-viewport-wrapper" id="viewport">
            <div class="active-window-pill" id="window-pill">
                <span>🪟</span> <span id="window-title">Loading display...</span>
            </div>
            <img id="stream-img" src="/stream.mjpg?token={{TOKEN}}" alt="Live Screen Stream" />
        </div>

        <div class="toolbar">
            <div class="control-group">
                <span class="label-text">Quality:</span>
                <select id="sel-quality" onchange="updateSettings()">
                    <option value="480">480p (Data Saver)</option>
                    <option value="720" selected>720p (Fast & Crisp)</option>
                    <option value="1080">1080p (Full HD)</option>
                </select>

                <span class="label-text" style="margin-left: 8px;">Target FPS:</span>
                <select id="sel-fps" onchange="updateSettings()">
                    <option value="10">10 FPS</option>
                    <option value="15" selected>15 FPS</option>
                    <option value="25">25 FPS</option>
                </select>
            </div>

            <div class="control-group">
                <button class="btn btn-accent" onclick="downloadSnapshot()">📸 Snapshot</button>
                <button class="btn" onclick="toggleFullscreen()">⛶ Fullscreen</button>
                <button class="btn btn-danger" onclick="stopStream()">⏹️ Stop Stream</button>
            </div>
        </div>
    </main>

    <script>
        const token = "{{TOKEN}}";
        let frameCount = 0;
        let lastTime = performance.now();

        // Calculate and render client-side FPS
        const img = document.getElementById('stream-img');
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

        // Poll system status & active window
        async function fetchStatus() {
            try {
                const res = await fetch(`/status?token=${token}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.cpu !== undefined) document.getElementById('stat-cpu').textContent = data.cpu + '%';
                    if (data.ram !== undefined) document.getElementById('stat-ram').textContent = data.ram + '%';
                    if (data.active_window) document.getElementById('window-title').textContent = data.active_window;
                }
            } catch (e) {}
        }
        setInterval(fetchStatus, 2000);
        fetchStatus();

        // Download full resolution snapshot
        function downloadSnapshot() {
            const a = document.createElement('a');
            a.href = `/snapshot.jpg?token=${token}&t=${Date.now()}`;
            a.download = `pc_screenshot_${Date.now()}.jpg`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        // Toggle Fullscreen on viewport
        function toggleFullscreen() {
            const vp = document.getElementById('viewport');
            if (!document.fullscreenElement) {
                if (vp.requestFullscreen) vp.requestFullscreen();
                else if (vp.webkitRequestFullscreen) vp.webkitRequestFullscreen();
            } else {
                if (document.exitFullscreen) document.exitFullscreen();
            }
        }

        // Update Quality/FPS settings
        async function updateSettings() {
            const quality = document.getElementById('sel-quality').value;
            const fps = document.getElementById('sel-fps').value;
            try {
                await fetch(`/config?token=${token}&res=${quality}&fps=${fps}`, { method: 'POST' });
            } catch (e) {}
        }

        // Stop stream
        async function stopStream() {
            if (!confirm('Stop PC Screen Casting?')) return;
            try {
                await fetch(`/stop?token=${token}`, { method: 'POST' });
                document.body.innerHTML = '<div style="display:flex;height:100vh;align-items:center;justify-content:center;flex-direction:column;font-family:sans-serif;color:#94a3b8;"><h2>Stream Ended</h2><p style="margin-top:8px;">Screen casting was stopped by user.</p></div>';
            } catch (e) {}
        }
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

        elif path == "/snapshot.jpg":
            img_bytes = self.caster.capture_single_frame(quality=85)
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

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.authenticate():
            self.send_unauthorized()
            return

        if path == "/stop":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            threading.Thread(target=self.caster.stop_web_cast, daemon=True).start()

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
            while self.is_web_streaming and (time.time() - t0 < 15):
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
            # Wait up to 5 seconds for initial tunnel generation
            t_wait = time.time()
            while time.time() - t_wait < 5 and not self.public_url:
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
