"""新浪财经个股新闻页爬虫 — server-rendered HTML.

不同于 sina_finance.py(走 search SPA 抓不到内容),本模块直接抓个股新闻聚合页,
该页面是 server-rendered 的 GB18030 HTML,稳定可解析。

URL 格式:
  A 股: https://finance.sina.com.cn/realstock/company/{sz|sh}{6位代码}/nc.shtml
  美股: https://finance.sina.com.cn/realstock/company/{TICKER}/nc.shtml
  港股: 暂不支持

返回格式同其它 crawler。
"""
from __future__ import annotations

import hashlib
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

# 个股新闻 URL 模板 — 注意是 GB18030 编码的页面
_SINA_NC_URL = "https://finance.sina.com.cn/realstock/company/{prefix}/nc.shtml"

# 抓取页内文章链接的正则 — sina 文章 URL 走 finance.sina.com.cn,日期+doc-...shtml 形式
_ARTICLE_RE = re.compile(
    r'<a\s+href="(https?://finance\.sina\.com\.cn/[^"]+/doc-[^"]+\.shtml)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
# URL 里的日期(2026-05-07)
_DATE_IN_URL = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/")


class SinaStockNewsClient:
    """个股新闻聚合页爬虫(免登录,免 cookie)。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://finance.sina.com.cn/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def fetch(self, stock_code: str) -> Iterator[dict]:
        """拉取某个股票的最近新闻。

        stock_code:
        - "300750" / "600519" → A 股,自动加 sz/sh 前缀
        - "VNET" / "TSLA"     → 美股,大写代码
        """
        prefix = _to_sina_prefix(stock_code)
        if not prefix:
            return  # 不支持的市场

        url = _SINA_NC_URL.format(prefix=prefix)
        try:
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            # 这个页面是 GB18030 编码,iso 解码会乱
            r.encoding = "gb18030"
        except requests.RequestException as e:
            print(f"  [sina_stock_news] request failed: {e}", file=sys.stderr)
            return

        seen_urls: set[str] = set()
        for m in _ARTICLE_RE.finditer(r.text):
            href = m.group(1).strip()
            title = m.group(2).strip()
            if href in seen_urls or len(title) < 4:
                continue
            seen_urls.add(href)

            pub_time = None
            d = _DATE_IN_URL.search(href)
            if d:
                try:
                    pub_time = datetime(*[int(x) for x in d.groups()]).isoformat()
                except (ValueError, TypeError):
                    pass

            yield {
                "source": "sina_stock",
                "post_id": _hash(href),
                "symbol": stock_code,
                "author": "新浪财经",
                "title": title[:200],
                "content": None,                # 详情页才能拿摘要,这里只拿标题
                "publish_time": pub_time,
                "view_count": None,
                "reply_count": None,
                "url": href,
            }

    def search_pages(self, keyword: str, pages: int = 1) -> Iterator[dict]:
        """统一接口名 — keyword 实际是 stock_code。

        sina 个股页一次性返回最近 ~30 条新闻,无分页 — pages 参数被忽略。
        """
        del pages  # noqa: B007 — 接口一致性占位
        yield from self.fetch(keyword)
        time.sleep(0.2)


def _to_sina_prefix(code: str) -> str | None:
    """股票代码 → 新浪 URL 前缀。"""
    s = (code or "").strip()
    if not s:
        return None
    s_upper = s.upper()
    # 美股:纯字母,如 VNET, TSLA
    if s_upper.isalpha():
        return s_upper
    # 6 位数字 = A 股
    if s.isdigit() and len(s) == 6:
        return f"sh{s}" if s.startswith(("6", "9")) else f"sz{s}"
    # 已带前缀(SH/SZ/HK)— 转小写
    if s_upper.startswith(("SH", "SZ")) and len(s) == 8:
        return s_upper.lower()
    return None


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]
