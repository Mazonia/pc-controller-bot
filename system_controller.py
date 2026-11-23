"""
System Controller Module for PC Remote Sentinel
Handles OS hardware metrics, webcam, screen capture/recording, power, and audio controls.
"""

import os
import sys
import gc
import time
import math
import re
import threading
import ctypes
try:
    import ctypes.wintypes
except Exception:
    pass
import subprocess
try:
    import winsound
except ImportError:
    winsound = None
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

import psutil
from PIL import ImageGrab
from loguru import logger

try:
    import cv2
except ImportError:
    cv2 = None


class SystemController:
    """Universal OS Controller for remote administration (Windows & macOS)."""

    _last_desktop_attach_time: float = 0.0
    _dpi_initialized: bool = False

    @staticmethod
    def get_system_stats() -> Dict[str, Any]:
        """Collect real-time CPU, RAM, Disk, Battery, and Uptime diagnostics."""
        cpu_pct = psutil.cpu_percent(interval=0.5)
        per_core = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory()
        disk_target = "C:\\" if IS_WINDOWS else "/"
        disk = psutil.disk_usage(disk_target)
        
        # Battery / Power status
        battery = psutil.sensors_battery()
        battery_info = "N/A (Desktop/AC)"
        if battery:
            plugged = "🔌 Plugged In" if battery.power_plugged else "🔋 On Battery"
            battery_info = f"{battery.percent:.0f}% ({plugged})"

        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_delta = datetime.now() - boot_time
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        return {
            "cpu_percent": cpu_pct,
            "per_core": per_core,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024 ** 3), 2),
            "memory_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "battery": battery_info,
            "uptime": uptime_str,
            "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            "session_state": SystemController.get_session_state(),
        }

    @classmethod
    def ensure_desktop_access(cls, force: bool = False) -> bool:
        """Attach thread to active Windows input desktop with 3.0s cache to eliminate input stutters."""
        if not IS_WINDOWS:
            return True
        now = time.time()
        if not force and (now - cls._last_desktop_attach_time < 3.0):
            return True
        try:
            if not cls._dpi_initialized:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    pass
                cls._dpi_initialized = True
            hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                ctypes.windll.user32.SetThreadDesktop(hdesk)
                cls._last_desktop_attach_time = now
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def get_session_state() -> str:
        """Detect if OS is at interactive desktop, lock screen, or Session 0."""
        if IS_MAC:
            try:
                out = subprocess.run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True, timeout=1.0).stdout
                if re.search(r'["\']?(?:CGSSessionScreenIsLocked|kCGSessionScreenIsLocked)["\']?\s*=\s*(?:1|yes|true|<true>)', out, re.IGNORECASE):
                    return "macOS Lock Screen 🔒"
                return "macOS Desktop (Unlocked) 🟢"
            except Exception:
                return "macOS Desktop 🟢"
        try:
            hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
            if hdesk:
                buf = ctypes.create_unicode_buffer(256)
                size = ctypes.c_uint(0)
                ctypes.windll.user32.GetUserObjectInformationW(hdesk, 2, buf, 256, ctypes.byref(size))
                desk = buf.value.lower()
                if desk == "default":
                    return "Interactive Desktop (Unlocked) 🟢"
                elif desk == "winlogon":
                    return "Windows Login / Lock Screen 🔒"
                return f"{buf.value} 🖥️"
        except Exception:
            pass
        return "Pre-Login / Session 0 🔒"

    @staticmethod
    def take_screenshot(output_path: Path) -> Tuple[bool, str]:
        """Capture full desktop screenshot with graceful pre-login detection."""
        if IS_MAC:
            try:
                res = subprocess.run(["/usr/sbin/screencapture", "-x", str(output_path)], capture_output=True, timeout=5.0)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True, "Screenshot captured"
            except Exception as se:
                logger.debug(f"macOS screencapture error: {se}, falling back to ImageGrab")
        try:
            SystemController.ensure_desktop_access()
            screenshot = ImageGrab.grab(all_screens=True)
            screenshot.save(output_path, "PNG")
            return True, "Screenshot captured"
        except Exception as e:
            err = str(e)
            logger.error(f"Screenshot error: {err}")
            if "screen grab failed" in err.lower():
                return False, "⚠️ Screen capture unavailable: PC is currently at the pre-login lock screen (Session 0). Please log into Windows to view active desktop."
            return False, f"Screenshot error: {err}"

    @staticmethod
    def take_webcam_photo(output_path: Path, camera_index: int = 0) -> Tuple[bool, str]:
        """Capture a single photo from webcam."""
        if cv2 is None:
            return False, "OpenCV (cv2) is not installed."
        
        backend = cv2.CAP_AVFOUNDATION if IS_MAC else cv2.CAP_DSHOW
        cap = cv2.VideoCapture(camera_index, backend)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return False, "Could not access webcam device."

        try:
            # Let sensor adjust for 3 frames
            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            if ret and frame is not None:
                cv2.imwrite(str(output_path), frame)
                return True, "Photo captured"
            return False, "Failed to grab webcam frame"
        except Exception as e:
            return False, f"Webcam error: {e}"
        finally:
            cap.release()

    @staticmethod
    def record_webcam_video(output_path: Path, duration_sec: int = 10, camera_index: int = 0) -> Tuple[bool, str]:
        """Record video clip from webcam for specified seconds."""
        if cv2 is None:
            return False, "OpenCV is not installed."
        
        backend = cv2.CAP_AVFOUNDATION if IS_MAC else cv2.CAP_DSHOW
        cap = cv2.VideoCapture(camera_index, backend)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return False, "Could not open webcam."

        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
            fps = 20.0
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

            end_time = time.time() + duration_sec
            while time.time() < end_time:
                ret, frame = cap.read()
                if ret and frame is not None:
                    out.write(frame)
                time.sleep(0.04)

            out.release()
            return True, f"Recorded {duration_sec}s webcam clip"
        except Exception as e:
            return False, f"Webcam recording failed: {e}"
        finally:
            cap.release()

    @staticmethod
    def record_screen_video(output_path: Path, duration_sec: int = 10) -> Tuple[bool, str]:
        """Record desktop screen video for specified seconds (up to 120s)."""
        if IS_MAC:
            try:
                res = subprocess.run(
                    ["/usr/sbin/screencapture", "-V", str(duration_sec), str(output_path)],
                    capture_output=True,
                    timeout=duration_sec + 10
                )
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True, f"Recorded {duration_sec}s screen video"
            except Exception as se:
                logger.debug(f"macOS native video recording error: {se}, falling back to frame loop")

        if cv2 is None:
            return False, "OpenCV is not installed."
        
        try:
            import numpy as np
            screen = ImageGrab.grab()
            width, height = screen.size
            scale = 1.0
            if width > 1920:
                scale = 1920.0 / width
                width = 1920
                height = int(height * scale)
            if width % 2 != 0:
                width -= 1
            if height % 2 != 0:
                height -= 1

            fps = 10.0
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

            end_time = time.time() + duration_sec
            frame_delay = 1.0 / fps

            while time.time() < end_time:
                t0 = time.time()
                img = None
                frame = None
                try:
                    img = ImageGrab.grab()
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    if scale != 1.0:
                        frame = cv2.resize(frame, (width, height))
                    out.write(frame)
                finally:
                    if img is not None:
                        del img
                    if frame is not None:
                        del frame

                elapsed = time.time() - t0
                if elapsed < frame_delay:
                    time.sleep(frame_delay - elapsed)

            out.release()
            gc.collect()
            return True, f"Recorded {duration_sec}s screen video"
        except Exception as e:
            return False, f"Screen recording failed: {e}"

    # ── Power & Session Management ──────────────────────────────────────

    @staticmethod
    def lock_workstation() -> bool:
        """Lock PC/Mac instantly using OS native APIs."""
        if IS_MAC:
            # 1. Try SACLockScreenImmediate via login framework
            try:
                for lib_name in (
                    "/System/Library/PrivateFrameworks/login.framework/Versions/Current/login",
                    "/System/Library/PrivateFrameworks/login.framework/login",
                    "login",
                ):
                    try:
                        lf = ctypes.CDLL(lib_name)
                        lf.SACLockScreenImmediate()
                        logger.info("macOS workstation locked via SACLockScreenImmediate.")
                        return True
                    except Exception:
                        continue
            except Exception:
                pass

            # 2. Try keyboard shortcut Ctrl+Cmd+Q via AppleScript
            try:
                subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 12 using {control down, command down}'], check=True, timeout=3.0)
                return True
            except Exception:
                pass

            # 3. Fallback to displaysleepnow
            try:
                subprocess.run(["pmset", "displaysleepnow"], check=True, timeout=3.0)
                return True
            except Exception as e:
                logger.error(f"macOS lock error: {e}")
                return False

        try:
            res = ctypes.windll.user32.LockWorkStation()
            if res != 0:
                logger.info("Workstation locked via ctypes user32.LockWorkStation.")
                return True
        except Exception as e:
            logger.debug(f"Direct LockWorkStation failed: {e}")

        try:
            res = subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], shell=False, timeout=3)
            if res.returncode == 0:
                logger.info("Workstation locked via rundll32.")
                return True
        except Exception as e:
            logger.debug(f"rundll32 LockWorkStation failed: {e}")

        try:
            res = subprocess.run(["tsdiscon"], shell=False, timeout=3)
            if res.returncode == 0:
                logger.info("Workstation locked via tsdiscon.")
                return True
        except Exception as e:
            logger.error(f"All workstation lock strategies failed: {e}")
            return False
        return False

    @staticmethod
    def sleep_pc() -> bool:
        """Put PC or Mac into sleep state."""
        if IS_MAC:
            try:
                subprocess.run(["pmset", "sleepnow"], check=True)
                return True
            except Exception:
                try:
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to sleep'], check=True)
                    return True
                except Exception as e:
                    logger.error(f"macOS sleep error: {e}")
                    return False

        try:
            res = subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], shell=False, timeout=5)
            if res.returncode == 0:
                return True
        except Exception as e:
            logger.debug(f"rundll32 SetSuspendState failed: {e}")

        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)"],
                capture_output=True,
                timeout=5
            )
            return res.returncode == 0
        except Exception as e:
            logger.error(f"Sleep error: {e}")
            return False

    @staticmethod
    def shutdown_pc(seconds: int = 0) -> bool:
        """Shutdown PC or Mac now or with timer."""
        if IS_MAC:
            try:
                if seconds > 0:
                    def _delayed_shut():
                        time.sleep(seconds)
                        subprocess.run(["osascript", "-e", 'tell application "System Events" to shut down'])
                    threading.Thread(target=_delayed_shut, daemon=True, name="MacDelayedShutdown").start()
                    return True
                subprocess.run(["osascript", "-e", 'tell application "System Events" to shut down'], check=True)
                return True
            except Exception as e:
                logger.error(f"macOS shutdown error: {e}")
                return False

        try:
            subprocess.run(["shutdown", "/s", "/t", str(seconds)], check=True)
            return True
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            return False

    @staticmethod
    def restart_pc(seconds: int = 0) -> bool:
        """Restart PC or Mac now or with timer."""
        if IS_MAC:
            try:
                if seconds > 0:
                    def _delayed_rst():
                        time.sleep(seconds)
                        subprocess.run(["osascript", "-e", 'tell application "System Events" to restart'])
                    threading.Thread(target=_delayed_rst, daemon=True, name="MacDelayedRestart").start()
                    return True
                subprocess.run(["osascript", "-e", 'tell application "System Events" to restart'], check=True)
                return True
            except Exception as e:
                logger.error(f"macOS restart error: {e}")
                return False

        try:
            subprocess.run(["shutdown", "/r", "/t", str(seconds)], check=True)
            return True
        except Exception as e:
            logger.error(f"Restart error: {e}")
            return False

    @staticmethod
    def cancel_shutdown() -> bool:
        """Cancel any pending shutdown timer."""
        if IS_MAC:
            return True

        try:
            subprocess.run(["shutdown", "/a"], check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def turn_off_monitors() -> bool:
        """Put monitors to sleep immediately (wakes up on mouse move/key press)."""
        if IS_MAC:
            try:
                subprocess.run(["pmset", "displaysleepnow"], check=True)
                return True
            except Exception as e:
                logger.error(f"macOS display sleep error: {e}")
                return False

        try:
            HWND_BROADCAST = 0xFFFF
            WM_SYSCOMMAND = 0x0112
            SC_MONITORPOWER = 0xF170
            MONITOR_OFF = 2
            ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)
            return True
        except Exception as e:
            logger.debug(f"Direct SendMessageW monitor off failed: {e}")

        try:
            cmd = "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class M { [DllImport(\"user32.dll\")] public static extern int SendMessage(int hWnd, int hMsg, int wParam, int lParam); }'; [M]::SendMessage(0xffff, 0x0112, 0xf170, 2)"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=5)
            return res.returncode == 0
        except Exception as e:
            logger.error(f"Monitor off error: {e}")
            return False

    @staticmethod
    def turn_on_monitors() -> bool:
        """Wake up and power on monitors immediately."""
        if IS_MAC:
            try:
                subprocess.run(["caffeinate", "-u", "-t", "2"], check=True)
                return True
            except Exception as e:
                logger.error(f"macOS display wake error: {e}")
                return False

        try:
            HWND_BROADCAST = 0xFFFF
            WM_SYSCOMMAND = 0x0112
            SC_MONITORPOWER = 0xF170
            MONITOR_ON = -1

            # 1. Broadcast WM_SYSCOMMAND to power on display
            ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_ON)

            # 2. Inform power subsystem that display is required (resets idle timers)
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            ctypes.windll.kernel32.SetThreadExecutionState(ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)

            # 3. Simulate relative hardware mouse movement to wake physical display controller
            MOUSEEVENTF_MOVE = 0x0001
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
            time.sleep(0.02)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, -1, 0, 0, 0)
            return True
        except Exception as e:
            logger.error(f"Monitor on error: {e}")
            return False

    # ── Audio & Speech Controls ─────────────────────────────────────────

    @staticmethod
    def control_media(action: str) -> bool:
        """
        Adjust volume and media playback via OS native keystrokes or AppleScript.
        action: 'up', 'down', 'mute', 'play_pause', 'play', 'pause', 'next', 'prev', 'stop'
        """
        if IS_MAC:
            try:
                act = action.lower().strip()
                if act in ("up",):
                    subprocess.run(["osascript", "-e", 'set volume output volume ((output volume of (get volume settings)) + 6)'], check=True)
                elif act in ("down",):
                    subprocess.run(["osascript", "-e", 'set volume output volume ((output volume of (get volume settings)) - 6)'], check=True)
                elif act in ("mute",):
                    subprocess.run(["osascript", "-e", 'set volume output muted (not (output muted of (get volume settings)))'], check=True)
                elif act in ("play_pause", "play", "pause"):
                    subprocess.run(["osascript", "-e", 'tell application "Music" to playpause'], check=True)
                elif act in ("next",):
                    subprocess.run(["osascript", "-e", 'tell application "Music" to next track'], check=True)
                elif act in ("prev",):
                    subprocess.run(["osascript", "-e", 'tell application "Music" to previous track'], check=True)
                return True
            except Exception as e:
                logger.error(f"macOS media control error: {e}")
                return False

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        # Mapping: (VK_CODE, SCAN_CODE)
        key_map = {
            "up": (0xAF, 0x30),          # VK_VOLUME_UP
            "down": (0xAE, 0x2E),         # VK_VOLUME_DOWN
            "mute": (0xAD, 0x20),         # VK_VOLUME_MUTE
            "play_pause": (0xCD, 0x22),   # VK_MEDIA_PLAY_PAUSE
            "play": (0xCD, 0x22),         # VK_MEDIA_PLAY_PAUSE
            "pause": (0xCD, 0x22),        # VK_MEDIA_PLAY_PAUSE
            "next": (0xB0, 0x19),         # VK_MEDIA_NEXT_TRACK
            "prev": (0xB1, 0x10),         # VK_MEDIA_PREV_TRACK
            "stop": (0xB2, 0x24),         # VK_MEDIA_STOP
        }
        entry = key_map.get(action.lower())
        if not entry:
            return False

        vk, scan = entry
        try:
            # Simulate a single genuine extended hardware media key press
            ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_EXTENDEDKEY, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            logger.error(f"Media control error: {e}")
            return False

    @staticmethod
    def change_volume(action: str) -> bool:
        """Backward-compatible alias for control_media."""
        return SystemController.control_media(action)

    @staticmethod
    def press_media_key(action: str) -> Tuple[bool, str]:
        """Convenience method returning (ok, msg) tuple for media key actions."""
        ok = SystemController.control_media(action)
        return ok, f"Media key '{action}' triggered" if ok else f"Unknown or failed media key: {action}"

    @staticmethod
    def get_active_window_title_fast() -> str:
        """Return title of current foreground window quickly without external imports."""
        if IS_MAC:
            try:
                as_cmd = 'tell application "System Events" to get name of first application process whose frontmost is true'
                title = subprocess.check_output(["osascript", "-e", as_cmd], timeout=1.5).decode().strip()
                return title or "macOS Desktop"
            except Exception:
                return "macOS Desktop"

        try:
            SystemController.ensure_desktop_access()
            user32 = ctypes.windll.user32
            h = user32.GetForegroundWindow()
            if h:
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buf, length + 1)
                    t = buf.value.strip()
                    if t:
                        return t
        except Exception:
            pass
        return "Desktop"

    @staticmethod
    def switch_virtual_desktop(action: str) -> Tuple[bool, str]:
        """
        Switch, create, or navigate Virtual Desktops / Spaces via native OS events.
        action: 'next', 'prev', 'new', 'close', 'task_view', 'show_desktop'
        """
        action = action.lower().strip()
        if IS_MAC:
            try:
                if action == "next":
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 124 using {control down}'], check=True)
                    return True, "Switched to next Space"
                elif action == "prev":
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 123 using {control down}'], check=True)
                    return True, "Switched to previous Space"
                elif action in ("task_view", "mission_control"):
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 126 using {control down}'], check=True)
                    return True, "Triggered Mission Control"
                elif action == "show_desktop":
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 103'], check=True)
                    return True, "Toggled Show Desktop"
                return True, f"macOS Space action '{action}' executed"
            except Exception as e:
                return False, f"macOS Space error: {e}"

        SystemController.ensure_desktop_access()
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        VK_LWIN = 0x5B
        VK_CONTROL = 0x11
        VK_RIGHT = 0x27
        VK_LEFT = 0x25
        VK_D = 0x44
        VK_F4 = 0x73
        VK_TAB = 0x09

        if action in ("next", "right"):
            primary, use_ctrl, ext, label = VK_RIGHT, True, True, "Next Desktop (Win+Ctrl+Right)"
        elif action in ("prev", "previous", "left"):
            primary, use_ctrl, ext, label = VK_LEFT, True, True, "Previous Desktop (Win+Ctrl+Left)"
        elif action in ("new", "create"):
            primary, use_ctrl, ext, label = VK_D, True, False, "New Virtual Desktop (Win+Ctrl+D)"
        elif action in ("close", "remove"):
            primary, use_ctrl, ext, label = VK_F4, True, False, "Close Virtual Desktop (Win+Ctrl+F4)"
        elif action in ("task_view", "overview", "tab"):
            primary, use_ctrl, ext, label = VK_TAB, False, False, "Task View (Win+Tab)"
        elif action in ("show_desktop", "desktop", "minimize_all"):
            primary, use_ctrl, ext, label = VK_D, False, False, "Show Desktop (Win+D)"
        else:
            return False, f"Unknown desktop action '{action}'. Valid: next, prev, new, close, task_view, show_desktop"

        user32 = ctypes.windll.user32
        try:
            # Press Windows key
            user32.keybd_event(VK_LWIN, 0, 0, 0)
            time.sleep(0.02)
            if use_ctrl:
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.02)

            # Press primary key
            flags = KEYEVENTF_EXTENDEDKEY if ext else 0
            user32.keybd_event(primary, 0, flags, 0)
            time.sleep(0.06)

            # Release primary key
            user32.keybd_event(primary, 0, flags | KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)
        except Exception as e:
            logger.error(f"Virtual desktop switch error: {e}")
            return False, f"Error switching desktop: {e}"
        finally:
            # Always guarantee modifier keys are released to avoid sticky keys
            if use_ctrl:
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.01)
            user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)

        time.sleep(0.12)
        active = SystemController.get_active_window_title_fast()
        return True, f"Switched desktop: {label} (Active: {active})"

    @staticmethod
    def cycle_window(direction: str = "next") -> Tuple[bool, str]:
        """
        Cycle between open application windows.
        First tries to advance sequentially through open application windows (Alt+Tab equivalent).
        Falls back to hardware Alt+Tab key events.
        """
        direction = direction.lower().strip()
        is_prev = direction in ("prev", "previous", "back", "left")

        if IS_MAC:
            try:
                wins = SystemController.get_open_windows(limit=25)
                if wins:
                    target = wins[1]["title"] if len(wins) > 1 and not is_prev else wins[-1]["title"]
                    ok, msg = SystemController.focus_window(target)
                    return ok, msg
                return True, "Cycled application"
            except Exception as e:
                return False, f"macOS cycle window error: {e}"

        SystemController.ensure_desktop_access()

        # 1. Smart sequential window list cycling
        try:
            wins = SystemController.get_open_windows(limit=25)
            if len(wins) > 1:
                cur_hwnd = ctypes.windll.user32.GetForegroundWindow()
                cur_idx = -1
                for i, w in enumerate(wins):
                    if w["hwnd"] == cur_hwnd:
                        cur_idx = i
                        break

                if cur_idx == -1:
                    target_idx = 1 if not is_prev else len(wins) - 1
                else:
                    target_idx = (cur_idx - 1) % len(wins) if is_prev else (cur_idx + 1) % len(wins)

                target_w = wins[target_idx]
                ok, _ = SystemController.focus_window(target_w["hwnd"])
                if ok:
                    lbl = "Prev Window (Alt+Shift+Tab)" if is_prev else "Next Window (Alt+Tab)"
                    return True, f"{lbl} -> {target_w['title']}"
        except Exception as e:
            logger.debug(f"Smart cycle fallback: {e}")

        # 2. Hardware Alt+Tab fallback
        VK_MENU = 0x12     # Alt
        VK_SHIFT = 0x10    # Shift
        VK_TAB = 0x09      # Tab
        KEYEVENTF_KEYUP = 0x0002

        user32 = ctypes.windll.user32
        try:
            user32.keybd_event(VK_MENU, 0, 0, 0)
            time.sleep(0.02)
            if is_prev:
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
                time.sleep(0.02)
            user32.keybd_event(VK_TAB, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)
        except Exception as e:
            logger.error(f"Cycle window error: {e}")
            return False, f"Error cycling window: {e}"
        finally:
            if is_prev:
                user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

        time.sleep(0.12)
        active = SystemController.get_active_window_title_fast()
        lbl = "Prev Window (Alt+Shift+Tab)" if is_prev else "Next Window (Alt+Tab)"
        return True, f"Switched to {lbl} -> {active}"

    @staticmethod
    def get_open_windows(limit: int = 25) -> List[Dict[str, Any]]:
        """
        Enumerate all active, visible top-level application windows with titles.
        Includes minimized application windows so they can be brought to focus.
        Filters out invisible helper / background system utility windows.
        """
        if IS_MAC:
            try:
                as_cmd = 'tell application "System Events" to get name of every process whose visible is true'
                out = subprocess.check_output(["osascript", "-e", as_cmd], timeout=3.0).decode("utf-8").strip()
                names = [n.strip() for n in out.split(",") if n.strip()]
                results = []
                for idx, name in enumerate(names[:limit], start=1):
                    results.append({
                        "hwnd": idx,
                        "title": name,
                        "process": name,
                        "pid": idx,
                        "is_minimized": False,
                    })
                return results
            except Exception as e:
                logger.error(f"macOS list windows error: {e}")
                return []

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        ignored_titles = {
            "program manager", "settings", "windows input experience", "setup",
            "microsoft text input application", "task switching", "nvidia geforce overlay",
            "desktopwindowcontentbridge", "screen clipping host"
        }
        ignored_processes = {
            "applicationframehost.exe", "shellexperiencehost.exe"
        }
        windows = []

        def enum_cb(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            if not title or title.lower() in ignored_titles:
                return True

            is_iconic = bool(user32.IsIconic(hwnd))
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            # Skip tiny invisible helper windows if not minimized
            if not is_iconic and (w < 60 or h < 60):
                return True

            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pname = ""
            try:
                pname = psutil.Process(pid.value).name()
            except Exception:
                pass

            if pname.lower() in ignored_processes and title.lower() in ("settings", "start", "search"):
                return True

            windows.append({
                "hwnd": hwnd,
                "title": title,
                "process": pname,
                "pid": pid.value,
                "is_minimized": is_iconic,
            })
            return True

        cb_proc = WNDENUMPROC(enum_cb)
        try:
            user32.EnumWindows(cb_proc, 0)
        except Exception as e:
            logger.error(f"EnumWindows error: {e}")

        # Put active window first if found
        try:
            fg = user32.GetForegroundWindow()
            windows.sort(key=lambda x: (x["hwnd"] != fg))
        except Exception:
            pass

        return windows[:limit]

    @staticmethod
    def focus_window(target: Any) -> Tuple[bool, str]:
        """
        Bring a specific application window to the foreground by HWND or partial title search.
        Restores window if minimized. Uses SwitchToThisWindow and input simulation to bypass Windows focus restrictions.
        """
        if IS_MAC:
            try:
                open_wins = SystemController.get_open_windows(limit=50)
                target_app = str(target)
                for w in open_wins:
                    if str(w["hwnd"]) == str(target) or str(target).lower() in w["title"].lower() or str(target).lower() in w["process"].lower():
                        target_app = w["process"]
                        break
                subprocess.run(["osascript", "-e", f'tell application "{target_app}" to activate'], check=True)
                return True, f"Focused '{target_app}'"
            except Exception as e:
                return False, f"macOS focus window error: {e}"

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32
        open_wins = SystemController.get_open_windows(limit=50)

        target_hwnd = None
        target_title = ""

        if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
            h_int = int(target)
            for w in open_wins:
                if w["hwnd"] == h_int:
                    target_hwnd = h_int
                    target_title = w["title"]
                    break
            if not target_hwnd and user32.IsWindow(h_int):
                target_hwnd = h_int
                target_title = f"Window {h_int}"
        elif isinstance(target, str):
            q = target.lower().strip()
            for w in open_wins:
                if q == w["process"].lower() or q in w["title"].lower() or q in w["process"].lower():
                    target_hwnd = w["hwnd"]
                    target_title = w["title"]
                    break

        if not target_hwnd:
            return False, f"Could not find open window matching '{target}'"

        try:
            # 1. Restore if minimized
            SW_RESTORE = 9
            SW_SHOW = 5
            if user32.IsIconic(target_hwnd):
                user32.ShowWindow(target_hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(target_hwnd, SW_SHOW)

            # 2. Use Microsoft SwitchToThisWindow API
            try:
                user32.SwitchToThisWindow(target_hwnd, True)
            except Exception:
                pass

            # 3. Simulate Alt key down/up to bypass Windows SetForegroundWindow lock
            VK_MENU = 0x12
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

            # 4. Bring window to top and set foreground
            user32.BringWindowToTop(target_hwnd)
            user32.SetForegroundWindow(target_hwnd)

            time.sleep(0.08)
            return True, f"Focused: {target_title}"
        except Exception as e:
            logger.error(f"Focus window error: {e}")
            return False, f"Error focusing window: {e}"

    # ── Remote Mouse & Direct Keyboard Control ──────────────────────────

    _mac_cg = None

    @classmethod
    def _get_mac_cg(cls):
        """Safely load and cache macOS CoreGraphics / ApplicationServices library."""
        if cls._mac_cg is not None:
            return cls._mac_cg
        for lib in [
            "ApplicationServices",
            "CoreGraphics",
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
        ]:
            try:
                cls._mac_cg = ctypes.CDLL(lib)
                return cls._mac_cg
            except Exception:
                continue
        try:
            import ctypes.util
            path = ctypes.util.find_library("ApplicationServices") or ctypes.util.find_library("CoreGraphics")
            if path:
                cls._mac_cg = ctypes.CDLL(path)
                return cls._mac_cg
        except Exception:
            pass
        return None

    @staticmethod
    def get_cursor_pos() -> Dict[str, int]:
        """Get current screen resolution and cursor position."""
        if IS_MAC:
            try:
                cg = SystemController._get_mac_cg()
                if not cg:
                    return {"x": 0, "y": 0, "screen_w": 1920, "screen_h": 1080}

                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
                class CGRect(ctypes.Structure):
                    _fields_ = [("origin", CGPoint), ("size", CGPoint)]

                cg.CGMainDisplayID.restype = ctypes.c_uint32
                cg.CGDisplayBounds.restype = CGRect
                cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
                bounds = cg.CGDisplayBounds(cg.CGMainDisplayID())
                screen_w = int(bounds.size.x) if bounds.size.x > 0 else 1920
                screen_h = int(bounds.size.y) if bounds.size.y > 0 else 1080

                cg.CGEventCreate.restype = ctypes.c_void_p
                cg.CGEventCreate.argtypes = [ctypes.c_void_p]
                cg.CGEventGetLocation.restype = CGPoint
                cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]

                ev = cg.CGEventCreate(None)
                if ev:
                    loc = cg.CGEventGetLocation(ev)
                    x, y = int(loc.x), int(loc.y)
                    try:
                        cg.CFRelease.argtypes = [ctypes.c_void_p]
                        cg.CFRelease(ev)
                    except Exception:
                        pass
                    return {"x": x, "y": y, "screen_w": screen_w, "screen_h": screen_h}
                return {"x": 0, "y": 0, "screen_w": screen_w, "screen_h": screen_h}
            except Exception:
                return {"x": 0, "y": 0, "screen_w": 1920, "screen_h": 1080}

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)

        class POINT(ctypes.Structure):
            _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return {
            "x": int(pt.x),
            "y": int(pt.y),
            "screen_w": int(w),
            "screen_h": int(h)
        }

    @staticmethod
    def mouse_move(dx: int, dy: int) -> bool:
        """Simulate relative hardware mouse movement."""
        if IS_MAC:
            cur = SystemController.get_cursor_pos()
            new_x = cur["x"] + dx
            new_y = cur["y"] + dy
            return SystemController.mouse_move_abs(new_x, new_y, normalized=False)

        SystemController.ensure_desktop_access()
        try:
            MOUSEEVENTF_MOVE = 0x0001
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, int(round(float(dx))), int(round(float(dy))), 0, 0)
            return True
        except Exception as e:
            logger.error(f"Mouse move error: {e}")
            return False

    @staticmethod
    def mouse_move_abs(x: float, y: float, normalized: bool = False) -> bool:
        """Move cursor to absolute coordinates (pixels or normalized 0.0-1.0)."""
        if IS_MAC:
            try:
                cur = SystemController.get_cursor_pos()
                sw, sh = cur["screen_w"], cur["screen_h"]
                px = float(max(0.0, min(1.0, float(x))) * (sw - 1)) if normalized else float(x)
                py = float(max(0.0, min(1.0, float(y))) * (sh - 1)) if normalized else float(y)
                px = max(0.0, min(float(sw - 1), px))
                py = max(0.0, min(float(sh - 1), py))

                cg = SystemController._get_mac_cg()
                if not cg:
                    return False

                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

                pt = CGPoint(px, py)
                cg.CGWarpMouseCursorPosition.argtypes = [CGPoint]
                cg.CGWarpMouseCursorPosition(pt)

                # Post mouse moved event so applications update hover and cursor position
                cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
                cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
                cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
                ev = cg.CGEventCreateMouseEvent(None, 5, pt, 0) # 5 = kCGEventMouseMoved
                if ev:
                    cg.CGEventPost(0, ev)
                    try:
                        cg.CFRelease.argtypes = [ctypes.c_void_p]
                        cg.CFRelease(ev)
                    except Exception:
                        pass
                return True
            except Exception as e:
                logger.error(f"macOS mouse abs move error: {e}")
                return False

        SystemController.ensure_desktop_access()
        try:
            user32 = ctypes.windll.user32
            if normalized:
                w = user32.GetSystemMetrics(0)
                h = user32.GetSystemMetrics(1)
                px = int(max(0.0, min(1.0, float(x))) * (w - 1))
                py = int(max(0.0, min(1.0, float(y))) * (h - 1))
            else:
                px = int(round(float(x)))
                py = int(round(float(y)))
            user32.SetCursorPos(px, py)
            return True
        except Exception as e:
            logger.error(f"Mouse abs move error: {e}")
            return False

    @staticmethod
    def mouse_click(button: str = "left", action: str = "click") -> bool:
        """
        Simulate mouse click, button down, button up, or double click.
        button: 'left', 'right', 'middle', 'double'
        action: 'click', 'down', 'up'
        """
        if IS_MAC:
            try:
                cur = SystemController.get_cursor_pos()
                btn = button.lower().strip()
                act = action.lower().strip()
                cg = SystemController._get_mac_cg()
                if not cg:
                    return False

                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

                pt = CGPoint(float(cur["x"]), float(cur["y"]))
                cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
                cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
                cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

                # Map buttons: Left (1, 2, 0), Right (3, 4, 1), Middle (25, 26, 2)
                if btn in ("right", "r"):
                    evt_down, evt_up, mouse_btn = 3, 4, 1
                elif btn in ("middle", "m"):
                    evt_down, evt_up, mouse_btn = 25, 26, 2
                else:
                    evt_down, evt_up, mouse_btn = 1, 2, 0

                is_double = (btn in ("double", "dblclick") or act == "double")

                def _post_event(evt_type, click_count=1):
                    ev = cg.CGEventCreateMouseEvent(None, evt_type, pt, mouse_btn)
                    if ev:
                        if click_count > 1:
                            try:
                                cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
                                cg.CGEventSetIntegerValueField(ev, 1, click_count) # 1 = kCGMouseEventClickState
                            except Exception:
                                pass
                        cg.CGEventPost(0, ev)
                        try:
                            cg.CFRelease.argtypes = [ctypes.c_void_p]
                            cg.CFRelease(ev)
                        except Exception:
                            pass

                if act in ("down", "click") or is_double:
                    _post_event(evt_down, click_count=1)
                if act in ("up", "click") or is_double:
                    _post_event(evt_up, click_count=1)

                if is_double:
                    time.sleep(0.05)
                    _post_event(evt_down, click_count=2)
                    _post_event(evt_up, click_count=2)

                return True
            except Exception as e:
                logger.error(f"macOS mouse click error: {e}")
                return False

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32
        btn = button.lower().strip()
        act = action.lower().strip()

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040

        try:
            if btn in ("double", "dblclick"):
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.02)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(0.05)
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.02)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                return True

            if btn in ("right", "r"):
                flags_down, flags_up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
            elif btn in ("middle", "m"):
                flags_down, flags_up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
            else:  # left
                flags_down, flags_up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

            if act == "down":
                user32.mouse_event(flags_down, 0, 0, 0, 0)
            elif act == "up":
                user32.mouse_event(flags_up, 0, 0, 0, 0)
            else:  # click
                user32.mouse_event(flags_down, 0, 0, 0, 0)
                time.sleep(0.02)
                user32.mouse_event(flags_up, 0, 0, 0, 0)
            return True
        except Exception as e:
            logger.error(f"Mouse click error: {e}")
            return False

    @staticmethod
    def mouse_scroll(delta: int) -> bool:
        """Simulate vertical mouse wheel scrolling (positive = up, negative = down)."""
        if IS_MAC:
            try:
                cg = SystemController._get_mac_cg()
                if not cg:
                    return False
                wheel_step = int(delta / 20) if abs(delta) >= 20 else (1 if delta > 0 else -1)
                try:
                    cg.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
                    cg.CGEventCreateScrollWheelEvent2.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
                    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
                    ev = cg.CGEventCreateScrollWheelEvent2(None, 1, 1, wheel_step, 0, 0)
                    if ev:
                        cg.CGEventPost(0, ev)
                        try:
                            cg.CFRelease.argtypes = [ctypes.c_void_p]
                            cg.CFRelease(ev)
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass
                key = 126 if delta > 0 else 125
                subprocess.run(["osascript", "-e", f'tell application "System Events" to key code {key}'], timeout=2)
                return True
            except Exception as e:
                logger.error(f"macOS mouse scroll error: {e}")
                return False

        SystemController.ensure_desktop_access()
        try:
            MOUSEEVENTF_WHEEL = 0x0800
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(round(float(delta))), 0)
            return True
        except Exception as e:
            logger.error(f"Mouse scroll error: {e}")
            return False

    @staticmethod
    def mouse_scroll_h(delta: int) -> bool:
        """Simulate horizontal mouse wheel scrolling (positive = right, negative = left)."""
        if IS_MAC:
            try:
                cg = SystemController._get_mac_cg()
                if not cg:
                    return False
                wheel_step = int(delta / 20) if abs(delta) >= 20 else (1 if delta > 0 else -1)
                try:
                    cg.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
                    cg.CGEventCreateScrollWheelEvent2.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
                    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
                    ev = cg.CGEventCreateScrollWheelEvent2(None, 1, 2, 0, wheel_step, 0)
                    if ev:
                        cg.CGEventPost(0, ev)
                        try:
                            cg.CFRelease.argtypes = [ctypes.c_void_p]
                            cg.CFRelease(ev)
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass
                key = 124 if delta > 0 else 123
                subprocess.run(["osascript", "-e", f'tell application "System Events" to key code {key}'], timeout=2)
                return True
            except Exception as e:
                logger.error(f"macOS mouse scroll_h error: {e}")
                return False

        SystemController.ensure_desktop_access()
        try:
            MOUSEEVENTF_HWHEEL = 0x01000
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, int(round(float(delta))), 0)
            return True
        except Exception as e:
            logger.error(f"Mouse horizontal scroll error: {e}")
            return False

    @staticmethod
    def execute_gesture(gesture: str) -> Tuple[bool, str]:
        """
        Execute standard Windows/macOS multi-touch gesture actions:
        - 3-Finger gestures:
            - task_view / swipe_up: Win + Tab / Mission Control
            - show_desktop / swipe_down / minimize_all: Win + D / Cmd + F3
            - switch_app_next / swipe_right: Alt + Tab / Next App
            - switch_app_prev / swipe_left: Alt + Shift + Tab / Prev App
            - search / tap: Win + S / Spotlight (Cmd + Space)
        - 4-Finger gestures:
            - next_desktop / swipe_right: Win + Ctrl + Right / Ctrl + Right
            - prev_desktop / swipe_left: Win + Ctrl + Left / Ctrl + Left
            - action_center / swipe_up: Win + A / Notification Center
            - swipe_down: Win + D / Cmd + F3
            - settings / tap: Win + I / System Settings
        - 2-Finger gestures:
            - right_click / tap: Right Click
            - zoom_in: Ctrl + Mouse Wheel Up / Cmd + Plus
            - zoom_out: Ctrl + Mouse Wheel Down / Cmd + Minus
            - zoom_reset: Ctrl + 0 / Cmd + 0
        - System shortcuts:
            - file_explorer: Win + E / Finder
            - clipboard: Win + V
            - snip / screenshot: Win + Shift + S / Cmd + Shift + 4
            - lock: Win + L / Lock Screen
        """
        g = str(gesture or "").lower().strip()

        if IS_MAC:
            if g in ("task_view", "show_all_windows", "three_finger_swipe_up", "3_finger_up", "taskview"):
                try:
                    subprocess.Popen(["open", "-a", "Mission Control"])
                    return True, "Mission Control opened"
                except Exception as e:
                    return False, str(e)
            elif g in ("show_desktop", "three_finger_swipe_down", "3_finger_down", "minimize_all", "desktop", "four_finger_swipe_down", "4_finger_down"):
                return SystemController.press_key("cmd+f3")
            elif g in ("switch_app_next", "switch_app", "three_finger_swipe_right", "3_finger_right", "alt_tab"):
                return SystemController.cycle_window("next")
            elif g in ("switch_app_prev", "three_finger_swipe_left", "3_finger_left", "alt_shift_tab"):
                return SystemController.cycle_window("prev")
            elif g in ("search", "three_finger_tap", "3_finger_tap", "win_s"):
                return SystemController.press_key("cmd+space")
            elif g in ("next_desktop", "four_finger_swipe_right", "4_finger_right"):
                return SystemController.press_key("ctrl+right")
            elif g in ("prev_desktop", "four_finger_swipe_left", "4_finger_left"):
                return SystemController.press_key("ctrl+left")
            elif g in ("action_center", "notifications", "four_finger_swipe_up", "4_finger_up", "win_a"):
                return SystemController.press_key("ctrl+down")
            elif g in ("settings", "four_finger_tap", "4_finger_tap", "win_i"):
                try:
                    subprocess.Popen(["open", "x-apple.systempreferences:"])
                    return True, "System Settings opened"
                except Exception as e:
                    return False, str(e)
            elif g in ("right_click", "two_finger_tap", "2_finger_tap"):
                ok = SystemController.mouse_click(button="right", action="click")
                return ok, "Right Click executed"
            elif g in ("middle_click", "3_finger_click"):
                ok = SystemController.mouse_click(button="middle", action="click")
                return ok, "Middle Click executed"
            elif g in ("zoom_in", "pinch_out"):
                return SystemController.press_key("cmd+plus")
            elif g in ("zoom_out", "pinch_in"):
                return SystemController.press_key("cmd+-")
            elif g in ("zoom_reset", "zoom_100"):
                return SystemController.press_key("cmd+0")
            elif g in ("file_explorer", "win_e"):
                try:
                    subprocess.Popen(["open", str(Path.home())])
                    return True, "Finder opened"
                except Exception as e:
                    return False, str(e)
            elif g in ("snip", "screenshot_tool", "win_shift_s"):
                return SystemController.press_key("cmd+shift+4")
            elif g in ("lock", "lock_screen", "win_l"):
                ok = SystemController.lock_workstation()
                return ok, "Mac Locked" if ok else "Lock failed"
            return False, f"Unknown gesture '{gesture}' on macOS"

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32

        # 3-Finger gestures
        if g in ("task_view", "show_all_windows", "three_finger_swipe_up", "3_finger_up", "taskview"):
            return SystemController.switch_virtual_desktop("task_view")

        elif g in ("show_desktop", "three_finger_swipe_down", "3_finger_down", "minimize_all", "desktop"):
            return SystemController.switch_virtual_desktop("show_desktop")

        elif g in ("switch_app_next", "switch_app", "three_finger_swipe_right", "3_finger_right", "alt_tab"):
            return SystemController.cycle_window("next")

        elif g in ("switch_app_prev", "three_finger_swipe_left", "3_finger_left", "alt_shift_tab"):
            return SystemController.cycle_window("prev")

        elif g in ("search", "three_finger_tap", "3_finger_tap", "win_s"):
            return SystemController.press_key("win+s")

        # 4-Finger gestures
        elif g in ("next_desktop", "four_finger_swipe_right", "4_finger_right"):
            return SystemController.switch_virtual_desktop("next")

        elif g in ("prev_desktop", "four_finger_swipe_left", "4_finger_left"):
            return SystemController.switch_virtual_desktop("prev")

        elif g in ("action_center", "notifications", "four_finger_swipe_up", "4_finger_up", "win_a"):
            return SystemController.press_key("win+a")

        elif g in ("four_finger_swipe_down", "4_finger_down"):
            return SystemController.switch_virtual_desktop("show_desktop")

        elif g in ("settings", "four_finger_tap", "4_finger_tap", "win_i"):
            return SystemController.press_key("win+i")

        # 2-Finger gestures
        elif g in ("right_click", "two_finger_tap", "2_finger_tap"):
            ok = SystemController.mouse_click(button="right", action="click")
            return ok, "Right Click executed"

        elif g in ("middle_click", "3_finger_click"):
            ok = SystemController.mouse_click(button="middle", action="click")
            return ok, "Middle Click executed"

        elif g in ("zoom_in", "pinch_out"):
            try:
                VK_CONTROL = 0x11
                MOUSEEVENTF_WHEEL = 0x0800
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.01)
                user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, 120, 0)
                time.sleep(0.02)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return True, "Zoom In (Ctrl+Wheel Up)"
            except Exception as e:
                return False, f"Zoom In error: {e}"

        elif g in ("zoom_out", "pinch_in"):
            try:
                VK_CONTROL = 0x11
                MOUSEEVENTF_WHEEL = 0x0800
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.01)
                user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -120, 0)
                time.sleep(0.02)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return True, "Zoom Out (Ctrl+Wheel Down)"
            except Exception as e:
                return False, f"Zoom Out error: {e}"

        elif g in ("zoom_reset", "zoom_100"):
            return SystemController.press_key("ctrl+0")

        # Productivity and OS shortcuts
        elif g in ("file_explorer", "win_e"):
            return SystemController.press_key("win+e")

        elif g in ("clipboard", "clipboard_history", "win_v"):
            return SystemController.press_key("win+v")

        elif g in ("snip", "screenshot_tool", "win_shift_s"):
            return SystemController.press_key("win+shift+s")

        elif g in ("lock", "lock_screen", "win_l"):
            ok = SystemController.lock_workstation()
            return ok, "PC Locked" if ok else "Lock failed"

        return False, f"Unknown gesture '{gesture}'"

    @staticmethod
    def type_text(text: str) -> Tuple[bool, str]:
        """
        Type text directly into active PC input field using Win32 SendInput Unicode events
        or AppleScript keystroke on macOS.
        Preserves unicode characters, emojis, accents, and symbols.
        """
        if not text:
            return True, "No text provided"

        if IS_MAC:
            try:
                # Handle newlines properly so AppleScript does not fail syntax parsing
                norm_text = text.replace("\r\n", "\n").replace("\r", "\n")
                lines = norm_text.split("\n")
                for i, line in enumerate(lines):
                    if line:
                        escaped = line.replace('\\', '\\\\').replace('"', '\\"')
                        script = f'tell application "System Events" to keystroke "{escaped}"'
                        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
                    if i < len(lines) - 1:
                        subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 36'], capture_output=True, timeout=5)
                return True, f"Typed {len(text)} characters into active window"
            except Exception as e:
                logger.error(f"macOS type_text error: {e}")
                return False, f"Typing error: {e}"

        SystemController.ensure_desktop_access()

        PUL = ctypes.POINTER(ctypes.c_ulong)

        class KeyBdInput(ctypes.Structure):
            _fields_ = [('wVk', ctypes.c_ushort),
                        ('wScan', ctypes.c_ushort),
                        ('dwFlags', ctypes.c_ulong),
                        ('time', ctypes.c_ulong),
                        ('dwExtraInfo', PUL)]

        class HardwareInput(ctypes.Structure):
            _fields_ = [('uMsg', ctypes.c_ulong),
                        ('wParamL', ctypes.c_short),
                        ('wParamH', ctypes.c_ushort)]

        class MouseInput(ctypes.Structure):
            _fields_ = [('dx', ctypes.c_long),
                        ('dy', ctypes.c_long),
                        ('mouseData', ctypes.c_ulong),
                        ('dwFlags', ctypes.c_ulong),
                        ('time', ctypes.c_ulong),
                        ('dwExtraInfo', PUL)]

        class Input_I(ctypes.Union):
            _fields_ = [('ki', KeyBdInput),
                        ('mi', MouseInput),
                        ('hi', HardwareInput)]

        class Input(ctypes.Structure):
            _fields_ = [('type', ctypes.c_ulong),
                        ('ii', Input_I)]

        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1
        user32 = ctypes.windll.user32

        try:
            for char in text:
                if char == "\r":
                    continue
                if char == "\n":
                    VK_RETURN = 0x0D
                    user32.keybd_event(VK_RETURN, 0, 0, 0)
                    time.sleep(0.01)
                    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.01)
                    continue

                code = ord(char)
                inp = Input()
                inp.type = INPUT_KEYBOARD
                inp.ii.ki.wVk = 0
                inp.ii.ki.wScan = code
                inp.ii.ki.dwFlags = KEYEVENTF_UNICODE
                sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(Input))

                inp.ii.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(Input))

                if sent == 0:
                    user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
                    time.sleep(0.002)
                    user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

                time.sleep(0.005)

            return True, f"Typed {len(text)} characters into active window"
        except Exception as e:
            logger.error(f"Type text error: {e}")
            return False, f"Typing error: {e}"

    @staticmethod
    def press_key(key: str) -> Tuple[bool, str]:
        """
        Press special key or shortcut combo (e.g., 'enter', 'backspace', 'ctrl+v', 'win+d', 'cmd+c').
        """
        k = key.lower().strip()

        if IS_MAC:
            k = key.lower().strip()
            mac_keycodes = {
                "enter": 36, "return": 36,
                "tab": 48,
                "space": 49,
                "backspace": 51, "bksp": 51, "delete": 51, "del": 51,
                "escape": 53, "esc": 53,
                "left": 123, "right": 124, "down": 125, "up": 126,
                "pageup": 116, "pagedown": 121, "home": 115, "end": 119,
                "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
                "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
            }
            # Special shortcuts translation for macOS
            if k in ("win+d", "super+d"):
                return SystemController.press_key("cmd+f3")
            if k in ("win+e", "super+e"):
                subprocess.Popen(["open", str(Path.home())])
                return True, "Finder opened"
            if k in ("alt+f4",):
                return SystemController.press_key("cmd+w")
            if k in ("ctrl", "control"):
                script = 'tell application "System Events" to key code 59'
                subprocess.run(["osascript", "-e", script], timeout=5)
                return True, "Control key pressed"
            if k in ("cmd", "command", "win", "super"):
                script = 'tell application "System Events" to key code 55'
                subprocess.run(["osascript", "-e", script], timeout=5)
                return True, "Command key pressed"
            if k in ("alt", "option", "opt"):
                script = 'tell application "System Events" to key code 58'
                subprocess.run(["osascript", "-e", script], timeout=5)
                return True, "Option key pressed"
            if k in ("shift",):
                script = 'tell application "System Events" to key code 56'
                subprocess.run(["osascript", "-e", script], timeout=5)
                return True, "Shift key pressed"

            parts = [p.strip() for p in k.split("+")]
            mods = []
            for p in parts[:-1]:
                if p in ("ctrl", "control"):
                    if len(parts[-1]) == 1 and parts[-1].lower() in "cvxzasfwqrt":
                        mods.append("command down")
                    else:
                        mods.append("control down")
                elif p in ("alt", "option", "opt"):
                    mods.append("option down")
                elif p in ("shift",):
                    mods.append("shift down")
                elif p in ("cmd", "command", "win", "super"):
                    mods.append("command down")

            using_clause = f" using {{{', '.join(mods)}}}" if mods else ""
            last = parts[-1]
            try:
                if last in mac_keycodes:
                    script = f'tell application "System Events" to key code {mac_keycodes[last]}{using_clause}'
                elif len(last) == 1:
                    escaped_char = last.replace('\\', '\\\\').replace('"', '\\"')
                    script = f'tell application "System Events" to keystroke "{escaped_char}"{using_clause}'
                else:
                    return False, f"Unknown key '{key}' on macOS"
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    return True, f"Key '{key}' pressed"
                return False, f"macOS key press failed: {res.stderr.strip()}"
            except Exception as e:
                logger.error(f"macOS press_key error: {e}")
                return False, f"Error pressing key: {e}"

        SystemController.ensure_desktop_access()
        user32 = ctypes.windll.user32

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        vk_map = {
            "enter": 0x0D, "return": 0x0D,
            "backspace": 0x08, "bksp": 0x08,
            "tab": 0x09,
            "escape": 0x1B, "esc": 0x1B,
            "space": 0x20,
            "delete": 0x2E, "del": 0x2E,
            "win": 0x5B, "super": 0x5B,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "pageup": 0x21, "pagedown": 0x22,
            "home": 0x24, "end": 0x23,
            "insert": 0x2D,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
            "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
            "f11": 0x7A, "f12": 0x7B,
        }

        parts = [p.strip() for p in k.split("+")]
        modifiers = []

        for p in parts[:-1]:
            if p in ("ctrl", "control"):
                modifiers.append(0x11)
            elif p in ("alt", "menu"):
                modifiers.append(0x12)
            elif p in ("shift",):
                modifiers.append(0x10)
            elif p in ("win", "super", "cmd"):
                modifiers.append(0x5B)

        last_part = parts[-1]
        if last_part in vk_map:
            primary_vk = vk_map[last_part]
        elif len(last_part) == 1:
            primary_vk = ord(last_part.upper())
        elif last_part in ("ctrl", "alt", "shift", "win"):
            mod_code = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}[last_part]
            user32.keybd_event(mod_code, 0, 0, 0)
            time.sleep(0.04)
            user32.keybd_event(mod_code, 0, KEYEVENTF_KEYUP, 0)
            return True, f"Pressed {last_part}"
        else:
            return False, f"Unknown key '{key}'"

        try:
            for mod in modifiers:
                user32.keybd_event(mod, 0, 0, 0)
                time.sleep(0.01)

            ext = primary_vk in (0x25, 0x26, 0x27, 0x28, 0x21, 0x22, 0x24, 0x23, 0x2E, 0x2D)
            flags = KEYEVENTF_EXTENDEDKEY if ext else 0
            user32.keybd_event(primary_vk, 0, flags, 0)
            time.sleep(0.04)
            user32.keybd_event(primary_vk, 0, flags | KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)
            return True, f"Key '{key}' pressed"
        except Exception as e:
            logger.error(f"Press key error: {e}")
            return False, f"Error pressing key: {e}"
        finally:
            for mod in reversed(modifiers):
                user32.keybd_event(mod, 0, KEYEVENTF_KEYUP, 0)


    @staticmethod
    def speak_text(text: str) -> bool:
        """Speak message aloud on PC/Mac speakers using native Speech Synthesis."""
        if IS_MAC:
            try:
                subprocess.Popen(["/usr/bin/say", text])
                return True
            except Exception as e:
                logger.error(f"macOS TTS error: {e}")
                return False

        try:
            safe_text = text.replace("'", "''").replace('"', '`"')
            cmd = f'Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak("{safe_text}")'
            subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd])
            return True
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return False

    @staticmethod
    def play_audio_file(file_path: Path) -> Tuple[bool, str]:
        """Play any audio file (Telegram voice note .ogg, .mp3, .wav, etc.) through speakers."""
        if IS_MAC:
            try:
                target_path = file_path
                temp_wav = None
                if file_path.suffix.lower() in (".ogg", ".oga"):
                    temp_wav = file_path.with_suffix(".temp.wav")
                    try:
                        import av
                        in_container = av.open(str(file_path))
                        out_container = av.open(str(temp_wav), mode="w", format="wav")
                        in_stream = in_container.streams.audio[0]
                        out_stream = out_container.add_stream("pcm_s16le", rate=44100, layout="stereo")
                        resampler = av.AudioResampler(format="s16", layout="stereo", rate=44100)
                        for frame in in_container.decode(in_stream):
                            for rf in resampler.resample(frame):
                                for packet in out_stream.encode(rf):
                                    out_container.mux(packet)
                        for packet in out_stream.encode(None):
                            out_container.mux(packet)
                        out_container.close()
                        in_container.close()
                        target_path = temp_wav
                    except Exception as conv_err:
                        logger.warning(f"Audio conversion warning: {conv_err}")

                res = subprocess.run(["/usr/bin/afplay", str(target_path)], capture_output=True, timeout=60)
                if temp_wav and temp_wav.exists():
                    try:
                        temp_wav.unlink()
                    except Exception:
                        pass
                if res.returncode == 0:
                    return True, "Audio played on Mac speakers"
                return False, f"afplay failed: {res.stderr.decode('utf-8', errors='ignore')}"
            except Exception as e:
                logger.error(f"Failed to play audio on macOS: {e}")
                return False, str(e)

        try:
            target_path = file_path
            temp_wav = None

            # Telegram voice notes are Opus in OGG; convert to PCM WAV for native Windows audio playback
            if file_path.suffix.lower() != ".wav":
                temp_wav = file_path.with_suffix(".temp.wav")
                try:
                    import av
                    in_container = av.open(str(file_path))
                    out_container = av.open(str(temp_wav), mode="w", format="wav")
                    in_stream = in_container.streams.audio[0]
                    out_stream = out_container.add_stream("pcm_s16le", rate=44100, layout="stereo")
                    resampler = av.AudioResampler(format="s16", layout="stereo", rate=44100)
                    for frame in in_container.decode(in_stream):
                        for rf in resampler.resample(frame):
                            for packet in out_stream.encode(rf):
                                out_container.mux(packet)
                    for packet in out_stream.encode(None):
                        out_container.mux(packet)
                    out_container.close()
                    in_container.close()
                    target_path = temp_wav
                except Exception as conv_err:
                    logger.warning(f"Audio conversion warning: {conv_err}")

            # Play using winsound SND_FILENAME
            try:
                winsound.PlaySound(str(target_path), winsound.SND_FILENAME)
            except Exception:
                try:
                    import playsound3
                    playsound3.playsound(str(target_path))
                except Exception as ps_err:
                    return False, f"Audio playback failed: {ps_err}"

            # Clean up temporary WAV file
            if temp_wav and temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass

            return True, "Audio played on PC speakers"
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
            return False, str(e)

    @staticmethod
    def play_alert_siren(label: str = "Instant Alarm") -> None:
        """Play alert siren sounds and voice alert immediately."""
        alarm_manager.trigger_alarm_now(label)

    @staticmethod
    def set_alarm(seconds: int, label: str = "Scheduled Alarm", callback=None) -> Dict[str, Any]:
        """Schedule a PC alarm timer with customizable duration and label."""
        return alarm_manager.set_alarm(seconds, label, callback)

    @staticmethod
    def cancel_alarm() -> bool:
        """Cancel any pending countdown/scheduled alarm."""
        return alarm_manager.cancel_alarm()

    @staticmethod
    def stop_alarm() -> bool:
        """Silence any currently ringing alarm."""
        return alarm_manager.stop_alarm()

    @staticmethod
    def get_alarm_status() -> Dict[str, Any]:
        """Fetch real-time alarm status (idle, scheduled, or ringing)."""
        return alarm_manager.get_status()

    @staticmethod
    def parse_alarm_time(text: str) -> Tuple[Optional[int], str]:
        """Parse customizable time inputs (relative '10m', '45s', or clock '18:30')."""
        return AlarmManager.parse_time_input(text)

    # ── Task Manager & Utilities ────────────────────────────────────────

    @staticmethod
    def list_top_processes(limit: int = 10, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """List top processes sorted by memory and active CPU consumption."""
        if count is not None:
            limit = count
        limit = max(1, min(100, int(limit)))
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_percent']):
            try:
                info = p.info
                name = info['name'] or "Unknown"
                procs.append({
                    "pid": info['pid'],
                    "name": name,
                    "mem": round(info['memory_percent'] or 0.0, 1),
                    "_proc": p,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort primarily by memory usage descending
        procs.sort(key=lambda x: x['mem'], reverse=True)
        top = procs[:limit]

        # Fast sampling for active CPU usage
        for item in top:
            try:
                item['_proc'].cpu_percent()
            except Exception:
                pass

        time.sleep(0.1)

        for item in top:
            try:
                item['cpu'] = round(item['_proc'].cpu_percent(), 1)
            except Exception:
                item['cpu'] = 0.0
            del item['_proc']

        return top

    PROTECTED_PROCESSES = {
        "csrss.exe", "smss.exe", "services.exe", "wininit.exe",
        "lsass.exe", "winlogon.exe", "system", "registry",
        "launchd", "kernel_task", "windowserver", "loginwindow",
        "diskarbitrationd", "coreauthd", "securityd", "syslogd"
    }

    @staticmethod
    def kill_process(identifier: Union[str, int, None] = None, pid: Optional[Union[int, str]] = None, name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Kill process by name or PID with strict safety checks to prevent
        interfering with other critical processes or trading bots.
        """
        if identifier is None:
            if pid is not None:
                identifier = str(pid)
            elif name is not None:
                identifier = str(name)
            else:
                return False, "No process identifier provided."
        target = str(identifier).strip()
        killed = 0
        my_pids = {os.getpid()}
        try:
            my_pids.add(os.getppid())
        except Exception:
            pass

        # 1. Protect against blanket termination of Python interpreters by name
        # to prevent terminating user trading bots or other critical Python applications.
        if target.lower() in ("python.exe", "pythonw.exe", "python"):
            return False, (
                "🛡️ Safety Shield: Terminating Python by name ('python.exe') is restricted to prevent "
                "accidentally killing other running Python applications (such as trading bots or background workers). "
                "Please specify the exact Process PID instead: '/kill <PID>'."
            )

        # 2. Protect against terminating critical Windows/macOS system components
        if target.lower() in SystemController.PROTECTED_PROCESSES:
            return False, f"🛡️ Safety Shield: Cannot terminate critical system process: '{target}'."

        if target.isdigit():
            pid = int(target)
            if pid in (0, 1, 4):
                return False, f"🛡️ Safety Shield: Refusing to terminate System core process (PID {pid})."
            if pid in my_pids:
                return False, f"🛡️ Safety Shield: Refusing to terminate Sentinel's own process (PID {pid})."
            try:
                p = psutil.Process(pid)
                pname = p.name().lower()
                if pname in SystemController.PROTECTED_PROCESSES:
                    return False, f"🛡️ Safety Shield: Cannot terminate critical Windows process: {p.name()} (PID {pid})."
                p.kill()
                return True, f"Killed process {p.name()} (PID {pid})"
            except psutil.NoSuchProcess:
                return False, f"No process found with PID {pid}."
            except psutil.AccessDenied:
                return False, f"Access denied trying to terminate PID {pid} (insufficient privileges)."
            except Exception as e:
                return False, f"Could not kill PID {pid}: {e}"
        else:
            for p in psutil.process_iter(['name', 'pid']):
                try:
                    if p.pid in my_pids:
                        continue
                    if p.info['name'] and p.info['name'].lower() == target.lower():
                        p.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if killed > 0:
                return True, f"Terminated {killed} instance{'s' if killed > 1 else ''} of '{target}'"
            return False, f"No running process found matching '{target}'"

    @staticmethod
    def get_clipboard() -> str:
        """Read current text contents from clipboard."""
        if IS_MAC:
            try:
                res = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, timeout=5)
                val = res.stdout
                return val if val else "[Clipboard text is empty]"
            except Exception as e:
                logger.error(f"Clipboard read error: {e}")
                return f"[Error reading clipboard: {e}]"

        try:
            import win32clipboard, win32con
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    return data if data else "[Clipboard text is empty]"
                return "[Clipboard does not contain text]"
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            logger.error(f"Clipboard read error: {e}")
            return f"[Error reading clipboard: {e}]"

    @staticmethod
    def set_clipboard(text: str) -> bool:
        """Copy text to clipboard."""
        if IS_MAC:
            try:
                proc = subprocess.Popen(["/usr/bin/pbcopy"], stdin=subprocess.PIPE, text=True)
                proc.communicate(input=text, timeout=5)
                return proc.returncode == 0
            except Exception as e:
                logger.error(f"macOS pbcopy error: {e}")
                return False

        try:
            import win32clipboard, win32con
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            logger.error(f"Clipboard write error: {e}")
            return False

    @staticmethod
    def scan_storage_candidates(recordings_dir: Path, downloads_dir: Path) -> List[Dict[str, Any]]:
        """
        Scan recordings and temporary downloads folders for cleanup candidates without deleting anything.
        Returns list of metadata dicts (path, name, folder, size_bytes, size_mb, age_str).
        """
        candidates = []
        now = time.time()
        for folder_type, folder in [("recordings", recordings_dir), ("downloads", downloads_dir)]:
            if not folder.exists():
                continue
            for item in folder.iterdir():
                if item.is_file():
                    try:
                        stat = item.stat()
                        age_sec = max(0, now - stat.st_mtime)
                        if age_sec < 60:
                            age_str = f"{int(age_sec)}s ago"
                        elif age_sec < 3600:
                            age_str = f"{int(age_sec / 60)}m ago"
                        elif age_sec < 86400:
                            age_str = f"{int(age_sec / 3600)}h ago"
                        else:
                            age_str = f"{int(age_sec / 86400)}d ago"

                        candidates.append({
                            "path": str(item.resolve()),
                            "name": item.name,
                            "folder": folder_type,
                            "size_bytes": stat.st_size,
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "age_str": age_str,
                        })
                    except Exception as e:
                        logger.warning(f"Could not stat {item.name}: {e}")
        return candidates

    @staticmethod
    def delete_storage_files(file_paths: List[str], allowed_dirs: List[Path]) -> Tuple[int, int]:
        """
        Securely delete explicitly approved files. Validates that each file path resides
        strictly within the allowed bot directories to prevent path traversal attacks.
        Returns (deleted_count, freed_bytes).
        """
        deleted_count = 0
        freed_bytes = 0
        resolved_allowed = [d.resolve() for d in allowed_dirs if d.exists()]

        for path_str in file_paths:
            try:
                p = Path(path_str).resolve()
                if not any(str(p).startswith(str(d)) for d in resolved_allowed):
                    logger.warning(f"Security: Refusing to delete file outside allowed dirs: {p}")
                    continue
                if p.is_file():
                    sz = p.stat().st_size
                    p.unlink()
                    deleted_count += 1
                    freed_bytes += sz
            except Exception as e:
                logger.error(f"Error deleting file {path_str}: {e}")

        return deleted_count, freed_bytes

    @staticmethod
    def cleanup_old_files(recordings_dir: Path, downloads_dir: Path, max_age_days: int = 3) -> Tuple[int, int]:
        """Delete recordings and temp files older than max_age_days. Returns (count, bytes_freed)."""
        deleted_count = 0
        freed_bytes = 0
        now = time.time()
        max_age_sec = max_age_days * 86400

        for folder in [recordings_dir, downloads_dir]:
            if not folder.exists():
                continue
            for item in folder.iterdir():
                if item.is_file():
                    try:
                        mtime = item.stat().st_mtime
                        if now - mtime > max_age_sec:
                            sz = item.stat().st_size
                            item.unlink()
                            deleted_count += 1
                            freed_bytes += sz
                    except Exception as e:
                        logger.warning(f"Could not remove old file {item.name}: {e}")
        return deleted_count, freed_bytes

    @staticmethod
    def format_size(num_bytes: int) -> str:
        """Format byte count into human-readable size string."""
        if num_bytes <= 0:
            return "0 B"
        num = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num) < 1024.0:
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
            num /= 1024.0
        return f"{num:.1f} PB"

    @staticmethod
    def get_system_drives() -> List[str]:
        """Detect all active logical drive roots."""
        if IS_MAC:
            drives = ["/"]
            vols = Path("/Volumes")
            if vols.exists():
                try:
                    for v in vols.iterdir():
                        if v.is_dir() and not v.name.startswith("."):
                            drives.append(str(v))
                except Exception:
                    pass
            return drives

        drives = []
        try:
            for p in psutil.disk_partitions():
                if p.device and p.device not in drives:
                    d = p.device
                    if not d.endswith("\\"):
                        d += "\\"
                    drives.append(d)
        except Exception:
            pass
        if not drives:
            drives = ["C:\\"]
        return drives

    @staticmethod
    def get_file_icon(name: str, is_dir: bool) -> str:
        """Return aesthetic emoji icon based on item type and file extension."""
        if is_dir:
            return "📁"
        ext = Path(name).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg"):
            return "🖼️"
        elif ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v"):
            return "🎥"
        elif ext in (".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"):
            return "🎵"
        elif ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".bz2", ".7zip"):
            return "📦"
        elif ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv", ".rtf"):
            return "📄"
        elif ext in (".py", ".js", ".html", ".css", ".json", ".ts", ".jsx", ".tsx", ".cpp", ".c", ".java", ".php", ".sh"):
            return "💻"
        elif ext in (".exe", ".bat", ".cmd", ".vbs", ".ps1", ".msi", ".dll"):
            return "⚙️"
        return "📄"

    @staticmethod
    def get_memory_status() -> Dict[str, Any]:
        """Fetch detailed RAM & Swap memory diagnostics with safe error handling."""
        try:
            vmem = psutil.virtual_memory()
            smem = psutil.swap_memory()
            rss_mb = 0.0
            try:
                rss_mb = round(psutil.Process().memory_info().rss / (1024 ** 2), 2)
            except Exception:
                pass
            return {
                "ok": True,
                "ram_total_gb": round(vmem.total / (1024 ** 3), 2),
                "ram_used_gb": round(vmem.used / (1024 ** 3), 2),
                "ram_free_gb": round(vmem.available / (1024 ** 3), 2),
                "ram_percent": vmem.percent,
                "swap_total_gb": round(smem.total / (1024 ** 3), 2),
                "swap_used_gb": round(smem.used / (1024 ** 3), 2),
                "swap_percent": smem.percent,
                "agent_memory_mb": rss_mb,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "ram_percent": 0.0,
            }

    @staticmethod
    def browse_directory(target_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse and list directory contents on the PC for remote file navigation.
        Includes alias expansion, access-denied containment, and safe memory capping.
        """
        home = Path.home()
        quick_access = {
            "desktop": str(home / "Desktop"),
            "downloads": str(home / "Downloads"),
            "documents": str(home / "Documents"),
            "pictures": str(home / "Pictures"),
        }
        if (home / "Music").exists():
            quick_access["music"] = str(home / "Music")
        if (home / "Videos").exists():
            quick_access["videos"] = str(home / "Videos")

        # Normalize target path and expand common aliases
        raw = (target_path or "").strip()
        raw_lower = raw.lower()

        if not raw or raw_lower in ("home", "~"):
            p = home / "Desktop" if (home / "Desktop").exists() else home
        elif raw_lower in quick_access:
            p = Path(quick_access[raw_lower])
        elif raw.startswith("~"):
            p = Path(raw).expanduser()
        elif re.match(r"^[a-zA-Z]:$", raw):
            p = Path(raw + "\\")
        elif raw in ("/", "\\"):
            p = Path("/" if IS_MAC else "C:\\")
        else:
            p = Path(raw)
            if not p.is_absolute():
                # Try relative to home first, then fallback to relative candidate
                cand = home / raw
                if cand.exists():
                    p = cand

        try:
            p = p.resolve()
        except Exception:
            pass

        # If not found, check single drive letter without colon
        if not p.exists() and len(raw) == 1 and raw.isalpha() and not IS_MAC:
            cand_drv = Path(f"{raw.upper()}:\\")
            if cand_drv.exists():
                p = cand_drv

        if not p.exists():
            return {
                "ok": False,
                "error": f"Path not found: '{target_path}'",
                "current_path": str(p),
                "parent_path": str(home),
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }

        # If user pointed directly to a file
        if p.is_file():
            sz = p.stat().st_size
            parent = str(p.parent)
            parent_parent = str(p.parent.parent) if p.parent != p.parent.parent else None
            return {
                "ok": True,
                "is_file": True,
                "file_path": str(p),
                "filename": p.name,
                "size": sz,
                "size_fmt": SystemController.format_size(sz),
                "current_path": parent,
                "parent_path": parent_parent,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }

        # List directory items with safe memory & network payload bounds
        dirs_list = []
        files_list = []
        MAX_ITEMS = 150  # Cap items to protect RAM and ensure MQTT packet stays well under 256KB
        total_scanned = 0

        ignored_names = {
            "desktop.ini", "ntuser.dat", "$recycle.bin", "system volume information",
            "hiberfil.sys", "pagefile.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp",
            ".ds_store", ".localized", ".trashes", ".fseventsd", ".spotlight-v100"
        }

        try:
            for entry in p.iterdir():
                total_scanned += 1
                try:
                    ename_lower = entry.name.lower()
                    if ename_lower in ignored_names or ename_lower.startswith("~$"):
                        continue
                    is_dir = entry.is_dir()
                    if is_dir:
                        if len(dirs_list) < MAX_ITEMS:
                            mtime = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                            dirs_list.append({
                                "name": entry.name,
                                "path": str(entry),
                                "is_dir": True,
                                "size": 0,
                                "size_fmt": "<DIR>",
                                "icon": "📁",
                                "modified": mtime,
                            })
                    else:
                        if len(files_list) < MAX_ITEMS:
                            st = entry.stat()
                            sz = st.st_size
                            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                            files_list.append({
                                "name": entry.name,
                                "path": str(entry),
                                "is_dir": False,
                                "size": sz,
                                "size_fmt": SystemController.format_size(sz),
                                "icon": SystemController.get_file_icon(entry.name, False),
                                "modified": mtime,
                            })
                except (PermissionError, OSError):
                    continue

        except PermissionError as e:
            # Contain permission errors gracefully so user remains in UI with active Up button
            parent = str(p.parent) if p != p.parent else None
            return {
                "ok": True,
                "is_file": False,
                "current_path": str(p),
                "parent_path": parent,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [
                    {
                        "name": "⛔ Access Denied (Protected System Folder)",
                        "path": str(p),
                        "is_dir": False,
                        "size": 0,
                        "size_fmt": "LOCKED",
                        "icon": "🔒",
                        "modified": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                ],
                "total_dirs": 0,
                "total_files": 1,
                "warning": f"Permission denied: {e}",
            }
        except Exception as e:
            parent = str(p.parent) if p != p.parent else None
            return {
                "ok": False,
                "error": str(e),
                "current_path": str(p),
                "parent_path": parent,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }

        # Sort: directories first (alphabetical), then files (alphabetical)
        dirs_list.sort(key=lambda x: x["name"].lower())
        files_list.sort(key=lambda x: x["name"].lower())

        # Combine with MAX_ITEMS ceiling
        combined_items = dirs_list[:MAX_ITEMS]
        remaining_slots = max(0, MAX_ITEMS - len(combined_items))
        if remaining_slots > 0:
            combined_items.extend(files_list[:remaining_slots])

        parent = str(p.parent) if p != p.parent else None
        is_truncated = total_scanned > len(combined_items)

        return {
            "ok": True,
            "is_file": False,
            "current_path": str(p),
            "parent_path": parent,
            "drives": SystemController.get_system_drives(),
            "quick_access": quick_access,
            "items": combined_items,
            "total_dirs": len(dirs_list),
            "total_files": len(files_list),
            "total_scanned": total_scanned,
            "truncated": is_truncated,
            "note": f"Showing {len(combined_items)} of {total_scanned} items to conserve memory & bandwidth" if is_truncated else "",
        }

    @staticmethod
    def run_cmd(command: str, bot_token: str = "") -> Tuple[int, str]:
        """Execute terminal command securely with dangerous command blocking and token masking."""
        cmd_lower = command.lower().strip()

        # Security policy: Block credential extraction & catastrophic system destruction
        blocked_keywords = [
            ".env", "type .env", "cat .env", "get-content .env",
            "format ", "diskpart", "del /f /s /q c:", "rmdir /s /q c:"
        ]
        for pattern in blocked_keywords:
            if pattern in cmd_lower:
                return -1, f"⛔ Security Violation: Execution of command containing '{pattern}' is blocked by Sentinel policy."

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            out = proc.stdout if proc.stdout else proc.stderr
            res_str = out.strip() or "[Command finished with no output]"

            # Prevent token leakage if environment variables are dumped
            if bot_token and bot_token in res_str:
                res_str = res_str.replace(bot_token, "[PROTECTED_BOT_TOKEN]")

            return proc.returncode, res_str
        except subprocess.TimeoutExpired:
            return -1, "Command timed out after 30 seconds."
        except Exception as e:
            return -1, f"Execution failed: {e}"

    @staticmethod
    def open_target(target: str) -> bool:
        """Open web URL or local file path."""
        try:
            if IS_MAC:
                subprocess.Popen(["open", target])
                return True
            elif IS_LINUX:
                subprocess.Popen(["xdg-open", target])
                return True
            else:
                os.startfile(target)
                return True
        except Exception as e:
            logger.error(f"Open target error: {e}")
            return False


class AlarmManager:
    """
    Manages custom PC countdown alarms, scheduled clock-time alarms,
    audible siren loops, and speech synthesis announcements.
    """
    def __init__(self):
        self.active_alarm: Optional[Dict[str, Any]] = None
        self._ringing: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._timer_cancel_event: threading.Event = threading.Event()
        self._current_label: str = ""
        self._on_trigger_callback = None

    def set_alarm(self, seconds: int, label: str = "Scheduled Alarm", callback=None) -> Dict[str, Any]:
        """Set a countdown alarm for X seconds with optional label and trigger callback."""
        self.cancel_alarm()
        self._stop_event.clear()
        self._timer_cancel_event.clear()

        now = time.time()
        target_time = now + seconds
        time_str = time.strftime("%H:%M:%S", time.localtime(target_time))

        self.active_alarm = {
            "target_time": target_time,
            "target_time_str": time_str,
            "label": label or "Scheduled Alarm",
            "duration_sec": seconds,
            "created_at": now
        }
        self._on_trigger_callback = callback

        def _timer_worker():
            if not self._timer_cancel_event.wait(timeout=seconds):
                # Alarm triggered!
                alarm_info = self.active_alarm
                self.active_alarm = None
                lbl = alarm_info["label"] if alarm_info else label
                t_str = alarm_info["target_time_str"] if alarm_info else time_str

                if self._on_trigger_callback:
                    try:
                        self._on_trigger_callback(lbl, t_str)
                    except Exception as err:
                        logger.error(f"Alarm trigger callback error: {err}")

                self._sound_alarm_loop(lbl)

        t = threading.Thread(target=_timer_worker, daemon=True, name="AlarmTimerThread")
        t.start()
        return self.active_alarm

    def cancel_alarm(self) -> bool:
        """Cancel any pending countdown/scheduled alarm."""
        had_alarm = self.active_alarm is not None
        self._timer_cancel_event.set()
        self.active_alarm = None
        return had_alarm

    def trigger_alarm_now(self, label: str = "Instant Alarm") -> None:
        """Sound alarm siren and voice immediately."""
        self.stop_alarm()
        t = threading.Thread(target=self._sound_alarm_loop, args=(label,), daemon=True, name="AlarmRingingThread")
        t.start()

    def stop_alarm(self) -> bool:
        """Silence any currently ringing alarm."""
        was_ringing = self._ringing
        self._stop_event.set()
        self._ringing = False
        return was_ringing

    def _sound_alarm_loop(self, label: str):
        """Sound audible alarm on PC with sirens and speech synthesis."""
        self._ringing = True
        self._current_label = label
        self._stop_event.clear()

        # Unmute and boost PC speaker volume
        try:
            SystemController.control_media("up")
            SystemController.control_media("up")
        except Exception:
            pass

        # Speak announcement in background
        if label:
            try:
                SystemController.speak_text(f"Attention! Alarm: {label}")
            except Exception:
                pass

        # Sound alternating siren beeps for up to 60s or until stopped
        start_time = time.time()
        while not self._stop_event.is_set() and (time.time() - start_time < 60):
            try:
                if IS_MAC:
                    subprocess.run(["/usr/bin/afplay", "/System/Library/Sounds/Ping.aiff"], timeout=1)
                    time.sleep(0.3)
                elif winsound:
                    winsound.Beep(1200, 250)
                    if self._stop_event.is_set():
                        break
                    winsound.Beep(800, 250)
                else:
                    time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

        self._ringing = False

    def get_status(self) -> Dict[str, Any]:
        """Return real-time alarm status dictionary."""
        now = time.time()
        if self._ringing:
            return {"status": "ringing", "label": self._current_label}
        if self.active_alarm:
            rem = max(1, int(math.ceil(self.active_alarm["target_time"] - now)))
            if rem > 0:
                mins = rem // 60
                secs = rem % 60
                hours = mins // 60
                mins = mins % 60
                if hours > 0:
                    time_left_str = f"{hours}h {mins}m {secs}s"
                elif mins > 0:
                    time_left_str = f"{mins}m {secs}s"
                else:
                    time_left_str = f"{secs}s"

                return {
                    "status": "scheduled",
                    "seconds_left": rem,
                    "time_left_str": time_left_str,
                    "target_time_str": self.active_alarm["target_time_str"],
                    "label": self.active_alarm["label"]
                }
        return {"status": "idle"}

    @staticmethod
    def parse_time_input(input_str: str) -> Tuple[Optional[int], str]:
        """
        Parse user time string supporting:
        - Relative intervals: '10s', '5m', '15m', '1.5h', '2h', '10' (minutes default)
        - Clock times: '14:30', '7:00am', '8:30pm'
        Returns (seconds, label).
        """
        text = input_str.strip()
        if not text:
            return None, ""

        parts = text.split(maxsplit=1)
        time_part = parts[0].lower().strip()
        label = parts[1].strip() if len(parts) > 1 else "Scheduled Alarm"

        # 1. Clock time (e.g. 18:30, 7:00, 7:30am, 8:45pm)
        clock_match = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", time_part)
        if clock_match:
            h = int(clock_match.group(1))
            m = int(clock_match.group(2))
            ampm = clock_match.group(3)
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            if 0 <= h <= 23 and 0 <= m <= 59:
                now = datetime.now()
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                seconds = int((target - now).total_seconds())
                return seconds, label

        # 2. Relative intervals (e.g. 30s, 5m, 10m, 1.5h, 2h, or plain numbers like 15)
        rel_match = re.match(r"^(\d+(?:\.\d+)?)\s*([smhd])?$", time_part)
        if rel_match:
            val = float(rel_match.group(1))
            unit = rel_match.group(2) or "m"
            multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
            seconds = int(val * multipliers.get(unit, 60))
            if seconds > 0:
                return seconds, label

        return None, label


alarm_manager = AlarmManager()

