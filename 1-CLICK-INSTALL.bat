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

:: 1. Auto-elevate to Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Elevating to Administrator...
    powershell -NoProfile -Command "Start-Process '%~dp0install.bat' -Verb RunAs"
    exit /b
)

:: Already admin, run install.bat directly
call "%~dp0install.bat"
