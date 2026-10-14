import io
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest
import agent
from agent import send_photo_to_telegram, handle_relay_command


def test_send_photo_compression(tmp_path):
    # Create a large dummy PNG file
    png_path = tmp_path / "test_screenshot.png"
    img = Image.new("RGB", (1920, 1080), color="blue")
    img.save(png_path, "PNG")

    assert png_path.exists()
    original_size = png_path.stat().st_size

    with patch("agent.TELEGRAM_BOT_TOKEN", "fake_bot_token"):
        with patch("agent.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            # Perform send
            result = send_photo_to_telegram(chat_id=123456, photo_path=png_path, caption="Test")

            assert result is True
            assert mock_post.called

            # Check that post was called with photo file
            call_kwargs = mock_post.call_args[1]
            assert "files" in call_kwargs
            assert "photo" in call_kwargs["files"]


def test_send_photo_retry_on_network_failure(tmp_path):
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_path, "JPEG")

    with patch("agent.TELEGRAM_BOT_TOKEN", "fake_bot_token"):
        with patch("agent.time.sleep") as mock_sleep:
            with patch("agent.httpx.post") as mock_post:
                # Fail twice with exception, succeed on 3rd attempt
                mock_post.side_effect = [
                    Exception("Socket connection reset"),
                    Exception("Timeout connecting to api.telegram.org"),
                    MagicMock(status_code=200),
                ]

                result = send_photo_to_telegram(chat_id=123456, photo_path=img_path)
                assert result is True
                assert mock_post.call_count == 3
                assert mock_sleep.call_count == 2


def test_send_photo_failure_reporting(tmp_path):
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_path, "JPEG")

    with patch("agent.TELEGRAM_BOT_TOKEN", "fake_bot_token"):
        with patch("agent.time.sleep"):
            with patch("agent.httpx.post", side_effect=Exception("Network down")):
                result = send_photo_to_telegram(chat_id=123456, photo_path=img_path)
                assert result is False


def test_handle_relay_command_screenshot_upload_failure(tmp_path):
    def fake_take_screenshot(path):
        Path(path).write_bytes(b"dummy image data")
        return (True, "Captured")

    with patch("agent.SystemController.take_screenshot", side_effect=fake_take_screenshot):
        with patch("agent.RECORDINGS_DIR", tmp_path):
            with patch("agent.send_photo_to_telegram", return_value=False):
                # When send_photo_to_telegram fails, handle_relay_command must NOT return ok=True!
                res = handle_relay_command({
                    "cmd": "screenshot",
                    "params": {"chat_id": 99999},
                })
                assert res["ok"] is False
                assert "timed out" in res["error"].lower() or "unstable" in res["error"].lower()


def test_handle_relay_command_clean_scan():
    fake_candidates = [{"name": "old_recording.mp4", "size_bytes": 1048576}]
    with patch("agent.SystemController.scan_storage_candidates", return_value=fake_candidates):
        res = handle_relay_command({"cmd": "clean_scan", "params": {}})
        assert res["ok"] is True
        assert res["candidates"] == fake_candidates


def test_handle_relay_command_clean_execute():
    with patch("agent.SystemController.cleanup_old_files", return_value=(5, 5242880)):
        res = handle_relay_command({"cmd": "clean_execute", "params": {}})
        assert res["ok"] is True
        assert res["deleted_count"] == 5
        assert res["freed_bytes"] == 5242880


def test_handle_relay_command_play_audio(tmp_path):
    import base64
    audio_data = b"dummy_audio_bytes"
    b64_str = base64.b64encode(audio_data).decode("ascii")

    with patch("agent.DOWNLOADS_DIR", tmp_path):
        with patch("agent.SystemController.play_audio_file", return_value=(True, "Audio played")):
            res = handle_relay_command({
                "cmd": "play_audio",
                "params": {"filename": "test_voice.ogg", "data_b64": b64_str},
            })
            assert res["ok"] is True
            assert res["success"] is True
            assert (tmp_path / "test_voice.ogg").exists()
            assert (tmp_path / "test_voice.ogg").read_bytes() == audio_data


def test_api_play_audio(tmp_path):
    from fastapi.testclient import TestClient
    from agent import app

    client = TestClient(app)
    with patch("agent.DOWNLOADS_DIR", tmp_path):
        with patch("agent.SystemController.play_audio_file", return_value=(True, "Audio played")):
            files = {"file": ("voice_test.ogg", b"fake_voice_data", "audio/ogg")}
            response = client.post("/play-audio", files=files)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["ok"] is True
            assert (tmp_path / "voice_test.ogg").exists()

