"""Session persistence for browser engine adapters.

Stores and retrieves full Playwright storage_state (cookies + localStorage)
per-engine so sessions survive across runs without requiring re-login.

Playwright storage_state format:
{
  "cookies": [...],
  "origins": [
    {
      "origin": "https://chat.deepseek.com",
      "localStorage": [{"name": "key", "value": "val"}, ...]
    }
  ]
}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


_SESSION_DIR = Path(os.environ.get(
    "BROWSER_SESSION_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "browser_sessions"),
))


def _ensure_dir() -> None:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)


def save_storage_state(engine_name: str, storage_state: dict) -> None:
    """Persist full storage_state (cookies + localStorage) to disk."""
    _ensure_dir()
    path = _SESSION_DIR / f"{engine_name}.json"
    path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2))


def load_storage_state(engine_name: str) -> Optional[dict]:
    """Load previously saved storage_state, or None if no session exists.

    Handles both new format (full storage_state with origins) and legacy
    format (plain cookie list) for backward compatibility.
    """
    path = _SESSION_DIR / f"{engine_name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # New format: {"cookies": [...], "origins": [...]}
        if isinstance(data, dict) and "cookies" in data:
            return data
        # Legacy format: plain list of cookies
        if isinstance(data, list):
            return {"cookies": data, "origins": []}
        return None
    except (json.JSONDecodeError, OSError):
        return None


def clear_session(engine_name: str) -> None:
    """Remove saved session for the given engine."""
    path = _SESSION_DIR / f"{engine_name}.json"
    path.unlink(missing_ok=True)


# Backward-compatible aliases
def load_cookies(engine_name: str) -> Optional[list]:
    """Load cookies only (backward compat). Returns cookie list or None."""
    state = load_storage_state(engine_name)
    if state:
        return state.get("cookies")
    return None


def save_cookies(engine_name: str, cookies: list) -> None:
    """Save cookies only (backward compat). Preserves existing localStorage."""
    existing = load_storage_state(engine_name) or {}
    existing["cookies"] = cookies
    if "origins" not in existing:
        existing["origins"] = []
    save_storage_state(engine_name, existing)


# ── Profile persistence (for cross-machine fingerprint consistency) ──


def save_engine_profile(engine_name: str, profile: dict) -> None:
    """Save fingerprint profile alongside storage_state for cross-machine reuse.

    CF-gated engines (ChatGPT / Gemini / Grok) require the same UA/platform
    profile at login time and runtime. The profile dict is saved next to the
    storage_state JSON so they can be uploaded together.
    """
    _ensure_dir()
    path = _SESSION_DIR / f"{engine_name}_profile.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False))


def load_engine_profile(engine_name: str) -> Optional[dict]:
    """Load previously saved fingerprint profile, or None if not found."""
    path = _SESSION_DIR / f"{engine_name}_profile.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
