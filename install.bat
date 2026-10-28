@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Universal Auto Installer
color 0B

:: Check for /SILENT flag (used by network deployer)
set "SILENT_MODE=0"
for %%a in (%*) do (
    if /i "%%a"=="/SILENT" set "SILENT_MODE=1"
)

echo ==============================================================
echo       PC REMOTE SENTINEL — UNIVERSAL PC AUTO INSTALLER
echo ==============================================================
echo.

:: 1. Check for Admin privileges and auto-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Requesting Administrator privileges...
    if "%SILENT_MODE%"=="1" (
        powershell -Command "Start-Process '%~f0' -ArgumentList '/SILENT' -Verb RunAs -Wait"
    ) else (
        powershell -Command "Start-Process '%~f0' -Verb RunAs"
    )
    exit /b
)

set "SRC_DIR=%~dp0"
set "DEST_DIR=C:\PCSentinel"
set "CONFIG_SRC=%SRC_DIR%deploy_config.env"

echo [*] Source directory: %SRC_DIR%
echo [*] Target install directory: %DEST_DIR%
echo [*] Target PC Name: [%COMPUTERNAME%]
echo.

:: 2. Check for working Python
echo [*] Checking Python environment...
set "PY_CMD="

:: Method 1: Check if python in PATH is working (not MS Store stub)
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CANDIDATE=%%i"
    if exist "!CANDIDATE!" (
        echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
        if errorlevel 1 set "PY_CMD=!CANDIDATE!"
    )
)
if defined PY_CMD goto :py_found

:: Method 2: Check py launcher
if not defined PY_CMD (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" set "PY_CMD=!CANDIDATE!"
    )
)
if defined PY_CMD goto :py_found

:: Method 3: Check standard Python install directories
if not defined PY_CMD (
    for %%p in (
        "C:\Program Files\Python314\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Program Files\Python310\python.exe"
        "C:\Python314\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    ) do (
        if not defined PY_CMD (
            if exist %%p (
                %%p -c "import sys" >nul 2>&1
                if !errorlevel! equ 0 set "PY_CMD=%%~p"
            )
        )
    )
)
if defined PY_CMD goto :py_found

:: Method 4: PowerShell query
if not defined PY_CMD (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Command python -ErrorAction SilentlyContinue).Source" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" (
            echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
            if errorlevel 1 set "PY_CMD=!CANDIDATE!"
        )
    )
)
if defined PY_CMD goto :py_found

:: Python not installed - Perform silent automated installation
echo [!] Working Python not found on this PC.
echo [*] Starting silent automated Python installation...

:: Priority A: Offline installer on USB drive
if exist "%SRC_DIR%python-installer.exe" (
    echo [*] Installing Python using offline installer from USB drive...
    start /wait "" "%SRC_DIR%python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
    timeout /t 3 /nobreak >nul
) else (
    :: Priority B: Download official installer silently via PowerShell
    echo [*] Downloading official Python installer...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '%TEMP%\python-installer.exe')"
    if exist "%TEMP%\python-installer.exe" (
        echo [*] Installing Python silently...
        start /wait "" "%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
        timeout /t 3 /nobreak >nul
        del /f /q "%TEMP%\python-installer.exe" >nul 2>&1
    ) else (
        :: Priority C: Winget fallback
        echo [*] Attempting winget silent install...
        winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
        timeout /t 8 /nobreak >nul
    )
)

:: Re-verify Python after installation
for %%p in (
    "C:\Program Files\Python314\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
    if not defined PY_CMD (
        if exist %%p (
            set "PY_CMD=%%~p"
            goto :py_found
        )
    )
)

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CANDIDATE=%%i"
    if exist "!CANDIDATE!" (
        echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
        if errorlevel 1 (
            set "PY_CMD=!CANDIDATE!"
            goto :py_found
        )
    )
)

echo [X] Error: Could not automatically install Python.
echo     Please install Python from https://www.python.org/downloads/
if not "%SILENT_MODE%"=="1" pause
exit /b 1

:py_found
echo [OK] Python is ready: %PY_CMD%
echo.

:: 3. Stop existing running agent if upgrading
echo [*] Stopping existing Sentinel agent processes (if any)...
taskkill /f /im pc-sentinel-agent.exe >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*agent.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
schtasks /end /tn "PCSentinelAgent" >nul 2>&1
timeout /t 1 /nobreak >nul

:: 4. Create destination directory structure
echo [*] Creating agent directory at %DEST_DIR%...
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
if not exist "%DEST_DIR%\recordings" mkdir "%DEST_DIR%\recordings"
if not exist "%DEST_DIR%\downloads" mkdir "%DEST_DIR%\downloads"

:: 5. Copy ONLY essential agent files (minimal footprint ~250KB)
echo [*] Copying necessary agent files...
copy /y "%SRC_DIR%agent.py" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%fleet_relay.py" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%system_controller.py" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%screen_caster.py" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%requirements_agent.txt" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%start_agent.bat" "%DEST_DIR%\" >nul
copy /y "%SRC_DIR%start_agent_hidden.vbs" "%DEST_DIR%\" >nul

if exist "%SRC_DIR%cloudflared.exe" (
    copy /y "%SRC_DIR%cloudflared.exe" "%DEST_DIR%\" >nul
)

if exist "%SRC_DIR%uninstall.bat" (
    copy /y "%SRC_DIR%uninstall.bat" "%DEST_DIR%\" >nul
)

