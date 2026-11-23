import io
import zipfile
import base64
import shutil
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from system_controller import SystemController
import agent
import bot


def test_battery_status():
    """Verify battery level and status string parsing."""
    status = SystemController.get_battery_status()
    assert isinstance(status, dict)
    assert "has_battery" in status
    assert "percent" in status
    assert "power_plugged" in status
    assert "status_str" in status


def test_battery_status_desktop_no_battery():
    """Verify battery reporting on desktop systems without battery."""
    with patch("psutil.sensors_battery", return_value=None):
        st = SystemController.get_battery_status()
        assert st["has_battery"] is False
        assert st["percent"] == 100
        assert "No Battery" in st["status_str"]


def test_wifi_details():
    """Verify Wi-Fi interface and nearby network extraction."""
    wifi = SystemController.get_wifi_details()
    assert isinstance(wifi, dict)
    assert "connected" in wifi
    assert "ssid" in wifi
    assert "bssid" in wifi
    assert "visible_networks" in wifi
    assert isinstance(wifi["visible_networks"], list)


def test_geolocation_mocked():
    """Verify geolocation parsing with mocked API response."""
    mock_payload = {
        "status": "success",
        "country": "Ghana",
        "countryCode": "GH",
        "regionName": "Greater Accra Region",
        "city": "Accra",
        "lat": 5.6037,
        "lon": -0.1869,
        "isp": "Starlink",
        "query": "102.176.65.10",
    }
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload
        mock_get.return_value = mock_resp

        geo = SystemController.get_geolocation()
        assert geo["ok"] is True
        assert geo["city"] == "Accra"
        assert geo["country"] == "Ghana"
        assert geo["lat"] == 5.6037
        assert "maps.google.com" in geo["google_maps"] or "google.com/maps" in geo["google_maps"]


def test_geolocation_offline_fallback():
    """Verify geolocation handles complete network loss gracefully."""
    with patch("httpx.get", side_effect=Exception("Network Unreachable")):
        geo = SystemController.get_geolocation()
        assert geo["ok"] is False
        assert geo["lat"] == 0.0
        assert geo["lon"] == 0.0
        assert "offline" in geo.get("error", "").lower() or "error" in geo


def test_tracking_dossier():
    """Verify complete tracking dossier structure."""
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "city": "Kumasi",
            "country": "Ghana",
            "lat": 6.6885,
            "lon": -1.6244,
            "query": "1.1.1.1",
        }
        mock_get.return_value = mock_resp

        dossier = SystemController.get_tracking_info()
        assert dossier["ok"] is True
        assert "hostname" in dossier
        assert "user" in dossier
        assert "battery" in dossier
        assert "wifi" in dossier
        assert "geo" in dossier
        assert "session_state" in dossier


def test_tracking_dossier_exception_safe():
    """Verify tracking dossier never crashes on internal errors."""
    with patch.object(SystemController, "get_battery_status", side_effect=RuntimeError("Sensor error")):
        dossier = SystemController.get_tracking_info()
        assert isinstance(dossier, dict)
        assert dossier["ok"] is False
        assert "Sensor error" in dossier.get("error", "")


def test_agent_relay_tracking_command():
    """Verify agent handles tracking command over relay."""
    with patch.object(SystemController, "get_tracking_info", return_value={"ok": True, "fake": "data"}):
        res = agent.handle_relay_command({"cmd": "tracking", "params": {}})
        assert res["ok"] is True
        assert "tracking" in res
        assert res["tracking"]["fake"] == "data"


def test_agent_relay_lockdown_lifecycle():
    """Verify lockdown enable, status, and disable transitions."""
    with patch.object(SystemController, "lock_workstation", return_value=True), \
         patch.object(SystemController, "turn_off_monitors", return_value=True), \
         patch.object(SystemController, "turn_on_monitors", return_value=True), \
         patch.object(SystemController, "take_webcam_photo", return_value=(True, "ok")), \
         patch.object(SystemController, "play_alert_siren", return_value=None), \
         patch.object(SystemController, "stop_alarm", return_value=True):

        # 1. Enable lockdown
        enable_res = agent.handle_relay_command({
            "cmd": "lockdown_enable",
            "params": {"silent": False, "alarm": True}
        })
        assert enable_res["ok"] is True
        assert enable_res["active"] is True
        assert agent.LOCKDOWN_ACTIVE is True

        # 2. Check status
        status_res = agent.handle_relay_command({"cmd": "lockdown_status", "params": {}})
        assert status_res["ok"] is True
        assert status_res["active"] is True

        # 3. Disable lockdown
        disable_res = agent.handle_relay_command({"cmd": "lockdown_disable", "params": {}})
        assert disable_res["ok"] is True
        assert disable_res["active"] is False
        assert agent.LOCKDOWN_ACTIVE is False


def test_lockdown_guard_auto_relock_on_breach():
    """Verify guard worker re-locks screen and captures evidence when desktop is unlocked."""
    agent.LOCKDOWN_ACTIVE = True
    agent._lockdown_stop_event.clear()

    mock_lock = MagicMock(return_value=True)
    mock_monitors = MagicMock(return_value=True)
    mock_photo = MagicMock(return_value=(True, "ok"))

    # Session state begins unlocked, then we trigger stop event
    states = ["Interactive Desktop (Unlocked) 🟢", "Windows Login / Lock Screen 🔒"]

    def fake_session():
        if states:
            val = states.pop(0)
            if not states:
                # Stop after processing breach
                agent.LOCKDOWN_ACTIVE = False
                agent._lockdown_stop_event.set()
            return val
        return "Windows Login / Lock Screen 🔒"

    with patch.object(SystemController, "get_session_state", side_effect=fake_session), \
         patch.object(SystemController, "lock_workstation", mock_lock), \
         patch.object(SystemController, "turn_off_monitors", mock_monitors), \
         patch.object(SystemController, "take_webcam_photo", mock_photo):

        # Run one iteration of worker directly
        agent._lockdown_guard_worker(chat_id=None)

        assert mock_lock.called
        assert mock_monitors.called


