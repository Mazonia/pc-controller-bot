import os
import sys
import py_compile
import json

installer_dir = r"C:\Users\Mazonia\Desktop\PC-Sentinel-SSD-Installer"
print(f"=== TESTING PORTABLE INSTALLER AT: {installer_dir} ===\n")

# 1. Check all required files exist
required_files = [
    "1-CLICK-INSTALL.bat",
    "install.bat",
    "uninstall.bat",
    "start_agent.bat",
    "start_agent_hidden.vbs",
    "agent.py",
    "fleet_relay.py",
    "system_controller.py",
    "screen_caster.py",
    "requirements_agent.txt",
    "deploy_config.env",
    "fleet.json",
    "python-installer.exe",
    "cloudflared.exe",
    "INSTRUCTIONS.txt"
]

print("[1] File Existence & Size Checks:")
all_exist = True
for f in required_files:
    p = os.path.join(installer_dir, f)
    if os.path.exists(p):
        sz = os.path.getsize(p)
        print(f"    [OK] {f:<25} ({sz:>10,} bytes)")
    else:
        print(f"    [FAIL] {f:<25} MISSING!")
        all_exist = False

assert all_exist, "Some required files are missing from the portable folder"

# 2. Syntax & Compilation check for all Python files in the portable folder
print("\n[2] Python Bytecode Compilation Checks:")
py_files = ["agent.py", "fleet_relay.py", "system_controller.py", "screen_caster.py"]
for pf in py_files:
    full_path = os.path.join(installer_dir, pf)
    py_compile.compile(full_path, doraise=True)
    print(f"    [OK] {pf:<25} compiled successfully with 0 syntax errors.")

# 3. Check Windows PE headers for bundled executables
print("\n[3] Windows Binary PE Header Checks:")
for exe in ["python-installer.exe", "cloudflared.exe"]:
    ep = os.path.join(installer_dir, exe)
    with open(ep, "rb") as f:
        header = f.read(2)
        assert header == b"MZ", f"{exe} is not a valid Windows executable (missing MZ signature)"
    print(f"    [OK] {exe:<25} valid MZ/PE executable header.")

# 4. Check deploy_config.env
print("\n[4] Configuration Checks:")
env_p = os.path.join(installer_dir, "deploy_config.env")
env_vars = {}
with open(env_p, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

for required_k in ["FLEET_SECRET", "TELEGRAM_BOT_TOKEN", "AUTHORIZED_USER_IDS", "MQTT_BROKER"]:
    assert required_k in env_vars and len(env_vars[required_k]) > 0, f"Missing {required_k}"
    print(f"    [OK] {required_k:<25} = {env_vars[required_k][:6]}... (Valid)")

# 5. Check fleet.json format
print("\n[5] Fleet Register (fleet.json) Checks:")
fj_p = os.path.join(installer_dir, "fleet.json")
with open(fj_p, "r", encoding="utf-8") as f:
    fj = json.load(f)
assert "pcs" in fj or "secret" in fj, "Invalid fleet.json structure"
print(f"    [OK] fleet.json is valid JSON with {len(fj.get('pcs', []))} pre-registered target PC(s).")

# 6. Test import sanity in python
print("\n[6] Module Import Sanity (Simulated Runtime):")
sys.path.insert(0, installer_dir)
import system_controller
import screen_caster
import fleet_relay
print("    [OK] system_controller, screen_caster, and fleet_relay imported cleanly.")

print("\n=== ALL PORTABLE INSTALLER TESTS PASSED WITH 100% SUCCESS! ===")
