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
        """Record desktop screen video for specified seconds."""
        if cv2 is None:
            return False, "OpenCV is not installed."
        
        try:
            import numpy as np
            screen = ImageGrab.grab()
            width, height = screen.size
            fps = 12.0
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

            end_time = time.time() + duration_sec
            frame_delay = 1.0 / fps

            while time.time() < end_time:
                t0 = time.time()
                img = ImageGrab.grab()
                frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
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
    def change_volume(action: str) -> bool:
        """
        Adjust master system volume using Windows virtual keystrokes.
        action: 'up', 'down', 'mute'
        """
        VK_VOLUME_MUTE = 0xAD
        VK_VOLUME_DOWN = 0xAE
        VK_VOLUME_UP = 0xAF

        code_map = {
            "up": VK_VOLUME_UP,
            "down": VK_VOLUME_DOWN,
            "mute": VK_VOLUME_MUTE
        }
        vk = code_map.get(action.lower())
        if not vk:
            return False

        try:
            # Send key down and up
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            return True
        except Exception as e:
            logger.error(f"Volume error: {e}")
            return False

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
        """List top processes sorted by CPU and memory."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                info = p.info
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'] or "Unknown",
                    "cpu": info['cpu_percent'] or 0.0,
                    "mem": round(info['memory_percent'] or 0.0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by memory usage descending
        procs.sort(key=lambda x: (x['mem'], x['cpu']), reverse=True)
        return procs[:limit]

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
    def run_cmd(command: str) -> Tuple[int, str]:
        """Execute terminal command and capture output."""
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            out = proc.stdout if proc.stdout else proc.stderr
            return proc.returncode, out.strip() or "[Command finished with no output]"
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
