"""华尔街见闻爬虫 — 专业财经资讯.

华尔街见闻有公开的搜索 API，覆盖全球财经快讯和深度分析。
API: https://api-one.wallstreetcn.com/apiv1/search/

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

_SEARCH_URL = "https://api-one.wallstreetcn.com/apiv1/search/global"


class WallstreetcnClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://wallstreetcn.com/",
        })

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """搜索华尔街见闻文章."""
        params = {
            "query": keyword,
            "limit": min(page_size, 50),
            "cursor": (page - 1) * page_size,
        }
        try:
            r = self.session.get(_SEARCH_URL, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [wallstreetcn] search failed: {e}", file=sys.stderr)
            return

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            print(f"  [wallstreetcn] invalid JSON, len={len(r.text)}", file=sys.stderr)
            return

        items = data.get("data", {}).get("items") or data.get("data", {}).get("list") or []
        if not isinstance(items, list):
            return

        for item in items:
            resource = item.get("resource") or item
            pub_time = None
            ts = resource.get("display_time") or resource.get("created_at")
            if ts:
                try:
                    pub_time = datetime.fromtimestamp(int(ts)).isoformat()
                except (ValueError, TypeError, OSError):
                    if isinstance(ts, str):
                        pub_time = ts[:19]

            article_id = str(resource.get("id") or resource.get("uri") or "")
            title = resource.get("title") or ""
            content = resource.get("content_short") or resource.get("summary") or ""

            yield {
                "source": "wallstreetcn",
                "post_id": article_id,
                "symbol": keyword,
                "author": resource.get("author", {}).get("display_name") if isinstance(resource.get("author"), dict) else None,
                "title": title[:200],
                "content": content[:500] or None,
                "publish_time": pub_time,
                "view_count": resource.get("page_views"),
                "reply_count": resource.get("comment_count"),
                # 见闻 API 偶尔给 praise_count(点赞);转发不暴露
                "like_count": resource.get("praise_count") or resource.get("likes_count"),
                "share_count": None,
                "url": resource.get("uri") or (f"https://wallstreetcn.com/articles/{article_id}" if article_id else None),
            }

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)
