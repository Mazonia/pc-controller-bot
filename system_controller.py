"""
System Controller Module for PC Remote Sentinel
Handles OS hardware metrics, webcam, screen capture/recording, power, and audio controls.
"""

import os
import sys
import time
import ctypes
import subprocess
import winsound
from datetime import datetime, timezone
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
        }

    @staticmethod
    def take_screenshot(output_path: Path) -> bool:
        """Capture full desktop screenshot."""
        try:
            screenshot = ImageGrab.grab(all_screens=True)
            screenshot.save(output_path, "PNG")
            return True
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return False

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

    # ── Audio & Speech Controls ─────────────────────────────────────────

    @staticmethod
    def control_media(action: str) -> bool:
        """
        Adjust volume and media playback via Windows virtual keystrokes.
        action: 'up', 'down', 'mute', 'play_pause', 'next', 'prev'
        """
        VK_VOLUME_MUTE = 0xAD
        VK_VOLUME_DOWN = 0xAE
        VK_VOLUME_UP = 0xAF
        VK_MEDIA_NEXT_TRACK = 0xB0
        VK_MEDIA_PREV_TRACK = 0xB1
        VK_MEDIA_PLAY_PAUSE = 0xCD

        code_map = {
            "up": VK_VOLUME_UP,
            "down": VK_VOLUME_DOWN,
            "mute": VK_VOLUME_MUTE,
            "play_pause": VK_MEDIA_PLAY_PAUSE,
            "next": VK_MEDIA_NEXT_TRACK,
            "prev": VK_MEDIA_PREV_TRACK,
        }
        vk = code_map.get(action.lower())
        if not vk:
            return False

        try:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
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
    def play_alert_siren() -> None:
        """Play alert siren sounds through PC speaker/audio output."""
        try:
            for _ in range(3):
                winsound.Beep(1200, 200)
                winsound.Beep(800, 200)
        except Exception:
            pass

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
