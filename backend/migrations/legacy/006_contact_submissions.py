"""Migration: create contact_submissions table for persisting contact form data.

Previously /api/contact only sent a confirmation email; now each submission
is also stored in the database for review.

Idempotent: re-running is a no-op. For fresh deployments the table is also
created by `Base.metadata.create_all` in geo/__init__.py.

Usage:
    cd backend && python migrations/006_contact_submissions.py
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

    import sqlite3

    db_path = db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='contact_submissions'"
    )
    if cur.fetchone():
        print("[migrate] contact_submissions table already exists — skipping")
        conn.close()
        return

    cur.execute("""
        CREATE TABLE contact_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            website TEXT NOT NULL,
            message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX ix_contact_submissions_id ON contact_submissions (id)")
    conn.commit()
    print("[migrate] contact_submissions table created")
    conn.close()


if __name__ == "__main__":
    main()
