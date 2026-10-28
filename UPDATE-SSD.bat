@echo off
setlocal enabledelayedexpansion
title "PC Remote Sentinel - Update SSD / Flash Drive"
color 0B
cd /d "%~dp0"

echo ==============================================================
echo       PC REMOTE SENTINEL — ONE-CLICK SSD / USB UPDATER
echo ==============================================================
echo.
echo   This tool updates your external SSD or USB drive with all
echo   latest installer, uninstaller, diagnostic, and sync files.
echo.
echo ==============================================================
echo.

:: Detect removable or external drives
echo [*] Scanning for connected USB / External SSD drives...
set "FOUND_DRIVE="

for %%d in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if exist "%%d:\" (
        if exist "%%d:\1-CLICK-INSTALL.bat" (
            set "FOUND_DRIVE=%%d:"
            echo   [+] Detected PC Sentinel USB at %%d:\
        ) else if exist "%%d:\PC-Sentinel-SSD-Installer\1-CLICK-INSTALL.bat" (
            set "FOUND_DRIVE=%%d:\PC-Sentinel-SSD-Installer"
            echo   [+] Detected PC-Sentinel-SSD-Installer at %%d:\PC-Sentinel-SSD-Installer
        )
    )
)

if not defined FOUND_DRIVE (
    powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -in @(2,3) -and $_.DeviceID -ne 'C:' } | ForEach-Object { Write-Host ('   - Drive ' + $_.DeviceID + ' (' + [math]::Round($_.FreeSpace/1GB, 1) + ' GB free)') }"
    echo.
    set /p "USER_DRIVE=Enter your SSD/USB drive letter (e.g. D: or D): "
    if not "!USER_DRIVE!"=="" (
        set "CLEAN_LETTER=!USER_DRIVE:~0,1!:"
        if exist "!CLEAN_LETTER!\" (
            set "FOUND_DRIVE=!CLEAN_LETTER!"
        )
    )
)

if not defined FOUND_DRIVE (
    color 0C
    echo.
    echo [X] No USB or SSD drive selected.
    echo     Please plug in your SSD and run this tool again.
    echo.
    pause
    exit /b 1
)

echo.
echo [*] Target drive: %FOUND_DRIVE%
echo [*] Copying latest tools, clean uninstaller, diagnostics, and sync scripts...

copy /y "%~dp01-CLICK-INSTALL.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0install.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0uninstall.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0start_agent.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0start_agent_hidden.vbs" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0agent.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0fleet_relay.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0system_controller.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0screen_caster.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0requirements_agent.txt" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0deploy_config.env" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0fleet.json" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0INSTRUCTIONS.txt" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0sync_fleet.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0sync_fleet.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0register_target_pc.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0DIAGNOSE-PC.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0diagnose_agent.py" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0UPDATE-SSD.bat" "%FOUND_DRIVE%\" >nul
copy /y "%~dp0prepare_usb.bat" "%FOUND_DRIVE%\" >nul

:: Also sync wheels if present
if exist "%~dp0wheels" (
    if not exist "%FOUND_DRIVE%\wheels" mkdir "%FOUND_DRIVE%\wheels" >nul 2>&1
    xcopy /y /q "%~dp0wheels\*.whl" "%FOUND_DRIVE%\wheels\" >nul 2>&1
)

:: Also sync python installer if present
if exist "%~dp0python-installer.exe" (
    if not exist "%FOUND_DRIVE%\python-installer.exe" (
        copy /y "%~dp0python-installer.exe" "%FOUND_DRIVE%\" >nul 2>&1
    )
)

:: Also sync cloudflared.exe if present
if exist "%~dp0cloudflared.exe" (
    if not exist "%FOUND_DRIVE%\cloudflared.exe" (
        copy /y "%~dp0cloudflared.exe" "%FOUND_DRIVE%\" >nul 2>&1
    )
)

echo.
color 0A
echo ==============================================================
echo    [OK] SSD / USB DRIVE UPDATED SUCCESSFULLY!
echo ==============================================================
echo.
echo    Location:  %FOUND_DRIVE%
echo    Included:
echo      [+] Universal Clean Uninstaller (uninstall.bat)
echo      [+] 1-Click Fast Installer (1-CLICK-INSTALL.bat)
echo      [+] Live Diagnostic Inspector (DIAGNOSE-PC.bat + diagnose_agent.py)
echo      [+] Fleet Synchronizer (sync_fleet.bat + sync_fleet.py)
echo      [+] Pre-bundled 100%% offline Python wheels
echo.
echo    Next steps on the target PC:
echo      1. Plug this SSD into the target PC
echo      2. Right-click uninstall.bat -> 'Run as administrator'
echo      3. Right-click 1-CLICK-INSTALL.bat -> 'Run as administrator'
echo      4. Run DIAGNOSE-PC.bat to verify online status
echo ==============================================================
echo.
pause
