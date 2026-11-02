"""登录态自动续期守护 —— 掉线(quarantined)的密码型账号自动重登,无需人工。

定时(ENGINE_REFRESH_INTERVAL_SEC,默认 900s)向后端拉 refresh-candidates(掉线 +
auth_type=password + 有加密凭证),解密 {identifier,password},跑 authorizer 重登 →
re-upload 续期(upsert 按 account_id 续,status 回 active,自动解隔离)。

需:ENGINE_SESSION_POOL_URL + service token + ENGINE_CRED_KEY 都就位才启用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

from . import crypto
from .authorizer import authorize_password
from .session_store import _POOL_URL, _POOL_TOKEN

_log = logging.getLogger("refresh-daemon")
_INTERVAL = int(os.environ.get("ENGINE_REFRESH_INTERVAL_SEC", "900"))
_BATCH = int(os.environ.get("ENGINE_REFRESH_BATCH", "5"))


def _enabled() -> bool:
    return bool(_POOL_URL and _POOL_TOKEN and crypto.enabled())


def _fetch_candidates() -> list:
    with httpx.Client(timeout=20) as c:
        r = c.get(f"{_POOL_URL}/api/engine-sessions/refresh-candidates",
                  params={"limit": _BATCH},
                  headers={"X-Service-Token": _POOL_TOKEN})
    return r.json() if r.status_code == 200 else []


async def _tick() -> None:
    cands = await asyncio.to_thread(_fetch_candidates)
    if not cands:
        return
    _log.info("[refresh] %d 个掉线账号待续期", len(cands))
    for cand in cands:
        plain = crypto.decrypt(cand.get("credentials") or "")
        if not plain:
            continue
        try:
            d = json.loads(plain)
            res = await authorize_password(cand["engine"], d["identifier"], d["password"])
            _log.info("[refresh] %s id=%s %s → %s", cand["engine"], cand["id"],
                      cand.get("account_handle"), "OK 已续期" if res.get("ok") else res.get("error"))
        except Exception as e:  # noqa: BLE001
            _log.warning("[refresh] id=%s 续期异常: %s", cand.get("id"), e)


async def refresh_loop(stop: asyncio.Event) -> None:
    if not _enabled():
        _log.info("[refresh] 未启用(POOL_URL / service token / ENGINE_CRED_KEY 未配齐)")
        return
    _log.info("[refresh] 守护启动,interval=%ds batch=%d", _INTERVAL, _BATCH)
    while not stop.is_set():
        try:
            await _tick()
        except Exception as e:  # noqa: BLE001
            _log.warning("[refresh] tick 出错: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=_INTERVAL)
        except asyncio.TimeoutError:
            pass
