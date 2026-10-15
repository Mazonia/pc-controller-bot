@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Network Fleet Deployer
cd /d "%~dp0"

echo ==============================================================
echo       PC REMOTE SENTINEL - NETWORK FLEET DEPLOYER
echo ==============================================================
echo.
echo   Starting the network deployment server...
echo   This will let you deploy to all PCs over WiFi.
echo.

:: Auto-elevate to admin (needed for firewall rules)
net session >nul 2>&1
if %errorlevel% neq 0 (
    if "%~1"=="--no-elevate" (
        echo [!] Running without administrator privileges.
        echo     [Windows firewall may prompt to allow network access]
    ) else (
        echo [!] Requesting Administrator privileges for firewall rules...
        powershell -Command "Start-Process cmd.exe -ArgumentList '/k cd /d \"\"%~dp0\"\" && \"\"%~f0\"\" --elevated' -Verb RunAs" 2>nul
        if %errorlevel% equ 0 exit /b
        echo [!] Elevation bypassed. Continuing in current window...
    )
)

:: Find working Python - try multiple reliable methods
set "PY_CMD="

:: Method 1: Direct python command execution check
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CANDIDATE=%%i"
    if exist "!CANDIDATE!" (
        echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
        if errorlevel 1 (
            set "PY_CMD=!CANDIDATE!"
        )
    )
)
if defined PY_CMD goto :py_found

:: Method 2: Check py launcher
if not defined PY_CMD (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" (
            set "PY_CMD=!CANDIDATE!"
        )
    )
)
if defined PY_CMD goto :py_found

:: Method 3: Check standard Python install directories
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
            if exist %%p (
                %%p -c "import sys" >nul 2>&1
                if !errorlevel! equ 0 (
                    set "PY_CMD=%%~p"
                )
            )
        )
    )
)
if defined PY_CMD goto :py_found

:: Method 4: PowerShell command query
if not defined PY_CMD (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Command python -ErrorAction SilentlyContinue).Source" 2^>nul') do (
        set "CANDIDATE=%%i"
        if exist "!CANDIDATE!" (
            echo !CANDIDATE! | findstr /i "WindowsApps" >nul 2>&1
            if errorlevel 1 (
                set "PY_CMD=!CANDIDATE!"
            )
        )
    )
)
if defined PY_CMD goto :py_found

:: Method 5: Windows Registry lookup
if not defined PY_CMD (
    for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\Python\PythonCore" /s /v ExecutablePath 2^>nul ^| findstr /i "ExecutablePath"') do (
        if not defined PY_CMD (
            if exist "%%b" set "PY_CMD=%%b"
        )
    )
    for /f "tokens=2*" %%a in ('reg query "HKCU\SOFTWARE\Python\PythonCore" /s /v ExecutablePath 2^>nul ^| findstr /i "ExecutablePath"') do (
        if not defined PY_CMD (
            if exist "%%b" set "PY_CMD=%%b"
        )
    )
)
if defined PY_CMD goto :py_found

:: If all methods failed
echo.
echo [X] Python not found! Please install Python first.
echo     Download from: https://www.python.org/downloads/
echo.
pause
exit /b 1

:py_found
echo [OK] Using Python: %PY_CMD%
echo.

:: Allow deployer through firewall (if running as admin)
net session >nul 2>&1
if %errorlevel% equ 0 (
    netsh advfirewall firewall delete rule name="PCSentinelDeployer" >nul 2>&1
    netsh advfirewall firewall add rule name="PCSentinelDeployer" dir=in action=allow protocol=TCP localport=9090 enable=yes profile=any >nul 2>&1
)

:: Run the deployer
"%PY_CMD%" "%~dp0network_deployer.py"
pause
