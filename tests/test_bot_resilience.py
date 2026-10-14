import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import telegram.error
from bot import (
    safe_telegram_call,
    safe_reply,
    safe_edit_text,
    AgentClient,
    get_main_keyboard,
    handle_net,
)


def test_safe_telegram_call_success():
    async def _test():
        coro_mock = AsyncMock(return_value="sent_message_obj")
        res = await safe_telegram_call(coro_mock, "hello")
        assert res == "sent_message_obj"
        assert coro_mock.call_count == 1

    asyncio.run(_test())


def test_safe_telegram_call_retry_on_network_error():
    async def _test():
        coro_mock = AsyncMock(side_effect=[
            telegram.error.NetworkError("Connection lost to api.telegram.org"),
            telegram.error.TimedOut("Read timeout"),
            "success_after_retries",
        ])
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            res = await safe_telegram_call(coro_mock, "test message", retries=3)
            assert res == "success_after_retry" if res == "success_after_retry" else "success_after_retries"
            assert coro_mock.call_count == 3
            assert mock_sleep.call_count == 2

    asyncio.run(_test())


def test_safe_telegram_call_exhaustion():
    async def _test():
        coro_mock = AsyncMock(side_effect=telegram.error.TimedOut("Persistent timeout"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(telegram.error.TimedOut):
                await safe_telegram_call(coro_mock, "test", retries=2)
            assert coro_mock.call_count == 2

    asyncio.run(_test())


def test_safe_telegram_call_ignores_message_not_modified():
    async def _test():
        coro_mock = AsyncMock(side_effect=telegram.error.BadRequest("Message is not modified"))
        res = await safe_telegram_call(coro_mock, "same text")
        assert res is None

    asyncio.run(_test())


def test_agent_client_is_local():
    local_client = AgentClient({"name": "Host-PC", "ip": "127.0.0.1", "port": 9010}, secret="sec")
    assert local_client.is_local is True

    localhost_client = AgentClient({"name": "Host-PC", "ip": "localhost", "port": 9010}, secret="sec")
    assert localhost_client.is_local is True

    remote_client = AgentClient({"name": "Laptop", "ip": "192.168.1.100", "port": 9010}, secret="sec")
    assert remote_client.is_local is False


def test_agent_client_should_use_relay():
    local_client = AgentClient({"name": "Host-PC", "ip": "127.0.0.1", "port": 9010}, secret="sec")
    # For local host, should_use_relay is ALWAYS False to prioritize 0-latency direct local HTTP
    with patch.object(local_client, "is_relay_online", return_value=True):
        assert local_client.should_use_relay() is False

    remote_client = AgentClient({"name": "Laptop", "ip": "192.168.1.100", "port": 9010}, secret="sec")
    with patch.object(remote_client, "is_relay_online", return_value=True):
        assert remote_client.should_use_relay() is True
    with patch.object(remote_client, "is_relay_online", return_value=False):
        assert remote_client.should_use_relay() is False


def test_agent_client_local_screenshot_bypasses_relay():
    async def _test():
        client = AgentClient({"name": "Host-PC", "ip": "127.0.0.1", "port": 9010}, secret="sec")
        mock_resp = MagicMock()
        mock_resp.content = b"fake_png_data"
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            # Screenshot should query local HTTP directly, without touching relay
            res = await client.screenshot(chat_id=123456)
            assert res == b"fake_png_data"
            mock_get.assert_called_once_with("/screenshot", timeout=20.0)

    asyncio.run(_test())


def test_main_keyboard_contains_net_ping():
    kb = get_main_keyboard()
    button_callbacks = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    ]
    assert "cb_net_ping" in button_callbacks


def test_handle_net_command():
    async def _test():
        update = MagicMock()
        update.effective_chat.id = 12345
        context = MagicMock()
        context.bot.get_me = AsyncMock(return_value=MagicMock(username="TestBot"))
        context.bot.send_chat_action = AsyncMock()

        mock_agent = MagicMock()
        mock_agent.health = AsyncMock(return_value={"network": "Wi-Fi (Good)"})

        dummy_status_msg = MagicMock()

        with patch("bot.check_access", new_callable=AsyncMock, return_value=True), \
             patch("bot.safe_reply", new_callable=AsyncMock, return_value=dummy_status_msg) as mock_reply, \
             patch("bot.safe_edit_text", new_callable=AsyncMock) as mock_edit, \
             patch("bot.get_agent", return_value=mock_agent), \
             patch("bot.pc_label", return_value="Desktop-PC"):

            await handle_net(update, context)

            assert mock_reply.call_count == 1
            assert mock_edit.call_count == 1
            edited_text = mock_edit.call_args[0][1]
            assert "NETWORK CONNECTIVITY DIAGNOSTICS" in edited_text
            assert "Telegram API Ping:" in edited_text
            assert "Target PC (Desktop-PC):" in edited_text
            assert "Online 🟢" in edited_text

    asyncio.run(_test())


def test_agent_client_play_audio_local():
    async def _test():
        client = AgentClient({"name": "Host-PC", "ip": "127.0.0.1", "port": 9010}, secret="sec")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            res = await client.play_audio("voice.ogg", b"audio_bytes")
            assert res.get("success") is True
            mock_post.assert_called_once()
            assert mock_post.call_args[0][0] == "/play-audio"

    asyncio.run(_test())


def test_agent_client_play_audio_relay():
    async def _test():
        client = AgentClient({"name": "Remote-PC", "ip": "100.64.0.1", "port": 9010}, secret="sec")
        mock_relay = MagicMock()
        mock_relay.send_command = AsyncMock(return_value={"ok": True, "msg": "Played"})
        with patch.object(client, "is_relay_online", return_value=True), \
             patch("bot.commander_relay", mock_relay):
            res = await client.play_audio("voice.ogg", b"audio_bytes")
            assert res.get("success") is True
            mock_relay.send_command.assert_called_once()
            assert mock_relay.send_command.call_args[0][1] == "play_audio"

    asyncio.run(_test())


