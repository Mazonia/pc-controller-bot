@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel — Stop Controller
cd /d "%~dp0"

color 0B
echo ==============================================================
echo            PC REMOTE SENTINEL — STOP CONTROLLER
echo ==============================================================
echo.

:: Parse command-line arguments
set "MODE=bot"
set "SILENT=0"
set "NO_PAUSE=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--all" set "MODE=all" & shift & goto :parse_args
if /i "%~1"=="-a" set "MODE=all" & shift & goto :parse_args
if /i "%~1"=="all" set "MODE=all" & shift & goto :parse_args
if /i "%~1"=="--agent" set "MODE=agent" & shift & goto :parse_args
if /i "%~1"=="--agent-only" set "MODE=agent" & shift & goto :parse_args
if /i "%~1"=="-agent" set "MODE=agent" & shift & goto :parse_args
if /i "%~1"=="agent" set "MODE=agent" & shift & goto :parse_args
if /i "%~1"=="--bot-only" set "MODE=bot_only" & shift & goto :parse_args
if /i "%~1"=="-b" set "MODE=bot_only" & shift & goto :parse_args
if /i "%~1"=="--silent" set "SILENT=1" & shift & goto :parse_args
if /i "%~1"=="-s" set "SILENT=1" & shift & goto :parse_args
if /i "%~1"=="--no-pause" set "NO_PAUSE=1" & shift & goto :parse_args
if /i "%~1"=="/q" set "NO_PAUSE=1" & shift & goto :parse_args
if /i "%~1"=="/silent" set "SILENT=1" & set "NO_PAUSE=1" & shift & goto :parse_args
shift
goto :parse_args
:args_done

:: -------------------------------------------------------------
:: STOP COMMANDER BOT (if mode is bot, bot_only, or all)
:: -------------------------------------------------------------
if /i "%MODE%"=="agent" goto :stop_agent_section

echo [*] Stopping PC Remote Sentinel Commander Bot...

:: 1. End Task Scheduler task instance if currently running
schtasks /end /tn "PC-Sentinel-Commander" >nul 2>&1

:: 2. Terminate runner loops (cmd.exe running run.bat) first so they do not auto-restart bot.py
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run.bat*') -and ($_.CommandLine -notlike '*stop*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 3. Terminate bot executables (pc-sentinel.exe and any python process running bot.py)
taskkill /f /im pc-sentinel.exe >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.CommandLine -like '*bot.py*') -and ($_.Name -notin @('powershell.exe', 'pwsh.exe')) -and ($_.CommandLine -notlike '*Get-CimInstance*') -and ($_.CommandLine -notlike '*Stop-Process*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 4. Verify bot processes are stopped
ping 127.0.0.1 -n 2 >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$rem = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'pc-sentinel.exe' -or $_.CommandLine -like '*bot.py*' -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run.bat*')) -and ($_.Name -notin @('powershell.exe', 'pwsh.exe')) -and ($_.CommandLine -notlike '*stop*') }; if ($rem) { exit 2 } else { exit 0 }"
set "CHECK_ERR=!errorlevel!"

:: If bot processes are still active (e.g. running under higher privileges), request elevation
if !CHECK_ERR! equ 2 (
    net session >nul 2>&1
    if !errorlevel! neq 0 (
        echo [!] Elevated privileges required to terminate active background process.
        echo [*] Requesting Administrator elevation...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList @('/c', 'call', ('\"' + '%~f0' + '\"'), '%*') -Verb RunAs" >nul 2>&1
        exit /b
    )
)

echo  [+] Commander Bot processes terminated.

:: -------------------------------------------------------------
:: AGENT HANDLING (if requested or detected)
:: -------------------------------------------------------------
:stop_agent_section

if /i "%MODE%"=="bot_only" goto :finish_summary

powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'pc-sentinel-agent.exe' -or $_.CommandLine -like '*agent.py*' -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*start_agent*')) -and ($_.Name -notin @('powershell.exe', 'pwsh.exe')) -and ($_.CommandLine -notlike '*stop*') }; if ($a) { exit 1 } else { exit 0 }"
set "AGENT_RUNNING=!errorlevel!"

if /i "%MODE%"=="all" goto :do_stop_agent
if /i "%MODE%"=="agent" goto :do_stop_agent

if !AGENT_RUNNING! equ 1 (
    if !SILENT! equ 0 (
        echo.
        echo [*] Note: Local Sentinel Agent [agent.py] is currently running in background.
        set /p STOP_AGENT_CHOICE="    Do you also want to stop the Local Agent? [Y/N, default=N]: "
        if /i "!STOP_AGENT_CHOICE!"=="Y" goto :do_stop_agent
        echo  [-] Local Agent left running.
        goto :finish_summary
    )
)
goto :finish_summary

:do_stop_agent
echo [*] Stopping PC Remote Sentinel Local Agent...
schtasks /end /tn "PC-Sentinel-Agent" >nul 2>&1
schtasks /end /tn "PCSentinelAgent" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*start_agent*') -and ($_.CommandLine -notlike '*stop*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /f /im pc-sentinel-agent.exe >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.CommandLine -like '*agent.py*') -and ($_.Name -notin @('powershell.exe', 'pwsh.exe')) -and ($_.CommandLine -notlike '*Get-CimInstance*') -and ($_.CommandLine -notlike '*Stop-Process*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo  [+] Local Agent processes terminated.

:: -------------------------------------------------------------
:: SUMMARY & CONFIRMATION
:: -------------------------------------------------------------
:finish_summary
echo.
color 0A
echo ==============================================================
echo    [OK] PC REMOTE SENTINEL HAS BEEN STOPPED SUCCESSFULLY!
echo ==============================================================
echo.
echo    Active processes have been terminated cleanly.
echo    Auto-restart loops (run.bat / start_agent.bat) are cleared.
echo.
echo    To start the bot again at any time:
echo      - Run 'run.bat' [terminal window]
echo      - Or run 'start_hidden.vbs' [silent background]
echo ==============================================================
echo.

if !NO_PAUSE! equ 0 (
    echo Press any key to exit...
    pause >nul
)
exit /b 0
