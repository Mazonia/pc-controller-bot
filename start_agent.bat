@echo off
title PC-Sentinel-Agent
cd /d "%~dp0"

echo ==============================================
echo     PC REMOTE SENTINEL AGENT — Starting
echo ==============================================
echo.

:: Create dedicated named executable so Task Manager shows 'pc-sentinel-agent.exe'
for /f "delims=" %%i in ('where python') do set PYTHON_BIN=%%i & goto :found_py
:found_py

if not exist pc-sentinel-agent.exe (
    copy "%PYTHON_BIN%" pc-sentinel-agent.exe >nul
)

:run_loop
echo [%TIME%] Starting PC Sentinel Agent as [pc-sentinel-agent.exe]...
pc-sentinel-agent.exe agent.py
echo [%TIME%] [!] Agent stopped (exit code %errorlevel%). Auto-restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto :run_loop
