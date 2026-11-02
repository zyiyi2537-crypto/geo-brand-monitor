import re
from datetime import datetime
from typing import Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
BASE = "https://guba.eastmoney.com"


class EastmoneyGubaClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": f"{BASE}/",
        })

    def fetch_list(self, symbol: str, page: int = 1) -> Iterator[dict]:
        sym = _guba_symbol(symbol)
        if page == 1:
            url = f"{BASE}/list,{sym}.html"
        else:
            url = f"{BASE}/list,{sym}_{page}.html"
        r = self.session.get(url, timeout=15, allow_redirects=False)
        if r.status_code in (301, 302) and "error" in (r.headers.get("Location") or ""):
            raise ValueError(f"eastmoney guba has no board for symbol {symbol!r} (url={url})")
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        yield from self._parse_list(r.text, symbol)

    def _parse_list(self, html: str, symbol: str) -> Iterator[dict]:
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("tr.listitem, div.articleh")
        for row in rows:
            href_el = row.select_one("div.title a, span.l3 a, a[data-postid]")
            if not href_el:
                continue
            href = href_el.get("href", "")
            title = href_el.get("title") or href_el.get_text(strip=True)
            author_el = row.select_one("div.author a, span.l4 a, font a")
            time_el = row.select_one("div.update, span.l5, span.l6, .time")
            read_el = row.select_one("div.read, span.l1, em.read")
            reply_el = row.select_one("div.reply, span.l2, em.reply")
            yield {
                "post_id": href_el.get("data-postid") or _extract_id(href),
                "source": "eastmoney",
                "symbol": symbol,
                "author": author_el.get_text(strip=True) if author_el else None,
                "title": title,
                "content": None,
                "publish_time": _parse_time(time_el.get_text(strip=True) if time_el else None),
                "view_count": _parse_int(read_el.get_text(strip=True) if read_el else None),
                "reply_count": _parse_int(reply_el.get_text(strip=True) if reply_el else None),
                "url": _normalize_url(href),
                "raw": None,
            }


def _guba_symbol(symbol: str) -> str:
    s = symbol.strip()
    low = s.lower()
    if low.startswith(("sh", "sz", "bj", "hk")):
        return low
    if low.startswith("us"):
        return "US" + s[2:].lstrip("_").upper()
    if any(c.isalpha() for c in s) and not any(c.isdigit() for c in s):
        return f"US{s.upper()}"
    return low


def _normalize_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    return urljoin(BASE, href)


def _extract_id(href: str) -> str | None:
    m = re.search(r"news,[^,]+,(\d+)\.html", href or "")
    if m:
        return m.group(1)
    m = re.search(r"/news/(\d+)", href or "")
    return m.group(1) if m else None


def _parse_int(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "")
    if not s:
        return None
    if s.endswith("万"):
        try:
            return int(float(s[:-1]) * 10000)
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_time(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    now = datetime.now()
    m = re.match(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        month, day, hour, minute = map(int, m.groups())
        dt = datetime(now.year, month, day, hour, minute)
        if dt > now:
            dt = dt.replace(year=now.year - 1)
        return dt.isoformat()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        return datetime(*map(int, m.groups())).isoformat()
    return s
