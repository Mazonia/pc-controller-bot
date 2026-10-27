import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from system_controller import SystemController
import agent
from agent import app, handle_relay_command


client = TestClient(app)


def test_system_controller_cursor_and_mouse():
    pos = SystemController.get_cursor_pos()
    assert "x" in pos
    assert "y" in pos
    assert "screen_w" in pos
    assert "screen_h" in pos
    assert pos["screen_w"] > 0
    assert pos["screen_h"] > 0


def test_system_controller_type_and_press():
    with patch("ctypes.windll.user32.SendInput") as mock_send:
        ok, msg = SystemController.type_text("Hello World!")
        assert ok is True
        assert "12 characters" in msg

    with patch("ctypes.windll.user32.keybd_event") as mock_keybd:
        ok, msg = SystemController.press_key("enter")
        assert ok is True
        assert "enter" in msg.lower()

        ok, msg = SystemController.press_key("ctrl+v")
        assert ok is True
        assert "ctrl+v" in msg.lower()


def test_relay_command_mouse_and_keyboard():
    with patch("system_controller.SystemController.mouse_move", return_value=True):
        res = handle_relay_command({"cmd": "mouse_input", "params": {"action": "move", "dx": 10, "dy": -5}})
        assert res["ok"] is True
        assert "cursor" in res

    with patch("system_controller.SystemController.type_text", return_value=(True, "Typed")):
        res = handle_relay_command({"cmd": "type_text", "params": {"text": "Test"}})
        assert res["ok"] is True

    with patch("system_controller.SystemController.press_key", return_value=(True, "Key pressed")):
        res = handle_relay_command({"cmd": "press_key", "params": {"key": "tab"}})
        assert res["ok"] is True


def test_fastapi_input_endpoints():
    with patch("system_controller.SystemController.mouse_move", return_value=True):
        resp = client.post("/input/mouse", json={"action": "move", "dx": 5, "dy": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "cursor" in data

    with patch("system_controller.SystemController.type_text", return_value=(True, "Typed")):
        resp = client.post("/input/type", json={"text": "Hello"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    with patch("system_controller.SystemController.press_key", return_value=(True, "Pressed")):
        resp = client.post("/input/key", json={"key": "esc"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    resp = client.get("/input/cursor")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_fastapi_float_and_get_endpoints():
    with patch("system_controller.SystemController.mouse_move", return_value=True) as mock_move:
        # POST with float strings
        resp = client.post("/input/mouse", json={"action": "move", "dx": "14.6", "dy": "-8.2"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_move.assert_called_with(15, -8)

        # GET with query params
        resp = client.get("/input/mouse?action=move&dx=5.1&dy=-2.9")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    with patch("system_controller.SystemController.type_text", return_value=(True, "Typed")) as mock_type:
        resp = client.get("/input/type?text=Hello+World")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_type.assert_called_with("Hello World")

    with patch("system_controller.SystemController.press_key", return_value=(True, "Pressed")) as mock_key:
        resp = client.get("/input/key?key=enter")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_key.assert_called_with("enter")


def test_type_text_fallback_when_sendinput_fails():
    with patch("ctypes.windll.user32.SendInput", return_value=0) as mock_send, \
         patch("ctypes.windll.user32.keybd_event") as mock_keybd:
        ok, msg = SystemController.type_text("A")
        assert ok is True
        # keybd_event should have been called as fallback
        assert mock_keybd.called

