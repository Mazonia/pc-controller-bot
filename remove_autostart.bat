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
    set "TARGET_BAT=%~f0"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList @('/k', 'call', ('\"' + $env:TARGET_BAT + '\"')) -Verb RunAs" >nul 2>&1
    exit /b
)

:: 2. Remove Task Scheduler Tasks
echo [1/3] Removing Windows Task Scheduler tasks...
schtasks /delete /tn "PC-Sentinel-Commander" /f >nul 2>&1
schtasks /delete /tn "PC-Sentinel-Agent" /f >nul 2>&1
echo     [+] Task Scheduler tasks removed.

:: 3. Remove Startup Folder Shortcuts
echo [2/3] Removing Windows Startup folder shortcuts...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_DIR%\PC-Sentinel-Commander.lnk" del /f /q "%STARTUP_DIR%\PC-Sentinel-Commander.lnk" >nul 2>&1
if exist "%STARTUP_DIR%\PC-Sentinel-Agent.lnk" del /f /q "%STARTUP_DIR%\PC-Sentinel-Agent.lnk" >nul 2>&1
echo     [+] Startup shortcuts deleted.

:: 4. Remove Registry Run Entries
echo [3/3] Removing CurrentUser Run registry entries...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PC-Sentinel-Commander" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PC-Sentinel-Agent" /f >nul 2>&1
echo     [+] Registry Run entries deleted.

:: 5. Option to stop running processes
echo.
set /p STOP_NOW="Do you want to stop any currently running Sentinel processes? (Y/N): "
if /i "%STOP_NOW%"=="Y" (
    taskkill /f /im pc-sentinel.exe >nul 2>&1
    taskkill /f /im pc-sentinel-agent.exe >nul 2>&1
    echo [+] Sentinel processes stopped.
)

echo.
echo =======================================================
echo    SUCCESS! Auto-start has been completely disabled.
echo =======================================================
echo.
pause
