"""Storage entrypoint:contextvar-aware connect 包装 + 重新导出 db 子模块.

多租户路由(取代历史的 6 层 monkey-patch):
- service.py 在请求入口 `current_account.set(account_id)`
- 业务子模块写 `from storage import connect; conn = connect()` 一律拿到当前
  contextvar 绑定的 PG schema(tenant_{N}.posts ...).
- 子模块的 `from storage import connect` 拷贝的是 **wrapper 函数引用**(就是
  下面这个 `connect`),wrapper 在每次调用时才读 contextvar,所以引用快照
  问题自动消失.
"""
from contextvars import ContextVar
from typing import Optional

from .db import (
    DATABASE_URL,
    DEFAULT_DB_PATH,
    connect as _db_connect,
    init_schema,
    upsert_post,
    upsert_analysis,
    insert_brief,
    insert_draft,
    posts_for_symbol,
    posts_missing_analysis,
    analyses_for_symbol,
    analyses_count_for_symbol,
    analyses_for_day,
    brand_post_lookup,
    ingest_jsonl_dir,
    get_query_last_run,
    upsert_query_last_run,
)


# 当前请求绑定的 account_id;service.py 的 endpoint 入口 set,exit reset.
current_account: ContextVar[Optional[int]] = ContextVar("current_account", default=None)


def connect(arg=None):
    """获取 PG 连接.

    - `arg=None`:走 contextvar 路由,绑定当前请求的 tenant schema.
    - `arg` 为 int:显式 account_id,跳过 contextvar(CLI / 脚本用).
    - 其它类型(历史 Path/str db_path 参数):忽略,fallback 走 contextvar.
      这是给上游 yuqin 模块的兼容兜底,vm02 service 调用路径不走这条分支.
    """
    if isinstance(arg, int):
        aid: Optional[int] = arg
    else:
        aid = current_account.get()
    return _db_connect(aid)


__all__ = [
    "DATABASE_URL",
    "DEFAULT_DB_PATH",
    "current_account",
    "connect",
    "init_schema",
    "upsert_post",
    "upsert_analysis",
    "insert_brief",
    "insert_draft",
    "posts_for_symbol",
    "posts_missing_analysis",
    "analyses_for_symbol",
    "analyses_count_for_symbol",
    "analyses_for_day",
    "brand_post_lookup",
    "ingest_jsonl_dir",
    "get_query_last_run",
    "upsert_query_last_run",
]
