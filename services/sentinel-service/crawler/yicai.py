"""第一财经爬虫 — 主流财经媒体.

第一财经搜索页可直接抓取 HTML。
URL: https://www.yicai.com/search?keys={keyword}

返回格式统一: [{source, post_id, symbol, author, title, content, ...}]
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import datetime
from typing import Iterator

import requests
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class YicaiClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def search(self, keyword: str, page: int = 1) -> Iterator[dict]:
        """搜索第一财经文章."""
        url = "https://www.yicai.com/search"
        params = {"keys": keyword, "page": page}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
        except requests.RequestException as e:
            print(f"  [yicai] search failed: {e}", file=sys.stderr)
            return

        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("div.u-news-item, li.f-cb, div.search-item, div.article-item"):
            a = item.select_one("h2 a, a.f-ff1, a.title, .u-news-title a")
            if not a:
                continue
            href = (a.get("href") or "").strip()
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            if href and not href.startswith("http"):
                href = f"https://www.yicai.com{href}"

            content_el = item.select_one("p, .u-news-summary, .desc, .summary")
            content = content_el.get_text(strip=True) if content_el else None

            time_el = item.select_one("span.date, time, .u-news-date, .time")
            author_el = item.select_one("span.author, .source, .u-news-author")

            yield {
                "source": "yicai",
                "post_id": _url_hash(href),
                "symbol": keyword,
                "author": author_el.get_text(strip=True) if author_el else "第一财经",
                "title": title[:200],
                "content": content[:500] if content else None,
                "publish_time": _parse_time(time_el.get_text(strip=True) if time_el else None),
                "view_count": None,
                "reply_count": None,
                "url": href,
            }

    def search_pages(self, keyword: str, pages: int = 3) -> Iterator[dict]:
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p)
            if p < pages:
                time.sleep(0.5)


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _parse_time(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()]).isoformat()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()]).isoformat()
    return None
