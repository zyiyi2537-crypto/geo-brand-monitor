"""Xvfb (X Virtual Framebuffer) integration for headless servers.

Provides a virtual DISPLAY so Playwright can run in headed mode,
which is necessary for some anti-bot systems (e.g. ByteDance CAPTCHA)
that detect headless Chrome.
"""

from __future__ import annotations

import atexit
import os
import subprocess

_xvfb_process = None


def is_xvfb_available() -> bool:
    """Check if Xvfb is installed on the system."""
    try:
        result = subprocess.run(
            ["which", "Xvfb"], capture_output=True, timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


def is_display_active() -> bool:
    """Check if a DISPLAY is already set (Xvfb or real X server)."""
    return bool(os.environ.get("DISPLAY", "").strip())


def start_xvfb(display: str = ":99", screen: str = "1920x1080x24") -> bool:
    """Start Xvfb if not already running. Returns True if display is ready."""
    global _xvfb_process
    if is_display_active():
        return True
    if not is_xvfb_available():
        return False
    try:
        _xvfb_process = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", screen, "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = display
        import time
        time.sleep(0.5)
        return True
    except Exception:
        return False


def stop_xvfb() -> None:
    """Stop Xvfb if we started it."""
    global _xvfb_process
    if _xvfb_process:
        try:
            _xvfb_process.terminate()
            _xvfb_process.wait(timeout=5)
        except Exception:
            pass
        _xvfb_process = None


atexit.register(stop_xvfb)
