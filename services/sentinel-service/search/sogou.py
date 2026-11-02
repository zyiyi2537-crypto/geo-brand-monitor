"""搜狗 sogou.com 搜索 — 免费,无需 API key,中文索引最深.

两个端点:
- www.sogou.com/web         — 通用网页搜索,支持 site: 直接过滤
- weixin.sogou.com/weixin   — 微信公众号专属搜索(对 mp.weixin.qq.com 索引最深)

对外接口与 baidu/cnbing/ddg 对齐: sogou_search(q, max_results, timelimit) -> [{title, href, body}].

为什么加这个:
- DDG 在 EC2 限流;baidu 需 cookie;cnbing 在海外 CAPTCHA
- 搜狗中文站索引广(微博/微信/雪球/今日头条/知乎都覆盖)
- 微信公众号搜索是搜狗官方独家入口,其他引擎都不如它

注意:hrefs 是 sogou.com/link?url=... 的跳转链,首层调用方拿到的就是这个;
如需真实 URL 可设 resolve_redirect=True(慢,需额外 GET 每条结果).
"""
from __future__ import annotations
import os
import sys
import time
import re
import requests
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

_TIMEOUT = 12
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _is_blocked(html: str) -> bool:
    return "请输入验证码" in html or "captcha" in html.lower() or "robot.html" in html


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    cookie = os.environ.get("SOGOU_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def _resolve_redirect(href: str, session: requests.Session) -> str:
    """sogou /link?url=... 跳转 → 真实 URL. 失败返原样."""
    if not href.startswith("/link?") and "sogou.com/link?" not in href:
        return href
    full = href if href.startswith("http") else "https://www.sogou.com" + href
    try:
        r = session.head(full, timeout=8, allow_redirects=False)
        loc = r.headers.get("Location")
        if loc:
            return loc
        # 有时是 JS 跳转 — GET 后从 meta refresh / window.location 提取
        r = session.get(full, timeout=8, allow_redirects=False)
        m = re.search(r'window\.location\.replace\("([^"]+)"', r.text)
        if m:
            return m.group(1)
        m = re.search(r'URL=([^"\']+)', r.text)
        if m:
            return m.group(1)
    except requests.RequestException:
        pass
    return full


def _parse_sogou_web(html: str) -> list[dict]:
    """解析 sogou.com/web 结果页."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []
    seen = set()
    # 主结果容器: div.vrwrap (新版) / div.results > div.vrwrap
    for div in soup.select("div.vrwrap, div.results .vrwrap"):
        h3 = div.select_one("h3.vr-title, h3.vrTitle")
        a = (h3.select_one("a[href]") if h3 else None) or div.select_one("a[href]")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        title = (a.get_text(strip=True) or "")
        # 摘要
        body_el = div.select_one(".str-info, .ft, .str_info")
        body = body_el.get_text(" ", strip=True) if body_el else ""
        results.append({"title": title[:200], "href": href, "body": body[:300]})
    return results


def _parse_sogou_weixin(html: str) -> list[dict]:
    """解析 weixin.sogou.com/weixin 结果页."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []
    seen = set()
    for li in soup.select("ul.news-list li, .news-box ul li"):
        h3 = li.select_one("h3 a, .txt-box h3 a")
        if not h3:
            continue
        href = (h3.get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        title = h3.get_text(strip=True)
        body_el = li.select_one(".txt-info, p.txt-info")
        body = body_el.get_text(" ", strip=True) if body_el else ""
        results.append({"title": title[:200], "href": href, "body": body[:300]})
    return results


def sogou_search(query: str, max_results: int = 10,
                 timelimit: str | None = None,
                 *, channel: str | None = None,
                 resolve_redirect: bool = False) -> list[dict]:
    """搜索并返回 [{title, href, body}].

    channel:
      - None / 'web'  → www.sogou.com/web (通用,支持 site:)
      - 'weixin'      → weixin.sogou.com/weixin (微信公众号专属;query 自动剥 site:mp.weixin.qq.com)
      - 'auto'        → 若 query 含 site:mp.weixin 则走 weixin,否则走 web

    timelimit: sogou 通用搜索 web 端不直接支持;微信端支持 sort=date.
    resolve_redirect: 是否把 /link?url= 解析成真实 URL(慢,默认 False).
    """
    if channel == "auto":
        channel = "weixin" if "site:mp.weixin.qq.com" in query else "web"

    session = _build_session()

    if channel == "weixin":
        # 微信端:剥离 site: 前缀,因为该端点本来就只搜 mp.weixin
        q = re.sub(r"site:mp\.weixin\.qq\.com\s*", "", query).strip()
        params = {"type": "2", "query": q, "ie": "utf8"}
        if timelimit:
            params["sort"] = "date"  # 时间倒序近似 timelimit 'd'/'w'
        url = "https://weixin.sogou.com/weixin"
    else:
        params = {"query": query, "num": max(min(max_results, 50), 10)}
        url = "https://www.sogou.com/web"

    try:
        r = session.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [sogou] request failed: {e}", file=sys.stderr)
        return []

    r.encoding = "utf-8"
    html = r.text
    if _is_blocked(html):
        hint = "" if os.environ.get("SOGOU_COOKIE") else " (set SOGOU_COOKIE env var to bypass)"
        print(f"  [sogou] CAPTCHA / verification page returned{hint}", file=sys.stderr)
        return []

    if channel == "weixin":
        results = _parse_sogou_weixin(html)
    else:
        results = _parse_sogou_web(html)

    if resolve_redirect:
        for r_ in results[:max_results]:
            r_["href"] = _resolve_redirect(r_["href"], session)
            time.sleep(0.2)  # 节流

    return results[:max_results]


if __name__ == "__main__":
    # python -m search.sogou 'site:weibo.com 世纪互联'
    q = " ".join(sys.argv[1:]) or "site:xueqiu.com 世纪互联"
    rows = sogou_search(q, max_results=10, channel="auto")
    print(f"[{len(rows)}] {q}")
    for x in rows[:5]:
        print(f"  · {x['title'][:60]}")
        print(f"    {x['href'][:100]}")
        print(f"    {x['body'][:80]}")
