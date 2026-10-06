@echo off
title PC-Remote-Sentinel
cd /d "%~dp0"

echo ==============================================
echo       PC REMOTE SENTINEL ^& COMMAND CENTER
echo ==============================================
echo.

if not exist .env (
    if exist .env.example (
        copy .env.example .env
        echo Created .env from template. Please configure your TELEGRAM_BOT_TOKEN!
    )
)

:: Create dedicated named executable so Task Manager displays 'pc-sentinel.exe' instead of generic 'python.exe'
for /f "delims=" %%i in ('where python') do set PYTHON_BIN=%%i & goto :found_py
:found_py

if not exist pc-sentinel.exe (
    copy "%PYTHON_BIN%" pc-sentinel.exe >nul
)

echo Starting PC Remote Sentinel Bot as [pc-sentinel.exe]...
pc-sentinel.exe bot.py
pause
