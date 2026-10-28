@echo off
setlocal enabledelayedexpansion
title PC Remote Sentinel - Fleet Synchronizer
cd /d "%~dp0"
color 0B

echo ==============================================================
echo       PC REMOTE SENTINEL — FLEET SYNCHRONIZER
echo ==============================================================
echo.
echo   This tool imports newly installed PCs from your connected
echo   USB / SSD drive into your master Telegram Bot fleet list.
echo.
echo ==============================================================
echo.

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

echo [*] Using Python: %PY_CMD%
echo [*] Scanning for connected drives containing fleet.json...

"%PY_CMD%" -c "
import json
import os
import sys
from pathlib import Path

host_fleet_path = Path(r'%~dp0fleet.json')
if not host_fleet_path.exists():
    host_fleet = {'secret': 'sentinel-fleet-secret-2026', 'pcs': []}
else:
    try:
        host_fleet = json.loads(host_fleet_path.read_text(encoding='utf-8'))
    except Exception:
        host_fleet = {'secret': 'sentinel-fleet-secret-2026', 'pcs': []}

existing_names = {p['name']: p for p in host_fleet.get('pcs', [])}
added_count = 0

# Check all drive letters D: through Z:
for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ':
    drive_fleet = Path(f'{letter}:/fleet.json')
    if drive_fleet.exists() and drive_fleet.resolve() != host_fleet_path.resolve():
        try:
            data = json.loads(drive_fleet.read_text(encoding='utf-8'))
            for pc in data.get('pcs', []):
                name = pc.get('name')
                if name and name not in existing_names:
                    host_fleet.setdefault('pcs', []).append(pc)
                    existing_names[name] = pc
                    added_count += 1
                    print(f'   [+] Discovered new PC from Drive {letter}: -> {name} ({pc.get(\"ip\")})')
        except Exception as e:
            pass

if added_count > 0:
    host_fleet_path.write_text(json.dumps(host_fleet, indent=4), encoding='utf-8')
    print(f'\n[OK] Successfully synchronized {added_count} new PC(s) to master fleet!')
else:
    print('\n[*] Master fleet is already up-to-date with all connected drives.')

print(f'\n--- Current Master Fleet ({len(host_fleet.get(\"pcs\", []))} PCs) ---')
for idx, pc in enumerate(host_fleet.get('pcs', []), 1):
    print(f'  {idx}. {pc.get(\"name\")} [{pc.get(\"label\", \"\")} ] - {pc.get(\"ip\", \"Unknown\")} ({pc.get(\"network\", \"LAN\")})')
"

echo.
color 0A
echo ==============================================================
echo    [OK] Fleet synchronization complete!
echo    Your Telegram Bot has automatically reloaded the PC list.
echo ==============================================================
echo.
pause
