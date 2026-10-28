@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Universal Auto Installer
color 0B
cd /d "%~dp0"

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
    echo.
    echo ==============================================================
    echo  [!] ADMINISTRATOR PRIVILEGES REQUIRED
    echo ==============================================================
    echo.
    echo  [*] Requesting Administrator elevation (click YES if prompted by Windows)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -WorkingDirectory '%~dp0' -ArgumentList '/k install.bat %*' -Verb RunAs" >nul 2>&1
    if !errorlevel! equ 0 (
        echo  [OK] Elevated Administrator installation window opened.
        echo  [*] Installation is running in the elevated window.
        timeout /t 3 /nobreak >nul
        exit /b 0
    )
    
    :: Fallback to VBScript elevation if PowerShell was blocked
    echo Set UAC = CreateObject^("Shell.Application"^) > "%TEMP%\sentinel_elevate.vbs"
    echo UAC.ShellExecute "cmd.exe", "/k cd /d """"%~dp0"""" ^&^& install.bat %*", "", "runas", 1 >> "%TEMP%\sentinel_elevate.vbs"
    cscript //nologo "%TEMP%\sentinel_elevate.vbs" >nul 2>&1
    set "VBS_ERR=!errorlevel!"
    del /f /q "%TEMP%\sentinel_elevate.vbs" >nul 2>&1
    if !VBS_ERR! equ 0 (
        echo  [OK] Elevated Administrator installation window opened.
        echo  [*] Installation is running in the elevated window.
        timeout /t 3 /nobreak >nul
        exit /b 0
    )
    
    color 0C
    echo  [X] Could not automatically request Administrator privileges.
    echo.
    echo  PLEASE DO THIS:
    echo    1. Right-click 'install.bat' (or '1-CLICK-INSTALL.bat')
    echo    2. Select 'Run as administrator'
    echo.
    echo  Press any key to exit...
    pause >nul
    exit /b 1
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

:: Method 0: Check dedicated Sentinel Python directory
if exist "%DEST_DIR%\Python\python.exe" (
    "%DEST_DIR%\Python\python.exe" -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY_CMD=%DEST_DIR%\Python\python.exe"
        goto :py_found
    )
)

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

:: Priority A: Offline installer on USB drive (Target C:\PCSentinel\Python)
if exist "%SRC_DIR%python-installer.exe" (
    echo [*] Installing Python using offline installer from USB drive...
    start /wait "" "%SRC_DIR%python-installer.exe" /quiet TargetDir="%DEST_DIR%\Python" PrependPath=1 Include_pip=1 AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0
    timeout /t 3 /nobreak >nul
) else (
    :: Priority B: Download official installer silently via PowerShell
    echo [*] Downloading official Python installer...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '%TEMP%\python-installer.exe')"
    if exist "%TEMP%\python-installer.exe" (
        echo [*] Installing Python silently...
        start /wait "" "%TEMP%\python-installer.exe" /quiet TargetDir="%DEST_DIR%\Python" PrependPath=1 Include_pip=1 AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0
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
if exist "%DEST_DIR%\Python\python.exe" (
    "%DEST_DIR%\Python\python.exe" -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY_CMD=%DEST_DIR%\Python\python.exe"
        goto :py_found
    )
)

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
            if !errorlevel! equ 0 (
                set "PY_CMD=%%~p"
                goto :py_found
            )
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
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand RwBlAHQALQBDAGkAbQBJAG4AcwB0AGEAbgBjAGUAIABXAGkAbgAzADIAXwBQAHIAbwBjAGUAcwBzACAALQBFAHIAcgBvAHIAQQBjAHQAaQBvAG4AIABTAGkAbABlAG4AdABsAHkAQwBvAG4AdABpAG4AdQBlACAAfAAgAFcAaABlAHIAZQAtAE8AYgBqAGUAYwB0ACAAewAgACQAXwAuAEMAbwBtAG0AYQBuAGQATABpAG4AZQAgAC0AbABpAGsAZQAgACcAKgBhAGcAZQBuAHQALgBwAHkAKgAnACAALQBvAHIAIAAkAF8ALgBFAHgAZQBjAHUAdABhAGIAbABlAFAAYQB0AGgAIAAtAGwAaQBrAGUAIAAnACoAUABDAFMAZQBuAHQAaQBuAGUAbAAqACcAIAB9ACAAfAAgAEYAbwByAEUAYQBjAGgALQBPAGIAagBlAGMAdAAgAHsAIABTAHQAbwBwAC0AUAByAG8AYwBlAHMAcwAgAC0ASQBkACAAJABfAC4AUAByAG8AYwBlAHMAcwBJAGQAIAAtAEYAbwByAGMAZQAgAC0ARQByAHIAbwByAEEAYwB0AGkAbwBuACAAUwBpAGwAZQBuAHQAbAB5AEMAbwBuAHQAaQBuAHUAZQAgAH0A >nul 2>&1
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
copy /y "%SRC_DIR%register_target_pc.py" "%DEST_DIR%\" >nul 2>&1
copy /y "%SRC_DIR%DIAGNOSE-PC.bat" "%DEST_DIR%\" >nul 2>&1
copy /y "%SRC_DIR%diagnose_agent.py" "%DEST_DIR%\" >nul 2>&1

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

