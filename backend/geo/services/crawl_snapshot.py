"""crawl_snapshot — 每天跑一次 AI 爬虫日志分析,把结果存进**共享数据库**.

prod 与 test 共用同一个库.要求:数据值只用正式环境的 —— 所以:
  - **只有 prod 写**:prod 系统 crontab 调本模块 __main__(读 prod nginx 日志,
    写 crawl_snapshot 单行).test **不跑** analysis,也不通过 web 触发重算.
  - **prod + test 都读同一行** → test 打开页面看到的就是正式环境的数据.

存储用幂等 `CREATE TABLE IF NOT EXISTS` + 单行 upsert,不走 alembic ——
避免给共享库加 migration、避免 prod 重启时 alembic 链出错拖垮启动.
crawl_snapshot 是缓存型产物(非核心域数据),这个取舍合理.

cron(仅 prod):
  5 3 * * * cd /home/ubuntu/Dev/geo/backend && ./.venv/bin/python -m geo.services.crawl_snapshot >> data/crawl_snapshot.log 2>&1
"""

import json
import os
from datetime import datetime, timezone

from sqlalchemy import text

from geo.database import SessionLocal
from geo_checker.modes.crawl_check import analyze_crawl_logs, resolve_log_paths

_LOG_GLOB = os.getenv("GEO_ACCESS_LOG_GLOB", "/var/log/nginx/access.log*")

_EMPTY = {
    "files": [], "total_size_mb": 0, "total_lines": 0, "parsed_lines": 0,
    "period": {"first": None, "last": None}, "total_bot_requests": 0,
    "bots": [], "missing_critical": [], "missing_optional": [],
}

_DDL = (
    "CREATE TABLE IF NOT EXISTS crawl_snapshot "
    "(id INTEGER PRIMARY KEY, generated_at VARCHAR, data TEXT)"
)


def build_snapshot() -> dict:
    """跑分析(读本机 nginx 日志),返回结构化结果 + 元数据."""
    files = resolve_log_paths(_LOG_GLOB)
    data = analyze_crawl_logs(files) if files else dict(_EMPTY)
    data["log_glob"] = _LOG_GLOB
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return data


def build_and_store() -> dict:
    """跑分析 + 写共享库单行(id=1).只应在 prod 上跑(读 prod 日志)."""
    data = build_snapshot()
    payload = json.dumps(data, ensure_ascii=False)
    db = SessionLocal()
    try:
        db.execute(text(_DDL))
        res = db.execute(
            text("UPDATE crawl_snapshot SET generated_at=:g, data=:d WHERE id=1"),
            {"g": data["generated_at"], "d": payload},
        )
        if res.rowcount == 0:
            db.execute(
                text("INSERT INTO crawl_snapshot (id, generated_at, data) VALUES (1, :g, :d)"),
                {"g": data["generated_at"], "d": payload},
            )
        db.commit()
    finally:
        db.close()
    return data


def load_snapshot() -> dict | None:
    """从共享库读最新快照.表还没建(prod 没跑过)时返回 None."""
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT data FROM crawl_snapshot WHERE id=1")).first()
        return json.loads(row[0]) if row else None
    except Exception:
        return None
    finally:
        db.close()


if __name__ == "__main__":
    d = build_and_store()
    print(
        f"[crawl_snapshot] {d.get('generated_at')} "
        f"bots={len(d.get('bots', []))} requests={d.get('total_bot_requests')} -> DB crawl_snapshot"
    )
