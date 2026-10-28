#!/usr/bin/env python3
"""
PC Remote Sentinel — Live Agent Diagnostics & Health Inspector
Runs comprehensive diagnostics on the PC Sentinel agent installation,
including runtime environment, dependencies, ports, MQTT relay connectivity, and logs.
"""

import os
import sys
import ssl
import time
import socket
import urllib.request
import subprocess
from pathlib import Path

DEST_DIR = Path(r"C:\PCSentinel")


def banner():
    print("=" * 64)
    print("      PC REMOTE SENTINEL — LIVE DIAGNOSTIC INSPECTOR")
    print("=" * 64)
    print(f"  Target PC Hostname: [{socket.gethostname()}]")
    print(f"  Python Runtime:     {sys.executable} (v{sys.version.split()[0]})")
    print("=" * 64)
    print()


def check_directory():
    print("[1] Inspecting Installation Directory...")
    if not DEST_DIR.exists():
        print(f"    [X] {DEST_DIR} does NOT exist!")
        print("        The PC Sentinel Agent is not installed on this PC.")
        print("        Please run 1-CLICK-INSTALL.bat as Administrator.")
        return False
    print(f"    [OK] Installation directory found at {DEST_DIR}")
    
    files = ["agent.py", "fleet_relay.py", "system_controller.py", "screen_caster.py", "start_agent.bat"]
    missing_files = [f for f in files if not (DEST_DIR / f).exists()]
    if missing_files:
        print(f"    [!] Warning: Missing core script files: {missing_files}")
    else:
        print("    [OK] All core agent python scripts present.")
    return True


def check_env():
    print("\n[2] Checking Configuration File (agent.env)...")
    env_file = DEST_DIR / "agent.env"
    if not env_file.exists():
        print("    [!] agent.env NOT found! Default configuration will be used.")
        return
    print(f"    [OK] Found {env_file}")
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            if "SECRET" in k or "TOKEN" in k:
                masked = v[:4] + "..." + v[-4:] if len(v) > 8 else "***"
                print(f"        {k}={masked}")
            else:
                print(f"        {k}={v}")
    except Exception as e:
        print(f"    [!] Could not parse agent.env: {e}")


def check_dependencies():
    print("\n[3] Verifying Python Dependencies...")
    modules = [
        ("fastapi", "FastAPI Web Engine"),
        ("uvicorn", "Uvicorn ASGI Server"),
        ("paho.mqtt", "Paho MQTT Client"),
        ("cryptography", "AES-256-GCM Encryption"),
        ("psutil", "System Process Monitor"),
        ("PIL", "Pillow Image Processing"),
        ("dotenv", "Python Dotenv Config"),
        ("loguru", "Loguru Logging"),
        ("httpx", "HTTP Client"),
        ("mss", "Fast Screen Grabber"),
        ("cv2", "OpenCV Video/Camera"),
    ]
    all_ok = True
    for mod_name, desc in modules:
        try:
            __import__(mod_name)
            print(f"    [OK] {mod_name:<14} ({desc})")
        except ImportError:
            print(f"    [FAIL] {mod_name:<12} is MISSING!")
            all_ok = False

    if not all_ok:
        print("\n    [!] Dependency check failed! Run install.bat to reinstall wheels.")
    return all_ok


def check_http():
    print("\n[4] Testing Local HTTP Agent (port 9010)...")
    try:
        req = urllib.request.urlopen("http://127.0.0.1:9010/health", timeout=3.0)
        code = req.getcode()
        body = req.read().decode("utf-8")
        if code == 200:
            print(f"    [OK] Agent is ACTIVE and responding: {body.strip()}")
            return True
        else:
            print(f"    [!] Port 9010 responded with unexpected code {code}")
            return False
    except urllib.error.URLError as e:
        print(f"    [!] Port 9010 not responding: {e.reason}")
        print("        The background agent process is either stopped or still starting up.")
        return False
    except Exception as e:
        print(f"    [!] Port 9010 check error: {e}")
        return False


def check_mqtt():
    print("\n[5] Testing Cloud Relay Connection (MQTT TLS)...")
    broker = "broker.emqx.io"
    port = 8883
    try:
        s = socket.create_connection((broker, port), timeout=5.0)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ss = ctx.wrap_socket(s)
        ss.close()
        print(f"    [OK] Outbound connection to {broker}:{port} (TLS) SUCCESSFUL!")
        print("        This PC can communicate globally with your Telegram Bot via Cloud Relay.")
        return True
    except Exception as e:
        print(f"    [!] Outbound connection failed: {e}")
        print(f"        Outbound port {port} may be blocked by this Wi-Fi router or firewall.")
        print("        Local Wi-Fi/LAN commands will still function normally.")
        return False


def show_logs():
    print("\n[6] Inspecting Recent Logs...")
    boot_log = DEST_DIR / "agent_boot.log"
    if boot_log.exists():
        print(f"    --- Last 12 lines of {boot_log.name} ---")
        try:
            lines = boot_log.read_text(encoding="utf-8", errors="replace").splitlines()
            for l in lines[-12:]:
                print(f"      {l}")
        except Exception as e:
            print(f"      Error reading log: {e}")
    else:
        print(f"    [i] No {boot_log.name} created yet.")

    agent_log = DEST_DIR / "agent.log"
    if agent_log.exists():
        print(f"\n    --- Last 12 lines of {agent_log.name} ---")
        try:
            lines = agent_log.read_text(encoding="utf-8", errors="replace").splitlines()
            for l in lines[-12:]:
                print(f"      {l}")
        except Exception as e:
            print(f"      Error reading log: {e}")
    else:
        print(f"    [i] No {agent_log.name} created yet.")


def run_interactive():
    print("\n" + "=" * 64)
    print("  DIAGNOSTIC ACTIONS:")
    print("  [1] Start Agent visibly right now in this window (shows all tracebacks)")
    print("  [2] Restart background Agent via Task Scheduler")
    print("  [3] Exit diagnostics")
    print("=" * 64)

    try:
        choice = input("Select an option [1, 2, or 3]: ").strip()
        if choice == "1":
            print("\n[*] Starting PC Sentinel Agent in the foreground...")
            print("[*] Press Ctrl+C at any time to stop.\n")
            os.chdir(DEST_DIR)
            subprocess.run([sys.executable, str(DEST_DIR / "agent.py")])
        elif choice == "2":
            print("\n[*] Restarting background agent...")
            subprocess.run(["schtasks", "/end", "/tn", "PCSentinelAgent"], capture_output=True)
            vbs = DEST_DIR / "start_agent_hidden.vbs"
            if vbs.exists():
                subprocess.run(["wscript.exe", str(vbs)])
                print("[OK] Background task restarted via start_agent_hidden.vbs.")
            else:
                subprocess.run(["schtasks", "/run", "/tn", "PCSentinelAgent"], capture_output=True)
                print("[OK] Background task started via Task Scheduler.")
            time.sleep(2)
            check_http()
            input("\nPress ENTER to finish...")
    except (KeyboardInterrupt, EOFError):
        pass


def main():
    banner()
    installed = check_directory()
    if not installed:
        input("\nPress ENTER to exit...")
        return

    check_env()
    check_dependencies()
    check_http()
    check_mqtt()
    show_logs()
    run_interactive()


if __name__ == "__main__":
    main()
