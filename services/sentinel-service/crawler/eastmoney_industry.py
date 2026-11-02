"""东方财富行业研究报告爬虫 — 行业层面观点.

API 实测可用:
  https://reportapi.eastmoney.com/report/jg

不限定股票代码,而是抓取目标股票所属行业的研究报告。
适合对个股进行"行业上下文"补充:行业景气度、政策影响、龙头股观点等。

可按 industry code 抓,也可按股票代码抓(转换为所属行业)。
"""
from __future__ import annotations

import hashlib
import re
import json
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

_INDUSTRY_URL = "https://reportapi.eastmoney.com/report/jg"


class EastmoneyIndustryClient:
    """行业研究报告爬虫(qType=2 = 行业研究)。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        })

    def fetch(self, stock_code: str, page: int = 1, page_size: int = 20,
              days_back: int = 30) -> Iterator[dict]:
        """拉取行业研究报告(默认最近 30 天)。

        如果传入是股票代码,API 会基于该股票所属行业返回相关研报。
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
            "qType": 2,
            "code": stock_code,
            "fields": "",
        }
        try:
            r = self.session.get(_INDUSTRY_URL, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [eastmoney_industry] request failed: {e}", file=sys.stderr)
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
    rid = str(item.get("id") or "")
    title = (item.get("title") or "").strip()
    org = item.get("orgSName") or item.get("orgName") or ""
    industry = item.get("industryName") or ""

    pub_time = None
    pub = item.get("publishDate")
    if pub:
        try:
            pub_time = datetime.strptime(pub[:19], "%Y-%m-%d %H:%M:%S").isoformat()
        except (ValueError, TypeError):
            pub_time = pub[:10]

    content = f"行业:{industry}" if industry else None

    url = f"https://data.eastmoney.com/report/zw_industry.jshtml?infocode={item.get('infoCode')}" if item.get("infoCode") else None

    return {
        "source": "eastmoney_industry",
        "post_id": rid or _hash(title + (pub or "")),
        "symbol": stock_code,
        "author": org or "券商行业研报",
        "title": title[:200],
        "content": content[:500] if content else None,
        "publish_time": pub_time,
        "view_count": None,
        "reply_count": None,
        "url": url,
    }


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]