:: 6. Generate agent.env
echo [*] Configuring agent settings for PC [%COMPUTERNAME%]...
(
    echo # Auto-generated by install.bat on %DATE% %TIME%
    echo PC_NAME=%COMPUTERNAME%
    
    if exist "%CONFIG_SRC%" (
        for /f "usebackq eol=# tokens=1* delims==" %%A in ("%CONFIG_SRC%") do (
            if not "%%A"=="" (
                echo %%A=%%B
            )
        )
    ) else (
        echo FLEET_SECRET=sentinel-fleet-secret-2026
        echo MQTT_BROKER=broker.emqx.io
        echo MQTT_PORT=8883
        echo MQTT_USE_TLS=true
        echo AGENT_PORT=9010
        echo STREAM_PORT=8585
    )
) > "%DEST_DIR%\agent.env"

:: 7. Create dedicated named binary
if not exist "%DEST_DIR%\pc-sentinel-agent.exe" (
    copy "%PY_CMD%" "%DEST_DIR%\pc-sentinel-agent.exe" >nul
)

:: 8. Install Python pip requirements
echo [*] Installing required Python packages...
"%PY_CMD%" -m ensurepip >nul 2>&1

set "PIP_SUCCESS=0"
if exist "%SRC_DIR%wheels" (
    echo [*] Installing pre-bundled packages from SSD (100%% offline)...
    "%PY_CMD%" -m pip install --quiet --no-index --find-links="%SRC_DIR%wheels" -r "%DEST_DIR%\requirements_agent.txt" >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] Offline packages installed successfully!
        set "PIP_SUCCESS=1"
    )
)

if "!PIP_SUCCESS!"=="0" (
    echo [*] Installing packages via online pip...
    "%PY_CMD%" -m pip install --quiet -r "%DEST_DIR%\requirements_agent.txt"
)
if %errorlevel% neq 0 (
    echo [!] Warning: Some pip dependencies could not be verified. Proceeding...
)

:: 9. Authorize Windows Defender Firewall (Prevents any firewall popups or blocks)
echo [*] Configuring Windows Defender Firewall permissions...
netsh advfirewall firewall delete rule name="PCSentinelAgent" >nul 2>&1
netsh advfirewall firewall delete rule name="PCSentinelPort" >nul 2>&1
netsh advfirewall firewall add rule name="PCSentinelAgent" dir=in action=allow program="%DEST_DIR%\pc-sentinel-agent.exe" enable=yes profile=any >nul 2>&1
netsh advfirewall firewall add rule name="PCSentinelPort" dir=in action=allow protocol=TCP localport=9010 enable=yes profile=any >nul 2>&1

:: 10. Register Task Scheduler auto-start (Runs completely silent on user logon with battery resilience)
echo [*] Registering auto-start background task in Windows Task Scheduler...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $trig = New-ScheduledTaskTrigger -AtLogOn; $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); $princ = New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\$env:USERNAME\" -LogonType Interactive -RunLevel Highest; $act = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '\"%DEST_DIR%\start_agent_hidden.vbs\"' -WorkingDirectory '%DEST_DIR%'; Register-ScheduledTask -TaskName 'PCSentinelAgent' -Action $act -Trigger $trig -Settings $set -Principal $princ -Force | Out-Null; }" >nul 2>&1
if %errorlevel% neq 0 (
    schtasks /delete /tn "PCSentinelAgent" /f >nul 2>&1
    schtasks /create /tn "PCSentinelAgent" /tr "wscript.exe \"%DEST_DIR%\start_agent_hidden.vbs\"" /sc ONLOGON /rl HIGHEST /f >nul 2>&1
)

:: Startup folder & Registry Run fallbacks
copy /y "%DEST_DIR%\start_agent_hidden.vbs" "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PCSentinelAgent" /t REG_SZ /d "wscript.exe \"%DEST_DIR%\start_agent_hidden.vbs\"" /f >nul 2>&1

:: 10. Register in USB fleet.json if available
if exist "%SRC_DIR%fleet.json" (
    "%PY_CMD%" -c "import json, sys; p, n = sys.argv[1], sys.argv[2]; f = open(p, 'r', encoding='utf-8'); d = json.load(f); f.close(); pcs = d.setdefault('pcs', []); pcs.append({'name': n, 'label': n, 'ip': '127.0.0.1', 'network': 'Remote/LAN'}) if not any(x.get('name') == n for x in pcs) else None; f = open(p, 'w', encoding='utf-8'); json.dump(d, f, indent=4); f.close()" "%SRC_DIR%fleet.json" "%COMPUTERNAME%" >nul 2>&1
)

:: 11. Launch agent right now in the background
echo [*] Starting PC Sentinel Agent in the background...
wscript.exe "%DEST_DIR%\start_agent_hidden.vbs"

echo.
color 0A
echo ==============================================================
echo    [OK] PC REMOTE SENTINEL INSTALLED SUCCESSFULLY!
echo ==============================================================
echo.
echo    PC Name:     %COMPUTERNAME%
echo    Location:    %DEST_DIR%
echo    Execution:   Running SILENTLY IN THE BACKGROUND (No Window)
echo    Auto-Start:  Enabled on Every Boot / Logon
echo    Networking:  Cloud Relay (Mobile Hotspot/Wi-Fi/LAN/CGNAT)
echo.
echo    This PC is now live and reporting to your Telegram Bot!
echo    You can safely unplug your USB pendrive now.
echo ==============================================================
echo.
if "%SILENT_MODE%"=="1" (
    echo [*] Silent network install complete. Exiting...
    exit /b 0
)
timeout /t 5

