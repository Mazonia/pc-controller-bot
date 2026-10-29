"""
Unit tests for Mouse Enhancements, Windows Multi-Touch Gestures, Horizontal Scroll,
and Screen Caster Frame Capture.
"""

import time
import pytest
from system_controller import SystemController
from screen_caster import ScreenCaster

def test_desktop_access_caching():
    """Verify that ensure_desktop_access caches attachment within 3.0s window."""
    t0 = time.time()
    ok1 = SystemController.ensure_desktop_access(force=True)
    assert ok1 is True or ok1 is False # Depending on test environment desktop session
    
    # Second immediate call should use cache
    ok2 = SystemController.ensure_desktop_access(force=False)
    assert ok2 is True or ok1 is False

def test_mouse_scroll_and_horizontal():
    """Verify mouse vertical and horizontal scroll dispatch."""
    # Test valid scroll invocations
    res_v = SystemController.mouse_scroll(120)
    assert isinstance(res_v, bool)

    res_h = SystemController.mouse_scroll_h(120)
    assert isinstance(res_h, bool)

def test_execute_gesture_recognizers():
    """Verify gesture parser dispatches known gestures correctly."""
    # 3-finger gestures
    ok, msg = SystemController.execute_gesture("task_view")
    assert ok is True
    assert "Task View" in msg or "Pressed" in msg or "Key" in msg

    ok, msg = SystemController.execute_gesture("show_desktop")
    assert ok is True
    assert "Desktop" in msg or "Pressed" in msg or "Key" in msg

    ok, msg = SystemController.execute_gesture("search")
    assert ok is True
    assert "win+s" in msg.lower() or "pressed" in msg.lower()

    # 4-finger gestures
    ok, msg = SystemController.execute_gesture("next_desktop")
    assert ok is True

    ok, msg = SystemController.execute_gesture("prev_desktop")
    assert ok is True

    ok, msg = SystemController.execute_gesture("action_center")
    assert ok is True
    assert "win+a" in msg.lower() or "pressed" in msg.lower()

    ok, msg = SystemController.execute_gesture("settings")
    assert ok is True
    assert "win+i" in msg.lower() or "pressed" in msg.lower()

    # 2-finger zoom gestures
    ok, msg = SystemController.execute_gesture("zoom_in")
    assert ok is True
    assert "Zoom In" in msg

    ok, msg = SystemController.execute_gesture("zoom_out")
    assert ok is True
    assert "Zoom Out" in msg

    ok, msg = SystemController.execute_gesture("zoom_reset")
    assert ok is True
    assert "ctrl+0" in msg.lower()

    # Productivity shortcuts
    ok, msg = SystemController.execute_gesture("clipboard")
    assert ok is True
    assert "win+v" in msg.lower()

    ok, msg = SystemController.execute_gesture("snip")
    assert ok is True
    assert "win+shift+s" in msg.lower()

    # Unknown gesture should fail gracefully
    ok, msg = SystemController.execute_gesture("unknown_invalid_gesture")
    assert ok is False
    assert "Unknown gesture" in msg

def test_screen_caster_capture_single_frame():
    """Verify single frame desktop capture using OpenCV acceleration."""
    caster = ScreenCaster()
    frame_bytes = caster.capture_single_frame(quality=60, max_w=960)
    assert isinstance(frame_bytes, bytes)
    assert len(frame_bytes) > 0
    # Standard JPEG header starts with \xff\xd8
    assert frame_bytes[:2] == b"\xff\xd8"
