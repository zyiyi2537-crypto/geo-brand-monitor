"""财联社 (cls.cn) 快讯爬虫 — 中国最快的财经快讯源.

财联社有公开的电报/快讯 API，实时性极强，是专业投资者常用数据源。
API: https://www.cls.cn/nodeapi/updateTelegraphList

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

# 财联社电报 API（公开,实测可用 endpoint）
# 历史 endpoint `updateTelegraph` 已 404,需要用 `updateTelegraphList`
_TELEGRAPH_URL = "https://www.cls.cn/nodeapi/updateTelegraphList"
# 公开搜索 API 已下线(404),保留站点搜索页 fallback,但优先用 telegraph 关键词过滤
_SEARCH_URL = "https://www.cls.cn/api/search"


class ClsFinanceClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://www.cls.cn/",
        })

    def fetch_telegraph(self, keyword: str | None = None, count: int = 50) -> Iterator[dict]:
        """拉取最新财联社电报（快讯）.

        无需登录，公开 API。可选按关键词过滤。
        参数 type 留空表示拉所有类别(否则可指定 jbl=精选)。
        """
        params = {
            "type": "",
            "rn": min(count, 100),
            "os": "web",
            "sv": "8.4.6",
            "app": "CailianpressWeb",
        }
        try:
            r = self.session.get(_TELEGRAPH_URL, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [cls] telegraph failed: {e}", file=sys.stderr)
            return

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            print("  [cls] invalid JSON response", file=sys.stderr)
            return

        items = data.get("data", {}).get("roll_data") or []
        for item in items:
            title = item.get("title") or ""
            content = item.get("content") or item.get("brief") or ""
            # 关键词过滤
            if keyword:
                text = f"{title} {content}".lower()
                if keyword.lower() not in text:
                    continue

            pub_time = None
            ctime = item.get("ctime")
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime)).isoformat()
                except (ValueError, TypeError, OSError):
                    pass

            yield {
                "source": "cls",
                "post_id": str(item.get("id") or ""),
                "symbol": keyword or "",
                "author": "财联社",
                "title": title[:200] if title else content[:80],
                "content": content[:500] if content else None,
                "publish_time": pub_time,
                "view_count": None,
                "reply_count": None,
                "url": f"https://www.cls.cn/detail/{item['id']}" if item.get("id") else None,
            }

    def search_news(self, keyword: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """搜索财联社文章 — 公开 API 已下线,只在第 1 页 silently 试一下,失败立即返回."""
        if page > 1:
            return
        params = {
            "keyword": keyword,
            "page": page,
            "size": min(page_size, 50),
            "type": "article",
        }
        try:
            r = self.session.get(_SEARCH_URL, params=params, timeout=10)
            if r.status_code == 404:
                return  # 静默 — 已下线,fetch_telegraph 是主要路径
            r.raise_for_status()
        except requests.RequestException:
            return  # 静默,主路径已经是 telegraph

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return

        items = data.get("data", {}).get("list") or data.get("data") or []
        if not isinstance(items, list):
            return

        for item in items:
            pub_time = None
            ctime = item.get("ctime") or item.get("mtime")
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime)).isoformat()
                except (ValueError, TypeError, OSError):
                    pass

            yield {
                "source": "cls",
                "post_id": str(item.get("id") or item.get("article_id") or ""),
                "symbol": keyword,
                "author": item.get("author") or item.get("source") or "财联社",
                "title": (item.get("title") or "")[:200],
                "content": (item.get("brief") or item.get("content") or "")[:500] or None,
                "publish_time": pub_time,
                "view_count": item.get("pv"),
                "reply_count": item.get("comment_num"),
                # 财联社 API 偶尔给 praise_num / share_num
                "like_count": item.get("praise_num") or item.get("like_num"),
                "share_count": item.get("share_num"),
                "url": f"https://www.cls.cn/detail/{item['id']}" if item.get("id") else None,
            }

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        """搜索多页."""
        for p in range(1, pages + 1):
            yield from self.search_news(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)
