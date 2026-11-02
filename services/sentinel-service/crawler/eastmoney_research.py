"""东方财富个股研报爬虫 — 券商研报观点流.

API 实测可用:
  https://reportapi.eastmoney.com/report/list

每条研报含:券商名、研究员、目标价、评级、摘要 — 高质量分析数据。
比新闻/股吧更"专业"的舆情维度。

支持 A 股代码(6 位数字),如 300750。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Iterator

import requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_RESEARCH_URL = "https://reportapi.eastmoney.com/report/list"


class EastmoneyResearchClient:
    """个股研报爬虫(qType=0 = 个股报告)。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        })

    def fetch(self, stock_code: str, page: int = 1, page_size: int = 20,
              days_back: int = 90) -> Iterator[dict]:
        """拉取某只 A 股的最新券商研报.

        days_back: 默认拉最近 90 天的研报,避免每次跑全量。
        """
        if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
            return

        end = datetime.now().date()
        begin = end - timedelta(days=max(days_back, 7))

        params = {
            "cb": "jQuery",
            "pageSize": min(page_size, 50),
            "beginTime": begin.strftime("%Y-%m-%d"),
            "endTime": end.strftime("%Y-%m-%d"),
            "pageNo": page,
            "qType": 0,                # 0=个股报告
            "code": stock_code,
            "fields": "",
        }
        try:
            r = self.session.get(_RESEARCH_URL, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [eastmoney_research] request failed: {e}", file=sys.stderr)
            return

        text = r.text.strip()
        m = re.search(r"^\w+\((.+)\)\s*$", text, re.DOTALL)
        if not m:
            return
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return

        for item in data.get("data") or []:
            yield _parse(item, stock_code)

    def search_pages(self, keyword: str, pages: int = 3, page_size: int = 20) -> Iterator[dict]:
        for p in range(1, pages + 1):
            yield from self.fetch(keyword, page=p, page_size=page_size)
            if p < pages:
                time.sleep(0.5)


def _parse(item: dict, stock_code: str) -> dict:
    info_code = item.get("infoCode") or ""
    title = (item.get("title") or "").strip()
    org = item.get("orgSName") or item.get("orgName") or ""

    pub_time = None
    pub = item.get("publishDate")
    if pub:
        try:
            pub_time = datetime.strptime(pub[:19], "%Y-%m-%d %H:%M:%S").isoformat()
        except (ValueError, TypeError):
            pub_time = pub[:10]

    rating = item.get("emRatingName") or item.get("ratingChange") or ""
    target = item.get("indvAimPriceL") or item.get("indvAimPriceT") or ""

    # 把评级、目标价拼到 content 里,LLM 分析时能感知"看多/看空"
    content_parts = []
    if rating:
        content_parts.append(f"评级:{rating}")
    if target:
        content_parts.append(f"目标价:{target}")
    if item.get("predictNextTwoYearEps"):
        content_parts.append(f"未来两年 EPS 预测:{item['predictNextTwoYearEps']}")

    content = "·".join(content_parts) or None

    url = f"https://data.eastmoney.com/report/info/{info_code}.html" if info_code else None

    return {
        "source": "eastmoney_research",
        "post_id": info_code or _hash(title + (pub or "")),
        "symbol": stock_code,
        "author": org or "券商研报",
        "title": title[:200],
        "content": content[:500] if content else None,
        "publish_time": pub_time,
        "view_count": None,
        "reply_count": None,
        "url": url,
    }


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]
