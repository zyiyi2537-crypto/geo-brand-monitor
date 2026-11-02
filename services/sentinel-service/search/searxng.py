"""SearXNG metasearch adapter.

SearXNG (https://docs.searxng.org) 是自托管元搜索:一次查询在 server 端 fan-out
到多个上游引擎(DuckDuckGo / Bing / Google / Baidu / Sogou …)并合并去重。用它
替代本服务自带的 baidu/cnbing/sogou/ddg —— 反爬 / IP 风控 / 代理(IP 池)全在
SearXNG 实例端处理,本仓库只剩一个纯 requests + JSON 的薄适配器。

需要一个可达实例,设 `SEARXNG_URL`(如 http://127.0.0.1:8888),且实例 settings.yml
的 search.formats 里开启 json。中文站覆盖取决于实例启用了哪些上游引擎(建议开
baidu / bing)。
"""
from __future__ import annotations

import os
import sys
import time

import requests


# 内部 d/w/m/y 桶 → SearXNG 的 time_range
_TIME_RANGE = {"d": "day", "w": "week", "m": "month", "y": "year"}

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 60   # SearXNG 经 Web Unlocker 抓百度每条可达 ~30s，给足
# 只取第 1 页:SearXNG 一次请求已聚合多引擎 ~10-20 条，足够监测用。
# 翻页会成倍触发 Web Unlocker 调用(慢 + 计费),稀疏查询还会一路翻到底导致 monitor 超时。
_MAX_PAGES = 1


def _base_url() -> str:
    url = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "SEARXNG_URL is not set — point it at your SearXNG instance, "
            "e.g. http://127.0.0.1:8888"
        )
    return url


def searxng_search(query: str, max_results: int = 10,
                   timelimit: str | None = None,
                   language: str = "all",
                   engines: list[str] | tuple[str, ...] | None = None,
                   categories: str = "general") -> list[dict]:
    """查询 SearXNG,返回 [{title, href, body, publish_time}]。

    timelimit: 'd'/'w'/'m'/'y' → SearXNG time_range;None = 不限。
    engines:   限定上游引擎(SearXNG `engines=` 参数);None 用实例默认。
    任何传输 / 格式错误返回 [](打 stderr),不让单条查询拖垮整个 plan。
    """
    base = _base_url()
    params: dict[str, str | int] = {
        "q": query,
        "format": "json",
        "language": language or "all",
        "categories": categories,
        "safesearch": 0,
    }
    # time_range:限定时间窗,只搜最近内容(要"最新舆情"用)。
    # 早期只有 bing 时 d/w/m 常返 0;现在有 baidu(Web Unlocker,带 publishedDate)+
    # 360search 支持时间过滤,可正常工作。bing 对时间过滤无结果时自动退出,不影响其它引擎。
    tr = _TIME_RANGE.get(timelimit) if timelimit else None
    if tr:
        params["time_range"] = tr
    if engines:
        params["engines"] = ",".join(engines)

    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Accept": "application/json"})

    out: list[dict] = []
    seen: set[str] = set()
    for pageno in range(1, _MAX_PAGES + 1):
        params["pageno"] = pageno
        try:
            r = session.get(f"{base}/search", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [searxng] request failed (page {pageno}): {e}", file=sys.stderr)
            break
        try:
            payload = r.json()
        except ValueError:
            print("  [searxng] non-JSON response — enable `json` in the instance's "
                  "settings.yml (search.formats).", file=sys.stderr)
            break
        page = payload.get("results") or []
        if not page:
            break
        for item in page:
            url = (item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "title": item.get("title") or "",
                "href": url,
                "body": item.get("content") or "",
                "publish_time": item.get("publishedDate"),
            })
            if len(out) >= max_results:
                return out
    return out[:max_results]
