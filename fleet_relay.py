"""
PC Remote Sentinel — Fleet Relay Engine
Cross-network communication bridge using MQTT over TLS with AES-256-GCM encryption.
Enables full remote management of multiple PCs whether on Local Wi-Fi, Ethernet, Mobile Hotspot, 4G/5G, or CGNAT.
"""

import os
import sys
import ssl
import json
import time
import uuid
import socket
import asyncio
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Callable

try:
    import psutil
except ImportError:
    psutil = None
from loguru import logger
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import paho.mqtt.client as mqtt


# ═══════════════════════════════════════════════════════════════════════
#   CRYPTOGRAPHY & TOPIC HELPERS
# ═══════════════════════════════════════════════════════════════════════

# Secrets that are public (shipped in this repository or its examples) or too short.
# Anyone who knows them can derive the fleet topic AND the AES key on the public broker.
LEGACY_DEFAULT_SECRET = "sentinel-fleet-secret-2026"
KNOWN_WEAK_SECRETS = {
    "",
    LEGACY_DEFAULT_SECRET,
    "your-random-shared-secret-key-here",
    "your_fleet_secret_here",
    "changeme",
    "secret",
}
MIN_SECRET_LENGTH = 16

# Commands an agent still accepts while running on a weak secret ("quarantine"),
# so the owner can rotate the secret remotely instead of losing the machine.
QUARANTINE_ALLOWED_COMMANDS = {"health", "status", "ping", "rotate_fleet_secret"}

MAX_COMMAND_AGE_SECONDS = 300      # reject commands older/newer than this (clock skew tolerance)
REPLAY_CACHE_SECONDS = 900


def is_weak_secret(secret: Optional[str]) -> bool:
    value = (secret or "").strip()
    return value.lower() in KNOWN_WEAK_SECRETS or len(value) < MIN_SECRET_LENGTH


def generate_fleet_secret() -> str:
    import secrets as _secrets
    return _secrets.token_urlsafe(32)


def allow_insecure_secret() -> bool:
    return os.getenv("ALLOW_INSECURE_DEFAULT_SECRET", "").strip().lower() in ("1", "true", "yes")


class ReplayGuard:
    """
    Rejects stale, duplicated or mis-addressed commands.

    The broker is public: anyone can record encrypted payloads and publish them
    again later. Each command therefore carries an epoch ``ts``, a unique ``id``
    and the ``target`` PC name.
    """

    def __init__(self, max_age: float = MAX_COMMAND_AGE_SECONDS, cache_seconds: float = REPLAY_CACHE_SECONDS):
        self.max_age = max_age
        self.cache_seconds = cache_seconds
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, data: dict, pc_name: str, now: Optional[float] = None) -> tuple:
        now = now if now is not None else time.time()
        try:
            ts = float(data.get("ts"))
        except (TypeError, ValueError):
            return False, "missing timestamp (sender must be updated)"
        if abs(now - ts) > self.max_age:
            return False, f"stale command ({int(now - ts)}s old)"
        target = data.get("target")
        if target is not None and str(target) != str(pc_name):
            return False, f"command addressed to '{target}'"
        req_id = str(data.get("id") or "")
        if not req_id:
            return False, "missing command id"
        with self._lock:
            for k in [k for k, t in self._seen.items() if now - t > self.cache_seconds]:
                self._seen.pop(k, None)
            if req_id in self._seen:
                return False, "replayed command id"
            self._seen[req_id] = now
        return True, "ok"


