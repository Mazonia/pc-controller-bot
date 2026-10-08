@echo off
title Uninstall PC Remote Sentinel Headless Task
cd /d "%~dp0"

echo =======================================================
echo    UNINSTALL PC REMOTE SENTINEL HEADLESS TASK
echo =======================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Requires Administrator privileges!
    echo Please right-click and select "Run as administrator".
    pause
    exit /b 1
)

schtasks /delete /tn "PC-Remote-Sentinel" /f

if %errorlevel% equ 0 (
    echo.
    echo [SUCCESS] Headless startup task removed successfully!
) else (
    echo.
    echo Task was not found or already removed.
)

echo.
pause
