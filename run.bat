@echo off
setlocal enabledelayedexpansion
title PC-Remote-Sentinel
cd /d "%~dp0"

echo ==============================================
echo       PC REMOTE SENTINEL ^& COMMAND CENTER
echo ==============================================
echo.

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env from template. Please configure your TELEGRAM_BOT_TOKEN!
    )
)

:: Find robust Python binary
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

:: Create named executables for clean Task Manager display
if defined PYTHON_BIN (
    if not exist "%~dp0pc-sentinel.exe" copy "!PYTHON_BIN!" "%~dp0pc-sentinel.exe" >nul 2>&1
    if not exist "%~dp0pc-sentinel-agent.exe" copy "!PYTHON_BIN!" "%~dp0pc-sentinel-agent.exe" >nul 2>&1
)

set "EXEC_CMD=python"
if exist "%~dp0pc-sentinel.exe" (
    set "EXEC_CMD=%~dp0pc-sentinel.exe"
) else if defined PYTHON_BIN (
    set "EXEC_CMD=!PYTHON_BIN!"
)

:run_loop
echo [%TIME%] Starting PC Remote Sentinel Bot as [!EXEC_CMD!]...
"!EXEC_CMD!" bot.py
echo [%TIME%] [!] Bot stopped (exit code %errorlevel%). Auto-restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto :run_loop
