"""
PC Remote Sentinel — Manager Authorization & Role-Based Access Control (RBAC)
Manages multi-user delegation, granular permission matrix, deep-link invite tokens,
per-device scoping, and audit logs.
"""

import os
import sys
import json
import secrets
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

import config
from loguru import logger

MANAGERS_FILE = config.BASE_DIR / "managers.json"
AUDIT_LOG_FILE = config.BASE_DIR / "audit_log.json"

# Standard Granular Permission Keys
PERMISSION_KEYS = [
    "can_power",      # Sleep, lock, restart, cancel shutdown
    "can_screen",     # Screenshot, screen video recording, live cast
    "can_input",      # Remote mouse gestures and typing
    "can_media",      # Volume, play/pause, speak TTS
    "can_webcam",     # Webcam snapshot and video (privacy sensitive)
    "can_files",      # File explorer, download files (data sensitive)
    "can_terminal",   # Shell command execution /cmd (system critical)
    "can_track",      # Geolocation and Wi-Fi tracking dossier
    "can_lockdown",   # Emergency anti-theft lockdown
]

DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "admin": {
        "can_power": True,
        "can_screen": True,
        "can_input": True,
        "can_media": True,
        "can_webcam": True,
        "can_files": True,
        "can_terminal": True,
        "can_track": True,
        "can_lockdown": True,
    },
    "manager": {
        "can_power": True,
        "can_screen": True,
        "can_input": True,
        "can_media": True,
        "can_webcam": False,
        "can_files": False,
        "can_terminal": False,
        "can_track": True,
        "can_lockdown": True,
    },
    "operator": {
        "can_power": True,
        "can_screen": True,
        "can_input": False,
        "can_media": True,
        "can_webcam": False,
        "can_files": False,
        "can_terminal": False,
        "can_track": True,
        "can_lockdown": False,
    },
    "viewer": {
        "can_power": False,
        "can_screen": False,
        "can_input": False,
        "can_media": False,
        "can_webcam": False,
        "can_files": False,
        "can_terminal": False,
        "can_track": True,
        "can_lockdown": False,
    },
}


