"""Migration: Membership v2 — 5 tier unified ladder.

Dev-environment script (no alembic). Idempotent:
- Adds the new columns on memberships (ALTER TABLE ADD COLUMN if missing)
- Creates user_check_usage table
- Creates sales_leads table
- Wipes user_memberships + memberships and reseeds the 5 default tiers

Usage (from repo root):
    cd backend && python -m migrations.001_membership_v2

The DDL step must run BEFORE importing any ORM service that queries the
memberships table, because the module-level `MembershipService()` eagerly
runs `SELECT count(*) FROM memberships` with the new schema.
"""
import sys
from pathlib import Path

# Make backend/ importable when invoked as a script
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MEMBERSHIP_NEW_COLUMNS = [
    ("slug", "TEXT"),
    ("tier_type", "TEXT NOT NULL DEFAULT 'saas'"),
    ("monthly_check_quota", "INTEGER NOT NULL DEFAULT 3"),
    ("allowed_check_categories", "TEXT"),
    ("features_json", "TEXT"),
    ("display_order", "INTEGER NOT NULL DEFAULT 0"),
]


def alter_memberships_table_raw():
    """Run ALTER TABLE via a raw sqlite3 connection, before importing the ORM."""
    from geo.database import settings

    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite:///"):
        print(f"[migrate] non-sqlite URL detected ({db_url}) — skipping raw ALTER")
        return

    # sqlite:///./data/geo_checker.db → ./data/geo_checker.db (relative to backend/)
    db_path_str = db_url.replace("sqlite:///", "", 1)
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = BACKEND_DIR / db_path
    if not db_path.exists():
        print(f"[migrate] {db_path} does not exist yet — skipping ALTER (create_all will build fresh schema)")
        return

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memberships'"
        )
        if not cur.fetchone():
            print("[migrate] memberships table not found — will be created by metadata")
            return

        cur.execute("PRAGMA table_info(memberships)")
        existing = {row[1] for row in cur.fetchall()}

        for name, ddl in MEMBERSHIP_NEW_COLUMNS:
            if name in existing:
                print(f"[migrate] memberships.{name} already exists, skipping")
                continue
            print(f"[migrate] ALTER TABLE memberships ADD COLUMN {name} {ddl}")
            cur.execute(f"ALTER TABLE memberships ADD COLUMN {name} {ddl}")
        conn.commit()
    finally:
        conn.close()


def create_new_tables():
    """Create any tables that don't yet exist (user_check_usage, sales_leads, etc.)."""
    from geo.database import Base, engine
    from geo.models import membership as _m  # noqa: F401  (register ORM)
    from geo.models import user as _u  # noqa: F401

    print("[migrate] create_all() — user_check_usage, sales_leads, etc.")
    Base.metadata.create_all(bind=engine)


def wipe_and_reseed():
    from sqlalchemy import text
    from geo.database import SessionLocal
    from geo.services.membership_service import MembershipService, DEFAULT_MEMBERSHIPS

    print("[migrate] wiping user_memberships + memberships")
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM user_memberships"))
        db.execute(text("DELETE FROM memberships"))
        db.commit()
    finally:
        db.close()

    print(f"[migrate] reseeding {len(DEFAULT_MEMBERSHIPS)} memberships")
    service = MembershipService()
    service.reseed_memberships()


def main():
    print("=" * 60)
    print("Migration 001: Membership v2 (5-tier ladder)")
    print("=" * 60)
    alter_memberships_table_raw()
    create_new_tables()
    wipe_and_reseed()
    print("[migrate] done.")


if __name__ == "__main__":
    main()
