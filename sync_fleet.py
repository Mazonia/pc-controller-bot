#!/usr/bin/env python3
"""
PC Remote Sentinel — Fleet Synchronization Tool
Scans all connected drives (USB flash drives, external SSDs) for fleet.json
and merges newly registered PCs into the master fleet configuration.
"""

import os
import sys
import json
from pathlib import Path


def get_master_fleet_path() -> Path:
    # Check current directory, then parent directory, then standard path
    candidates = [
        Path(__file__).resolve().parent / "fleet.json",
        Path.cwd() / "fleet.json",
        Path(r"c:\Users\Mazonia\Desktop\My Bots\PC-Remote-Sentinel\fleet.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def load_fleet(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"secret": "sentinel-fleet-secret-2026", "pcs": []}


def save_fleet(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def main():
    print("=" * 62)
    print("      PC REMOTE SENTINEL — FLEET SYNCHRONIZER")
    print("=" * 62)
    print()

    master_path = get_master_fleet_path()
    print(f"[*] Master Fleet File: {master_path}")
    master_fleet = load_fleet(master_path)

    existing_names = {p["name"]: p for p in master_fleet.get("pcs", []) if "name" in p}
    print(f"[*] Currently registered PCs in Master Bot: {len(existing_names)}")
    for p in existing_names.values():
        print(f"    - {p.get('name')} [{p.get('label', '')}] ({p.get('network', 'LAN')})")

    print("\n[*] Scanning connected drives (D: to Z:) for new PC registrations...")
    discovered = []

    # Check root of drives and subdirectories
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        candidates = [
            Path(f"{letter}:/fleet.json"),
            Path(f"{letter}:/PC-Sentinel-SSD-Installer/fleet.json"),
            Path(f"{letter}:/PCSentinel/fleet.json"),
        ]
        for cp in candidates:
            if cp.exists() and cp.resolve() != master_path.resolve():
                try:
                    drive_data = json.loads(cp.read_text(encoding="utf-8"))
                    for pc in drive_data.get("pcs", []):
                        name = pc.get("name")
                        if name and name not in existing_names:
                            discovered.append((pc, str(cp)))
                            existing_names[name] = pc
                except Exception as e:
                    print(f"    [!] Error reading {cp}: {e}")

    if discovered:
        for pc, source in discovered:
            master_fleet.setdefault("pcs", []).append(pc)
            print(f"    [+] Discovered new PC from {source}: {pc.get('name')} (IP: {pc.get('ip')})")
        save_fleet(master_path, master_fleet)
        print(f"\n[OK] Successfully synchronized {len(discovered)} new PC(s) to master fleet!")
    else:
        print("    [i] No new PCs found automatically on connected external drives.")

    # Interactive Quick-Add Fallback
    print("\n" + "-" * 62)
    print("QUICK MANUAL PC REGISTRATION:")
    print("If you know the PC Name of the new device you installed on,")
    print("you can register it directly right now.")
    print("-" * 62)

    try:
        pc_input = input("Enter new PC name (or press ENTER to finish): ").strip()
        if pc_input:
            if pc_input in existing_names:
                print(f"[!] PC '{pc_input}' is already in your fleet list.")
            else:
                ip_input = input(f"Enter IP for '{pc_input}' [leave blank for Auto/Relay]: ").strip() or "127.0.0.1"
                label_input = input(f"Enter custom label/nickname [leave blank for '{pc_input}']: ").strip() or pc_input
                new_pc = {
                    "name": pc_input,
                    "label": label_input,
                    "ip": ip_input,
                    "network": "Cloud Relay" if ip_input in ("127.0.0.1", "Remote") else f"LAN ({ip_input})",
                }
                master_fleet.setdefault("pcs", []).append(new_pc)
                save_fleet(master_path, master_fleet)
                print(f"\n[OK] Added '{pc_input}' ({label_input}) to Master Fleet!")
    except (KeyboardInterrupt, EOFError):
        pass

    # Print final fleet summary
    print("\n" + "=" * 62)
    print("CURRENT MASTER FLEET:")
    print("=" * 62)
    current_fleet = load_fleet(master_path)
    for idx, pc in enumerate(current_fleet.get("pcs", []), 1):
        print(f"  {idx}. {pc.get('name')} | Label: {pc.get('label')} | IP: {pc.get('ip')} | {pc.get('network', 'LAN')}")

    print("=" * 62)
    print("Your Telegram Bot has reloaded the fleet list.")
    print("Open Telegram and send /pcs to view and switch between your PCs.")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    main()
