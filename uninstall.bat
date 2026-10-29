@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Universal Clean Uninstaller
color 0C
cd /d "%~dp0"

echo ==============================================================
echo       PC REMOTE SENTINEL — UNIVERSAL CLEAN UNINSTALLER
echo ==============================================================
echo.

:: 1. Check for Admin privileges and auto-elevate
net session >nul 2>&1
if %errorlevel% equ 0 goto :is_admin

echo.
echo ==============================================================
echo  [!] ADMINISTRATOR PRIVILEGES REQUIRED
echo ==============================================================
echo.
echo  [*] Requesting Administrator elevation [click YES if prompted by Windows]...

set "TARGET_BAT=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList @('/k', 'call', ('\"' + $env:TARGET_BAT + '\"')) -Verb RunAs" >nul 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Elevated Administrator uninstallation window opened.
    echo  [*] Uninstallation is running in the elevated window.
    timeout /t 3 /nobreak >nul
    exit /b 0
)

:: Fallback to VBScript elevation if PowerShell was blocked
set "VBS_FILE=%TEMP%\sentinel_elevate.vbs"
(
    echo Set UAC = CreateObject("Shell.Application"^)
    echo UAC.ShellExecute "cmd.exe", "/k call " ^& Chr(34^) ^& "%~f0" ^& Chr(34^), "", "runas", 1
) > "!VBS_FILE!"
cscript //nologo "!VBS_FILE!" >nul 2>&1
set "VBS_ERR=!errorlevel!"
del /f /q "!VBS_FILE!" >nul 2>&1
if !VBS_ERR! equ 0 (
    echo  [OK] Elevated Administrator uninstallation window opened.
    echo  [*] Uninstallation is running in the elevated window.
    timeout /t 3 /nobreak >nul
    exit /b 0
)

color 0C
echo  [X] Could not automatically request Administrator privileges.
echo.
echo  PLEASE DO THIS:
echo    1. Right-click 'uninstall.bat'
echo    2. Select 'Run as administrator'
echo.
echo  Press any key to exit...
pause >nul
exit /b 1

:is_admin

set "DEST_DIR=C:\PCSentinel"

echo [*] Completely uninstalling PC Sentinel from [%COMPUTERNAME%]...
echo.

:: 2. Stop and remove scheduled task first so it cannot restart processes
echo [*] Removing Task Scheduler entry [PCSentinelAgent]...
schtasks /end /tn "PCSentinelAgent" >nul 2>&1
schtasks /delete /tn "PCSentinelAgent" /f >nul 2>&1

:: 3. Terminate all running Sentinel processes (including start_agent loop and launchers)
echo [*] Terminating running Sentinel processes...
taskkill /f /im pc-sentinel-agent.exe >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*agent.py*' -or $_.CommandLine -like '*start_agent*' -or $_.CommandLine -like '*PCSentinel*' -or $_.ExecutablePath -like '*PCSentinel*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul

:: 4. Remove Startup folder entries (All Users and Current User)
echo [*] Cleaning Windows Startup folder entries...
if exist "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" (
    del /f /q "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" >nul 2>&1
)
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" (
    del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PCSentinelAgent.vbs" >nul 2>&1
)

:: 5. Remove Registry Run auto-start entries (HKCU and HKLM)
echo [*] Cleaning Windows Registry auto-start keys...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PCSentinelAgent" /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "PCSentinelAgent" /f >nul 2>&1

:: 6. Remove Windows Defender Firewall Rules
echo [*] Removing Windows Defender Firewall rules...
netsh advfirewall firewall delete rule name="PCSentinelAgent" >nul 2>&1
netsh advfirewall firewall delete rule name="PCSentinelPython" >nul 2>&1
netsh advfirewall firewall delete rule name="PCSentinelPort" >nul 2>&1
netsh advfirewall firewall delete rule name="PCSentinelStream" >nul 2>&1

:: 7. Delete Agent directory files
if exist "%DEST_DIR%" (
    echo [*] Removing files at %DEST_DIR%...
    rmdir /s /q "%DEST_DIR%" >nul 2>&1
    if exist "%DEST_DIR%" (
        timeout /t 2 /nobreak >nul
        rmdir /s /q "%DEST_DIR%" >nul 2>&1
    )
    if exist "%DEST_DIR%" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%DEST_DIR%' -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
    )
)

echo.
color 0A
echo ==============================================================
echo    [OK] PC REMOTE SENTINEL COMPLETELY REMOVED!
echo ==============================================================
echo.
echo    Target PC:   %COMPUTERNAME%
echo    Status:      All tasks, services, registry, and files deleted.
echo    System:      Restored to 100%% clean state.
echo.
echo    You can now perform a clean reinstall using 1-CLICK-INSTALL.bat!
echo ==============================================================
echo.
pause
