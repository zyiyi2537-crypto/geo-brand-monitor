"""Per-request structured log for all /api/check* endpoints.

写一条 JSONL 到独立文件 backend/logs/requests.jsonl,每个 API 请求一行。
不影响现有 geo.timing(那个是 per-check_* 函数的细粒度)和 journald
(那里仍然有完整的 app 日志)。

用法(每个 check 端点加两行):

    from geo.utils.request_log import request_log

    @router.post("/check/anonymous")
    async def check_anonymous(body, request, response):
        ...
        with request_log("check.anonymous", "default", body.url,
                         anon_id=client_id, tier="free") as rec:
            result = await asyncio.to_thread(run_geo_check, ...)
            rec["score"] = result.score
            rec["grade"] = result.grade
            return result

每条日志格式:

    {
      "request_id": "a1b2c3d4",
      "endpoint": "check.anonymous",
      "mode": "default",
      "url": "https://moltspay.com",
      "user_id": null,
      "anon_id": "cookie-xxx",
      "tier": "free",
      "started_at": "2026-04-17T10:30:45.000+00:00",
      "finished_at": "2026-04-17T10:30:45.123+00:00",
      "duration_ms": 123,
      "status": 200,
      "score": 80,            # optional,由 caller 填
      "grade": "A",
      "error": null
    }

错误路径(caller 抛异常)也会记录,`status` 默认 500,`error` 填
异常的 repr,方便后期事故排查。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Dict, Any

_log = logging.getLogger("geo.request")
_log.setLevel(logging.INFO)
_log.propagate = True  # 仍然冒泡到 root logger,journald 也能看到

_LOG_FILE: Optional[str] = None


def _date_suffix_namer(default_name: str) -> str:
    """把 TimedRotatingFileHandler 默认的 "requests.jsonl.2026-04-17" 名字
    改成 "requests-2026-04-17.jsonl",让 .jsonl 扩展名保留,IDE 语法高亮
    正常,`jq ... requests-2026-04-*.jsonl` 通配跨日查询方便。"""
    directory, filename = os.path.split(default_name)
    prefix = "requests.jsonl."
    if filename.startswith(prefix):
        date = filename[len(prefix):]
        return os.path.join(directory, f"requests-{date}.jsonl")
    return default_name


def configure_request_log(log_dir: str = "logs", backup_count: int = 30) -> str:
    """幂等地配置 FileHandler。在 main.py app 启动时调一次即可。

    轮转策略:**每日 UTC 00:00 切割**。当天活跃文件始终叫
    `requests.jsonl`,午夜过后它会被改名成 `requests-YYYY-MM-DD.jsonl`
    (昨天的),然后新的 `requests.jsonl` 继续写今天的数据。

    Args:
        log_dir: 相对于当前 CWD 的日志目录(backend 运行时 CWD 是 /backend)
        backup_count: 保留多少天的老 log(默认 30 天)

    Returns:
        实际写入的完整路径。如果 handler 已经配置过,直接返回已有的路径。
    """
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE  # 已配置

    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "requests.jsonl")

    handler = TimedRotatingFileHandler(
        path,
        when="midnight",   # 每天 0:00 切
        interval=1,        # 每 1 天
        backupCount=backup_count,
        utc=True,          # 服务器也是 UTC,显式声明避免未来改时区踩坑
        encoding="utf-8",
    )
    # suffix 决定切割后文件名的日期部分格式;默认对 'midnight' 就是 %Y-%m-%d
    handler.suffix = "%Y-%m-%d"
    # namer 改变最终文件名:把 .jsonl.2026-04-17 改成 -2026-04-17.jsonl
    handler.namer = _date_suffix_namer
    # 每一行就是纯 JSON,不加时间前缀(JSON 里已经有 started_at / finished_at)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(handler)
    _LOG_FILE = os.path.abspath(path)
    _log.info(json.dumps({
        "event": "request_log_init",
        "path": _LOG_FILE,
        "rotation": "daily_utc_midnight",
        "backup_days": backup_count,
    }, ensure_ascii=False))
    return _LOG_FILE


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def request_log(
    endpoint: str,
    mode: str,
    url: str,
    *,
    user_id: Optional[int] = None,
    anon_id: Optional[str] = None,
    tier: str = "free",
) -> Dict[str, Any]:
    """Context manager。进入 block 时记开始时间,离开时记结束 + 写 JSONL。

    Caller 可以在 block 内往 yield 的 dict 塞额外字段(score / grade /
    cache_hit 等),它们会合并进最终的日志条目。

    异常会被捕获 → 打日志(status=500,error=repr(exc))→ 重新 raise,
    所以业务语义不受影响,只是日志完整。
    """
    rid = uuid.uuid4().hex[:12]
    started = time.time()
    record: Dict[str, Any] = {
        "request_id": rid,
        "endpoint": endpoint,
        "mode": mode,
        "url": url,
        "user_id": user_id,
        "anon_id": anon_id,
        "tier": tier,
        "started_at": _iso_now(),
    }
    status = 200
    error: Optional[str] = None
    try:
        yield record
    except BaseException as exc:
        status = getattr(exc, "status_code", 500)
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["finished_at"] = _iso_now()
        record["duration_ms"] = int((time.time() - started) * 1000)
        record.setdefault("status", status)
        if error is not None:
            record["error"] = error
        try:
            _log.info(json.dumps(record, ensure_ascii=False, default=str))
        except Exception:
            # 日志层不能让业务挂掉
            pass
