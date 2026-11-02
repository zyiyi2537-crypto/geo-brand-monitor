"""新浪财经爬虫 — 新闻 + 股吧.

两个数据源：
1. 新浪财经搜索 API（新闻文章）
2. 新浪股吧帖子列表（散户讨论）

返回格式与 eastmoney 一致：[{source, post_id, symbol, author, title, content, ...}]
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


class SinaFinanceClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def search_news(self, keyword: str, page: int = 1, count: int = 20) -> Iterator[dict]:
        """通过新浪财经搜索 API 搜新闻.

        https://search.sina.com.cn/news?q=关键词&range=all&num=20&page=1
        """
        url = "https://search.sina.com.cn/news"
        params = {
            "q": keyword,
            "range": "all",
            "num": min(count, 50),
            "page": page,
        }
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
        except requests.RequestException as e:
            print(f"  [sina] search failed: {e}", file=sys.stderr)
            return

        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("div.result, div.box-result"):
            a = item.select_one("h2 a, a.title")
            if not a:
                continue
            href = (a.get("href") or "").strip()
            if not href:
                continue
            title = a.get_text(strip=True)
            snippet_el = item.select_one("p.content, .des-border, .r-info")
            content = snippet_el.get_text(strip=True) if snippet_el else None
            time_el = item.select_one("span.fgray_time, .r-time, .time")
            pub_time = _parse_sina_time(time_el.get_text(strip=True) if time_el else None)

            yield {
                "source": "sina",
                "post_id": _url_hash(href),
                "symbol": keyword,
                "author": _extract_source(item),
                "title": title,
                "content": content,
                "publish_time": pub_time,
                "view_count": None,
                "reply_count": None,
                "url": href,
            }

    def search_pages(self, keyword: str, pages: int = 3, count: int = 20) -> Iterator[dict]:
        """搜索多页新闻."""
        for p in range(1, pages + 1):
            yield from self.search_news(keyword, page=p, count=count)
            if p < pages:
                time.sleep(0.8)

    def fetch_guba(self, symbol: str, page: int = 1) -> Iterator[dict]:
        """新浪股吧帖子列表.

        http://guba.sina.com.cn/?s=bar&name={symbol}
        """
        url = f"http://guba.sina.com.cn/"
        params = {"s": "bar", "name": symbol, "page": page}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
        except requests.RequestException as e:
            print(f"  [sina_guba] request failed: {e}", file=sys.stderr)
            return

        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("ul.listMain li, div.stockcodec_list li, tr"):
            a = item.select_one("a")
            if not a:
                continue
            href = (a.get("href") or "").strip()
            title = a.get("title") or a.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            time_el = item.select_one("span.time, td.time, .date")
            yield {
                "source": "sina_guba",
                "post_id": _url_hash(href),
                "symbol": symbol,
                "author": None,
                "title": title,
                "content": None,
                "publish_time": _parse_sina_time(time_el.get_text(strip=True) if time_el else None),
                "view_count": None,
                "reply_count": None,
                "url": href if href.startswith("http") else f"http://guba.sina.com.cn{href}",
            }


def _url_hash(url: str) -> str:
    """URL → 短 hash 作为 post_id."""
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _extract_source(item) -> str | None:
    """提取新闻来源（媒体名）."""
    source_el = item.select_one("span.fgray_time + span, .r-source, .source")
    if source_el:
        return source_el.get_text(strip=True)
    return None


def _parse_sina_time(s: str | None) -> str | None:
    """解析新浪的各种时间格式."""
    if not s:
        return None
    s = s.strip()
    # "2026年05月07日 14:30"
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()]).isoformat()
    # "05月07日 14:30"
    m = re.match(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", s)
    if m:
        month, day, hour, minute = [int(x) for x in m.groups()]
        return datetime(datetime.now().year, month, day, hour, minute).isoformat()
    # "2026-05-07 14:30:00"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()]).isoformat()
    # "3小时前" / "昨天 14:30" 等不做精确解析
    return None
