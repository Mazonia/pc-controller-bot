"""
System Controller Module for PC Remote Sentinel
Handles OS hardware metrics, webcam, screen capture/recording, power, and audio controls.
"""

import os
import sys
import time
import math
import re
import threading
import ctypes
import ctypes.wintypes
import subprocess
import winsound
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import psutil
from PIL import ImageGrab
from loguru import logger

try:
    import cv2
except ImportError:
    cv2 = None


class SystemController:
    """Windows PC Controller for remote administration."""

    @staticmethod
    def get_system_stats() -> Dict[str, Any]:
        """Collect real-time CPU, RAM, Disk, Battery, and Uptime diagnostics."""
        cpu_pct = psutil.cpu_percent(interval=0.5)
        per_core = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        
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

    @staticmethod
    def ensure_desktop_access() -> bool:
        """Attach thread to active Windows input desktop."""
        try:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
            hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                ctypes.windll.user32.SetThreadDesktop(hdesk)
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def get_session_state() -> str:
        """Detect if Windows is at interactive desktop, lock screen, or Session 0."""
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
        
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
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
        
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
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
                img = ImageGrab.grab()
                frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                if scale != 1.0:
                    frame = cv2.resize(frame, (width, height))
                out.write(frame)
                elapsed = time.time() - t0
                if elapsed < frame_delay:
                    time.sleep(frame_delay - elapsed)

            out.release()
            return True, f"Recorded {duration_sec}s screen video"
        except Exception as e:
            return False, f"Screen recording failed: {e}"

    # ── Power & Session Management ──────────────────────────────────────

    @staticmethod
    def lock_workstation() -> bool:
        """Lock Windows PC instantly using user32 API, rundll32, or session disconnect."""
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
        """Put PC into sleep state using powrprof API and powershell fallback."""
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
        """Shutdown PC now or with timer."""
        try:
            subprocess.run(["shutdown", "/s", "/t", str(seconds)], check=True)
            return True
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            return False

    @staticmethod
    def restart_pc(seconds: int = 0) -> bool:
        """Restart PC now or with timer."""
        try:
            subprocess.run(["shutdown", "/r", "/t", str(seconds)], check=True)
            return True
        except Exception as e:
            logger.error(f"Restart error: {e}")
            return False

    @staticmethod
    def cancel_shutdown() -> bool:
        """Cancel any pending shutdown timer."""
        try:
            subprocess.run(["shutdown", "/a"], check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def turn_off_monitors() -> bool:
        """Put monitors to sleep immediately (wakes up on mouse move/key press)."""
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
        Adjust volume and media playback via Windows virtual keystrokes with extended scan codes.
        Executes a clean, single hardware-level keystroke without duplicate broadcasts to prevent double-toggling.
        action: 'up', 'down', 'mute', 'play_pause', 'play', 'pause', 'next', 'prev', 'stop'
        """
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
        Switch, create, or navigate Windows Virtual Desktops via hardware key events.
        action: 'next', 'prev', 'new', 'close', 'task_view', 'show_desktop'
        """
        SystemController.ensure_desktop_access()
        action = action.lower().strip()
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
        SystemController.ensure_desktop_access()
        direction = direction.lower().strip()
        is_prev = direction in ("prev", "previous", "back", "left")

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


    @staticmethod
    def speak_text(text: str) -> bool:
        """Speak message aloud on PC speakers using Windows Speech Synthesis."""
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
        """Play any audio file (Telegram voice note .ogg, .mp3, .wav, etc.) through PC speakers."""
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
    def list_top_processes(limit: int = 10) -> List[Dict[str, Any]]:
        """List top processes sorted by memory and active CPU consumption."""
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

    @staticmethod
    def kill_process(identifier: str) -> Tuple[bool, str]:
        """Kill process by name or PID."""
        target = identifier.strip()
        killed = 0
        if target.isdigit():
            pid = int(target)
            try:
                p = psutil.Process(pid)
                p.kill()
                return True, f"Killed process {p.name()} (PID {pid})"
            except Exception as e:
                return False, f"Could not kill PID {pid}: {e}"
        else:
            for p in psutil.process_iter(['name']):
                try:
                    if p.info['name'] and p.info['name'].lower() == target.lower():
                        p.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if killed > 0:
                return True, f"Terminated {killed} instances of {target}"
            return False, f"No running process found matching '{target}'"

    @staticmethod
    def get_clipboard() -> str:
        """Read current text contents from Windows clipboard."""
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
        """Copy text to Windows clipboard."""
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
        """Detect all active logical drive roots on Windows."""
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
    def browse_directory(target_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse and list directory contents on the PC for remote file navigation.
        Returns normalized paths, drives, quick-access shortcuts, and sorted item list.
        """
        home = Path.home()
        quick_access = {
            "desktop": str(home / "Desktop"),
            "downloads": str(home / "Downloads"),
            "documents": str(home / "Documents"),
            "pictures": str(home / "Pictures"),
        }

        # Normalize target path
        if not target_path or not target_path.strip():
            p = home / "Desktop" if (home / "Desktop").exists() else home
        else:
            t = target_path.strip()
            if re.match(r"^[a-zA-Z]:$", t):
                t += "\\"
            p = Path(t)

        try:
            p = p.resolve()
        except Exception:
            pass

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
            return {
                "ok": True,
                "is_file": True,
                "file_path": str(p),
                "filename": p.name,
                "size": sz,
                "size_fmt": SystemController.format_size(sz),
                "current_path": str(p.parent),
                "parent_path": str(p.parent.parent) if p.parent != p.parent.parent else None,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }

        # List directory items
        items = []
        ignored_names = {
            "desktop.ini", "ntuser.dat", "$recycle.bin", "system volume information",
            "hiberfil.sys", "pagefile.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp"
        }
        try:
            for entry in p.iterdir():
                try:
                    if entry.name.lower() in ignored_names:
                        continue
                    is_dir = entry.is_dir()
                    sz = entry.stat().st_size if not is_dir else 0
                    mtime = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    items.append({
                        "name": entry.name,
                        "path": str(entry),
                        "is_dir": is_dir,
                        "size": sz,
                        "size_fmt": SystemController.format_size(sz) if not is_dir else "<DIR>",
                        "icon": SystemController.get_file_icon(entry.name, is_dir),
                        "modified": mtime,
                    })
                except (PermissionError, OSError):
                    continue
        except PermissionError as e:
            return {
                "ok": False,
                "error": f"Access Denied: {e}",
                "current_path": str(p),
                "parent_path": str(p.parent) if p != p.parent else None,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "current_path": str(p),
                "parent_path": str(p.parent) if p != p.parent else None,
                "drives": SystemController.get_system_drives(),
                "quick_access": quick_access,
                "items": [],
            }

        # Sort: directories first (alphabetical), then files (alphabetical)
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        parent = str(p.parent) if p != p.parent else None

        return {
            "ok": True,
            "is_file": False,
            "current_path": str(p),
            "parent_path": parent,
            "drives": SystemController.get_system_drives(),
            "quick_access": quick_access,
            "items": items,
            "total_dirs": sum(1 for x in items if x["is_dir"]),
            "total_files": sum(1 for x in items if not x["is_dir"]),
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
                winsound.Beep(1200, 250)
                if self._stop_event.is_set():
                    break
                winsound.Beep(800, 250)
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

