@echo off
title PC Remote Sentinel — Setup Auto-Start
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo =======================================================
echo    PC REMOTE SENTINEL — AUTO-START INSTALLER
echo =======================================================
echo.
echo This will configure your PC to automatically launch the
echo Central Commander Bot in the background whenever you boot
echo or log into Windows.
echo.

:: 1. Auto-elevate to Administrator via UAC
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: 2. Ensure dedicated executable exists for Task Manager visibility
if not exist "%~dp0pc-sentinel.exe" (
    echo Creating dedicated pc-sentinel.exe executable...
    for /f "delims=" %%i in ('where python') do set "PYTHON_BIN=%%i" & goto :found_py
    :found_py
    if defined PYTHON_BIN (
        copy "!PYTHON_BIN!" "%~dp0pc-sentinel.exe" >nul
    )
)

:: 3. Register Task Scheduler Task (runs elevated at logon)
echo [1/2] Registering Windows Task Scheduler startup task...
schtasks /create /tn "PC-Sentinel-Commander" /tr "wscript.exe \"%~dp0start_hidden.vbs\"" /sc onlogon /rl highest /f >nul 2>&1

if %errorlevel% equ 0 (
    echo     [+] Task Scheduler task 'PC-Sentinel-Commander' registered successfully!
) else (
    echo     [!] Warning: Task Scheduler registration returned code %errorlevel%.
)

:: 4. Create Windows Startup Folder shortcut as backup redundancy
echo [2/2] Creating Windows Startup folder shortcut...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\PC-Sentinel-Commander.lnk"

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%~dp0start_hidden.vbs\"'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'PC Remote Sentinel Fleet Commander'; $s.Save()" >nul 2>&1

if exist "%SHORTCUT_PATH%" (
    echo     [+] Startup folder shortcut created successfully!
)

echo.
echo =======================================================
echo    SUCCESS! Auto-Start is fully configured.
echo =======================================================
echo.
echo The Commander Bot will now start silently in the background
echo every time Windows boots or you log in.
echo.

:: 5. Option to launch right now
set /p LAUNCH_NOW="Do you want to launch the Commander Bot in the background right now? (Y/N): "
if /i "%LAUNCH_NOW%"=="Y" (
    echo Starting Commander Bot...
    wscript.exe "%~dp0start_hidden.vbs"
    timeout /t 2 >nul
    echo [+] Bot is running in the background!
)

echo.
echo Press any key to exit.
pause >nul
