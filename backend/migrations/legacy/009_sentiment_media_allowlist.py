"""Migration: add media_allowlist_json column to sentiment_accounts.

存储用户为该账号选择的媒体平台白名单(平台 code 列表,例:["xueqiu","weibo"]).
空列表 = 全 15 个平台都跑(等同于 sentinel-service 的默认行为).

与 services/sentinel-service/search/plan.py 的 PLATFORM_CATALOG 对齐;
backend → sentinel 透传时由 sentinel_client 把 code 翻成域名.

Idempotent: skips if the column already exists or the table is missing.

Usage:
    cd backend && python migrations/009_sentiment_media_allowlist.py
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
        if "media_allowlist_json" in columns:
            print("[migrate] media_allowlist_json already exists — nothing to do")
            return
        cur.execute(
            "ALTER TABLE sentiment_accounts ADD COLUMN media_allowlist_json TEXT DEFAULT '[]'"
        )
        conn.commit()
        print("[migrate] added media_allowlist_json column to sentiment_accounts")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
