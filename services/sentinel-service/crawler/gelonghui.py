"""格隆汇爬虫 — 港美股深度分析社区.

格隆汇有公开的搜索 API，专注港股/美股/中概股深度分析。
API: https://www.gelonghui.com/api/search/

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


class GelonghuiClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://www.gelonghui.com/",
        })

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """搜索格隆汇文章."""
        url = "https://www.gelonghui.com/api/search/"
        params = {
            "keyword": keyword,
            "page": page,
            "pageSize": min(page_size, 50),
            "type": "article",
        }
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [gelonghui] search failed: {e}", file=sys.stderr)
            return

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            # 可能返回 HTML（WAF/验证）
            if "<html" in r.text[:500].lower():
                print("  [gelonghui] got HTML instead of JSON (possible WAF)", file=sys.stderr)
            else:
                print(f"  [gelonghui] invalid JSON, len={len(r.text)}", file=sys.stderr)
            return

        items = data.get("result") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("list") or items.get("items") or items.get("data") or []
        if not isinstance(items, list):
            return

        for item in items:
            pub_time = None
            ts = item.get("timestamp") or item.get("createAt") or item.get("publishAt")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        pub_time = datetime.fromtimestamp(ts if ts > 1e12 else ts).isoformat()
                    elif isinstance(ts, str):
                        pub_time = ts[:19]
                except (ValueError, TypeError, OSError):
                    pass

            article_id = str(item.get("id") or item.get("articleId") or "")
            yield {
                "source": "gelonghui",
                "post_id": article_id,
                "symbol": keyword,
                "author": item.get("authorName") or item.get("nick") or None,
                "title": (item.get("title") or "")[:200],
                "content": (item.get("summary") or item.get("content") or "")[:500] or None,
                "publish_time": pub_time,
                "view_count": item.get("viewCount") or item.get("pv"),
                "reply_count": item.get("commentCount"),
                # 格隆汇 API 偶尔给 likeCount;转发不暴露
                "like_count": item.get("likeCount") or item.get("praiseCount"),
                "share_count": item.get("shareCount"),
                "url": f"https://www.gelonghui.com/p/{article_id}" if article_id else None,
            }

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)
