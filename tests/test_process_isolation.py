import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from system_controller import SystemController
from bot import ensure_single_bot_instance


def test_kill_process_blocks_blanket_python_termination():
    """Verify that kill_process by name refuses to kill python.exe to protect other Python apps like trading bots."""
    for name in ["python.exe", "python", "pythonw.exe", "PYTHON.EXE"]:
        ok, msg = SystemController.kill_process(name)
        assert ok is False
        assert "Safety Shield" in msg
        assert "trading bots" in msg.lower() or "other running python" in msg.lower()


def test_kill_process_blocks_system_critical_processes():
    """Verify critical OS processes cannot be terminated."""
    for sys_proc in ["csrss.exe", "smss.exe", "services.exe", "wininit.exe", "lsass.exe"]:
        ok, msg = SystemController.kill_process(sys_proc)
        assert ok is False
        assert "Safety Shield" in msg


def test_kill_process_protects_own_pid():
    """Verify Sentinel refuses to terminate its own process PID."""
    my_pid = str(os.getpid())
    ok, msg = SystemController.kill_process(my_pid)
    assert ok is False
    assert "Sentinel's own process" in msg


def test_kill_process_allows_safe_pid_termination():
    """Verify valid non-protected PIDs can still be terminated when explicitly targeted."""
    mock_proc = MagicMock()
    mock_proc.name.return_value = "notepad.exe"

    with patch("psutil.Process", return_value=mock_proc):
        ok, msg = SystemController.kill_process("999999")
        assert ok is True
        assert "Killed process notepad.exe" in msg
        assert mock_proc.kill.called


def test_single_bot_instance_isolates_unrelated_python_processes():
    """
    Verify ensure_single_bot_instance does NOT terminate unrelated Python processes,
    such as trading bots, background services, or other user scripts.
    """
    my_pid = os.getpid()

    # Process 1: User's Trading Bot
    trader_proc = MagicMock()
    trader_proc.pid = 11111
    trader_proc.info = {
        "pid": 11111,
        "name": "python.exe",
        "cmdline": ["python.exe", "C:\\Users\\User\\TradingBot\\main.py", "--live"],
    }

    # Process 2: Another unrelated developer tool
    dev_proc = MagicMock()
    dev_proc.pid = 22222
    dev_proc.info = {
        "pid": 22222,
        "name": "python.exe",
        "cmdline": ["C:\\Python314\\python.exe", "-m", "http.server", "8000"],
    }

    # Process 3: Stale Sentinel instance from this directory
    stale_sentinel = MagicMock()
    stale_sentinel.pid = 33333
    cur_dir = str(Path(__file__).resolve().parent.parent).lower()
    stale_sentinel.info = {
        "pid": 33333,
        "name": "pc-sentinel.exe",
        "cmdline": [f"{cur_dir}\\pc-sentinel.exe", "bot.py"],
    }

    mock_processes = [trader_proc, dev_proc, stale_sentinel]

    with patch("psutil.process_iter", return_value=mock_processes):
        ensure_single_bot_instance()

        # Trader bot MUST NOT be terminated
        assert not trader_proc.terminate.called
        # Developer tool MUST NOT be terminated
        assert not dev_proc.terminate.called
        # Only the stale Sentinel bot from this directory should be terminated
        assert stale_sentinel.terminate.called


def test_storage_cleanup_path_traversal_protection(tmp_path):
    """Verify delete_storage_files strictly refuses to delete files outside allowed bot directories."""
    allowed_dir = tmp_path / "allowed_recordings"
    allowed_dir.mkdir()
    valid_file = allowed_dir / "valid_rec.mp4"
    valid_file.write_bytes(b"rec_data")

    outside_dir = tmp_path / "other_app_data"
    outside_dir.mkdir()
    sensitive_file = outside_dir / "trading_config.json"
    sensitive_file.write_bytes(b'{"key": "secret"}')

    # Attempt to delete both valid and outside sensitive files
    deleted_cnt, freed = SystemController.delete_storage_files(
        [str(valid_file), str(sensitive_file)],
        allowed_dirs=[allowed_dir]
    )

    # Valid file deleted
    assert not valid_file.exists()
    assert deleted_cnt == 1

    # Outside file protected and untouched!
    assert sensitive_file.exists()
    assert sensitive_file.read_bytes() == b'{"key": "secret"}'
