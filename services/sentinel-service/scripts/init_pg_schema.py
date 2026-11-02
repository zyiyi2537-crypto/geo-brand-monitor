"""为指定 account 在 PG 内创建 tenant schema + 5 张业务表.

用法(在 sentinel-service 工作目录下):
    DATABASE_URL=postgresql://appuser:***@host:port/appdb \
    python -m scripts.init_pg_schema --account 2

迁移脚本 deploy-test-env 的阶段 3.7 在 pgloader 拷数据前调一次,
确保目标 schema + 表结构齐全(pgloader 用 data only 模式不再建表).

幂等可重跑.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让 storage 包可 import — 跟 service.py 一样把仓库根挂上 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from storage import connect, init_schema   # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="init sentinel PG tenant schema")
    p.add_argument("--account", type=int, required=True, help="account_id (int)")
    args = p.parse_args()

    conn = connect(args.account)
    try:
        init_schema(conn)
        print(f"[init_pg_schema] tenant_{args.account} OK")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
