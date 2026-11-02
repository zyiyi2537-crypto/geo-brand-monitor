"""Migration: create anonymous_check_usage table for per-cookie anonymous quotas.

Adds a tracking table so unregistered visitors can be limited to 3 checks per
calendar month per browser, keyed by the `geo_anon_id` cookie the backend
sets on the first anonymous request (mirroring the registered free-tier
limit). For fresh deployments the table is created automatically by
`Base.metadata.create_all` in geo/__init__.py — this script exists only so
already-running databases pick up the new table without restarting through
the bootstrap path.

Idempotent: re-running is a no-op. Also handles the in-development case
where an earlier revision of this migration created the table with an
`ip_address` column — it renames the column to `client_id` so the schema
matches the ORM.

Usage:
    cd backend && python migrations/004_anonymous_check_usage.py
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
            CREATE TABLE IF NOT EXISTS anonymous_check_usage (
                client_id   VARCHAR(64) NOT NULL,
                year_month  TEXT        NOT NULL,
                used_count  INTEGER     NOT NULL DEFAULT 0,
                PRIMARY KEY (client_id, year_month)
            )
            """
        )
        # If a prior dev run created the table with `ip_address` instead of
        # `client_id`, rename it in-place. SQLite ≥ 3.25 supports RENAME COLUMN.
        cur.execute("PRAGMA table_info(anonymous_check_usage)")
        cols = {row[1] for row in cur.fetchall()}
        if "ip_address" in cols and "client_id" not in cols:
            cur.execute(
                "ALTER TABLE anonymous_check_usage RENAME COLUMN ip_address TO client_id"
            )
            print("[migrate] renamed ip_address → client_id")
        conn.commit()
        print("[migrate] ensured anonymous_check_usage table exists")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
