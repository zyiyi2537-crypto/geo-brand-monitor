"""Migration: add `currency` column to memberships and backfill per-tier values.

Background: Stripe Checkout was previously hardcoded to `currency = "usd"` in
StripeService.create_checkout_session, so a CNY-priced "检测会员" tier (price
19.9, intended ¥19.9/月) was being charged as $19.90 USD ≈ ¥144 in LIVE mode.
This migration introduces a per-tier currency column so domestic SaaS tiers
charge in CNY and overseas service tiers stay in USD.

Idempotent — safe to run repeatedly:
- ALTER TABLE memberships ADD COLUMN currency TEXT NOT NULL DEFAULT 'usd' (skip if exists)
- UPDATE existing rows by slug to the correct currency

Usage:
    cd backend && python migrations/002_membership_currency.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


SLUG_CURRENCY = {
    "free": "cny",
    "pro": "cny",
    "starter": "usd",
    "growth": "usd",
    "scale": "usd",
}


def alter_and_backfill_raw():
    """Use a raw sqlite3 connection so we can run ALTER TABLE before the
    SQLAlchemy ORM (which would error out if the new column is missing)."""
    from geo.database import settings

    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite:///"):
        print(f"[migrate] non-sqlite URL detected ({db_url}) — skipping raw ALTER")
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
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memberships'"
        )
        if not cur.fetchone():
            print("[migrate] memberships table not found — skipping")
            return

        cur.execute("PRAGMA table_info(memberships)")
        existing = {row[1] for row in cur.fetchall()}

        if "currency" not in existing:
            print("[migrate] ALTER TABLE memberships ADD COLUMN currency TEXT NOT NULL DEFAULT 'usd'")
            cur.execute(
                "ALTER TABLE memberships ADD COLUMN currency TEXT NOT NULL DEFAULT 'usd'"
            )
        else:
            print("[migrate] memberships.currency already exists, skipping ALTER")

        for slug, currency in SLUG_CURRENCY.items():
            cur.execute(
                "UPDATE memberships SET currency = ? WHERE slug = ? AND (currency IS NULL OR currency != ?)",
                (currency, slug, currency),
            )
            if cur.rowcount:
                print(f"[migrate] backfilled {slug} → {currency} ({cur.rowcount} row)")
            else:
                print(f"[migrate] {slug} already correct ({currency})")

        conn.commit()
    finally:
        conn.close()


def main():
    alter_and_backfill_raw()
    print("[migrate] done")


if __name__ == "__main__":
    main()
