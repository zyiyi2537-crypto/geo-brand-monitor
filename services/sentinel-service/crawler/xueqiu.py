"""雪球爬虫 — 中国最大投资社区.

雪球有公开的帖子列表 API（无需登录即可拿到标题 + 摘要 + 互动数据）。
股票讨论页：https://xueqiu.com/S/{SYMBOL}
API：https://xueqiu.com/query/v1/symbol/search/status

返回格式与 eastmoney 一致：[{source, post_id, symbol, author, title, content, ...}]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Iterator

import requests

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class XueqiuClient:
    """雪球帖子爬虫.

    雪球需要先访问首页拿到 cookie（xq_a_token），否则 API 返回 400.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self._init_cookie()

    def _init_cookie(self):
        """访问雪球首页获取必要的 cookie."""
        try:
            self.session.get("https://xueqiu.com/", timeout=10)
        except requests.RequestException as e:
            print(f"  [xueqiu] cookie init failed: {e}", file=sys.stderr)

    def fetch_posts(self, symbol: str, count: int = 50, page: int = 1) -> Iterator[dict]:
        """拉取某只股票的讨论帖.

        symbol: 股票代码（如 VNET、SH600519、01810 等）
        count: 每页数量（最大 100）
        page: 页码
        """
        xq_symbol = _to_xueqiu_symbol(symbol)
        url = "https://xueqiu.com/query/v1/symbol/search/status"
        params = {
            "u": "",
            "SID": "",
            "symbol": xq_symbol,
            "sort": "",
            "source": "all",
            "count": min(count, 100),
            "page": page,
            "q": "",
            "type": "11",  # 讨论
        }
        try:
            r = self.session.get(url, params=params, timeout=15)
            if r.status_code == 400:
                # cookie 可能过期，重新获取
                self._init_cookie()
                r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [xueqiu] request failed: {e}", file=sys.stderr)
            return

        # WAF 拦截时返回 HTML 而非 JSON
        ct = r.headers.get("content-type", "")
        if "json" not in ct and "<html" in r.text[:500].lower():
            print("  [xueqiu] WAF blocked (got HTML instead of JSON)", file=sys.stderr)
            return

        try:
            data = r.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            print("  [xueqiu] invalid JSON response", file=sys.stderr)
            return
        items = data.get("list") or []
        for item in items:
            yield _parse_item(item, symbol)

    def fetch_pages(self, symbol: str, pages: int = 3, count: int = 50) -> Iterator[dict]:
        """拉取多页."""
        for p in range(1, pages + 1):
            yield from self.fetch_posts(symbol, count=count, page=p)
            if p < pages:
                time.sleep(0.5)  # 避免限速


def _to_xueqiu_symbol(symbol: str) -> str:
    """将通用股票代码转为雪球格式.

    雪球格式: 美股=VNET, A股=SH600519/SZ000001, 港股=01810
    """
    s = symbol.strip().upper()
    # 已经是雪球格式
    if s.startswith(("SH", "SZ", "HK")):
        return s
    # 纯字母 → 美股
    if s.isalpha():
        return s
    # 6 位数字 → A 股
    if s.isdigit() and len(s) == 6:
        if s.startswith(("6", "9")):
            return f"SH{s}"
        return f"SZ{s}"
    # 5 位数字 → 港股
    if s.isdigit() and len(s) <= 5:
        return s.zfill(5)
    return s


def _parse_item(item: dict, symbol: str) -> dict:
    """将雪球 API 返回的帖子转为统一格式."""
    user = item.get("user") or {}
    created = item.get("created_at")
    publish_time = None
    if created:
        try:
            # 雪球时间戳是毫秒
            publish_time = datetime.fromtimestamp(created / 1000).isoformat()
        except (ValueError, TypeError, OSError):
            pass

    # 提取文字内容，去掉 HTML 标签
    text = item.get("text") or ""
    if "<" in text:
        import re
        text = re.sub(r"<[^>]+>", "", text)
    # 截取前 500 字作为 content
    content = text[:500] if text else None

    return {
        "source": "xueqiu",
        "post_id": str(item.get("id") or ""),
        "symbol": symbol,
        "author": user.get("screen_name"),
        "title": item.get("title") or (text[:80] if text else ""),
        "content": content,
        "publish_time": publish_time,
        "view_count": item.get("view_count"),
        "reply_count": item.get("reply_count"),
        # 雪球 API 公开返回 like_count / retweet_count;不存在时 None,排序时按 0 处理
        "like_count": item.get("like_count") or item.get("fav_count"),
        "share_count": item.get("retweet_count"),
        "url": f"https://xueqiu.com{item['target']}" if item.get("target") else None,
    }
