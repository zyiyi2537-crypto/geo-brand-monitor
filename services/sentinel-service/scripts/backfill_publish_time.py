"""一次性回填:给存量 posts 补 publish_time(发布日期)。

背景:早期入库的帖子大量 publish_time=NULL(搜索引擎结果页未解析到发布时间)。
展示层的新鲜度闸门按 COALESCE(publish_time, ingested_at) 判断,NULL 会回退到
"入库时间"——于是"今天爬到的 2024 年文章"被当成今天的内容露出来。本脚本用
search.pipeline.extract_publish_date 从 title+content 里尽力抽一个绝对日期回填,
让这些陈旧内容被新鲜度闸门正确挡掉。

只回填 publish_time IS NULL 的行;抽不到日期的保持 NULL(不瞎猜)。幂等,可重跑。

用法(在 sentinel-service 目录,带 DATABASE_URL 环境):
    .venv/bin/python -m scripts.backfill_publish_time            # 全部 tenant_* schema
    .venv/bin/python -m scripts.backfill_publish_time 1 1000001  # 指定 account_id
    DRY_RUN=1 .venv/bin/python -m scripts.backfill_publish_time  # 只统计不写库
"""
from __future__ import annotations

import os
import sys

import psycopg
from psycopg.rows import dict_row

from search.pipeline import extract_publish_date

DRY_RUN = os.environ.get("DRY_RUN", "") not in ("", "0", "false", "False")


def _list_tenant_schemas(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE 'tenant_%' ORDER BY schema_name"
        )
        return [r["schema_name"] for r in cur.fetchall()]


def backfill_schema(conn: psycopg.Connection, schema: str) -> tuple[int, int]:
    """返回 (扫描数, 回填数)。"""
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{schema}", public')
        cur.execute(
            "SELECT source, post_id, title, content FROM posts "
            "WHERE publish_time IS NULL"
        )
        rows = cur.fetchall()
    scanned = len(rows)
    filled = 0
    for r in rows:
        d = extract_publish_date(f"{r.get('title') or ''} {r.get('content') or ''}")
        if not d:
            continue
        filled += 1
        if not DRY_RUN:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE posts SET publish_time = %s "
                    "WHERE source = %s AND post_id = %s AND publish_time IS NULL",
                    (d, r["source"], str(r["post_id"])),
                )
    if not DRY_RUN:
        conn.commit()
    return scanned, filled


def main() -> None:
    dburl = os.environ.get("DATABASE_URL", "")
    if not dburl:
        sys.exit("DATABASE_URL 未设置")
    ids = [a for a in sys.argv[1:] if a.isdigit()]
    conn = psycopg.connect(dburl, row_factory=dict_row)
    try:
        if ids:
            schemas = [f"tenant_{int(i)}" for i in ids]
        else:
            schemas = _list_tenant_schemas(conn)
        total_scanned = total_filled = 0
        for sch in schemas:
            try:
                scanned, filled = backfill_schema(conn, sch)
            except psycopg.Error as e:
                conn.rollback()
                print(f"  {sch}: ERROR {e}")
                continue
            total_scanned += scanned
            total_filled += filled
            print(f"  {sch}: null={scanned} filled={filled}"
                  + (" (dry-run)" if DRY_RUN else ""))
        print(f"DONE schemas={len(schemas)} scanned_null={total_scanned} "
              f"filled={total_filled}" + (" (dry-run)" if DRY_RUN else ""))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
