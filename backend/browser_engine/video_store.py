"""Video snapshot storage management for browser engine recordings.

Stores MP4 recordings of Playwright browser sessions in
data/snapshots/{engine}/{date}_{query_hash}.mp4.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from pathlib import Path

_SNAPSHOT_BASE = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def get_snapshot_dir(engine_name: str) -> Path:
    """Return (and create) the snapshot directory for an engine."""
    d = _SNAPSHOT_BASE / engine_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_video_filename(engine_name: str, query: str) -> str:
    """Produce a filename like 2026-04-27_deepseek_a1b2c3.webm."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
    return f"{date_str}_{engine_name}_{query_hash}.webm"


def should_record() -> bool:
    """Check if video recording is enabled via environment variable."""
    return os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")


async def get_video_path(page) -> str | None:
    """Get the video file path from a Playwright page, or None."""
    try:
        if page.video:
            return await page.video.path()
    except Exception:
        pass
    return None


def cleanup_old_snapshots(max_age_days: int = 30) -> int:
    """Delete snapshot files older than max_age_days. Returns count deleted."""
    if not _SNAPSHOT_BASE.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in _SNAPSHOT_BASE.rglob("*.mp4"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    return deleted
