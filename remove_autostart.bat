@echo off
title PC Remote Sentinel — Remove Auto-Start
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo =======================================================
echo    PC REMOTE SENTINEL — REMOVE AUTO-START
echo =======================================================
echo.

:: 1. Auto-elevate to Administrator via UAC
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: 2. Remove Task Scheduler Task
echo [1/2] Removing Windows Task Scheduler task...
schtasks /delete /tn "PC-Sentinel-Commander" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo     [+] Task Scheduler task removed.
) else (
    echo     [-] Task was not found in Task Scheduler (or already removed).
)

:: 3. Remove Startup Folder Shortcut
echo [2/2] Removing Windows Startup folder shortcut...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\PC-Sentinel-Commander.lnk"
if exist "%SHORTCUT_PATH%" (
    del /f /q "%SHORTCUT_PATH%" >nul 2>&1
    echo     [+] Startup shortcut deleted.
) else (
    echo     [-] Shortcut was not found in Startup folder.
)

:: 4. Option to stop running process
echo.
set /p STOP_NOW="Do you want to stop any currently running bot processes? (Y/N): "
if /i "%STOP_NOW%"=="Y" (
    taskkill /f /im pc-sentinel.exe >nul 2>&1
    echo [+] Bot process stopped.
)

echo.
echo =======================================================
echo    SUCCESS! Auto-start has been disabled.
echo =======================================================
echo.
pause