def test_agent_ota_update_success(tmp_path):
    """Verify OTA update validates syntax, extracts files, and prepares restart."""
    code = "def sample():\n    return 42\n"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test_module.py", code)
    b64_zip = base64.b64encode(zip_buf.getvalue()).decode("ascii")

    with patch("agent.BASE_DIR", tmp_path), \
         patch("subprocess.Popen") as mock_popen, \
         patch("threading.Thread") as mock_thread:

        res = agent.apply_agent_update(zip_b64=b64_zip)
        assert res["ok"] is True
        assert "test_module.py" in res["updated_files"]
        assert (tmp_path / "test_module.py").exists()
        assert (tmp_path / "test_module.py").read_text() == code


def test_agent_ota_update_with_files_dict(tmp_path):
    """Verify OTA update handles individual files dict payload."""
    code = "MESSAGE = 'hello from update'\n"
    b64_code = base64.b64encode(code.encode("utf-8")).decode("ascii")

    with patch("agent.BASE_DIR", tmp_path), \
         patch("subprocess.Popen"), \
         patch("threading.Thread"):

        res = agent.apply_agent_update(files_dict={"custom.py": b64_code})
        assert res["ok"] is True
        assert "custom.py" in res["updated_files"]
        assert (tmp_path / "custom.py").exists()
        assert (tmp_path / "custom.py").read_text() == code


def test_agent_ota_update_empty_payload(tmp_path):
    """Verify OTA update rejects empty package gracefully."""
    with patch("agent.BASE_DIR", tmp_path):
        res = agent.apply_agent_update(zip_b64=None, files_dict=None)
        assert res["ok"] is False
        assert "No update package" in res["error"]


def test_agent_ota_update_syntax_error_rejected(tmp_path):
    """Verify OTA update rejects syntax errors before overwriting existing files."""
    existing_file = tmp_path / "sample.py"
    existing_file.write_text("# Original valid code\n")

    invalid_code = "def bad_syntax(:\n    pass"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("sample.py", invalid_code)
    b64_zip = base64.b64encode(zip_buf.getvalue()).decode("ascii")

    with patch("agent.BASE_DIR", tmp_path):
        res = agent.apply_agent_update(zip_b64=b64_zip)
        assert res["ok"] is False
        assert "Syntax error" in res["error"]
        assert existing_file.read_text() == "# Original valid code\n"


def test_bot_create_update_bundle():
    """Verify bot packages core agent files into a valid non-empty zip bundle."""
    bundle_bytes, packaged = bot.create_agent_update_bundle()
    assert isinstance(bundle_bytes, bytes)
    assert len(bundle_bytes) > 1000
    assert "agent.py" in packaged
    assert "system_controller.py" in packaged

    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as zf:
        names = zf.namelist()
        assert "agent.py" in names
        assert "system_controller.py" in names


def test_bot_keyboards():
    """Verify main keyboard and lockdown keyboards have the expected interactive buttons."""
    main_kb = bot.get_main_keyboard()
    button_callbacks = [btn.callback_data for row in main_kb.inline_keyboard for btn in row]
    assert "cb_track" in button_callbacks
    assert "cb_lockdown_menu" in button_callbacks
    assert "cb_update_agent" in button_callbacks

    lockdown_inactive_kb = bot.get_lockdown_keyboard(is_active=False)
    inact_callbacks = [btn.callback_data for row in lockdown_inactive_kb.inline_keyboard for btn in row]
    assert "cb_lockdown_loud" in inact_callbacks
    assert "cb_lockdown_silent" in inact_callbacks

    lockdown_active_kb = bot.get_lockdown_keyboard(is_active=True)
    act_callbacks = [btn.callback_data for row in lockdown_active_kb.inline_keyboard for btn in row]
    assert "cb_lockdown_disarm" in act_callbacks


@pytest.mark.anyio
async def test_bot_agent_client_local_methods():
    """Verify AgentClient tracking, lockdown, and update methods work cleanly."""
    pc_data = {"name": "Test-PC", "ip": "127.0.0.1", "port": 9010, "is_host": True}
    client = bot.AgentClient(pc_data, secret="test-secret")

    # Mock _get and _post
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {"ok": True, "tracking": {"city": "Accra"}, "active": True}

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"ok": True, "active": True}

    with patch.object(client, "_get", new=AsyncMock(return_value=mock_get_resp)), \
         patch.object(client, "_post", new=AsyncMock(return_value=mock_post_resp)):

        tracking = await client.get_tracking()
        assert tracking.get("city") == "Accra"

        lock_res = await client.lockdown_enable(silent=False, alarm=True)
        assert lock_res["ok"] is True

        disarm_res = await client.lockdown_disable()
        assert disarm_res["ok"] is True

        status_res = await client.lockdown_status()
        assert status_res["ok"] is True
