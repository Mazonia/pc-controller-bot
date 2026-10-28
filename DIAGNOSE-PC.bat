@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Diagnostics & Health Inspector
color 0B

echo ==============================================================
echo       PC REMOTE SENTINEL — LIVE DIAGNOSTIC INSPECTOR
echo ==============================================================
echo.
echo   Inspecting PC Sentinel Agent status on [%COMPUTERNAME%]...
echo.
echo ==============================================================
echo.

set "DEST_DIR=C:\PCSentinel"
set "PY_CMD="

:: 1. Check directory
if not exist "%DEST_DIR%" (
    color 0C
    echo [X] C:\PCSentinel folder NOT FOUND!
    echo     The agent does not appear to be installed on this PC.
    echo     Please run 1-CLICK-INSTALL.bat as Administrator.
    echo.
    pause
    exit /b 1
)
echo [OK] Install folder found: %DEST_DIR%

:: 2. Find Python
if exist "%DEST_DIR%\python_path.txt" (
    set /p SAVED_PY=<"%DEST_DIR%\python_path.txt"
    if exist "!SAVED_PY!" set "PY_CMD=!SAVED_PY!"
)
if not defined PY_CMD (
    for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        set "PY_CMD=%%i"
    )
)
if not defined PY_CMD (
    for %%p in (
        "C:\Program Files\Python314\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
    ) do (
        if not defined PY_CMD if exist %%p set "PY_CMD=%%~p"
    )
)
if not defined PY_CMD set "PY_CMD=python"

echo [OK] Python runtime: %PY_CMD%

:: 3. Test Dependencies
echo [*] Testing Python packages...
"%PY_CMD%" -c "
import sys
mods = ['fastapi', 'uvicorn', 'paho.mqtt', 'cryptography', 'psutil', 'PIL', 'dotenv', 'loguru']
missing = []
for m in mods:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
if missing:
    print('   [FAIL] Missing required modules:', missing)
    sys.exit(1)
else:
    print('   [OK] All core packages installed and working!')
"
if %errorlevel% neq 0 (
    color 0C
    echo [!] Missing Python packages detected. Run install.bat to reinstall wheels.
)

:: 4. Test Local Agent HTTP
echo [*] Testing local Agent HTTP server (port 9010)...
set "HTTP_OK=0"
for /f "delims=" %%h in ('"%PY_CMD%" -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9010/health', timeout=2).getcode())" 2^>nul') do (
    if "%%h"=="200" set "HTTP_OK=1"
)
if "!HTTP_OK!"=="1" (
    color 0A
    echo   [OK] Agent is ACTIVE and responding on http://127.0.0.1:9010/health
) else (
    color 0E
    echo   [!] Port 9010 did NOT respond (Agent process may be stopped or starting).
)

:: 5. Test Cloud Relay MQTT
echo [*] Testing Cloud Relay connection to broker.emqx.io:8883...
"%PY_CMD%" -c "
import ssl, socket, sys
try:
    s = socket.create_connection(('broker.emqx.io', 8883), timeout=5)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ss = ctx.wrap_socket(s)
    ss.close()
    print('   [OK] Outbound connection to broker.emqx.io:8883 (TLS) SUCCESSFUL!')
except Exception as e:
    print('   [FAIL] Could not connect to broker.emqx.io:8883:', e)
    print('   [!] This network or firewall may be blocking outbound port 8883 (TLS MQTT).')
"

:: 6. Display Boot and Error Logs
echo.
echo ==============================================================
echo    DIAGNOSTIC LOG PREVIEWS
echo ==============================================================
if exist "%DEST_DIR%\agent_boot.log" (
    echo --- Last 10 lines of agent_boot.log ---
    powershell -NoProfile -Command "Get-Content '%DEST_DIR%\agent_boot.log' -Tail 10" 2>nul
) else (
    echo [i] No agent_boot.log found.
)
echo.
if exist "%DEST_DIR%\agent.log" (
    echo --- Last 10 lines of agent.log ---
    powershell -NoProfile -Command "Get-Content '%DEST_DIR%\agent.log' -Tail 10" 2>nul
) else (
    echo [i] No agent.log found.
)

echo.
echo ==============================================================
echo [1] Start Agent visibly right now in this window (to see errors)
echo [2] Restart background Agent via Task Scheduler
echo [3] Exit diagnostics
echo ==============================================================
set /p "CHOICE=Select an option [1, 2, or 3]: "

if "%CHOICE%"=="1" (
    echo.
    echo [*] Starting Agent in foreground (Press Ctrl+C to stop)...
    cd /d "%DEST_DIR%"
    "%PY_CMD%" "%DEST_DIR%\agent.py"
) else if "%CHOICE%"=="2" (
    echo [*] Restarting background agent...
    schtasks /run /tn "PCSentinelAgent" >nul 2>&1
    wscript.exe "%DEST_DIR%\start_agent_hidden.vbs" >nul 2>&1
    echo [OK] Agent background task started.
    pause
)
