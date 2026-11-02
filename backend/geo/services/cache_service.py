"""Redis-backed report cache service.

设计目标:
- 所有 check 报表(默认 + 高级)统一走 Redis db=7,TTL 24 小时
- key 由 (url, mode, tier, include_fix, extra) SHA1 决定,同键 = 可共享
- value 走 gzip 压缩(报表 JSON 约 27 KB,压缩后 5-10 KB)
- Redis 不可用时静默降级(返回 None / set 时无操作),不让缓存层把业务打挂

key 命名规范:
    geo:report:<mode>:<sha1(url|tier|include_fix|extra)>

其中 mode 作为可见的层级(`default` / `visibility` / `entity` / `citation` /
`aeo` / `authority` / `crawl-test` / `compare`),便于运维用
`SCAN 0 MATCH 'geo:report:visibility:*'` 逐类排查。

使用方式:
    from geo.services.cache_service import get_cached_report, set_cached_report

    key = make_cache_key("default", url, tier="free", include_fix=True)
    cached = get_cached_report(key)
    if cached:
        return cached  # type: dict

    result = ...expensive check...
    set_cached_report(key, result, ttl_s=86400)

降级策略:
- Redis 连不上 / 超时 / 返回异常 → 日志 warn 一次,本次请求降级到"无缓存"
- 不允许 exception 冒泡到业务层,即便 Redis 完全宕机,API 依然正常响应(只是慢)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from typing import Any, Optional

import redis

_log = logging.getLogger(__name__)

# 默认 TTL 24 小时
DEFAULT_TTL_S = 24 * 60 * 60

# Redis 连接 URL。约定用 db=7(db 0/1 是其他应用的)。可通过 REDIS_URL
# 环境变量覆盖,方便开发/测试切库。运维约束见
# docs/engineering/checker-reliability-and-performance.md。
_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/7")

# 全局单例 Redis client。redis-py 的 Redis 对象自带连接池,线程安全。
# decode_responses=False 因为 value 是 gzipped bytes。
_NO_CACHE = os.environ.get("GEO_NO_CACHE", "").strip().lower() in ("1", "true", "yes")

if _NO_CACHE:
    _client: Optional[redis.Redis] = None
    _log.info("cache_service: cache disabled via GEO_NO_CACHE=1")
else:
    try:
        _client = redis.Redis.from_url(
            _REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            health_check_interval=30,
        )
        # 连通性探测,失败时保持 _client 但后续操作会 raise RedisError → 被我们吞掉
        _client.ping()
        _log.info("cache_service: Redis connected at %s", _REDIS_URL)
    except redis.RedisError as e:
        _log.warning("cache_service: Redis unavailable at %s: %s — cache disabled", _REDIS_URL, e)
        _client = None


def _stable_str(v: Any) -> str:
    """把任意 JSON-able 对象转成稳定字符串(排序 key)。"""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def make_cache_key(
    mode: str,
    url: str,
    *,
    tier: str = "free",
    include_fix: bool = True,
    extra: Any = None,
) -> str:
    """构造缓存 key。同一 (mode, url, tier, include_fix, extra) = 同一 key。"""
    payload = "|".join([
        url,
        tier,
        "1" if include_fix else "0",
        _stable_str(extra),
    ])
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"geo:report:{mode}:{h}"


def get_cached_report(key: str) -> Optional[dict]:
    """命中返回 dict,未命中 / Redis 不可用返回 None。永远不 raise。"""
    if _client is None:
        return None
    try:
        raw = _client.get(key)
        if raw is None:
            return None
        try:
            payload = gzip.decompress(raw)
        except OSError:
            # 历史遗留的非压缩值
            payload = raw
        return json.loads(payload)
    except redis.RedisError as e:
        _log.warning("cache_service.get: %s — treating as miss", e)
        return None
    except (ValueError, TypeError) as e:
        # JSON 解析失败,说明 value 坏了,丢弃
        _log.warning("cache_service.get: corrupt value for %s: %s", key, e)
        try:
            _client.delete(key)
        except redis.RedisError:
            pass
        return None


def set_cached_report(key: str, value: dict, ttl_s: int = DEFAULT_TTL_S) -> bool:
    """写入缓存。成功 True / 失败 / Redis 不可用 False。永远不 raise。"""
    if _client is None:
        return False
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(payload, compresslevel=6)
        _client.setex(key, ttl_s, compressed)
        return True
    except redis.RedisError as e:
        _log.warning("cache_service.set: %s — skipping cache write", e)
        return False
    except (TypeError, ValueError) as e:
        _log.warning("cache_service.set: serialization failed: %s", e)
        return False


def delete_cached_report(key: str) -> bool:
    """显式驱逐一条 cache。返回 True 如果成功,False 如果 Redis 不可用。"""
    if _client is None:
        return False
    try:
        _client.delete(key)
        return True
    except redis.RedisError as e:
        _log.warning("cache_service.delete: %s", e)
        return False


def is_available() -> bool:
    """检查 Redis 当前是否可用。API 层诊断用。"""
    if _client is None:
        return False
    try:
        _client.ping()
        return True
    except redis.RedisError:
        return False
