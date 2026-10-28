@echo off
setlocal enabledelayedexpansion
title "PC Remote Sentinel - Live Diagnostic Inspector"
color 0B

:: 1. Check directory
set "DEST_DIR=C:\PCSentinel"
set "SRC_DIR=%~dp0"

:: 2. Find Python runtime
set "PY_CMD="

if exist "%DEST_DIR%\python_path.txt" (
    set /p SAVED_PY=<"%DEST_DIR%\python_path.txt"
    if exist "!SAVED_PY!" set "PY_CMD=!SAVED_PY!"
)

if not defined PY_CMD (
    for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" (
            echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
            if errorlevel 1 set "PY_CMD=!CANDIDATE!"
        )
    )
)

if not defined PY_CMD (
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
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) do (
        if not defined PY_CMD if exist %%p set "PY_CMD=%%~p"
    )
)

if not defined PY_CMD set "PY_CMD=python"

:: 3. Run diagnose_agent.py
if exist "%SRC_DIR%diagnose_agent.py" (
    "%PY_CMD%" "%SRC_DIR%diagnose_agent.py"
) else if exist "%DEST_DIR%\diagnose_agent.py" (
    "%PY_CMD%" "%DEST_DIR%\diagnose_agent.py"
) else (
    echo [!] diagnose_agent.py script not found.
    echo Please make sure the USB drive or install folder contains diagnose_agent.py.
    pause
)

