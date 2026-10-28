@echo off
setlocal enabledelayedexpansion
title PC-Sentinel-Agent
cd /d "%~dp0"

set "PY_CMD="

:: Priority 0: Exact Python executable saved during installation
if exist "%~dp0python_path.txt" (
    set /p SAVED_PY=<"%~dp0python_path.txt"
    if exist "!SAVED_PY!" (
        "!SAVED_PY!" -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY_CMD=!SAVED_PY!"
            goto :found_py
        )
    )
)

:: Priority 0.5: Check dedicated Sentinel Python directory
if exist "%~dp0Python\python.exe" (
    "%~dp0Python\python.exe" -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY_CMD=%~dp0Python\python.exe"
        goto :found_py
    )
)

:: Priority 1: Use dedicated named binary if present and functional in directory
if exist "%~dp0pc-sentinel-agent.exe" (
    "%~dp0pc-sentinel-agent.exe" -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY_CMD=%~dp0pc-sentinel-agent.exe"
        goto :found_py
    )
)

:: Check direct python
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CANDIDATE=%%i"
    if exist "!CANDIDATE!" (
        echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
        if errorlevel 1 set "PY_CMD=!CANDIDATE!"
    )
)
if defined PY_CMD goto :found_py

:: Check py launcher
if not defined PY_CMD (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" set "PY_CMD=!CANDIDATE!"
    )
)
if defined PY_CMD goto :found_py

:: Check common paths
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
        "C:\Python310\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    ) do (
        if not defined PY_CMD (
            if exist %%p set "PY_CMD=%%~p"
        )
    )
)
if defined PY_CMD goto :found_py

set "PY_CMD=python"
 
:found_py
:run_loop
echo [%DATE% %TIME%] Starting Agent using: %PY_CMD% >> "%~dp0agent_boot.log"
"%PY_CMD%" "%~dp0agent.py" >> "%~dp0agent_boot.log" 2>&1
echo [%DATE% %TIME%] Agent exited with code %errorlevel%. Restarting in 3s... >> "%~dp0agent_boot.log"
timeout /t 3 /nobreak >nul
goto :run_loop
