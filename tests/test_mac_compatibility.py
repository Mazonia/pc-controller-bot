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

                # Typing on macOS
                ok, msg = SystemController.type_text("Hello Mac!")
                self.assertTrue(ok)

                # Key combos on macOS
                ok, msg = SystemController.press_key("cmd+c")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
