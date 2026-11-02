"""Migration: refresh membership tier pricing + quotas to the new 2026-04 plan.

Changes vs. the previous seed:
- free         ¥0 (cny, unlimited)     → $0  (usd, 3 checks/mo), renamed 注册会员
- pro          ¥19.9 (cny, 10/mo)      → $9.99 (usd, 20 checks/mo)
- starter      $2,000 service          → $999 /月 saas, unlimited
- growth       $4,000 service          → $2,500 /月 saas, unlimited
- scale        $8,000 service          → Get-a-Demo service (price=0, unlimited)

Idempotent: re-running UPDATEs against already-migrated rows is a no-op.
features / not_included / features_json are JSON-encoded strings. Keeping the
mapping in one place means future edits to the shape don't require touching
this script.

Usage:
    cd backend && python migrations/003_membership_plan_update.py
"""
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main():
    # Import lazily so the script can be run without the full app bootstrapped.
    from geo.services.membership_service import DEFAULT_MEMBERSHIPS
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
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memberships'"
        )
        if not cur.fetchone():
            print("[migrate] memberships table not found — skipping")
            return

        for data in DEFAULT_MEMBERSHIPS:
            features_json_str = (
                json.dumps(data["features_json"], ensure_ascii=False)
                if data.get("features_json") is not None
                else None
            )
            allowed_str = (
                json.dumps(data["allowed_check_categories"], ensure_ascii=False)
                if data.get("allowed_check_categories") is not None
                else None
            )
            cur.execute(
                """
                UPDATE memberships
                   SET name = ?,
                       price = ?,
                       currency = ?,
                       period = ?,
                       description = ?,
                       popular = ?,
                       tier_type = ?,
                       monthly_check_quota = ?,
                       allowed_check_categories = ?,
                       features = ?,
                       not_included = ?,
                       features_json = ?,
                       display_order = ?
                 WHERE slug = ?
                """,
                (
                    data["name"],
                    data["price"],
                    data["currency"],
                    data["period"],
                    data["description"],
                    1 if data["popular"] else 0,
                    data["tier_type"],
                    data["monthly_check_quota"],
                    allowed_str,
                    json.dumps(data["features"], ensure_ascii=False),
                    json.dumps(data["not_included"], ensure_ascii=False),
                    features_json_str,
                    data["display_order"],
                    data["slug"],
                ),
            )
            if cur.rowcount:
                print(f"[migrate] updated {data['slug']}")
            else:
                # Row missing (fresh DB that never had the old seed) — insert it.
                cur.execute(
                    """
                    INSERT INTO memberships (
                        slug, name, price, currency, period, description,
                        popular, tier_type, monthly_check_quota,
                        allowed_check_categories, features, not_included,
                        features_json, display_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["slug"],
                        data["name"],
                        data["price"],
                        data["currency"],
                        data["period"],
                        data["description"],
                        1 if data["popular"] else 0,
                        data["tier_type"],
                        data["monthly_check_quota"],
                        allowed_str,
                        json.dumps(data["features"], ensure_ascii=False),
                        json.dumps(data["not_included"], ensure_ascii=False),
                        features_json_str,
                        data["display_order"],
                    ),
                )
                print(f"[migrate] inserted {data['slug']}")

        conn.commit()
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
