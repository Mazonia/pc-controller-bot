"""Test isolation: strong throw-away fleet secret, never the developer's real one."""
import os
import sys
from pathlib import Path

os.environ["FLEET_SECRET"] = "test-fleet-secret-for-unit-tests-only-0123"
os.environ["AGENT_SECRET"] = ""
os.environ.setdefault("ALLOW_INSECURE_DEFAULT_SECRET", "")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
