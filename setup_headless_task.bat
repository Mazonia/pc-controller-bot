@echo off
title Setup PC Remote Sentinel Headless Task
cd /d "%~dp0"

echo =======================================================
echo    PC REMOTE SENTINEL -- HEADLESS STARTUP INSTALLER
echo =======================================================
echo.
echo This installer registers Sentinel as an automatic boot task
echo in Windows Task Scheduler.
echo.
echo Mode: Runs at computer startup (ONSTART) as SYSTEM,
echo so the bot is online even before anyone logs into Windows!
echo.

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This installer requires Administrator privileges!
    echo Please right-click this batch file and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

:: Create dedicated named executable if needed
set "BOT_EXE=%~dp0pc-sentinel.exe"
if not exist "%BOT_EXE%" (
    for /f "delims=" %%i in ('where python') do set "PYTHON_BIN=%%i" & goto :found_py
    :found_py
    copy "%PYTHON_BIN%" "%BOT_EXE%" >nul
)

:: Register task running at startup as SYSTEM
schtasks /create /tn "PC-Remote-Sentinel" /tr "\"%BOT_EXE%\" \"%~dp0bot.py\"" /sc onstart /ru SYSTEM /rl highest /f

if %errorlevel% equ 0 (
    echo.
    echo [SUCCESS] PC Remote Sentinel successfully registered in Task Scheduler!
    echo.
    echo Task Name: PC-Remote-Sentinel
    echo Trigger:   At System Startup (Boot)
    echo Account:   SYSTEM (Headless 24/7)
    echo.
    echo The bot will now run automatically whenever your PC turns on,
    echo even if no one logs into Windows!
) else (
    echo.
    echo [ERROR] Failed to register task. Error code: %errorlevel%
)

echo.
pause
