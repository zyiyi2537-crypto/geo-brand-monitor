"""百度贴吧爬虫 — 股票相关贴吧.

百度贴吧无 WAF 限制，国内机房可直连。
通过关键词搜索帖子或直接进入特定贴吧获取帖子列表。

搜索 API: https://tieba.baidu.com/f/search/res
贴吧列表: https://tieba.baidu.com/f?kw={bar_name}
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


class BaiduTiebaClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def search(self, keyword: str, page: int = 1) -> Iterator[dict]:
        """搜索贴吧帖子."""
        url = "https://tieba.baidu.com/f/search/res"
        params = {
            "qw": keyword,
            "rn": 20,
            "pn": (page - 1) * 20,
        }
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
        except requests.RequestException as e:
            print(f"  [tieba] search failed: {e}", file=sys.stderr)
            return

        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("div.s_post"):
            a = item.select_one("a.bluelink, span.p_title a")
            if not a:
                continue
            href = a.get("href", "").strip()
            if not href:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            content_el = item.select_one("div.p_content, .p_excerpt")
            content = content_el.get_text(strip=True) if content_el else None

            time_el = item.select_one("font.p_green, span.p_date, .create_time")
            author_el = item.select_one("a.p_violet, a[href*='home/main']")
            forum_el = item.select_one("a.p_forum, font.p_violet")

            url_full = href if href.startswith("http") else f"https://tieba.baidu.com{href}"

            yield {
                "source": "tieba",
                "post_id": _url_hash(url_full),
                "symbol": keyword,
                "author": author_el.get_text(strip=True) if author_el else None,
                "title": title[:200],
                "content": content[:500] if content else None,
                "publish_time": _parse_time(time_el.get_text(strip=True) if time_el else None),
                "view_count": None,
                "reply_count": None,
                "url": url_full,
            }

    def fetch_bar(self, bar_name: str, page: int = 1) -> Iterator[dict]:
        """获取特定贴吧的帖子列表.

        bar_name: 贴吧名，如 "世纪互联" 或 "VNET"
        """
        url = "https://tieba.baidu.com/f"
        params = {"kw": bar_name, "pn": (page - 1) * 50}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
        except requests.RequestException as e:
            print(f"  [tieba] bar fetch failed: {e}", file=sys.stderr)
            return

        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("li.j_thread_list, div.t_con"):
            a = item.select_one("a.j_th_tit, a.threadlist_title")
            if not a:
                continue
            href = a.get("href", "").strip()
            title = a.get("title") or a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            author_el = item.select_one("span.tb_icon_author, a.frs-author-name-wrap")
            reply_el = item.select_one("span.threadlist_rep_num, span.j_num_reply")
            time_el = item.select_one("span.threadlist_reply_date, span.j_reply_data")

            url_full = f"https://tieba.baidu.com{href}" if href.startswith("/") else href

            yield {
                "source": "tieba",
                "post_id": _extract_tid(href) or _url_hash(url_full),
                "symbol": bar_name,
                "author": author_el.get_text(strip=True) if author_el else None,
                "title": title[:200],
                "content": None,
                "publish_time": _parse_time(time_el.get_text(strip=True) if time_el else None),
                "view_count": None,
                "reply_count": _parse_int(reply_el.get_text(strip=True) if reply_el else None),
                "url": url_full,
            }

    def search_pages(self, keyword: str, pages: int = 3) -> Iterator[dict]:
        """搜索多页."""
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p)
            if p < pages:
                time.sleep(0.5)

    def fetch_bar_pages(self, bar_name: str, pages: int = 3) -> Iterator[dict]:
        """获取多页贴吧帖子."""
        for p in range(1, pages + 1):
            yield from self.fetch_bar(bar_name, page=p)
            if p < pages:
                time.sleep(0.5)


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _extract_tid(href: str) -> str | None:
    m = re.search(r"/p/(\d+)", href or "")
    return m.group(1) if m else None


def _parse_int(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "")
    try:
        return int(s)
    except ValueError:
        return None


def _parse_time(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    # "2026-05-07 14:30"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()]).isoformat()
    # "05-07 14:30"
    m = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{2}):(\d{2})", s)
    if m:
        month, day, hour, minute = [int(x) for x in m.groups()]
        now = datetime.now()
        dt = datetime(now.year, month, day, hour, minute)
        if dt > now:
            dt = dt.replace(year=now.year - 1)
        return dt.isoformat()
    return None
