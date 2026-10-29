#!/usr/bin/env python3
"""
PC Remote Sentinel — Target PC Registration Helper
Safely detects local network IP and appends target PC info to fleet.json on the installer drive.
"""

import sys
import json
import socket
from pathlib import Path


def get_local_ip() -> str:
    # Try multiple common DNS servers with short timeouts
    for target in [("8.8.8.8", 80), ("1.1.1.1", 80), ("192.168.1.1", 80), ("10.0.0.1", 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
    return "127.0.0.1"


def main():
    if len(sys.argv) < 3:
        print("Usage: register_target_pc.py <fleet_json_path> <pc_name>")
        return

    fleet_path = Path(sys.argv[1])
    pc_name = sys.argv[2].strip()

    if not pc_name:
        pc_name = socket.gethostname()

    local_ip = get_local_ip()
    network_type = f"LAN ({local_ip})" if local_ip != "127.0.0.1" else "Remote/Relay"

    if not fleet_path.exists():
        fleet_data = {"secret": "sentinel-fleet-secret-2026", "pcs": []}
    else:
        try:
            fleet_data = json.loads(fleet_path.read_text(encoding="utf-8"))
        except Exception:
            fleet_data = {"secret": "sentinel-fleet-secret-2026", "pcs": []}

    pcs = fleet_data.setdefault("pcs", [])

    # Check if already present
    existing = next((p for p in pcs if p.get("name") == pc_name), None)
    if existing:
        existing["ip"] = local_ip
        existing["port"] = 9010
        existing["network"] = network_type
    else:
        pcs.append({
            "name": pc_name,
            "label": pc_name,
            "ip": local_ip,
            "port": 9010,
            "network": network_type,
        })

    try:
        fleet_path.write_text(json.dumps(fleet_data, indent=4), encoding="utf-8")
        print(f"[OK] Successfully registered PC '{pc_name}' (IP: {local_ip}) into {fleet_path.name}")
    except Exception as e:
        print(f"[!] Note: Could not update {fleet_path.name} on drive: {e}")


if __name__ == "__main__":
    main()
