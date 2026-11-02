"""引用标题回填 — 引擎没给标题的 citation,走 browser-service 真实浏览器抓 <title>.

为什么需要:不少引擎(如 DeepSeek)只回 URL 不回标题;知乎这类被引文章对裸 HTTP
请求返回 403,只有真实浏览器(带反检测)能拿到标题.所以统一走 browser-service 的
/fetch-title.best-effort:抓不到就保持空,由调用方回退到显示 URL.

调用方:geo_checker/analyzers/source_trace.py 在聚合前批量回填一次.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

log = logging.getLogger(__name__)

# 单次回填的上限 / 并发 / 单条超时 — 都可 env 覆盖.上限避免一次跑批抓太多拖慢结果.
TITLE_FETCH_MAX = int(os.environ.get("GEO_TITLE_FETCH_MAX", "15"))
TITLE_FETCH_CONCURRENCY = int(os.environ.get("GEO_TITLE_FETCH_CONCURRENCY", "4"))
TITLE_FETCH_TIMEOUT_MS = int(os.environ.get("GEO_TITLE_FETCH_TIMEOUT_MS", "15000"))


def _region_for(url: str) -> str:
    """信源以国内站点(知乎/微信/CSDN…)为主,默认走 cn 实例.需要时可按域名细分."""
    return "cn"


def resolve_titles(urls: Iterable[str]) -> dict[str, str]:
    """对一批 URL 抓页面标题,返回 {url: title}(只含成功抓到的).

    best-effort、去重、有上限.全程不抛异常 — browser-service 不可用时返回空 dict.
    """
    uniq: list[str] = []
    seen: set[str] = set()
    for u in urls:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        return {}

    if len(uniq) > TITLE_FETCH_MAX:
        log.info("[title-fetch] 待抓 %d 条,超上限只取前 %d 条(其余保持显示 URL)",
                 len(uniq), TITLE_FETCH_MAX)
        uniq = uniq[:TITLE_FETCH_MAX]

    try:
        from browser_engine.client import fetch_title
    except Exception:  # noqa: BLE001
        log.warning("[title-fetch] browser_engine.client 不可用,跳过标题回填")
        return {}

    out: dict[str, str] = {}
    try:
        with ThreadPoolExecutor(max_workers=max(1, TITLE_FETCH_CONCURRENCY)) as ex:
            futs = {
                ex.submit(fetch_title, u, _region_for(u), TITLE_FETCH_TIMEOUT_MS): u
                for u in uniq
            }
            for f in as_completed(futs):
                u = futs[f]
                try:
                    t = f.result()
                except Exception:  # noqa: BLE001
                    t = ""
                if t:
                    out[u] = t
    except Exception:  # noqa: BLE001
        log.exception("[title-fetch] 批量抓标题失败")
        return out
    log.info("[title-fetch] %d/%d 条抓到标题", len(out), len(uniq))
    return out
