"""cn.bing.com 搜索 — 国内可直连,不需要代理.

bing.com 国际版在国内被 GFW 干扰,但 cn.bing.com 正常可用.
返回格式与 ddg / baidu 模块一致: [{title, href, body}, ...].
"""
from __future__ import annotations

import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 10

_TIMELIMIT_MAP = {
    "d": "ex1:\"ez1\"",   # Past 24 hours
    "w": "ex1:\"ez2\"",   # Past week
    "m": "ex1:\"ez3\"",   # Past month
}


def cnbing_search(query: str, max_results: int = 10,
                  timelimit: str | None = None) -> list[dict]:
    """Search cn.bing.com, return [{title, href, body}].

    `timelimit`:
      - 'd' (day) / 'w' (week) / 'm' (month) — 标量预设
      - 'YYYY-MM-DD..YYYY-MM-DD' — 绝对日期范围(走 ez5 自定义 filter)
      - None — 不过滤
    """
    params: dict[str, str | int] = {
        "q": query,
        "count": max(min(max_results, 50), 10),
        "ensearch": "0",  # Force Chinese results
    }
    if timelimit and ".." in timelimit:
        # Bing 自定义范围: ex1:"ez5_<days>_<days>",days = unix_seconds // 86400
        try:
            from datetime import datetime, timezone
            lo_str, hi_str = timelimit.split("..", 1)
            lo_days = int(datetime.fromisoformat(lo_str).replace(tzinfo=timezone.utc).timestamp() // 86400)
            hi_days = int(datetime.fromisoformat(hi_str).replace(tzinfo=timezone.utc).timestamp() // 86400)
            params["filters"] = f"ex1:\"ez5_{lo_days}_{hi_days}\""
        except (ValueError, TypeError):
            pass
    elif timelimit and timelimit in _TIMELIMIT_MAP:
        params["filters"] = _TIMELIMIT_MAP[timelimit]

    headers = {
        "User-Agent": _UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    }

    try:
        r = requests.get(
            "https://cn.bing.com/search",
            params=params, headers=headers, timeout=_TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [cnbing] request failed: {e}", file=sys.stderr)
        return []

    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")

    results: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href or not urlparse(href).hostname:
            continue
        title = a.get_text(" ", strip=True)
        snippet_el = li.select_one(".b_caption p, .b_lineclamp2, .b_paractl")
        body = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        results.append({"title": title, "href": href, "body": body})
        if len(results) >= max_results:
            break

    return results
