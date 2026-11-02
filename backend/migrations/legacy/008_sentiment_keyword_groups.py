"""Migration: add keyword_groups_json column to sentiment_accounts.

Stores structured keyword categorization (entity / legal / exec / project /
competitor / custom) used by the new categorical keyword editor — replaces
the flat keyword list as the primary source. Old keywords_json is kept as a
fallback for accounts that never opted into the editor.

Idempotent: skips if the column already exists or the table is missing.

Usage:
    cd backend && python migrations/008_sentiment_keyword_groups.py
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
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sentiment_accounts'"
        )
        if not cur.fetchone():
            print("[migrate] sentiment_accounts table not present — Base.metadata.create_all will create it with the new column")
            return
        cur.execute("PRAGMA table_info(sentiment_accounts)")
        columns = [row[1] for row in cur.fetchall()]
        if "keyword_groups_json" in columns:
            print("[migrate] keyword_groups_json already exists — nothing to do")
            return
        cur.execute(
            "ALTER TABLE sentiment_accounts ADD COLUMN keyword_groups_json TEXT DEFAULT '[]'"
        )
        conn.commit()
        print("[migrate] added keyword_groups_json column to sentiment_accounts")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
