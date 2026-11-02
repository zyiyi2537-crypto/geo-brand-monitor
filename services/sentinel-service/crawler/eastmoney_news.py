"""东方财经资讯搜索爬虫 — 抓新闻/研报/公告.

不同于 eastmoney.py（股吧帖子），这个模块走东方财富的资讯搜索 API，
能抓到财经新闻、研报、公告等正式内容。

搜索 API: https://search-api-web.eastmoney.com/search/jsonp
"""
from __future__ import annotations

import hashlib
import json
import re
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

_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"


class EastmoneyNewsClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://so.eastmoney.com/",
        })

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """搜索东财资讯.

        type 可选: cmsArticleWebOld(资讯), cmsArticleWebNew(快讯)
        """
        param = json.dumps({
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticleWebOld", "cmsArticleWebNew"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "pageIndex": page,
            "pageSize": min(page_size, 50),
        }, ensure_ascii=False)

        try:
            r = self.session.get(
                _SEARCH_URL,
                params={"cb": "j", "param": param},
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [eastmoney_news] request failed: {e}", file=sys.stderr)
            return

        # 解析 JSONP: callback({...}) — callback 名可能是 j 或 jQuery...
        text = r.text.strip()
        m = re.search(r"^\w+\((.+)\)\s*$", text, re.DOTALL)
        if not m:
            print(f"  [eastmoney_news] JSONP parse failed, len={len(text)}, start={text[:50]!r}", file=sys.stderr)
            return

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            print(f"  [eastmoney_news] JSON decode error: {e}", file=sys.stderr)
            return

        # result 是 dict，key = type 名, value = article list
        # 把所有类型的文章都收集起来
        result = data.get("result") or {}
        articles: list[dict] = []
        if isinstance(result, dict):
            for _type_key, items in result.items():
                if isinstance(items, list):
                    articles.extend(items)
        elif isinstance(result, list):
            articles = result
        for art in articles:
            yield _parse_article(art, keyword)

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        """搜索多页."""
        for p in range(1, pages + 1):
            yield from self.search(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)


def _parse_article(art: dict, keyword: str) -> dict:
    """将搜索结果转为统一 post 格式."""
    url = art.get("url") or art.get("articleUrl") or ""
    title = art.get("title") or ""
    # 清理 HTML 高亮标签
    title = re.sub(r"<[^>]+>", "", title)
    content = art.get("content") or art.get("mediaName") or ""
    content = re.sub(r"<[^>]+>", "", content)

    pub_time = None
    date_str = art.get("date") or art.get("showTime") or ""
    if date_str:
        try:
            # 格式: "2026-05-07 14:30:00"
            pub_time = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S").isoformat()
        except (ValueError, TypeError):
            pub_time = date_str

    return {
        "source": "eastmoney_news",
        "post_id": art.get("code") or art.get("artCode") or _url_hash(url),
        "symbol": keyword,
        "author": art.get("mediaName"),
        "title": title[:200],
        "content": content[:500] if content else None,
        "publish_time": pub_time,
        "view_count": None,
        "reply_count": None,
        "url": url,
    }


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]
