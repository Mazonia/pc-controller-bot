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

echo Starting PC Sentinel Agent as [pc-sentinel-agent.exe]...
pc-sentinel-agent.exe agent.py
if errorlevel 1 (
    echo [!] Agent exited with error code %errorlevel%.
    timeout /t 5 >nul
)
