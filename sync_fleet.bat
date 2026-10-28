@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Fleet Synchronizer
cd /d "%~dp0"
color 0B

set "PY_CMD="
if exist "%~dp0python_path.txt" (
    set /p SAVED_PY=<"%~dp0python_path.txt"
    if exist "!SAVED_PY!" set "PY_CMD=!SAVED_PY!"
)
if not defined PY_CMD (
    for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" set "PY_CMD=!CANDIDATE!"
    )
)
if not defined PY_CMD (
    for %%p in (
        "C:\Program Files\Python314\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
    ) do (
        if not defined PY_CMD if exist %%p set "PY_CMD=%%~p"
    )
)
if not defined PY_CMD set "PY_CMD=python"

"%PY_CMD%" "%~dp0sync_fleet.py"

echo.
pause
