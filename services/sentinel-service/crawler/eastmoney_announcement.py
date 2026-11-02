"""东方财富公告爬虫 — 上市公司公告/PDF 流.

不同于 eastmoney_news(资讯/研报),本模块走 np-anotice-stock 接口,
返回的是真公告(公告 PDF 标题、披露时间、公告类型)。

API 实测可用:
  https://np-anotice-stock.eastmoney.com/api/security/ann

stock_list 必须是 6 位股票代码(A 股),如 300750(宁德时代)。
对于美股/港股,本爬虫返回空(由调用方判断是否调用)。

返回格式同其它 crawler: [{source, post_id, symbol, ...}]
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

_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"


class EastmoneyAnnouncementClient:
    """A 股上市公司公告流(财报、增减持、复牌、回购等)。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        })

    def fetch(self, stock_code: str, page: int = 1, page_size: int = 20) -> Iterator[dict]:
        """拉取某只 A 股的公告.

        stock_code: 6 位代码,如 "300750"。本爬虫只支持 A 股。
        """
        if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
            return  # 非 A 股代码,跳过

        params = {
            "cb": "jQuery",
            "sr": -1,
            "page_size": min(page_size, 50),
            "page_index": page,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": stock_code,
            "f_node": 0,
            "s_node": 0,
        }
        try:
            r = self.session.get(_ANN_URL, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [eastmoney_ann] request failed: {e}", file=sys.stderr)
            return

        # 解析 JSONP: jQuery({...})
        text = r.text.strip()
        m = re.search(r"^\w+\((.+)\)\s*$", text, re.DOTALL)
        if not m:
            print(f"  [eastmoney_ann] JSONP parse failed, len={len(text)}", file=sys.stderr)
            return

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            print(f"  [eastmoney_ann] JSON decode error: {e}", file=sys.stderr)
            return

        items = (data.get("data") or {}).get("list") or []
        for ann in items:
            yield _parse_announcement(ann, stock_code)

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        """统一接口名 — 这里 keyword 实际是 stock_code(由 service 层传入)。"""
        for p in range(1, pages + 1):
            yield from self.fetch(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)


def _parse_announcement(ann: dict, stock_code: str) -> dict:
    """东财公告 JSON → 统一 post 格式."""
    art_code = ann.get("art_code") or ""
    title = (ann.get("title") or "").strip()
    # codes 数组里第一个是当前股票
    codes = ann.get("codes") or []
    short_name = codes[0].get("short_name") if codes else ""
    columns = ann.get("columns") or []
    column_name = columns[0].get("column_name") if columns else ""

    # 时间字段:notice_date / display_time / sort_date 都可能有
    pub_time = None
    for key in ("notice_date", "display_time", "sort_date"):
        v = ann.get(key)
        if v:
            try:
                # "2026-05-07 18:50:09:998" 或 "2026-05-07 00:00:00"
                v_clean = v.replace(":998", "").replace(":000", "")[:19]
                pub_time = datetime.strptime(v_clean, "%Y-%m-%d %H:%M:%S").isoformat()
                break
            except (ValueError, TypeError):
                pub_time = v[:19]
                break

    # 公告 URL — 东财公告详情页
    url = f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html" if art_code else None

    return {
        "source": "eastmoney_ann",
        "post_id": art_code or _hash(title + (pub_time or "")),
        "symbol": stock_code,
        "author": short_name or "公司公告",
        "title": title[:200],
        # 公告本身只有标题,把分类作为 content,便于分析
        "content": column_name[:500] if column_name else None,
        "publish_time": pub_time,
        "view_count": None,
        "reply_count": None,
        "url": url,
    }


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]
