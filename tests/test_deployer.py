import os
from pathlib import Path
import pytest
from network_deployer import AGENT_CORE_FILES, OPTIONAL_LARGE_FILES, get_local_ip, get_subnet, DEPLOY_DIR


def test_agent_core_files_exist():
    """Verify that every essential agent core file exists in the repository."""
    for filename in AGENT_CORE_FILES:
        filepath = os.path.join(DEPLOY_DIR, filename)
        assert os.path.exists(filepath), f"Essential agent file missing from project: {filename}"


def test_agent_core_files_contain_no_bot_or_secrets():
    """Verify target PCs only receive agent files, NEVER bot/secret/master files."""
    forbidden = [
        "bot.py",
        "config.py",
        ".env",
        "fleet.json",
        "fleet_deploy_log.json",
        "Dockerfile",
        "docker-compose.yml",
        "requirements-bot.txt",
    ]
    for filename in forbidden:
        assert filename not in AGENT_CORE_FILES, f"Forbidden master file leaked to target PCs: {filename}"


def test_agent_core_files_includes_uninstaller():
    """Verify that uninstall.bat is included in core files for clean agent removal on target PCs."""
    assert "uninstall.bat" in AGENT_CORE_FILES
    assert "agent.py" in AGENT_CORE_FILES
    assert "fleet_relay.py" in AGENT_CORE_FILES
    assert "system_controller.py" in AGENT_CORE_FILES
    assert "screen_caster.py" in AGENT_CORE_FILES
    assert "requirements_agent.txt" in AGENT_CORE_FILES
    assert "start_agent.bat" in AGENT_CORE_FILES
    assert "start_agent_hidden.vbs" in AGENT_CORE_FILES


def test_network_ip_and_subnet_format():
    """Verify IP and subnet parsing functions return valid formats."""
    ip = get_local_ip()
    parts = ip.split(".")
    assert len(parts) == 4
    for p in parts:
        assert p.isdigit()
        assert 0 <= int(p) <= 255

    subnet = get_subnet()
    sub_parts = subnet.split(".")
    assert len(sub_parts) == 3
    for p in sub_parts:
        assert p.isdigit()
        assert 0 <= int(p) <= 255
