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
        """Lock Windows PC instantly."""
        try:
            ctypes.windll.user32.LockWorkStation()
            return True
        except Exception as e:
            logger.error(f"Lock error: {e}")
            return False

    @staticmethod
    def sleep_pc() -> bool:
        """Put PC into sleep state."""
        try:
            # Uses SetSuspendState or fallback powershell
            res = subprocess.run(["powershell", "-Command", "Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)"], capture_output=True)
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

