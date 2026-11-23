"""
Tests for Manager Authorization & Role-Based Access Control (RBAC),
Device Scoping, Dynamic Bot Keyboards, and Anti-VPN Tracking.
"""

import os
import json
import tempfile
import pytest
from pathlib import Path

from manager_auth import ManagerAuth, DEFAULT_ROLE_PERMISSIONS, PERMISSION_KEYS
import config
from bot import get_pc_picker_keyboard, get_main_keyboard, is_authorized
from system_controller import SystemController


@pytest.fixture
def temp_auth_engine(tmp_path):
    mgr_file = tmp_path / "test_managers.json"
    audit_file = tmp_path / "test_audit.json"
    engine = ManagerAuth(data_file=mgr_file, audit_file=audit_file)
    return engine


class TestManagerRBAC:
    def test_owner_permissions(self, temp_auth_engine):
        engine = temp_auth_engine
        # Ensure owner is recognized and has all permissions
        for owner_id in config.AUTHORIZED_USER_IDS:
            assert engine.is_owner(owner_id) is True
            assert engine.is_authorized(owner_id) is True
            assert engine.get_user_role(owner_id) == "owner"
            for perm in PERMISSION_KEYS:
                assert engine.has_permission(owner_id, perm) is True
            assert engine.can_manage_pc(owner_id, "Any-Random-PC") is True

    def test_create_and_claim_invite(self, temp_auth_engine):
        engine = temp_auth_engine
        token = engine.create_invite(
            role="manager",
            allowed_pcs=["Office-PC", "Host-PC"],
            created_by=12345,
        )
        assert token.startswith("inv_")
        assert len(engine.list_pending_invites()) == 1

        # Claim invite
        user_id = 998877
        ok, msg, mgr_rec = engine.claim_invite(
            token=token,
            user_id=user_id,
            username="testmanager",
            display_name="Test Manager",
        )
        assert ok is True
        assert mgr_rec is not None
        assert mgr_rec["user_id"] == user_id
        assert mgr_rec["role"] == "manager"
        assert mgr_rec["allowed_pcs"] == ["Office-PC", "Host-PC"]

        # Verify single-use: cannot be claimed a second time
        ok2, msg2, _ = engine.claim_invite(token=token, user_id=11111)
        assert ok2 is False
        assert "invalid or has already been used" in msg2

        # Verify registered manager status
        assert engine.is_authorized(user_id) is True
        assert engine.is_manager(user_id) is True
        assert engine.get_user_role(user_id) == "manager"

    def test_device_scoping(self, temp_auth_engine):
        engine = temp_auth_engine
        user_id = 554433
        token = engine.create_invite(
            role="operator",
            allowed_pcs=["Laptop-1"],
            created_by=12345,
        )
        engine.claim_invite(token, user_id=user_id, username="device_mgr")

        # Allowed for Laptop-1, denied for Laptop-2
        assert engine.can_manage_pc(user_id, "Laptop-1") is True
        assert engine.can_manage_pc(user_id, "Laptop-2") is False

        # Filter fleet list
        fleet_pcs = [
            {"name": "Laptop-1", "label": "Dev Laptop"},
            {"name": "Laptop-2", "label": "Finance PC"},
            {"name": "Server-Main", "label": "Core Server"},
        ]
        filtered = engine.get_allowed_pcs(user_id, fleet_pcs)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "Laptop-1"

    def test_pre_authorization_by_username(self, temp_auth_engine):
        engine = temp_auth_engine
        engine.add_pending_by_username(
            username="@JohnDoe",
            role="viewer",
            allowed_pcs=["*"],
            added_by=12345,
        )
        assert "johndoe" in engine.data["pending_by_username"]

        # When John Doe interacts with the bot
        claimed = engine.claim_pending_username(
            user_id=777888,
            username="johndoe",
            display_name="John Doe",
        )
        assert claimed is not None
        assert claimed["role"] == "viewer"
        assert engine.is_authorized(777888) is True
        assert engine.get_user_role(777888) == "viewer"
        # Pending record is cleared
        assert "johndoe" not in engine.data["pending_by_username"]

    def test_granular_permission_toggles(self, temp_auth_engine):
        engine = temp_auth_engine
        user_id = 332211
        token = engine.create_invite(role="manager")
        engine.claim_invite(token, user_id=user_id)

        # Default manager role: can_terminal is False, can_screen is True
        assert engine.has_permission(user_id, "can_terminal") is False
        assert engine.has_permission(user_id, "can_screen") is True

        # Toggle can_terminal to True
        new_val = engine.toggle_permission(user_id, "can_terminal")
        assert new_val is True
        assert engine.has_permission(user_id, "can_terminal") is True

        # Toggle back to False
        new_val2 = engine.toggle_permission(user_id, "can_terminal")
        assert new_val2 is False
        assert engine.has_permission(user_id, "can_terminal") is False

    def test_revocation_and_removal(self, temp_auth_engine):
        engine = temp_auth_engine
        user_id = 889900
        token = engine.create_invite(role="admin")
        engine.claim_invite(token, user_id=user_id, username="temp_admin")
        assert engine.is_authorized(user_id) is True

        # Remove manager
        removed = engine.remove_manager(user_id)
        assert removed is True
        assert engine.is_authorized(user_id) is False
        assert engine.get_manager(user_id) is None

        # Remove by username for pending
        engine.add_pending_by_username("alex")
        assert engine.remove_by_username("alex") is True
        assert "alex" not in engine.data["pending_by_username"]

    def test_rotating_audit_log(self, temp_auth_engine):
        engine = temp_auth_engine
        for i in range(25):
            engine.record_audit(
                user_id=1000 + i,
                username=f"user_{i}",
                action="TEST_ACTION",
                target_pc="Host-PC",
                details=f"Event #{i}",
            )

        logs = engine.get_audit_log(limit=10)
        assert len(logs) == 10
        assert logs[-1]["action"] == "TEST_ACTION"
        assert logs[-1]["details"] == "Event #24"


