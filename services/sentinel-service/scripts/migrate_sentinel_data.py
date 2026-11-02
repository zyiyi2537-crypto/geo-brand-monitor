"""一次性:把 sentinel 5 个 account_*/yuqing.db 数据搬到 PG appdb 的
tenant_{N} schema.前置:`init_pg_schema --account N` 必须先跑过(本脚本只
搬数据,不建 schema).

DATABASE_URL 从环境读;每个 yuqing.db → PG schema tenant_{account_id}.

幂等:每张表先 TRUNCATE 再批插.

执行(在 vm02 sentinel 工作目录下):
    DATABASE_URL='postgresql://appuser:***@database.example.com:9000/appdb' \
    /opt/geo/backend/venv/bin/python -m scripts.migrate_sentinel_data
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import psycopg


DATABASE_URL = os.environ.get("DATABASE_URL") or ""
DATA_DIR = Path(
    os.environ.get(
        "SENTINEL_DATA_DIR",
        "/opt/geo/services/sentinel-service/data",
    )
)

TABLES = ["posts", "analyses", "briefs", "drafts", "query_runs"]
ID_TABLES = {"briefs", "drafts"}  # BIGSERIAL — 搬完要 setval


def migrate(account_id: int, src_path: Path) -> dict:
    schema = f"tenant_{account_id}"
    stats: dict[str, int | str] = {}

    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    try:
        with psycopg.connect(DATABASE_URL, autocommit=False) as dst:
            with dst.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}", public')

            for tbl in TABLES:
                try:
                    rows = src.execute(f"SELECT * FROM {tbl}").fetchall()
                except sqlite3.OperationalError:
                    stats[tbl] = "missing_in_src"
                    continue
                if not rows:
                    stats[tbl] = 0
                    continue
                cols = list(rows[0].keys())
                placeholders = ",".join(["%s"] * len(cols))
                col_list = ",".join(f'"{c}"' for c in cols)
                # briefs/drafts 有 IDENTITY id,要保留源 id → OVERRIDING SYSTEM VALUE
                override = (
                    "OVERRIDING SYSTEM VALUE "
                    if tbl in ID_TABLES else ""
                )
                with dst.cursor() as cur:
                    cur.execute(f'TRUNCATE "{tbl}"')
                    cur.executemany(
                        f'INSERT INTO "{tbl}" ({col_list}) '
                        f'{override}VALUES ({placeholders})',
                        [tuple(r[c] for c in cols) for r in rows],
                    )
                stats[tbl] = len(rows)

            # 重置 IDENTITY 序列起点,避免后续 INSERT 撞主键
            with dst.cursor() as cur:
                for tbl in ID_TABLES:
                    cur.execute(f'SELECT COALESCE(MAX(id), 0) AS m FROM "{tbl}"')
                    row = cur.fetchone()
                    m = row[0] if row else 0
                    if m:
                        seq_q = (
                            "SELECT setval("
                            "pg_get_serial_sequence(%s, 'id'), %s, true)"
                        )
                        cur.execute(seq_q, (f"{schema}.{tbl}", m))

            dst.commit()
    finally:
        src.close()

    return stats


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    any_done = False
    for d in sorted(DATA_DIR.glob("account_*")):
        try:
            account_id = int(d.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        src = d / "yuqing.db"
        if not src.exists():
            print(f"[skip] account_{account_id}: no yuqing.db")
            continue
        if src.stat().st_size == 0:
            print(f"[skip] account_{account_id}: yuqing.db is 0 bytes")
            continue
        try:
            stats = migrate(account_id, src)
            print(f"[ok]   account_{account_id}: {stats}")
            any_done = True
        except Exception as e:
            print(f"[FAIL] account_{account_id}: {e}", file=sys.stderr)
            raise

    if not any_done:
        print("WARNING: no account migrated", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
