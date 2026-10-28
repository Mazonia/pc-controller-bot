@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - 1-Click Fast Installer
color 0B
cd /d "%~dp0"

echo ==============================================================
echo       PC REMOTE SENTINEL — 1-CLICK INSTANT PC INSTALLER
echo ==============================================================
echo.
echo   This installer sets up the PC Sentinel agent silently
echo   in the background and connects this PC directly to your
echo   Telegram Bot.
echo.
echo ==============================================================
echo.

:: 1. Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Administrator privileges required for background service setup.
    echo [*] Requesting Administrator privileges (please click YES on the Windows prompt)...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -WorkingDirectory '%~dp0' -ArgumentList '/k install.bat' -Verb RunAs" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Elevated Administrator installation window launched!
        echo [*] Installation is running in the new window.
        timeout /t 3 /nobreak >nul
        exit /b 0
    )
    
    :: Fallback to VBScript elevation if PowerShell was blocked
    echo Set UAC = CreateObject^("Shell.Application"^) > "%TEMP%\sentinel_elevate.vbs"
    echo UAC.ShellExecute "cmd.exe", "/k cd /d """"%~dp0"""" ^&^& install.bat", "", "runas", 1 >> "%TEMP%\sentinel_elevate.vbs"
    cscript //nologo "%TEMP%\sentinel_elevate.vbs" >nul 2>&1
    set "VBS_ERR=!errorlevel!"
    del /f /q "%TEMP%\sentinel_elevate.vbs" >nul 2>&1
    if !VBS_ERR! equ 0 (
        echo [OK] Elevated Administrator installation window launched!
        echo [*] Installation is running in the new window.
        timeout /t 3 /nobreak >nul
        exit /b 0
    )
    
    color 0C
    echo ==============================================================
    echo  [!] ADMINISTRATOR PRIVILEGES REQUIRED
    echo ==============================================================
    echo.
    echo  Automatic elevation was blocked by Windows.
    echo.
    echo  PLEASE DO THIS:
    echo    1. Right-click '1-CLICK-INSTALL.bat' (or 'install.bat')
    echo    2. Select 'Run as administrator'
    echo.
    echo ==============================================================
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

:: Already admin, run install.bat directly
call "%~dp0install.bat"
exit /b %errorlevel%


