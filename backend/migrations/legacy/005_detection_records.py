"""Migration: create detection_records table for persisted per-user GEO checks.

Personal center (`/account`) shows a history of checks the user has run.
Previously `/api/check` only bumped `user_check_usage.used_count`; now each
successful logged-in check also writes a row here so the frontend can list
and replay past results without re-running the checker.

Idempotent: re-running is a no-op. For fresh deployments the table is also
created by `Base.metadata.create_all` in geo/__init__.py — this script
exists so already-running dev databases pick up the new table without
restarting through the bootstrap path.

Usage:
    cd backend && python migrations/005_detection_records.py
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS detection_records (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                url             TEXT    NOT NULL,
                score           INTEGER,
                grade           TEXT,
                tier            TEXT,
                mode            TEXT    NOT NULL DEFAULT 'free',
                result_snapshot TEXT    NOT NULL,
                created_at      DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ix_detection_records_user_id ON detection_records (user_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ix_detection_records_created_at ON detection_records (created_at)"
        )
        conn.commit()
        print("[migrate] ensured detection_records table exists")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