class TestBotDynamicKeyboards:
    def test_main_keyboard_owner_vs_manager(self):
        owner_id = list(config.AUTHORIZED_USER_IDS)[0] if config.AUTHORIZED_USER_IDS else 0
        owner_kb = get_main_keyboard(user_id=owner_id)

        # Owner keyboard must contain Push Update and Rename PC
        all_owner_callbacks = [btn.callback_data for row in owner_kb.inline_keyboard for btn in row]
        assert "cb_update_agent" in all_owner_callbacks
        assert "cb_rename_current" in all_owner_callbacks
        assert "cb_shot" in all_owner_callbacks
        assert "cb_track" in all_owner_callbacks

    def test_pc_picker_keyboard_scoping(self):
        fleet = {
            "pcs": [
                {"name": "PC-Alpha", "label": "Alpha Workstation"},
                {"name": "PC-Beta", "label": "Beta Laptop"},
            ]
        }
        health = {"PC-Alpha": {"online": True}, "PC-Beta": {"online": False}}

        # Owner gets admin buttons
        owner_id = list(config.AUTHORIZED_USER_IDS)[0] if config.AUTHORIZED_USER_IDS else 0
        kb = get_pc_picker_keyboard(fleet, health, user_id=owner_id)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "fleet_rename_menu" in callbacks
        assert "fleet_overview" in callbacks
        assert "cb_mgr_list" in callbacks


class TestAntiVPNTracking:
    def test_vpn_interface_detection(self):
        vpn_info = SystemController.detect_vpn_interfaces()
        assert isinstance(vpn_info, dict)
        assert "active" in vpn_info
        assert "tunnels" in vpn_info
        assert isinstance(vpn_info["active"], bool)
        assert isinstance(vpn_info["tunnels"], list)

    def test_hardware_gateway_detection(self):
        hw_gw = SystemController.get_hardware_gateway()
        assert isinstance(hw_gw, dict)
        assert "gateway_ip" in hw_gw
        assert "gateway_mac" in hw_gw
        assert "physical_interface" in hw_gw

    def test_get_tracking_info_structure(self):
        data = SystemController.get_tracking_info()
        assert "hostname" in data
        assert "vpn" in data
        assert "hardware_gateway" in data
        assert "wifi" in data
        assert "geo" in data
        assert "battery" in data
        assert "session_state" in data
        assert "uptime" in data
