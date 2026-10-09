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

import psutil
from loguru import logger
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import paho.mqtt.client as mqtt


# ═══════════════════════════════════════════════════════════════════════
#   CRYPTOGRAPHY & TOPIC HELPERS
# ═══════════════════════════════════════════════════════════════════════

class FleetCrypto:
    """AES-256-GCM encryption/decryption using shared FLEET_SECRET."""

    def __init__(self, secret: str):
        if not secret:
            secret = "sentinel-default-secret-key-2026"
        self.secret = secret
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

        try:
            logger.info(f"Connecting Fleet Relay to {self.broker}:{self.port} (TLS={self.use_tls})...")
            self.client.connect_async(self.broker, self.port, keepalive=30)
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
        """Send encrypted response back to the Central Bot."""
        if not self.client or not self.is_connected:
            return
        try:
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
            "cpu": psutil.cpu_percent(interval=None),
            "ram": psutil.virtual_memory().percent,
            "timestamp": datetime.now().isoformat(),
        })
        self.client.publish(self.topic_status, payload, qos=1, retain=True)

    def _heartbeat_worker(self):
        """Periodic telemetry heartbeat every 30 seconds."""
        while self._running:
            time.sleep(30)
            if self.is_connected:
                try:
                    self.publish_status("online")
                except Exception:
                    pass


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
    ):
        self.crypto = FleetCrypto(secret)
        self.broker = broker
        self.port = port
        self.use_tls = use_tls
        self.on_alert_callback = on_alert_callback
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

        try:
            logger.info(f"Connecting Fleet Commander Relay to {self.broker}:{self.port}...")
            self.client.connect_async(self.broker, self.port, keepalive=30)
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
                self.pcs[pc_name] = data
                logger.debug(f"Fleet PC status update: {pc_name} -> {data.get('status')} ({data.get('network')})")

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
        self, pc_name: str, cmd: str, params: Optional[dict] = None, timeout: float = 20.0
    ) -> dict:
        """
        Send encrypted command to a PC and await response.
        Works across mobile data, LAN, or any network.
        """
        if not self.is_connected:
            return {"ok": False, "error": "Relay broker not connected. Please check internet connection."}

        req_id = uuid.uuid4().hex[:8]
        payload_dict = {
            "id": req_id,
            "cmd": cmd,
            "params": params or {},
            "timestamp": datetime.now().isoformat(),
        }

        future = self._loop.create_future()
        self._pending_requests[req_id] = future

        topic = f"{self.prefix}/cmd/{pc_name}"
        raw_payload = self.crypto.encrypt(payload_dict)

        try:
            self.client.publish(topic, raw_payload, qos=1)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            return {"ok": False, "error": f"PC '{pc_name}' did not respond within {int(timeout)}s (may be sleeping or offline)."}
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            return {"ok": False, "error": f"Failed to send command: {e}"}

    def get_pc_list(self) -> Dict[str, dict]:
        """Return dict of all registered PCs and their live status."""
        # Check staleness: if last_seen > 90 seconds ago and status is online, mark as possibly idle/offline
        now = time.time()
        for name, info in self.pcs.items():
            if info.get("status") == "online" and (now - info.get("last_seen", 0) > 90):
                info["status"] = "offline"
        return dict(self.pcs)
