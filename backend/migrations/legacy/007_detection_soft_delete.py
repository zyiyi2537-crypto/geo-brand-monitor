"""Migration: add deleted_at column to detection_records for soft delete.

Instead of permanently removing records, deletion now sets deleted_at so
the record remains visible (with strikethrough styling) but cannot be
viewed or operated on further.

Idempotent: re-running is a no-op (checks for column existence first).

Usage:
    cd backend && python migrations/007_detection_soft_delete.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main():
    from geo.database import settings

    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite:///"):
        print(f"[migrate] non-sqlite URL detected ({db_url}) — aborting")
        return

    db_path_str = db_url.replace("sqlite:///", "", 1)
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = BACKEND_DIR / db_path
    if not db_path.exists():
        print(f"[migrate] {db_path} does not exist yet — nothing to migrate")
        return

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Check if column already exists
        cur.execute("PRAGMA table_info(detection_records)")
        columns = [row[1] for row in cur.fetchall()]
        if "deleted_at" in columns:
            print("[migrate] deleted_at column already exists — nothing to do")
            return
        cur.execute("ALTER TABLE detection_records ADD COLUMN deleted_at DATETIME DEFAULT NULL")
        conn.commit()
        print("[migrate] added deleted_at column to detection_records")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
