"""Worker agent loop — pull 模型.

browser-service 配了 DISPATCH_CENTER_URL 后,lifespan 起这个后台 loop:
  测出口 IP → register → 循环{ heartbeat + claim 领任务 → run_hot 跑 → POST 结果 }

worker 只需出站到中心(NAT/代理后可用)。并发受 max_concurrency 限;熔断中的引擎不 claim。
中心 disable/drain 该 worker 时,claim 返空,loop 空转等待。

ENV:
- DISPATCH_CENTER_URL     调度中心地址(必填才启用),如 https://dispatch.vigilath.com
- DISPATCH_TOKEN          共享鉴权 token(与中心一致)
- WORKER_UID              可选稳定 id(不填中心生成,重启会变新 worker)
- WORKER_LABEL            可选展示名
- WORKER_EXIT_IP          可选手填出口 IP(不填自动探测)
- WORKER_HEARTBEAT_SEC    心跳间隔秒(默认 30)
- WORKER_POLL_SEC         claim 轮询间隔秒(默认 3)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Awaitable, Callable

import httpx

log = logging.getLogger("browser-service.agent")

_IP_PROBES = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]


async def _detect_exit_ip() -> str:
    override = os.environ.get("WORKER_EXIT_IP", "").strip()
    if override:
        return override
    async with httpx.AsyncClient(timeout=8) as client:
        for url in _IP_PROBES:
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception:  # noqa: BLE001
                continue
    return ""


async def agent_loop(
    *,
    run_hot: Callable[[str, str], Awaitable[dict]],
    engines: list[str],
    max_concurrency: int,
    breaker_engines: Callable[[], set[str]],
    stop: asyncio.Event,
) -> None:
    center = os.environ.get("DISPATCH_CENTER_URL", "").rstrip("/")
    if not center:
        return
    token = os.environ.get("DISPATCH_TOKEN", "").strip()
    headers = {"X-Dispatch-Token": token} if token else {}
    label = os.environ.get("WORKER_LABEL", "")
    region = os.environ.get("REGION", "cn")
    hb_sec = int(os.environ.get("WORKER_HEARTBEAT_SEC", "30"))
    poll_sec = int(os.environ.get("WORKER_POLL_SEC", "3"))
    hostname = socket.gethostname()
    exit_ip = await _detect_exit_ip()
    uid = os.environ.get("WORKER_UID", "").strip()

    sem = asyncio.Semaphore(max_concurrency)
    inflight = 0
    inflight_by_engine: dict[str, int] = {}

    async def _register(client: httpx.AsyncClient) -> str:
        body = {"worker_uid": uid or None, "hostname": hostname, "label": label,
                "region": region, "exit_ip": exit_ip, "engines": engines,
                "max_concurrency": max_concurrency, "version": "1"}
        r = await client.post(f"{center}/dispatch/register", json=body, headers=headers)
        r.raise_for_status()
        return r.json()["worker_uid"]

    async def _run_and_report(client: httpx.AsyncClient, task: dict, my_uid: str) -> None:
        nonlocal inflight
        eng = task["engine"]
        try:
            async with sem:
                res = await run_hot(eng, task["query"])
            payload = {"worker_uid": my_uid, "task_id": task["task_id"],
                       "kind": task.get("kind", "telemetry"),   # 原样回传,中心据此路由落库
                       "answer": res.get("answer", ""), "citations": res.get("citations", []),
                       "source_url": res.get("source_url"), "video_url": res.get("video_url"),
                       "error": res.get("error")}
            await client.post(f"{center}/dispatch/result", json=payload, headers=headers)
        except Exception as e:  # noqa: BLE001
            log.warning("[agent] task %s run/report failed: %s", task.get("task_id"), e)
        finally:
            inflight -= 1
            inflight_by_engine[eng] = max(0, inflight_by_engine.get(eng, 0) - 1)

    # 注册(失败重试到成功 / stop)
    async with httpx.AsyncClient(timeout=30) as client:
        while not stop.is_set():
            try:
                uid = await _register(client)
                log.info("[agent] registered uid=%s host=%s exit_ip=%s engines=%s",
                         uid, hostname, exit_ip, engines)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("[agent] register failed, retry in 10s: %s", e)
                await asyncio.sleep(10)

        last_hb = 0.0
        loop = asyncio.get_event_loop()
        while not stop.is_set():
            now = loop.time()
            # 心跳
            if now - last_hb >= hb_sec:
                try:
                    await client.post(f"{center}/dispatch/heartbeat", headers=headers, json={
                        "worker_uid": uid, "in_flight": inflight, "exit_ip": exit_ip,
                        "breaker": {e: 1 for e in breaker_engines()},
                    })
                    last_hb = now
                except Exception as e:  # noqa: BLE001
                    log.warning("[agent] heartbeat failed: %s", e)
            # 领任务:每个引擎在 worker 上只有 1 条串行 hot session,所以每引擎最多领 1 条
            # 在飞行 —— 否则一个慢/坏引擎(如登录失效的 yuanbao)会占满槽位把别的引擎饿死。
            broken = breaker_engines()
            idle_engines = [e for e in engines
                            if e not in broken and inflight_by_engine.get(e, 0) == 0]
            for eng in idle_engines:
                if inflight >= max_concurrency:
                    break
                try:
                    r = await client.post(f"{center}/dispatch/claim", headers=headers, json={
                        "worker_uid": uid, "engines": [eng], "free_slots": 1,
                    })
                    r.raise_for_status()
                    tasks = r.json()
                except Exception as e:  # noqa: BLE001
                    log.warning("[agent] claim %s failed: %s", eng, e)
                    tasks = []
                for task in tasks:
                    inflight += 1
                    inflight_by_engine[eng] = inflight_by_engine.get(eng, 0) + 1
                    asyncio.create_task(_run_and_report(client, task, uid))
            await asyncio.sleep(poll_sec)
    log.info("[agent] loop stopped")
