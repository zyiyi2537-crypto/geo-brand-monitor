"""知乎直采适配器 —— 经 search_v3 API(登录态)抓问答/文章 UGC。

知乎搜索 API 需登录(`z_c0`)+ 设备标识(`d_c0`);搜索引擎对知乎收录有限,
而知乎有大量**员工爆料 / 离职评价 / 行业深度**(舆情高价值)。本适配器用一个
知乎账号 cookie(环境变量 `ZHIHU_COOKIE`,需含 `z_c0` + `d_c0`)直采。
发布时间取条目结构化 `created_time`(unix)—— 天然解决时间问题。

cookie 失效(z_c0 过期)→ 返回 [](打 stderr),不拖垮 plan;换 cookie 更新 `ZHIHU_COOKIE`。
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests

_API = "https://www.zhihu.com/api/v4/search_v3"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_TIMEOUT = 25
_CST = timezone(timedelta(hours=8))
_TAG_RE = re.compile(r'<[^>]+>')


def _cookie() -> str:
    c = os.environ.get("ZHIHU_COOKIE", "").strip()
    if not c:
        raise RuntimeError("ZHIHU_COOKIE 未设置 —— 需含 z_c0 + d_c0 的知乎 cookie")
    return c


def _clean(s: str | None) -> str:
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', s or '')).strip()


def _ts_to_iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), _CST).isoformat(timespec="minutes")
    except Exception:
        return None


def _url_for(obj: dict) -> str:
    t = obj.get("type")
    oid = obj.get("id")
    if t == "answer":
        qid = ((obj.get("question") or {}).get("id"))
        if qid and oid:
            return f"https://www.zhihu.com/question/{qid}/answer/{oid}"
    if t == "article":
        return f"https://zhuanlan.zhihu.com/p/{oid}"
    if t == "question":
        return f"https://www.zhihu.com/question/{oid}"
    if t == "zvideo":
        return f"https://www.zhihu.com/zvideo/{oid}"
    return obj.get("url") or ""


def zhihu_search(query: str, max_results: int = 20,
                 timelimit: str | None = None) -> list[dict]:
    """知乎综合搜索,返回 [{title,href,body,publish_time,author}]。失败返回 []。"""
    headers = {
        "User-Agent": _UA, "Cookie": _cookie(),
        "Accept": "application/json, text/plain, */*",
        "x-api-version": "3.0.91",
        "Referer": ("https://www.zhihu.com/search?type=content&q="
                    + urllib.parse.quote(query)),
    }
    params = {"t": "general", "q": query, "offset": 0,
              "limit": min(max_results, 20), "correction": 1}
    try:
        r = requests.get(_API, params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [zhihu] request failed: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for it in data.get("data", []):
        obj = it.get("object") or {}
        if not isinstance(obj, dict):
            continue
        title = _clean(obj.get("title") or (obj.get("question") or {}).get("name"))
        body = _clean(obj.get("excerpt") or obj.get("content"))
        if not (title or body):
            continue
        author = ((obj.get("author") or {}).get("name")) or None
        pub = _ts_to_iso(obj.get("created_time") or obj.get("updated_time"))
        out.append({
            "title": title or body[:48],
            "href": _url_for(obj),
            "body": body or title,
            "publish_time": pub,
            "author": author,
        })
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":   # 自测:python - "世纪互联"
    q = sys.argv[1] if len(sys.argv) > 1 else "世纪互联"
    rows = zhihu_search(q, max_results=10)
    print(f"query={q!r} → {len(rows)} 条")
    for r in rows:
        print(f"  {r['publish_time']!s:<17} @{r['author']}: {r['title'][:30]} | {r['body'][:40]}  {r['href']}")
