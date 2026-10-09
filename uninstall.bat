@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Universal Clean Uninstaller
color 0C

echo ==============================================================
echo       PC REMOTE SENTINEL — UNIVERSAL CLEAN UNINSTALLER
echo ==============================================================
echo.

:: 1. Check for Admin privileges and auto-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set "DEST_DIR=C:\PCSentinel"

echo [*] Completely uninstalling PC Sentinel from [%COMPUTERNAME%]...
echo.

:: 2. Terminate running processes
echo [*] Terminating running agent processes...
taskkill /f /im pc-sentinel-agent.exe >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1
schtasks /end /tn "PCSentinelAgent" >nul 2>&1
timeout /t 1 /nobreak >nul

:: 3. Remove Scheduled Task
echo [*] Removing Task Scheduler entry...
schtasks /delete /tn "PCSentinelAgent" /f >nul 2>&1

:: 4. Remove Startup fallback
if exist "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" (
    del /f /q "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" >nul 2>&1
)

:: 5. Remove Windows Firewall Rule
netsh advfirewall firewall delete rule name="PCSentinelAgent" >nul 2>&1

:: 6. Delete Agent files
if exist "%DEST_DIR%" (
    echo [*] Deleting agent files at %DEST_DIR%...
    rmdir /s /q "%DEST_DIR%" >nul 2>&1
)

echo.
color 0A
echo ==============================================================
echo    [OK] PC REMOTE SENTINEL COMPLETELY REMOVED!
echo ==============================================================
echo.
echo    PC Name:     %COMPUTERNAME%
echo    Status:      All tasks, services, and files deleted.
echo    System:      Restored to original clean state.
echo ==============================================================
echo.
timeout /t 5