class FleetCrypto:
    """AES-256-GCM encryption/decryption using shared FLEET_SECRET."""

    def __init__(self, secret: str):
        secret = (secret or "").strip()
        if not secret:
            # Kept only so legacy fleets keep talking; such agents run in quarantine.
            secret = LEGACY_DEFAULT_SECRET
        self.secret = secret
        self.is_weak = is_weak_secret(secret)
        self.key = hashlib.sha256(secret.encode("utf-8")).digest()
        self.aesgcm = AESGCM(self.key)
        self.fleet_id = hashlib.sha256((secret + "_fleet_salt").encode("utf-8")).hexdigest()[:12]

    def encrypt(self, payload: dict) -> bytes:
        """Encrypt JSON dict with a random 12-byte nonce."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    def decrypt(self, raw_bytes: bytes) -> Optional[dict]:
        """Decrypt raw bytes (nonce + ciphertext + tag) back into JSON dict."""
        try:
            if len(raw_bytes) < 28:
                return None
            nonce = raw_bytes[:12]
            ciphertext = raw_bytes[12:]
            data = self.aesgcm.decrypt(nonce, ciphertext, None)
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            logger.debug(f"Decryption failed: {e}")
            return None


def get_network_info() -> Dict[str, str]:
    """Detect local IP and determine if PC is on LAN, Cellular, or Hotspot."""
    lan_ip = "127.0.0.1"
    net_type = "Unknown"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # Inspect network interfaces
    try:
        if psutil:
            for iface_name, addrs in psutil.net_if_addrs().items():
                name_lower = iface_name.lower()
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address == lan_ip:
                        if any(k in name_lower for k in ["cell", "mobile", "wwan", "lte", "modem", "tether"]):
                            net_type = f"Mobile Data / Dongle ({lan_ip})"
                        elif "wi-fi" in name_lower or "wireless" in name_lower or "wlan" in name_lower:
                            if lan_ip.startswith("192.168.43.") or lan_ip.startswith("172.20.10."):
                                net_type = f"Phone Hotspot ({lan_ip})"
                            else:
                                net_type = f"Wi-Fi ({lan_ip})"
                        elif "ethernet" in name_lower or "eth" in name_lower or "local area" in name_lower:
                            net_type = f"Ethernet ({lan_ip})"
                        elif lan_ip.startswith("100."):
                            net_type = f"Cellular CGNAT ({lan_ip})"
                        else:
                            net_type = f"Network ({lan_ip})"
                        break
    except Exception:
        pass

    if net_type == "Unknown":
        net_type = f"LAN ({lan_ip})"

    return {"ip": lan_ip, "type": net_type}


# ═══════════════════════════════════════════════════════════════════════
#   AGENT RELAY (Runs on each Monitored PC)
# ═══════════════════════════════════════════════════════════════════════

class FleetAgentRelay:
    """
    Outbound MQTT bridge running on each PC.
    Works behind CGNAT, mobile hotspots, cellular modems, or local LAN.
    """

    def __init__(
        self,
        pc_name: str,
        secret: str,
        broker: str = "broker.emqx.io",
        port: int = 8883,
        use_tls: bool = True,
        command_handler: Optional[Callable[[dict], Any]] = None,
    ):
        self.pc_name = pc_name
        self.crypto = FleetCrypto(secret)
        self.broker = broker
        self.port = port
        self.use_tls = use_tls
        self.command_handler = command_handler
        self.replay_guard = ReplayGuard()
        self.quarantined = self.crypto.is_weak and not allow_insecure_secret()
        if self.quarantined:
            logger.critical(
                "FLEET_SECRET is missing, default or too short — anyone could command this PC via the public "
                "broker. Agent is in QUARANTINE (only status/health/rotate_fleet_secret accepted). "
                "Send /rotatesecret from the bot, or set a strong FLEET_SECRET in agent.env."
            )
        self.client: Optional[mqtt.Client] = None
        self.is_connected = False
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Topics
        prefix = f"sentinel/{self.crypto.fleet_id}"
        self.topic_status = f"{prefix}/status/{self.pc_name}"
        self.topic_cmd = f"{prefix}/cmd/{self.pc_name}"
        self.topic_resp = f"{prefix}/resp/{self.pc_name}"
        self.topic_alert = f"{prefix}/alert/{self.pc_name}"

    def start(self):
        """Start the agent relay client in a background thread."""
        self._running = True
        client_id = f"sentinel_agent_{self.pc_name}_{uuid.uuid4().hex[:6]}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)

        if self.use_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)

        # LWT: If agent disconnects abruptly, broker sets status to offline
        offline_payload = self.crypto.encrypt({
            "status": "offline",
            "pc_name": self.pc_name,
            "timestamp": datetime.now().isoformat(),
        })
        self.client.will_set(self.topic_status, offline_payload, qos=1, retain=True)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=2, max_delay=30)

        try:
            logger.info(f"Connecting Fleet Relay to {self.broker}:{self.port} (TLS={self.use_tls})...")
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Relay connect error: {e}")

        # Start background heartbeat
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()

    def stop(self):
        """Clean shutdown of relay."""
        self._running = False
        if self.client:
            try:
                offline_payload = self.crypto.encrypt({
                    "status": "offline",
                    "pc_name": self.pc_name,
                    "timestamp": datetime.now().isoformat(),
                })
                self.client.publish(self.topic_status, offline_payload, qos=1, retain=True)
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, rc, props=None):
        if rc == 0:
            self.is_connected = True
            logger.info(f"Fleet Relay connected! Subscribing to command topic for {self.pc_name}")
            client.subscribe(self.topic_cmd, qos=1)
            self.publish_status("online")
        else:
            logger.warning(f"Fleet Relay connect failed with code {rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, props=None):
        self.is_connected = False
        logger.warning(f"Fleet Relay disconnected (rc={rc}). Will auto-reconnect...")

    def _on_message(self, client, userdata, msg):
        try:
            data = self.crypto.decrypt(msg.payload)
            if not data:
                return

            req_id = data.get("id", "")
            cmd = data.get("cmd", "")

            ok, reason = self.replay_guard.check(data, self.pc_name)
            if not ok:
                logger.warning(f"Dropped fleet command [{cmd}] (req_id={req_id}): {reason}")
                return

            if self.quarantined and cmd not in QUARANTINE_ALLOWED_COMMANDS:
                logger.warning(f"Quarantine: refused fleet command [{cmd}] — weak fleet secret")
                self.send_response({
                    "id": req_id, "ok": False,
                    "error": "Agent is in security quarantine (weak/default FLEET_SECRET). "
                             "Run /rotatesecret in the bot to secure this PC.",
                })
                return

            logger.info(f"Received fleet command [{cmd}] (req_id={req_id})")

            if self.command_handler:
                threading.Thread(
                    target=self._dispatch_command,
                    args=(req_id, data),
                    daemon=True,
                ).start()
        except Exception as e:
            logger.error(f"Error handling relay message: {e}")

    def _dispatch_command(self, req_id: str, data: dict):
        try:
            res = self.command_handler(data)
            if not isinstance(res, dict):
                res = {"ok": True, "result": res}
            res["id"] = req_id
            self.send_response(res)
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            self.send_response({"id": req_id, "ok": False, "error": str(e)})

    def send_response(self, response_data: dict):
        """Send encrypted response back to the Central Bot with packet size protection."""
        if not self.client or not self.is_connected:
            return
        try:
            payload = self.crypto.encrypt(response_data)
            # Guard against public MQTT broker packet limits (256KB-1MB)
            if len(payload) > 220 * 1024:
                logger.warning(f"Relay response payload ({len(payload)} bytes) is near broker limit. Pruning list items...")
                if "items" in response_data and isinstance(response_data["items"], list):
                    response_data["items"] = response_data["items"][:50]
                    response_data["truncated"] = True
                    payload = self.crypto.encrypt(response_data)
            self.client.publish(self.topic_resp, payload, qos=1)
        except Exception as e:
            logger.error(f"Failed to send response: {e}")

    def send_alert(self, alert_data: dict):
        """Send asynchronous alert (e.g. alarm triggered) to the Central Bot."""
        if not self.client or not self.is_connected:
            return
        try:
            alert_data["pc_name"] = self.pc_name
            alert_data["timestamp"] = datetime.now().isoformat()
            payload = self.crypto.encrypt(alert_data)
            self.client.publish(self.topic_alert, payload, qos=1)
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def publish_status(self, status: str = "online"):
        """Publish updated online telemetry."""
        if not self.client or not self.is_connected:
            return
        net = get_network_info()
        payload = self.crypto.encrypt({
            "status": status,
            "pc_name": self.pc_name,
            "hostname": socket.gethostname(),
            "ip": net["ip"],
            "network": net["type"],
            "cpu": psutil.cpu_percent(interval=None) if psutil else 0.0,
            "ram": psutil.virtual_memory().percent if psutil else 0.0,
            "timestamp": datetime.now().isoformat(),
        })
        self.client.publish(self.topic_status, payload, qos=1, retain=True)

    def _heartbeat_worker(self):
        """Periodic telemetry heartbeat every 20 seconds with proactive auto-reconnect."""
        discon_cycles = 0
        while self._running:
            time.sleep(20)
            if self.is_connected:
                discon_cycles = 0
                try:
                    self.publish_status("online")
                except Exception:
                    pass
            else:
                discon_cycles += 1
                if discon_cycles >= 2:
                    try:
                        logger.info("Fleet Relay connection inactive. Proactively triggering reconnect...")
                        self.client.reconnect()
                        discon_cycles = 0
                    except Exception as rec_err:
                        logger.debug(f"Proactive reconnect notice: {rec_err}")


# ═══════════════════════════════════════════════════════════════════════
#   COMMANDER RELAY (Runs inside Central Telegram Bot)
# ═══════════════════════════════════════════════════════════════════════

class FleetCommanderRelay:
    """
    Central Controller relay inside bot.py.
    Listens for all PC heartbeats and dispatches encrypted commands.
    """

    def __init__(
        self,
        secret: str,
        broker: str = "broker.emqx.io",
        port: int = 8883,
        use_tls: bool = True,
        on_alert_callback: Optional[Callable[[dict], None]] = None,
        on_status_callback: Optional[Callable[[str, dict, bool], None]] = None,
    ):
        self.crypto = FleetCrypto(secret)
        self.broker = broker
        self.port = port
        self.use_tls = use_tls
        self.on_alert_callback = on_alert_callback
        self.on_status_callback = on_status_callback
        self.client: Optional[mqtt.Client] = None
        self.is_connected = False
        self.pcs: Dict[str, dict] = {}  # pc_name -> {status, ip, network, last_seen, ...}
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        prefix = f"sentinel/{self.crypto.fleet_id}"
        self.prefix = prefix
        self.topic_status_wildcard = f"{prefix}/status/+"
        self.topic_resp_wildcard = f"{prefix}/resp/+"
        self.topic_alert_wildcard = f"{prefix}/alert/+"

    def start(self, loop: asyncio.AbstractEventLoop):
        """Start commander MQTT listener."""
        self._loop = loop
        client_id = f"sentinel_commander_{uuid.uuid4().hex[:6]}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)

        if self.use_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=2, max_delay=30)

        try:
            logger.info(f"Connecting Fleet Commander Relay to {self.broker}:{self.port}...")
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Commander relay connect error: {e}")

    def stop(self):
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, rc, props=None):
        if rc == 0:
            self.is_connected = True
            logger.info("Fleet Commander Relay connected! Subscribing to fleet topics...")
            client.subscribe([
                (self.topic_status_wildcard, 1),
                (self.topic_resp_wildcard, 1),
                (self.topic_alert_wildcard, 1),
            ])
        else:
            logger.warning(f"Commander Relay connect failed with rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, props=None):
        self.is_connected = False
        logger.warning(f"Commander Relay disconnected (rc={rc}). Will auto-reconnect...")

    def _on_message(self, client, userdata, msg):
        try:
            data = self.crypto.decrypt(msg.payload)
            if not data:
                return

            topic = msg.topic
            if "/status/" in topic:
                pc_name = data.get("pc_name") or topic.split("/")[-1]
                data["last_seen"] = time.time()
                is_new = pc_name not in self.pcs
                was_offline = (self.pcs.get(pc_name, {}).get("status") == "offline") if not is_new else False
                self.pcs[pc_name] = data
                logger.debug(f"Fleet PC status update: {pc_name} -> {data.get('status')} ({data.get('network')})")
                if self.on_status_callback and (is_new or was_offline) and data.get("status") == "online":
                    try:
                        if self._loop:
                            self._loop.call_soon_threadsafe(self.on_status_callback, pc_name, data, is_new)
                        else:
                            self.on_status_callback(pc_name, data, is_new)
                    except Exception as cb_err:
                        logger.error(f"Error in on_status_callback: {cb_err}")

            elif "/resp/" in topic:
                req_id = data.get("id")
                if req_id and req_id in self._pending_requests:
                    future = self._pending_requests.pop(req_id)
                    if self._loop and not future.done():
                        self._loop.call_soon_threadsafe(future.set_result, data)

            elif "/alert/" in topic:
                logger.warning(f"Fleet alert received: {data}")
                if self.on_alert_callback:
                    if self._loop:
                        self._loop.call_soon_threadsafe(self.on_alert_callback, data)
                    else:
                        self.on_alert_callback(data)

        except Exception as e:
            logger.error(f"Commander on_message error: {e}")

    async def send_command(
        self, pc_name: str, cmd: str, params: Optional[dict] = None, timeout: float = 30.0, retries: int = 1
    ) -> dict:
        """
        Send encrypted command to a PC and await response.
        Works across mobile data, LAN, or any network.
        Gracefully handles network jitter, brief disconnects, and packet loss.
        """
        # If briefly disconnected, wait up to 6s for auto-reconnect before giving up
        if not self.is_connected:
            logger.info(f"Relay temporarily disconnected. Waiting up to 6s for reconnect before sending '{cmd}'...")
            wait_start = time.time()
            while not self.is_connected and (time.time() - wait_start < 6.0):
                await asyncio.sleep(0.3)

        if not self.is_connected:
            return {
                "ok": False,
                "error": "Relay broker not connected. Network connection may be down or severely unstable.",
            }

        last_error = ""
        topic = f"{self.prefix}/cmd/{pc_name}"

        for attempt in range(retries + 1):
            req_id = uuid.uuid4().hex
            payload_dict = {
                "id": req_id,
                "cmd": cmd,
                "params": params or {},
                "timestamp": datetime.now().isoformat(),
                "ts": time.time(),          # replay protection (epoch, timezone independent)
                "target": pc_name,          # binds the command to one PC
            }

            future = self._loop.create_future()
            self._pending_requests[req_id] = future
            raw_payload = self.crypto.encrypt(payload_dict)

            try:
                self.client.publish(topic, raw_payload, qos=1)
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                self._pending_requests.pop(req_id, None)
                last_error = f"PC '{pc_name}' did not respond within {int(timeout)}s (unstable connection or PC is busy/sleeping)."
                if attempt < retries:
                    logger.warning(f"Command '{cmd}' to '{pc_name}' timed out after {timeout}s. Retrying once...")
                    await asyncio.sleep(1.0)
                    continue
                return {"ok": False, "error": last_error}
            except Exception as e:
                self._pending_requests.pop(req_id, None)
                last_error = f"Failed to send command: {e}"
                if attempt < retries:
                    logger.warning(f"Command '{cmd}' to '{pc_name}' failed with {e}. Retrying...")
                    await asyncio.sleep(1.0)
                    continue
                return {"ok": False, "error": last_error}

        return {"ok": False, "error": last_error or "Command failed"}

    def get_pc_list(self) -> Dict[str, dict]:
        """Return dict of all registered PCs and their live status."""
        # Check staleness: if last_seen > 90 seconds ago and status is online, mark as possibly idle/offline
        now = time.time()
        for name, info in self.pcs.items():
            if info.get("status") == "online" and (now - info.get("last_seen", 0) > 90):
                info["status"] = "offline"
        return dict(self.pcs)
