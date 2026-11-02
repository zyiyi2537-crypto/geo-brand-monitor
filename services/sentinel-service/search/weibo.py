"""微博直采适配器 —— 经 s.weibo.com(PC 登录态)抓实时 UGC。

搜索引擎(百度/必应/360)基本不收录微博个人帖,且微博站内搜索强制登录。
本适配器用一个 PC 微博账号的 cookie(环境变量 `WEIBO_COOKIE`,需含 SUB+SUBP)
直接打 s.weibo.com,**综合(热度)+ 实时(时间)双路召回**,补上 UGC 盲区
(讨薪 / 维权 / 做空 / 爆雷这类负面)。发帖时间从卡片结构化解析 —— 天然解决
"时间对不上"的问题。

cookie 会过期(SUB 的 ALF 时间戳约数周),失效时本适配器返回 [](打 stderr),
不拖垮整个 plan;换 cookie 只需更新 `WEIBO_COOKIE`。
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

import requests

_BASE = "https://s.weibo.com/weibo"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_TIMEOUT = 25

# s.weibo.com 结果页结构(实测):每个结果在一个 card-wrap 里 —
#   正文:<p class="txt" node-type="feed_list_content" nick-name="昵称"> … </p>
#   时间+链接:<div class="from"> <a href="//weibo.com/UID/MID?…">05月15日 08:51</a> 来自 … </div>
_CARD_SPLIT = re.compile(r'<div class="card-wrap"')
_CONTENT_RE = re.compile(r'<p class="txt"[^>]*nick-name="([^"]*)"[^>]*>(.*?)</p>', re.S)
_FROM_RE = re.compile(
    r'<div class="from"\s*>\s*<a\s+href="(//weibo\.com/[^"]+)"[^>]*>\s*(.*?)\s*</a>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def _cookie() -> str:
    c = os.environ.get("WEIBO_COOKIE", "").strip()
    if not c:
        raise RuntimeError("WEIBO_COOKIE 未设置 —— 需一个 PC 微博账号 cookie(含 SUB+SUBP)")
    return c


def _clean(html: str) -> str:
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', html)).replace('​', '').strip()


def _parse_time(s: str, today: date) -> str | None:
    """微博相对/绝对时间 → ISO。'X分钟前'/'今天 HH:MM'→今天;'M月D日'→今年;'YYYY-MM-DD'原样。"""
    s = s.strip()
    if not s:
        return None
    if re.search(r'\d+\s*(秒|分钟|小时)前', s) or s.startswith('今天'):
        d = today
    elif s.startswith('昨天'):
        d = today - timedelta(days=1)
    else:
        m = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r'(\d{1,2})月(\d{1,2})日', s)        # 05月15日 → 今年
        if m:
            return f"{today.year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        m = re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})', s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return None
    hm = re.search(r'(\d{1,2}):(\d{2})', s)
    if hm:
        return f"{d.isoformat()}T{int(hm.group(1)):02d}:{hm.group(2)}"
    return d.isoformat()


def _fetch(query: str, realtime: bool) -> str:
    params: dict[str, str] = {"q": query}
    if realtime:                       # 实时(按时间)—— 抓低传播 UGC(讨薪/维权)
        params["xsort"] = "time"
        params["suball"] = "1"
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA, "Cookie": _cookie(), "Referer": "https://s.weibo.com/"})
    r = session.get(_BASE, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.text


def _parse(html: str, today: date) -> list[dict]:
    out: list[dict] = []
    for card in _CARD_SPLIT.split(html)[1:]:
        if "wb-ad-tile" in card:          # 跳过广告卡(无真实发帖时间)
            continue
        cm = _CONTENT_RE.search(card)
        if not cm:
            continue
        text = _clean(cm.group(2))
        if not text:
            continue
        fm = _FROM_RE.search(card)
        url, pub = "", None
        if fm:
            url = "https:" + fm.group(1).split("?")[0]
            pub = _parse_time(_clean(fm.group(2)), today)
        out.append({
            "title": text[:48],
            "href": url,
            "body": text,
            "publish_time": pub,
            "author": cm.group(1).strip(),
        })
    return out


def weibo_search(query: str, max_results: int = 20,
                 timelimit: str | None = None) -> list[dict]:
    """综合 + 实时双路召回,按帖子 URL 去重;返回 [{title,href,body,publish_time,author}]。

    任何传输 / cookie 失效 → 返回已收集到的部分(打 stderr),不抛出。

    实时(xsort=time)优先、综合次之,**每路各自配额 max_results** —— 否则综合
    的旧爆款帖会先填满名额,导致最新的实时 UGC 永远轮不到(舆情最在意的就是最新)。
    """
    today = date.today()
    seen: set[str] = set()
    out: list[dict] = []
    for realtime in (True, False):       # 实时优先(抓最新),再综合(热度)
        try:
            html = _fetch(query, realtime)
        except Exception as e:
            print(f"  [weibo] fetch failed (realtime={realtime}): {e}", file=sys.stderr)
            continue
        if "passport.weibo.com" in html and len(html) < 5000:
            print("  [weibo] cookie 失效(被跳登录页)—— 请更新 WEIBO_COOKIE", file=sys.stderr)
            return out
        cnt = 0
        for it in _parse(html, today):
            key = it["href"] or it["body"][:40]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
            cnt += 1
            if cnt >= max_results:        # 每路独立配额,保证实时也能进
                break
    return out


if __name__ == "__main__":   # 自测:python -m search.weibo "世纪互联 欠薪"
    import json
    q = sys.argv[1] if len(sys.argv) > 1 else "世纪互联"
    rows = weibo_search(q, max_results=12)
    print(f"query={q!r} → {len(rows)} 条")
    for r in rows:
        print(f"  {r['publish_time']!s:<17} @{r['author']}: {r['body'][:48]}  {r['href']}")
