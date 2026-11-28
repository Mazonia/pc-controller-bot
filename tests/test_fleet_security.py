"""Security tests: replay protection, weak-secret quarantine, LAN auth and secret rotation."""

import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import fleet_relay
from fleet_relay import (
    FleetAgentRelay,
    FleetCrypto,
    LEGACY_DEFAULT_SECRET,
    ReplayGuard,
    generate_fleet_secret,
    is_weak_secret,
)

STRONG = "a-strong-fleet-secret-that-is-long-enough"


def _cmd(cmd="status", target="PC1", ts=None, cid=None):
    return {"id": cid or uuid.uuid4().hex, "cmd": cmd, "params": {}, "ts": time.time() if ts is None else ts,
            "target": target}


# ── secrets ──────────────────────────────────────────────────────────────

def test_weak_secret_detection():
    for weak in ("", LEGACY_DEFAULT_SECRET, "your-random-shared-secret-key-here", "short"):
        assert is_weak_secret(weak)
    assert not is_weak_secret(STRONG)
    assert not is_weak_secret(generate_fleet_secret())


def test_empty_secret_maps_to_flagged_legacy_key():
    assert FleetCrypto("").is_weak and FleetCrypto("").secret == LEGACY_DEFAULT_SECRET
    assert not FleetCrypto(STRONG).is_weak


# ── replay guard ─────────────────────────────────────────────────────────

def test_replay_guard_accepts_fresh_rejects_replay():
    g = ReplayGuard()
    c = _cmd()
    assert g.check(c, "PC1")[0]
    ok, reason = g.check(dict(c), "PC1")
    assert not ok and "replay" in reason


def test_replay_guard_rejects_stale_future_missing_ts_and_wrong_target():
    g = ReplayGuard(max_age=300)
    assert not g.check(_cmd(ts=time.time() - 3600), "PC1")[0]
    assert not g.check(_cmd(ts=time.time() + 3600), "PC1")[0]
    legacy = _cmd()
    legacy.pop("ts")
    assert "timestamp" in g.check(legacy, "PC1")[1]
    assert not g.check(_cmd(target="OTHER-PC"), "PC1")[0]


# ── agent relay quarantine ───────────────────────────────────────────────

def _relay(secret, handler, monkeypatch, insecure=""):
    monkeypatch.setenv("ALLOW_INSECURE_DEFAULT_SECRET", insecure)
    r = FleetAgentRelay(pc_name="PC1", secret=secret, command_handler=handler)
    r.send_response = MagicMock()
    r._dispatch_command = lambda req_id, data: handler(data)  # run inline for the test
    return r


def _deliver(relay, payload):
    import threading
    orig = threading.Thread

    class Inline:
        def __init__(self, target, args, daemon=True):
            self.t, self.a = target, args

        def start(self):
            self.t(*self.a)

    fleet_relay.threading.Thread = Inline
    try:
        relay._on_message(None, None, SimpleNamespace(payload=relay.crypto.encrypt(payload)))
    finally:
        fleet_relay.threading.Thread = orig


def test_weak_secret_agent_only_accepts_quarantine_commands(monkeypatch):
    handled = []
    r = _relay("", lambda d: handled.append(d["cmd"]) or {"ok": True}, monkeypatch)
    assert r.quarantined
    _deliver(r, _cmd("cmd"))
    assert handled == []
    assert "quarantine" in r.send_response.call_args.args[0]["error"]
    _deliver(r, _cmd("rotate_fleet_secret"))
    _deliver(r, _cmd("status"))
    assert handled == ["rotate_fleet_secret", "status"]


def test_explicit_insecure_opt_in_disables_quarantine(monkeypatch):
    r = _relay("", lambda d: {"ok": True}, monkeypatch, insecure="true")
    assert not r.quarantined


def test_strong_secret_agent_runs_commands_and_drops_replays(monkeypatch):
    handled = []
    r = _relay(STRONG, lambda d: handled.append(d["cmd"]) or {"ok": True}, monkeypatch)
    assert not r.quarantined
    c = _cmd("screenshot")
    _deliver(r, c)
    _deliver(r, c)  # captured & replayed from the public broker
    assert handled == ["screenshot"]


def test_commander_stamps_ts_and_target():
    import asyncio
    from fleet_relay import FleetCommanderRelay
    cr = FleetCommanderRelay(secret=STRONG)
    cr.is_connected = True
    cr.client = MagicMock()
    sent = {}

    def publish(topic, raw, qos=1):
        sent["data"] = cr.crypto.decrypt(raw)
        sent["topic"] = topic

    cr.client.publish.side_effect = publish

    async def run():
        cr._loop = asyncio.get_running_loop()
        return await cr.send_command("PC1", "status", timeout=0.05, retries=0)

    asyncio.run(run())
    assert sent["topic"].endswith("/cmd/PC1")
    assert sent["data"]["target"] == "PC1" and abs(sent["data"]["ts"] - time.time()) < 5


# ── agent LAN API ────────────────────────────────────────────────────────

def test_lan_api_requires_secret_even_when_agent_secret_unset():
    import agent
    client = TestClient(agent.app)
    assert client.get("/status").status_code == 403
    assert client.post("/cmd", json={"command": "whoami"}).status_code == 403
    good = TestClient(agent.app, headers={"X-Agent-Secret": agent.AGENT_SECRET or agent.FLEET_SECRET})
    assert good.get("/health").status_code == 200


def test_lan_api_quarantine_with_weak_secret(monkeypatch):
    import agent
    monkeypatch.setattr(agent, "FLEET_SECRET", LEGACY_DEFAULT_SECRET)
    monkeypatch.setattr(agent, "AGENT_SECRET", "")
    monkeypatch.setenv("ALLOW_INSECURE_DEFAULT_SECRET", "")
    client = TestClient(agent.app, headers={"X-Agent-Secret": LEGACY_DEFAULT_SECRET})
    assert client.post("/cmd", json={"command": "whoami"}).status_code == 423
    assert client.get("/health").status_code == 200


def test_rotation_validates_and_persists(tmp_path, monkeypatch):
    import agent
    env = tmp_path / "agent.env"
    env.write_text("PC_NAME=PC1\nFLEET_SECRET=old\n", encoding="utf-8")
    monkeypatch.setattr(agent, "BASE_DIR", tmp_path)
    monkeypatch.setattr(agent, "AGENT_SECRET", "")
    monkeypatch.setattr(agent, "FLEET_SECRET", agent.FLEET_SECRET)  # restored after the test
    monkeypatch.setattr(agent.threading, "Timer", lambda *a, **k: SimpleNamespace(start=lambda: None))
    assert agent.rotate_fleet_secret("short")["ok"] is False
    new = generate_fleet_secret()
    assert agent.rotate_fleet_secret(new)["ok"] is True
    text = env.read_text(encoding="utf-8")
    assert f"FLEET_SECRET={new}" in text and "FLEET_SECRET=old" not in text and "PC_NAME=PC1" in text
    assert agent.FLEET_SECRET == new


def test_screen_caster_token_check_is_constant_time_and_strict():
    import screen_caster
    handler = screen_caster.StreamHTTPHandler.__new__(screen_caster.StreamHTTPHandler)
    handler.caster = SimpleNamespace(auth_token="tok123")
    handler.path = "/?token=tok123"
    assert handler.authenticate()
    handler.path = "/?token=tok12"
    assert not handler.authenticate()
    handler.caster = SimpleNamespace(auth_token="")
    handler.path = "/?token="
    assert not handler.authenticate()
