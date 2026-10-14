"""
Unit & Integration Tests: Process Isolation & Non-Interference Guarantees
Verifies that PC-Remote-Sentinel strictly isolates its process management and
NEVER terminates or interferes with external Python processes, trading bots,
or other applications on the system.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import psutil

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from bot import ensure_single_bot_instance


def test_ensure_single_instance_ignores_unrelated_python_process():
    """Verify that ensure_single_bot_instance ignores generic external Python scripts."""
    # Spawn a dummy external background python process
    dummy_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Give it a moment to initialize
        time.sleep(0.3)
        assert dummy_proc.poll() is None, "Dummy process failed to start"

        # Execute single bot instance cleanup
        ensure_single_bot_instance()

        # Verify dummy process is completely unharmed
        assert dummy_proc.poll() is None, "Generic external python process was wrongly killed!"
    finally:
        dummy_proc.kill()
        dummy_proc.wait()


def test_ensure_single_instance_ignores_bot_py_in_other_directories(tmp_path):
    """
    CRITICAL TEST:
    Verify that an external script named 'bot.py' in a DIFFERENT directory
    (e.g., XAUUSD-AI-Trading-Bot\\core\\bot.py) is NOT terminated.
    """
    other_dir = tmp_path / "other_bot_dir"
    other_dir.mkdir(parents=True, exist_ok=True)
    other_bot = other_dir / "bot.py"
    other_bot.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")

    external_bot_proc = subprocess.Popen(
        [sys.executable, str(other_bot)],
        cwd=str(other_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.4)
        assert external_bot_proc.poll() is None, "External bot.py process failed to start"

        # Execute our cleaner
        ensure_single_bot_instance()

        # The external bot in other_dir MUST STILL BE RUNNING
        assert external_bot_proc.poll() is None, (
            "External bot.py in another directory was wrongly terminated by ensure_single_bot_instance!"
        )
    finally:
        external_bot_proc.kill()
        external_bot_proc.wait()


def test_ensure_single_instance_ignores_agent_process():
    """Verify that ensure_single_bot_instance NEVER kills pc-sentinel-agent."""
    mock_agent = MagicMock()
    mock_agent.pid = 99999
    mock_agent.info = {
        "pid": 99999,
        "name": "pc-sentinel-agent.exe",
        "cmdline": ["pc-sentinel-agent.exe", "agent.py"],
        "exe": str(config.BASE_DIR / "pc-sentinel-agent.exe"),
    }

    with patch("psutil.process_iter", return_value=[mock_agent]):
        with patch("os.getpid", return_value=12345):
            ensure_single_bot_instance()

    # Agent terminate should NOT be called
    mock_agent.terminate.assert_not_called()


def test_ensure_single_instance_ignores_xau_trader():
    """Verify that ensure_single_bot_instance NEVER touches the XAUUSD Trading Bot."""
    mock_trader = MagicMock()
    mock_trader.pid = 88888
    mock_trader.info = {
        "pid": 88888,
        "name": "xau-trader.exe",
        "cmdline": ["xau-trader.exe", "main.py"],
        "exe": "C:\\Users\\Mazonia\\Desktop\\XAUUSD-AI-Trading-Bot\\xau-trader.exe",
    }

    with patch("psutil.process_iter", return_value=[mock_trader]):
        with patch("os.getpid", return_value=12345):
            ensure_single_bot_instance()

    mock_trader.terminate.assert_not_called()


def test_ensure_single_instance_terminates_only_own_duplicate():
    """Verify that an older duplicate instance of PC-Remote-Sentinel Commander IS terminated."""
    mock_stale_commander = MagicMock()
    mock_stale_commander.pid = 77777
    mock_stale_commander.info = {
        "pid": 77777,
        "name": "pc-sentinel.exe",
        "cmdline": ["pc-sentinel.exe", "bot.py"],
        "exe": str(config.BASE_DIR / "pc-sentinel.exe"),
    }

    with patch("psutil.process_iter", return_value=[mock_stale_commander]):
        with patch("os.getpid", return_value=12345):
            ensure_single_bot_instance()

    # Stale duplicate commander MUST be terminated
    mock_stale_commander.terminate.assert_called_once()


def test_port_isolation_and_no_collision():
    """Verify that ports used by PC-Remote-Sentinel and XAUUSD Trading Bot are distinct."""
    sentinel_agent_port = int(os.getenv("AGENT_PORT", "9010"))
    sentinel_stream_port = int(os.getenv("STREAM_PORT", "8585"))
    xau_dashboard_port = 8080

    ports = [sentinel_agent_port, sentinel_stream_port, xau_dashboard_port]
    # All 3 ports must be completely unique with zero collisions
    assert len(ports) == len(set(ports)), f"Port collision detected between services: {ports}"
