import asyncio
import time
from unittest.mock import MagicMock, patch
import pytest
from fleet_relay import FleetCommanderRelay, FleetAgentRelay


def test_commander_relay_init_and_topics():
    relay = FleetCommanderRelay(secret="test-secret-relay", broker="localhost", port=1883, use_tls=False)
    assert relay.broker == "localhost"
    assert relay.port == 1883
    assert not relay.is_connected
    assert "sentinel/" in relay.prefix
    assert relay.topic_status_wildcard.endswith("/status/+")
    assert relay.topic_cmd.startswith(relay.prefix) if hasattr(relay, "topic_cmd") else True


def test_commander_send_command_auto_wait_reconnect():
    async def _test():
        relay = FleetCommanderRelay(secret="test-secret", broker="localhost", port=1883, use_tls=False)
        relay._loop = asyncio.get_running_loop()
        relay.client = MagicMock()

        # Simulate reconnecting after 0.3 seconds
        async def simulate_reconnect():
            await asyncio.sleep(0.3)
            relay.is_connected = True

        asyncio.create_task(simulate_reconnect())

        # Mock publish to answer the pending request future immediately
        def fake_publish(topic, payload, qos=1):
            decrypted = relay.crypto.decrypt(payload)
            req_id = decrypted["id"]
            # Trigger fake response
            fake_resp = relay.crypto.encrypt({"id": req_id, "ok": True, "result": "reconnected_success"})
            msg = MagicMock()
            msg.topic = f"{relay.prefix}/resp/Test-PC"
            msg.payload = fake_resp
            relay._on_message(relay.client, None, msg)

        relay.client.publish = fake_publish

        # Should wait for reconnect and succeed rather than failing immediately
        res = await relay.send_command("Test-PC", "status", timeout=5.0)
        assert res.get("ok") is True
        assert res.get("result") == "reconnected_success"

    asyncio.run(_test())


def test_commander_send_command_timeout_retry():
    async def _test():
        relay = FleetCommanderRelay(secret="test-secret", broker="localhost", port=1883, use_tls=False)
        relay._loop = asyncio.get_running_loop()
        relay.is_connected = True
        relay.client = MagicMock()

        attempts = 0

        def mock_publish(topic, payload, qos=1):
            nonlocal attempts
            attempts += 1
            decrypted = relay.crypto.decrypt(payload)
            req_id = decrypted["id"]
            # On second attempt, respond!
            if attempts == 2:
                fake_resp = relay.crypto.encrypt({"id": req_id, "ok": True, "data": "recovered_on_retry"})
                msg = MagicMock()
                msg.topic = f"{relay.prefix}/resp/Test-PC"
                msg.payload = fake_resp
                relay._on_message(relay.client, None, msg)

        relay.client.publish = mock_publish

        # With timeout=0.3s and retries=1, attempt 1 will time out, attempt 2 will succeed
        res = await relay.send_command("Test-PC", "ping", timeout=0.3, retries=1)
        assert res.get("ok") is True
        assert res.get("data") == "recovered_on_retry"
        assert attempts == 2

    asyncio.run(_test())


def test_commander_get_pc_list_staleness():
    relay = FleetCommanderRelay(secret="test-secret")
    now = time.time()
    relay.pcs = {
        "PC-Active": {"status": "online", "last_seen": now - 10},
        "PC-Stale": {"status": "online", "last_seen": now - 120},
    }

    pc_list = relay.get_pc_list()
    assert pc_list["PC-Active"]["status"] == "online"
    assert pc_list["PC-Stale"]["status"] == "offline"


def test_commander_on_status_callback():
    callback_calls = []

    def mock_cb(pc_name, data, is_new):
        callback_calls.append((pc_name, data["status"], is_new))

    relay = FleetCommanderRelay(secret="test-secret", on_status_callback=mock_cb)
    client = MagicMock()

    # 1. First status message for new PC
    msg1 = MagicMock()
    msg1.topic = f"{relay.prefix}/status/Laptop-Office"
    msg1.payload = relay.crypto.encrypt({"status": "online", "pc_name": "Laptop-Office", "network": "Wi-Fi"})
    relay._on_message(client, None, msg1)

    assert len(callback_calls) == 1
    assert callback_calls[0] == ("Laptop-Office", "online", True)

    # 2. Subsequent status message for already known online PC should not re-trigger
    msg2 = MagicMock()
    msg2.topic = f"{relay.prefix}/status/Laptop-Office"
    msg2.payload = relay.crypto.encrypt({"status": "online", "pc_name": "Laptop-Office", "network": "Wi-Fi"})
    relay._on_message(client, None, msg2)

    assert len(callback_calls) == 1

