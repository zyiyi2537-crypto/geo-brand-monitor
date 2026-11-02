"""IM 事件跨 worker 去重 —— Redis SETNX 优先,Redis 不可用时回退进程内存。

飞书/企微/钉钉都是「至少一次」投递且会超时重投。uvicorn 多 worker 时进程内 dict
各存一份,重投打到别的 worker 就会被重复处理(同一条消息回两遍)。用 Redis 共享去重根治;
没有 Redis 时回退到进程内存(单 worker 仍有效)。
"""
from __future__ import annotations

import os
import time

try:
    import redis.asyncio as _aioredis
except ImportError:  # pragma: no cover
    _aioredis = None

_redis_client = None
_redis_down = False
_mem: dict[str, float] = {}


def _get_redis():
    global _redis_client, _redis_down
    if _aioredis is None or _redis_down:
        return None
    if _redis_client is None:
        url = (os.environ.get("REDIS_URL") or "").strip() or "redis://127.0.0.1:6379/0"
        try:
            _redis_client = _aioredis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        except Exception:  # noqa: BLE001
            _redis_down = True
            return None
    return _redis_client


async def seen_before(key: str, ttl: int = 600) -> bool:
    """True = 该 key 已处理过(重复事件,应丢弃);False = 首见。空 key 视为非重复。"""
    global _redis_down
    if not key:
        return False
    r = _get_redis()
    if r is not None:
        try:
            ok = await r.set(f"agent:im:seen:{key}", "1", nx=True, ex=ttl)
            return not ok          # set 成功=首见;未 set(已存在)=重复
        except Exception:  # noqa: BLE001
            _redis_down = True      # Redis 抽风则永久回退内存,避免每条都等超时
    now = time.time()
    for k in [k for k, t in _mem.items() if now - t > ttl]:
        _mem.pop(k, None)
    if key in _mem:
        return True
    _mem[key] = now
    return False
