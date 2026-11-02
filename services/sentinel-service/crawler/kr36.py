"""36kr 爬虫 — 科技财经深度内容.

36kr 有公开的搜索 API。
API: https://gateway.36kr.com/api/mis/nav/search/suggest

返回格式统一: [{source, post_id, symbol, author, title, content, ...}]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Iterator

import requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_SEARCH_URL = "https://gateway.36kr.com/api/mis/nav/search/suggest"


class Kr36Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://36kr.com/",
        })

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """搜索 36kr 文章."""
        payload = {
            "keyword": keyword,
            "partner_id": "wap",
            "param": {
                "siteId": 1,
                "platformId": 2,
            },
            "page": page,
            "pageSize": min(page_size, 50),
        }
        try:
            r = self.session.post(_SEARCH_URL, json=payload, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [36kr] search failed: {e}", file=sys.stderr)
            return

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            print(f"  [36kr] invalid JSON, len={len(r.text)}", file=sys.stderr)
            return

        items = (data.get("data") or {}).get("itemList") or []
        if not isinstance(items, list):
            return

        for wrapper in items:
            item = wrapper.get("templateMaterial") or wrapper
            if not isinstance(item, dict):
                continue

            pub_time = None
            ts = item.get("publishTime") or item.get("created_at")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        ts_sec = ts / 1000 if ts > 1e12 else ts
                        pub_time = datetime.fromtimestamp(ts_sec).isoformat()
                    elif isinstance(ts, str):
                        pub_time = ts[:19]
                except (ValueError, TypeError, OSError):
                    pass

            article_id = str(item.get("itemId") or item.get("id") or "")
            yield {
                "source": "36kr",
                "post_id": article_id,
                "symbol": keyword,
                "author": item.get("authorName") or item.get("author") or None,
                "title": (item.get("widgetTitle") or item.get("title") or "")[:200],
                "content": (item.get("summary") or item.get("description") or "")[:500] or None,
                "publish_time": pub_time,
                "view_count": item.get("pageView") or item.get("pv"),
                "reply_count": item.get("commentCount"),
                # 36kr API 偶尔给 favourite(收藏)/ share — 当作 like / share
                "like_count": item.get("favourite") or item.get("favouriteCount") or item.get("likeCount"),
                "share_count": item.get("shareCount"),
                "url": f"https://36kr.com/p/{article_id}" if article_id else None,
            }

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)