class ManagerAuth:
    """Thread-safe manager authorization and RBAC persistence engine."""

    def __init__(self, data_file: Path = MANAGERS_FILE, audit_file: Path = AUDIT_LOG_FILE):
        self.data_file = data_file
        self.audit_file = audit_file
        self._lock = threading.Lock()
        self.data: Dict[str, Any] = {"managers": {}, "invites": {}, "pending_by_username": {}}
        self.load()

    def load(self):
        with self._lock:
            if self.data_file.exists():
                try:
                    with open(self.data_file, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                        self.data.setdefault("managers", {})
                        self.data.setdefault("invites", {})
                        self.data.setdefault("pending_by_username", {})
                except Exception as e:
                    logger.error(f"Failed to load managers.json: {e}")
                    self.data = {"managers": {}, "invites": {}, "pending_by_username": {}}
            else:
                self.data = {"managers": {}, "invites": {}, "pending_by_username": {}}
                self.save_unlocked()

    def save(self):
        with self._lock:
            self.save_unlocked()

    def save_unlocked(self):
        try:
            temp_file = self.data_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.data_file)
        except Exception as e:
            logger.error(f"Failed to save managers.json: {e}")

    # ── Role & Authentication Checks ───────────────────────────────────

    def is_owner(self, user_id: int) -> bool:
        """Verify if user is the immutable Super Admin (Owner)."""
        return user_id in config.AUTHORIZED_USER_IDS

    def get_manager(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve manager record if user is an authorized delegated manager."""
        with self._lock:
            return self.data.get("managers", {}).get(str(user_id))

    def is_manager(self, user_id: int) -> bool:
        """Check if user is a registered delegated manager."""
        return self.get_manager(user_id) is not None

    def is_authorized(self, user_id: int) -> bool:
        """Check if user has any access (Owner or Manager)."""
        return self.is_owner(user_id) or self.is_manager(user_id)

    def get_user_role(self, user_id: int) -> str:
        """Get user role string: 'owner', role name, or 'unauthorized'."""
        if self.is_owner(user_id):
            return "owner"
        mgr = self.get_manager(user_id)
        if mgr:
            return mgr.get("role", "manager")
        return "unauthorized"

    # ── Scoping & Permissions ──────────────────────────────────────────

    def can_manage_pc(self, user_id: int, pc_name: str) -> bool:
        """Check if user is authorized to view or manage target PC."""
        if self.is_owner(user_id):
            return True
        mgr = self.get_manager(user_id)
        if not mgr:
            return False
        allowed = mgr.get("allowed_pcs", [])
        return "*" in allowed or pc_name in allowed

    def get_allowed_pcs(self, user_id: int, all_pcs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter fleet PC list according to user's device permissions."""
        if self.is_owner(user_id):
            return all_pcs
        mgr = self.get_manager(user_id)
        if not mgr:
            return []
        allowed = mgr.get("allowed_pcs", [])
        if "*" in allowed:
            return all_pcs
        return [pc for pc in all_pcs if pc.get("name") in allowed]

    def has_permission(self, user_id: int, perm_key: str) -> bool:
        """Check if user has specific granular permission."""
        if self.is_owner(user_id):
            return True
        mgr = self.get_manager(user_id)
        if not mgr:
            return False
        return bool(mgr.get("permissions", {}).get(perm_key, False))

    # ── Invites & Onboarding ───────────────────────────────────────────

    def create_invite(
        self,
        role: str = "manager",
        allowed_pcs: Optional[List[str]] = None,
        custom_permissions: Optional[Dict[str, bool]] = None,
        expires_hours: int = 48,
        created_by: int = 0
    ) -> str:
        """Generate a secure, single-use onboarding deep-link token."""
        token = f"inv_{secrets.token_hex(6)}"
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=expires_hours)

        perms = DEFAULT_ROLE_PERMISSIONS.get(role, DEFAULT_ROLE_PERMISSIONS["manager"]).copy()
        if custom_permissions:
            perms.update(custom_permissions)

        record = {
            "token": token,
            "role": role,
            "allowed_pcs": allowed_pcs or ["*"],
            "permissions": perms,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "created_by": created_by,
        }

        with self._lock:
            self.data.setdefault("invites", {})[token] = record
            self.save_unlocked()

        return token

    def claim_invite(
        self,
        token: str,
        user_id: int,
        username: str = "",
        display_name: str = ""
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Claim a single-use invite token and register manager."""
        with self._lock:
            invites = self.data.setdefault("invites", {})
            invite = invites.get(token)
            if not invite:
                return False, "Invite link is invalid or has already been used.", None

            # Check expiration
            expires_at = datetime.fromisoformat(invite["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                invites.pop(token, None)
                self.save_unlocked()
                return False, "This invite link has expired.", None

            # Create manager record
            now_str = datetime.now(timezone.utc).isoformat()
            manager_record = {
                "user_id": user_id,
                "username": username.lstrip("@").strip(),
                "display_name": display_name or username or str(user_id),
                "role": invite.get("role", "manager"),
                "allowed_pcs": invite.get("allowed_pcs", ["*"]),
                "permissions": invite.get("permissions", DEFAULT_ROLE_PERMISSIONS["manager"].copy()),
                "added_at": now_str,
                "added_by": invite.get("created_by", 0),
                "active": True,
            }

            self.data.setdefault("managers", {})[str(user_id)] = manager_record
            invites.pop(token, None)  # Single-use consumption
            self.save_unlocked()

        logger.info(f"Invite token '{token}' claimed by {display_name} ({user_id})")
        return True, "Invite claimed successfully!", manager_record

    def add_pending_by_username(
        self,
        username: str,
        role: str = "manager",
        allowed_pcs: Optional[List[str]] = None,
        permissions: Optional[Dict[str, bool]] = None,
        added_by: int = 0
    ):
        """Pre-authorize a manager by @username so they are onboarded when they start the bot."""
        uname = username.lstrip("@").strip().lower()
        perms = DEFAULT_ROLE_PERMISSIONS.get(role, DEFAULT_ROLE_PERMISSIONS["manager"]).copy()
        if permissions:
            perms.update(permissions)

        with self._lock:
            self.data.setdefault("pending_by_username", {})[uname] = {
                "username": uname,
                "role": role,
                "allowed_pcs": allowed_pcs or ["*"],
                "permissions": perms,
                "added_by": added_by,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.save_unlocked()

    def claim_pending_username(
        self,
        user_id: int,
        username: str,
        display_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Check if interacting user matches a pending @username authorization."""
        if not username:
            return None
        uname = username.lstrip("@").strip().lower()

        with self._lock:
            pending = self.data.setdefault("pending_by_username", {})
            if uname not in pending:
                return None

            record = pending.pop(uname)
            manager_record = {
                "user_id": user_id,
                "username": uname,
                "display_name": display_name or username,
                "role": record.get("role", "manager"),
                "allowed_pcs": record.get("allowed_pcs", ["*"]),
                "permissions": record.get("permissions", DEFAULT_ROLE_PERMISSIONS["manager"].copy()),
                "added_at": datetime.now(timezone.utc).isoformat(),
                "added_by": record.get("added_by", 0),
                "active": True,
            }
            self.data.setdefault("managers", {})[str(user_id)] = manager_record
            self.save_unlocked()

        logger.info(f"Pending username '@{uname}' claimed by user ID {user_id}")
        return manager_record

    # ── Manager Modification & Revocation ──────────────────────────────

    def remove_manager(self, user_id: int) -> bool:
        """Permanently remove manager access."""
        with self._lock:
            managers = self.data.setdefault("managers", {})
            uid_str = str(user_id)
            if uid_str in managers:
                managers.pop(uid_str)
                self.save_unlocked()
                logger.info(f"Manager {user_id} removed.")
                return True
        return False

    def remove_by_username(self, username: str) -> bool:
        """Remove manager or pending authorization by username."""
        uname = username.lstrip("@").strip().lower()
        found = False
        with self._lock:
            pending = self.data.setdefault("pending_by_username", {})
            if uname in pending:
                pending.pop(uname)
                found = True

            managers = self.data.setdefault("managers", {})
            for uid, mgr in list(managers.items()):
                if mgr.get("username", "").lower() == uname:
                    managers.pop(uid)
                    found = True
                    break

            if found:
                self.save_unlocked()
        return found

    def toggle_permission(self, user_id: int, perm_key: str) -> Optional[bool]:
        """Toggle an individual granular permission for a manager."""
        with self._lock:
            mgr = self.data.setdefault("managers", {}).get(str(user_id))
            if not mgr:
                return None
            perms = mgr.setdefault("permissions", {})
            curr = perms.get(perm_key, False)
            perms[perm_key] = not curr
            self.save_unlocked()
            return perms[perm_key]

    def set_allowed_pcs(self, user_id: int, pcs: List[str]) -> bool:
        """Update allowed PCs for a manager."""
        with self._lock:
            mgr = self.data.setdefault("managers", {}).get(str(user_id))
            if not mgr:
                return False
            mgr["allowed_pcs"] = pcs
            self.save_unlocked()
            return True

    def set_role(self, user_id: int, new_role: str) -> bool:
        """Change manager's role and reset permissions to role default."""
        with self._lock:
            mgr = self.data.setdefault("managers", {}).get(str(user_id))
            if not mgr:
                return False
            mgr["role"] = new_role
            if new_role in DEFAULT_ROLE_PERMISSIONS:
                mgr["permissions"] = DEFAULT_ROLE_PERMISSIONS[new_role].copy()
            self.save_unlocked()
            return True

    def list_managers(self) -> List[Dict[str, Any]]:
        """List all registered managers."""
        with self._lock:
            return list(self.data.get("managers", {}).values())

    def list_pending_invites(self) -> List[Dict[str, Any]]:
        """List active pending invites."""
        with self._lock:
            return list(self.data.get("invites", {}).values())

    # ── Audit Trail ────────────────────────────────────────────────────

    def record_audit(self, user_id: int, username: str, action: str, target_pc: str = "", details: str = ""):
        """Record critical action to rotating audit log file."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "username": username,
            "action": action,
            "target_pc": target_pc,
            "details": details,
        }
        try:
            entries = []
            if self.audit_file.exists():
                try:
                    with open(self.audit_file, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except Exception:
                    entries = []
            entries.append(entry)
            entries = entries[-200:]  # Keep latest 200 events
            with open(self.audit_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Audit log write failed: {e}")

    def get_audit_log(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Fetch latest audit log entries."""
        if not self.audit_file.exists():
            return []
        try:
            with open(self.audit_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data[-limit:]
        except Exception:
            return []


# Global Singleton Instance
manager_auth = ManagerAuth()
