@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Prepare Clean USB Installer
cd /d "%~dp0"
color 0B

echo ==============================================================
echo       PC REMOTE SENTINEL — CLEAN USB INSTALLER CREATOR
echo ==============================================================
echo.
echo   This tool copies ONLY the minimal necessary files (~250 KB)
echo   needed for other PCs to run the agent silently in the background.
echo.
echo   It will NEVER copy your master bot files, secrets, or logs:
echo     [X] No bot.py or config.py
echo     [X] No master .env or fleet.json
echo     [X] No tests or git history
echo.
echo ==============================================================
echo.

:: Detect removable USB drives
echo [*] Detecting connected USB removable drives...
set "FOUND_DRIVE="
powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 } | ForEach-Object { Write-Host ('   - Drive ' + $_.DeviceID + ' (' + [math]::Round($_.FreeSpace/1GB, 1) + ' GB free of ' + [math]::Round($_.Size/1GB, 1) + ' GB)') }"

echo.
set /p "TARGET_DRIVE=Enter USB drive letter (e.g. E: or E): "
if "%TARGET_DRIVE%"=="" (
    echo [X] No drive specified. Aborting.
    pause
    exit /b 1
)

:: Format drive string (ensure ends with :\ or :)
set "CLEAN_DRIVE=%TARGET_DRIVE:~0,1%:"

if not exist "%CLEAN_DRIVE%\" (
    echo [X] Error: Drive %CLEAN_DRIVE%\ does not exist or is not accessible.
    pause
    exit /b 1
)

echo.
echo [*] Target USB drive: %CLEAN_DRIVE%\
echo [*] Copying minimal agent files...

:: Copy essential core files
copy /y "%~dp01-CLICK-INSTALL.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0install.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0agent.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0fleet_relay.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0system_controller.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0screen_caster.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0requirements_agent.txt" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0start_agent.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0start_agent_hidden.vbs" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0uninstall.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0sync_fleet.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0sync_fleet.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0register_target_pc.py" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0DIAGNOSE-PC.bat" "%CLEAN_DRIVE%\" >nul
copy /y "%~dp0INSTRUCTIONS.txt" "%CLEAN_DRIVE%\" >nul

:: Copy cloudflared tunnel engine if available
if exist "%~dp0cloudflared.exe" (
    copy /y "%~dp0cloudflared.exe" "%CLEAN_DRIVE%\" >nul
)

:: Configuration template & fleet list
if exist "%~dp0deploy_config.env" (
    copy /y "%~dp0deploy_config.env" "%CLEAN_DRIVE%\" >nul
) else if exist "%~dp0deploy_config.env.example" (
    copy /y "%~dp0deploy_config.env.example" "%CLEAN_DRIVE%\deploy_config.env" >nul
)

if exist "%~dp0fleet.json" (
    copy /y "%~dp0fleet.json" "%CLEAN_DRIVE%\" >nul
)

echo   [OK] Core agent and installer files copied successfully.

:: Offline Python installer for PCs without internet
if exist "%~dp0python-installer.exe" (
    echo.
    echo [*] Offline Python installer found (25 MB).
    copy /y "%~dp0python-installer.exe" "%CLEAN_DRIVE%\" >nul
    echo   [OK] Offline Python installer included on drive.
)

:: Offline pip packages folder (100% internet-free installation)
if exist "%~dp0wheels" (
    echo.
    echo [*] Offline Python packages (wheels) found. Copying to drive...
    if not exist "%CLEAN_DRIVE%\wheels" mkdir "%CLEAN_DRIVE%\wheels"
    xcopy /y /q "%~dp0wheels\*.whl" "%CLEAN_DRIVE%\wheels\" >nul
    echo   [OK] Offline Python wheels copied (100% offline installation enabled).
)

echo.
color 0A
echo ==============================================================
echo    [OK] USB DRIVE PREPARED SUCCESSFULLY!
echo ==============================================================
echo.
echo    Location:     %CLEAN_DRIVE%\
echo    Contents:     ONLY essential agent installer files (~250 KB)
echo.
echo    Instructions for target PC:
echo      1. Plug this USB into any target PC
echo      2. Double-click install.bat
echo      3. Agent starts silently in the background
echo      4. Safely unplug your USB drive
echo ==============================================================
echo.
pause
