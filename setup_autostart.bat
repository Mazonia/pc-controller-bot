@echo off
title PC Remote Sentinel — Setup Auto-Start
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo =======================================================
echo    PC REMOTE SENTINEL — AUTO-START INSTALLER
echo =======================================================
echo.
echo This will configure your PC to automatically launch both
echo the Central Commander Bot and the Local Agent silently
echo whenever Windows boots, restarts, or you log in.
echo.

:: 1. Auto-elevate to Administrator via UAC
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    set "TARGET_BAT=%~f0"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList @('/k', 'call', ('\"' + $env:TARGET_BAT + '\"')) -Verb RunAs" >nul 2>&1
    exit /b
)

:: 2. Ensure dedicated executables exist for Task Manager visibility
set "PYTHON_BIN="
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CANDIDATE=%%i"
    if exist "!CANDIDATE!" (
        echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
        if errorlevel 1 set "PYTHON_BIN=!CANDIDATE!"
    )
)
if not defined PYTHON_BIN (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" set "PYTHON_BIN=!CANDIDATE!"
    )
)
if not defined PYTHON_BIN (
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
        if not defined PYTHON_BIN (
            if exist %%p set "PYTHON_BIN=%%~p"
        )
    )
)
if defined PYTHON_BIN (
    if not exist "%~dp0pc-sentinel.exe" copy "!PYTHON_BIN!" "%~dp0pc-sentinel.exe" >nul 2>&1
    if not exist "%~dp0pc-sentinel-agent.exe" copy "!PYTHON_BIN!" "%~dp0pc-sentinel-agent.exe" >nul 2>&1
)

:: 3. Register Resilient Windows Task Scheduler Tasks (No battery limits, auto-restart)
echo [1/3] Registering Task Scheduler tasks with battery resilience...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $dir = '%~dp0'.TrimEnd('\'); $trig = New-ScheduledTaskTrigger -AtLogOn; $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); $princ = New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\$env:USERNAME\" -LogonType Interactive -RunLevel Highest; $botAct = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $dir + '\start_hidden.vbs\"') -WorkingDirectory $dir; Register-ScheduledTask -TaskName 'PC-Sentinel-Commander' -Action $botAct -Trigger $trig -Settings $set -Principal $princ -Force | Out-Null; $agentAct = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $dir + '\start_agent_hidden.vbs\"') -WorkingDirectory $dir; Register-ScheduledTask -TaskName 'PC-Sentinel-Agent' -Action $agentAct -Trigger $trig -Settings $set -Principal $princ -Force | Out-Null; }" >nul 2>&1

if %errorlevel% equ 0 (
    echo     [+] Task Scheduler tasks [Commander + Agent] configured with 24/7 battery resilience!
) else (
    echo     [!] Note: Falling back to schtasks /create...
    schtasks /create /tn "PC-Sentinel-Commander" /tr "wscript.exe \"%~dp0start_hidden.vbs\"" /sc onlogon /rl highest /f >nul 2>&1
    schtasks /create /tn "PC-Sentinel-Agent" /tr "wscript.exe \"%~dp0start_agent_hidden.vbs\"" /sc onlogon /rl highest /f >nul 2>&1
)

:: 4. Create Windows Startup Folder shortcuts (Layer 2 redundancy)
echo [2/3] Creating Windows Startup folder shortcuts...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $ws = New-Object -ComObject WScript.Shell; $s1 = $ws.CreateShortcut('%STARTUP_DIR%\PC-Sentinel-Commander.lnk'); $s1.TargetPath = 'wscript.exe'; $s1.Arguments = '\"%~dp0start_hidden.vbs\"'; $s1.WorkingDirectory = '%~dp0'; $s1.Description = 'PC Remote Sentinel Fleet Commander'; $s1.Save(); $s2 = $ws.CreateShortcut('%STARTUP_DIR%\PC-Sentinel-Agent.lnk'); $s2.TargetPath = 'wscript.exe'; $s2.Arguments = '\"%~dp0start_agent_hidden.vbs\"'; $s2.WorkingDirectory = '%~dp0'; $s2.Description = 'PC Remote Sentinel Local Agent'; $s2.Save(); }" >nul 2>&1

echo     [+] Startup folder shortcuts created for Commander and Agent!

:: 5. Register in Windows Registry Run (Layer 3 redundancy)
echo [3/3] Registering in Windows CurrentUser Run registry...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PC-Sentinel-Commander" /t REG_SZ /d "wscript.exe \"%~dp0start_hidden.vbs\"" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PC-Sentinel-Agent" /t REG_SZ /d "wscript.exe \"%~dp0start_agent_hidden.vbs\"" /f >nul 2>&1
echo     [+] Registry Run entries registered!

echo.
echo =======================================================
echo    SUCCESS! Triple-layer Auto-Start is configured.
echo =======================================================
echo.
echo Both the Commander Bot and Local Agent will now start silently
echo in the background whenever Windows boots, restarts, wakes up,
echo or logs in, even while on battery.
echo.

:: 6. Option to launch right now
set /p LAUNCH_NOW="Do you want to launch both Sentinel Bot & Agent in the background now? (Y/N): "
if /i "%LAUNCH_NOW%"=="Y" (
    echo Starting Commander Bot and Agent...
    wscript.exe "%~dp0start_hidden.vbs"
    wscript.exe "%~dp0start_agent_hidden.vbs"
    timeout /t 2 >nul
    echo [+] Sentinel Bot and Agent are running in the background!
)

echo.
echo Press any key to exit.
pause >nul
