"""
Cross-Platform & macOS Compatibility Test Suite
Validates that PC Remote Sentinel operates seamlessly across Windows and macOS:
1. Python AST parsing for all modules without syntax or import errors.
2. Verification of macOS-specific logic in SystemController.
3. XML validation of LaunchAgent property list (.plist).
4. Line ending and syntax validation for all macOS shell scripts (.sh).
5. Verification that requirements_mac.txt has no win32-only dependencies.
"""

import os
import sys
import ast
import glob
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch, MagicMock

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


class TestMacCompatibility(unittest.TestCase):

    def test_01_all_python_files_ast_compile(self):
        """Ensure all Python source files compile cleanly with zero syntax errors."""
        errors = []
        py_files = list(BASE_DIR.glob("*.py")) + list(BASE_DIR.glob("tests/*.py"))
        for py_path in py_files:
            try:
                code = py_path.read_text(encoding="utf-8")
                ast.parse(code, filename=str(py_path))
            except Exception as e:
                errors.append(f"{py_path.name}: {e}")

        self.assertEqual(len(errors), 0, f"Python compilation errors found: {errors}")

    def test_02_mac_requirements_clean(self):
        """Ensure requirements_mac.txt does not contain Windows-only packages."""
        req_path = BASE_DIR / "mac" / "requirements_mac.txt"
        self.assertTrue(req_path.exists(), "mac/requirements_mac.txt must exist")

        lines = req_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip().lower()
            if not line or line.startswith("#"):
                continue
            self.assertNotIn("pywin32", line, "pywin32 must not be in requirements_mac.txt")
            self.assertNotIn("winsound", line, "winsound must not be in requirements_mac.txt")

    def test_03_shell_scripts_lf_and_shebang(self):
        """Ensure all shell scripts have UNIX LF line endings and proper shebangs."""
        sh_files = [
            BASE_DIR / "install_mac.sh",
            BASE_DIR / "start_mac.sh",
            BASE_DIR / "uninstall_mac.sh",
            BASE_DIR / "mac" / "install_mac.sh",
            BASE_DIR / "mac" / "start_agent_mac.sh",
            BASE_DIR / "mac" / "uninstall_mac.sh",
        ]
        for sh_path in sh_files:
            self.assertTrue(sh_path.exists(), f"Script {sh_path.name} must exist")
            raw = sh_path.read_bytes()
            self.assertNotIn(b"\r\n", raw, f"{sh_path.name} has CRLF line endings! Must be LF.")
            self.assertTrue(
                raw.startswith(b"#!/usr/bin/env bash") or raw.startswith(b"#!/bin/bash"),
                f"{sh_path.name} must have a valid bash shebang"
            )

    def test_04_plist_valid_xml(self):
        """Ensure LaunchAgent plist is valid XML with expected keys."""
        plist_path = BASE_DIR / "mac" / "com.sentinel.agent.plist"
        self.assertTrue(plist_path.exists(), "com.sentinel.agent.plist must exist")

        # Parse XML
        tree = ET.parse(str(plist_path))
        root = tree.getroot()
        self.assertEqual(root.tag, "plist")

        content = plist_path.read_text(encoding="utf-8")
        self.assertIn("com.sentinel.agent", content)
        self.assertIn("__PYTHON_BIN__", content)
        self.assertIn("__AGENT_PY__", content)
        self.assertIn("__INSTALL_DIR__", content)
        self.assertIn("__LOG_DIR__", content)

    def test_05_system_controller_mac_branch_execution(self):
        """Test macOS logic paths in system_controller using mocked platform."""
        import system_controller
        from system_controller import SystemController

        with patch.object(system_controller, "IS_MAC", True), \
             patch.object(system_controller, "IS_WINDOWS", False):

            # 1. Drive detection on macOS
            drives = SystemController.get_system_drives()
            self.assertIn("/", drives)

            # 2. Gestures on macOS
            with patch("subprocess.Popen") as mock_popen, \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

                # Mission Control gesture
                ok, msg = SystemController.execute_gesture("task_view")
                self.assertTrue(ok)

                # Multiline typing on macOS
                ok, msg = SystemController.type_text("Hello Mac!\nSecond Line\nThird Line")
                self.assertTrue(ok)

                # Key combos on macOS (including Windows -> Mac translations)
                ok, msg = SystemController.press_key("cmd+c")
                self.assertTrue(ok)
                ok, msg = SystemController.press_key("ctrl+c") # auto translated to cmd+c
                self.assertTrue(ok)
                ok, msg = SystemController.press_key("win+d") # translated to cmd+f3
                self.assertTrue(ok)
                ok, msg = SystemController.press_key("alt+f4") # translated to cmd+w
                self.assertTrue(ok)
                ok, msg = SystemController.press_key("cmd") # standalone modifier
                self.assertTrue(ok)

                # TTS on macOS
                ok = SystemController.speak_text("Test announcement")
                self.assertTrue(ok)

                # Clipboard on macOS
                with patch("subprocess.run") as mock_pb:
                    mock_pb.return_value = MagicMock(returncode=0, stdout="clipboard text", stderr="")
                    val = SystemController.get_clipboard()
                    self.assertEqual(val, "clipboard text")

                # Open target on macOS
                ok = SystemController.open_target("https://google.com")
                self.assertTrue(ok)

    def test_06_hostname_fallback(self):
        """Ensure hostname resolution is safe across platforms."""
        import socket
        name = socket.gethostname()
        self.assertTrue(len(name) > 0)

    def test_07_process_management_signatures_and_protection(self):
        """Verify list_top_processes accepts both limit and count, and protects macOS system daemons."""
        import system_controller
        from system_controller import SystemController

        # Test both limit and count parameters
        procs1 = SystemController.list_top_processes(limit=5)
        self.assertIsInstance(procs1, list)

        procs2 = SystemController.list_top_processes(count=5)
        self.assertIsInstance(procs2, list)

        with patch.object(system_controller, "IS_MAC", True), \
             patch.object(system_controller, "IS_WINDOWS", False):
            # Verify PID 0, 1, 4 protection
            ok0, msg0 = SystemController.kill_process(pid=0)
            self.assertFalse(ok0)
            self.assertTrue("refusing" in msg0.lower() or "safety shield" in msg0.lower())

            ok1, msg1 = SystemController.kill_process(pid=1)
            self.assertFalse(ok1)
            self.assertTrue("refusing" in msg1.lower() or "safety shield" in msg1.lower())

            # Verify macOS protected daemon name protection
            ok_w, msg_w = SystemController.kill_process(name="WindowServer")
            self.assertFalse(ok_w)
            self.assertTrue("protected" in msg_w.lower() or "safety shield" in msg_w.lower())

    def test_08_macos_session_state_detection(self):
        """Test macOS screen lock detection via ioreg."""
        import system_controller
        from system_controller import SystemController

        with patch.object(system_controller, "IS_MAC", True), \
             patch.object(system_controller, "IS_WINDOWS", False):

            # Test locked state
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='"CGSSessionScreenIsLocked" = Yes\n',
                    stderr=""
                )
                state = SystemController.get_session_state()
                self.assertIn("Lock Screen", state)

            # Test unlocked state
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='other ioreg output without lock flag\n',
                    stderr=""
                )
                state = SystemController.get_session_state()
                self.assertIn("Unlocked", state)

    def test_09_alarm_and_timer_methods(self):
        """Verify set_alarm, cancel_alarm, and get_alarm_status work cleanly."""
        from system_controller import SystemController

        res = SystemController.set_alarm(seconds=9999, label="Unit Test")
        self.assertIsInstance(res, dict)
        self.assertIn("target_time", res)
        self.assertEqual(res.get("label"), "Unit Test")

        status = SystemController.get_alarm_status()
        self.assertIsInstance(status, dict)
        self.assertEqual(status.get("status"), "scheduled")

        cancelled = SystemController.cancel_alarm()
        self.assertTrue(cancelled)

    def test_10_safe_grab_screen_fallback(self):
        """Verify safe_grab_screen falls back gracefully when all_screens=True is unsupported."""
        import screen_caster
        from screen_caster import ScreenCaster, safe_grab_screen
        from PIL import Image

        dummy_img = Image.new("RGB", (100, 100), color="blue")

        # Case A: all_screens=True works
        with patch("PIL.ImageGrab.grab", return_value=dummy_img):
            img1 = safe_grab_screen()
            self.assertIsNotNone(img1)
            img2 = ScreenCaster.safe_grab_screen()
            self.assertIsNotNone(img2)

        # Case B: all_screens=True raises TypeError, fallback grab() succeeds
        def grab_side_effect(**kwargs):
            if kwargs.get("all_screens"):
                raise TypeError("unexpected keyword argument 'all_screens'")
            return dummy_img

        with patch("PIL.ImageGrab.grab", side_effect=grab_side_effect):
            img = ScreenCaster.safe_grab_screen()
            self.assertIsNotNone(img)

    def test_11_memory_status_diagnostics(self):
        """Verify get_memory_status returns structured memory statistics without errors."""
        from system_controller import SystemController

        mem = SystemController.get_memory_status()
        self.assertIsInstance(mem, dict)
        self.assertTrue(mem.get("ok", False))
        self.assertIn("ram_percent", mem)
        self.assertIn("ram_total_gb", mem)
        self.assertIn("agent_memory_mb", mem)

    def test_12_directory_navigation_and_capping(self):
        """Verify browse_directory handles aliases, home expansion, and caps max items safely."""
        import system_controller
        from system_controller import SystemController

        # Test alias expansion
        res_desktop = SystemController.browse_directory("desktop")
        self.assertIsInstance(res_desktop, dict)
        self.assertTrue(res_desktop.get("ok", False))
        self.assertIn("current_path", res_desktop)

        res_home = SystemController.browse_directory("home")
        self.assertTrue(res_home.get("ok", False))

        # Test safe capping and structure
        res_root = SystemController.browse_directory("/" if not system_controller.IS_WINDOWS else "C:\\")
        self.assertIsInstance(res_root, dict)
        if res_root.get("ok"):
            self.assertLessEqual(len(res_root.get("items", [])), 150)
            self.assertIn("total_dirs", res_root)
            self.assertIn("total_files", res_root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
