@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - 1-Click Fast Installer
color 0B
cd /d "%~dp0"

echo ==============================================================
echo       PC REMOTE SENTINEL — 1-CLICK INSTANT PC INSTALLER
echo ==============================================================
echo.
echo   This installer sets up the PC Sentinel agent silently
echo   in the background and connects this PC directly to your
echo   Telegram Bot.
echo.
echo ==============================================================
echo.

:: 1. Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Administrator privileges required to install system background tasks.
    echo [*] Launching elevated Administrator installation window...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~dp0install.bat\"\"' -Verb RunAs" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Administrator installation window opened.
        echo You can now review progress in the elevated window.
    ) else (
        color 0C
        echo [X] Could not automatically request Administrator privileges.
        echo.
        echo PLEASE DO THIS:
        echo   1. Right-click '1-CLICK-INSTALL.bat' (or 'install.bat')
        echo   2. Select 'Run as administrator'
        echo.
    )
    echo.
    echo Press any key to close this launcher...
    pause >nul
    exit /b
)

:: Already admin, run install.bat directly
call "%~dp0install.bat"

echo.
echo Press any key to exit...
pause >nul