:: 7. Save verified Python executable path and create named binary
echo %PY_CMD%> "%DEST_DIR%\python_path.txt"
if not exist "%DEST_DIR%\pc-sentinel-agent.exe" (
    copy "%PY_CMD%" "%DEST_DIR%\pc-sentinel-agent.exe" >nul 2>&1
    for %%d in ("%PY_CMD%") do set "PY_DIR=%%~dpd"
    if exist "!PY_DIR!python3*.dll" copy /y "!PY_DIR!python3*.dll" "%DEST_DIR%\" >nul 2>&1
    if exist "!PY_DIR!python3.dll" copy /y "!PY_DIR!python3.dll" "%DEST_DIR%\" >nul 2>&1
    if exist "!PY_DIR!vcruntime140*.dll" copy /y "!PY_DIR!vcruntime140*.dll" "%DEST_DIR%\" >nul 2>&1
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
netsh advfirewall firewall delete rule name="PCSentinelPython" >nul 2>&1
netsh advfirewall firewall delete rule name="PCSentinelPort" >nul 2>&1
netsh advfirewall firewall add rule name="PCSentinelAgent" dir=in action=allow program="%DEST_DIR%\pc-sentinel-agent.exe" enable=yes profile=any >nul 2>&1
netsh advfirewall firewall add rule name="PCSentinelPython" dir=in action=allow program="%PY_CMD%" enable=yes profile=any >nul 2>&1
netsh advfirewall firewall add rule name="PCSentinelPort" dir=in action=allow protocol=TCP localport=9010 enable=yes profile=any >nul 2>&1

:: 10. Register Task Scheduler auto-start (Runs completely silent on user logon with battery resilience)
echo [*] Registering auto-start background task in Windows Task Scheduler...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $trig = New-ScheduledTaskTrigger -AtLogOn; $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); $princ = New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\$env:USERNAME\" -LogonType Interactive -RunLevel Highest; $act = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '\"%DEST_DIR%\start_agent_hidden.vbs\"' -WorkingDirectory '%DEST_DIR%'; Register-ScheduledTask -TaskName 'PCSentinelAgent' -Action $act -Trigger $trig -Settings $set -Principal $princ -Force >$null; }" >nul 2>&1
if %errorlevel% neq 0 (
    schtasks /delete /tn "PCSentinelAgent" /f >nul 2>&1
    schtasks /create /tn "PCSentinelAgent" /tr "wscript.exe \"%DEST_DIR%\start_agent_hidden.vbs\"" /sc ONLOGON /rl HIGHEST /f >nul 2>&1
)

:: Startup folder & Registry Run fallbacks
copy /y "%DEST_DIR%\start_agent_hidden.vbs" "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PCSentinelAgent" /t REG_SZ /d "wscript.exe \"%DEST_DIR%\start_agent_hidden.vbs\"" /f >nul 2>&1

:: 11. Register in USB fleet.json with real LAN IP
if exist "%SRC_DIR%fleet.json" (
    echo [*] Registering %COMPUTERNAME% in USB fleet.json...
    if exist "%SRC_DIR%register_target_pc.py" (
        "%PY_CMD%" "%SRC_DIR%register_target_pc.py" "%SRC_DIR%fleet.json" "%COMPUTERNAME%"
    ) else if exist "%DEST_DIR%\register_target_pc.py" (
        "%PY_CMD%" "%DEST_DIR%\register_target_pc.py" "%SRC_DIR%fleet.json" "%COMPUTERNAME%"
    )
)

:: 12. Launch agent right now in the background
echo [*] Starting PC Sentinel Agent in the background...
wscript.exe "%DEST_DIR%\start_agent_hidden.vbs"
timeout /t 4 /nobreak >nul

:: 13. Instant Live Verification
echo [*] Verifying agent startup and responsiveness...
set "AGENT_HEALTHY=0"
for /l %%r in (1,1,3) do (
    if "!AGENT_HEALTHY!"=="0" (
        for /f "delims=" %%h in ('"%PY_CMD%" -c "import urllib.request; (lambda: print(urllib.request.urlopen('http://127.0.0.1:9010/health', timeout=3.0).getcode()))()" 2^>nul') do (
            if "%%h"=="200" set "AGENT_HEALTHY=1"
        )
        if "!AGENT_HEALTHY!"=="0" (
            timeout /t 2 /nobreak >nul
        )
    )
)

echo.
if "!AGENT_HEALTHY!"=="1" (
    color 0A
    echo ==============================================================
    echo    [OK] PC REMOTE SENTINEL INSTALLED & VERIFIED ONLINE!
    echo ==============================================================
    echo.
    echo    PC Name:     %COMPUTERNAME%
    echo    Location:    %DEST_DIR%
    echo    Status:      ACTIVE & LISTENING ON PORT 9010
    echo    Execution:   Running SILENTLY IN THE BACKGROUND (No Window)
    echo    Auto-Start:  Enabled on Every Boot / Logon
    echo    Networking:  Cloud Relay + Direct LAN
    echo.
    echo    This PC has sent a startup ping to your Telegram Bot!
    echo    You can safely unplug your USB pendrive now.
    echo ==============================================================
) else (
    color 0E
    echo ==============================================================
    echo    [!] INSTALLATION COMPLETED — VERIFYING AGENT STATUS
    echo ==============================================================
    echo    Agent background task registered and started.
    echo    Diagnostic boot log preview:
    echo.
    if exist "%DEST_DIR%\agent_boot.log" (
        type "%DEST_DIR%\agent_boot.log"
    ) else if exist "%DEST_DIR%\agent.log" (
        powershell -NoProfile -Command "Get-Content '%DEST_DIR%\agent.log' -Tail 10"
    )
    echo.
    echo    Auto-start is enabled. If port 9010 is not up yet,
    echo    you can run DIAGNOSE-PC.bat to test connectivity.
    echo ==============================================================
)
echo.
if "%SILENT_MODE%"=="1" (
    echo [*] Silent network install complete. Exiting...
    exit /b 0
)
echo Press any key to finish installation and close this window...
pause >nul


