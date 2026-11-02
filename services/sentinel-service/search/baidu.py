"""Thin Baidu SERP wrapper.

Baidu has no clean public web-search API, so we scrape the HTML SERP
(`https://www.baidu.com/s?wd=…`). Results are wrapped in `baidu.com/link?url=…`
redirects; the real target is usually exposed in the `mu` attribute on the
outer result `<div>`. When `mu` is missing we HEAD-follow the redirect.

Why this exists: ddgs (DuckDuckGo / Bing / Google etc.) under-indexes Chinese
sites (xueqiu, eastmoney, zhihu, weibo). Baidu indexes them best, so adding
it dramatically improves recall on Chinese-platform `site:` queries.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


_TIMELIMIT_SECONDS = {
    "d": 24 * 3600,
    "w": 7 * 24 * 3600,
    "m": 31 * 24 * 3600,
    "y": 365 * 24 * 3600,
}


def _gpc_for_timelimit(timelimit: str | None) -> str | None:
    """Build Baidu's `gpc` date-range param. Returns None for no filter.

    Accepts:
      - 'd'/'w'/'m'/'y': past N days/weeks/months/years (relative)
      - 'YYYY-MM-DD..YYYY-MM-DD': absolute date range (e.g. '2026-05-02..2026-05-08')

    Baidu relies on its own page-discovery date, which is not always accurate,
    but it is strictly better than no filter for "fresh content" queries.
    """
    if not timelimit:
        return None
    # 绝对日期范围
    if ".." in timelimit:
        try:
            from datetime import datetime, timezone
            lo_str, hi_str = timelimit.split("..", 1)
            lo = int(datetime.fromisoformat(lo_str).replace(tzinfo=timezone.utc).timestamp())
            hi = int(datetime.fromisoformat(hi_str).replace(tzinfo=timezone.utc).timestamp())
            # 加 86399 让 hi 包含到当天 23:59:59
            return f"stf={lo},{hi + 86399}|stftype=1"
        except (ValueError, TypeError):
            return None
    # 相对窗口
    delta = _TIMELIMIT_SECONDS.get(timelimit)
    if not delta:
        return None
    end = int(time.time())
    return f"stf={end - delta},{end}|stftype=1"


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 12
_BAIDU_LINK_PREFIXES = ("http://www.baidu.com/link", "https://www.baidu.com/link")
# Verification / WAF challenge markers (fragments that survive any encoding fallback)
_BLOCK_MARKERS = ("百度安全验证", "网络不给力", "wappass.baidu.com", "passport.baidu.com/v2/?reg")


def _is_baidu_redirect(url: str) -> bool:
    return url.startswith(_BAIDU_LINK_PREFIXES)


def _is_blocked(html: str) -> bool:
    if any(m in html for m in _BLOCK_MARKERS):
        return True
    # Verification page is tiny (~1.5KB) and has no result divs / h3 tags
    return len(html) < 4000 and "<h3" not in html and "result c-container" not in html


def _resolve(url: str, session: requests.Session) -> str | None:
    try:
        r = session.head(url, allow_redirects=True, timeout=_TIMEOUT)
        return r.url
    except requests.RequestException:
        return None


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Referer": "https://www.baidu.com/",
    })
    cookie = os.environ.get("BAIDU_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def baidu_search(query: str, max_results: int = 10,
                 timelimit: str | None = None) -> list[dict]:
    """Returns a list of {title, href, body} dicts.

    Hrefs are resolved out of `baidu.com/link?url=…` shells when possible
    (preferred via `mu` attribute, fallback via HEAD redirect). Items where
    the real URL can't be recovered are dropped.

    `timelimit` (d/w/m/y) narrows results to that lookback window via Baidu's
    `gpc` date-range param. None = no filter.

    If Baidu serves a verification / security check page (common from cloud
    IPs), returns []. Set `BAIDU_COOKIE` env var (paste from a logged-in
    browser session) to bypass.
    """
    rn = max(min(max_results, 50), 10)
    params: dict[str, str | int] = {"wd": query, "rn": rn, "ie": "utf-8"}
    gpc = _gpc_for_timelimit(timelimit)
    if gpc:
        params["gpc"] = gpc
    session = _build_session()
    try:
        r = session.get("https://www.baidu.com/s", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [baidu] request failed: {e}", file=sys.stderr)
        return []

    # Baidu sometimes omits charset in Content-Type → requests falls back to
    # ISO-8859-1 and mangles Chinese. Force UTF-8.
    r.encoding = "utf-8"
    html = r.text

    if _is_blocked(html):
        hint = "" if os.environ.get("BAIDU_COOKIE") else " (set BAIDU_COOKIE env var to bypass)"
        print(f"  [baidu] verification page returned — IP likely blocked{hint}",
              file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "lxml")
    raw: list[dict] = []
    for div in soup.select("div.result.c-container, div.result-op.c-container"):
        # Skip ads (Baidu marks them with "广告" badge near the title)
        if div.find(string=lambda s: s and "广告" in s and len(s) < 6):
            continue
        a = div.select_one("h3 a") or div.select_one("a.title-text") or div.select_one("a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = (div.get("mu") or div.get("data-href") or a.get("href") or "").strip()
        if not href:
            continue
        abstract = div.select_one(
            ".c-abstract, .content-right_8Zs40, [class*='abstract'], [class*='content-right']"
        )
        body = abstract.get_text(" ", strip=True) if abstract else ""
        raw.append({"title": title, "href": href, "body": body})
        if len(raw) >= max_results:
            break

    # Resolve any remaining baidu redirect URLs in parallel
    to_resolve = [(i, item["href"]) for i, item in enumerate(raw) if _is_baidu_redirect(item["href"])]
    if to_resolve:
        with ThreadPoolExecutor(max_workers=min(8, len(to_resolve))) as pool:
            resolved = list(pool.map(lambda u: _resolve(u, session), [u for _, u in to_resolve]))
        for (i, _), real in zip(to_resolve, resolved):
            if real:
                raw[i]["href"] = real

    # Drop anything whose real URL we still couldn't recover
    out = [item for item in raw if not _is_baidu_redirect(item["href"]) and urlparse(item["href"]).hostname]
    return out[:max_results]
