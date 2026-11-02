"""雪球抓取 helper —— 在独立 scrapling-venv 中运行(Scrapling StealthyFetcher 过 WAF)。

雪球搜索页有 JS WAF(_waf_bd8ce2ce37),纯请求(连带 xq_a_token)都过不去,必须真浏览器
执行 JS。Scrapling 浏览器栈(playwright + curl_cffi)较重且与 fastapi 服务的 anyio 版本
冲突,故**隔离在 /opt/geo/scrapling-venv**,由 search/xueqiu.py 通过 subprocess 调用,
本脚本只往 stdout 打一行 JSON。WAF 过后搜索页公开,**无需登录 cookie**。

用法: /opt/geo/scrapling-venv/bin/python xueqiu_fetch.py "<query>" [max]
"""
import json
import logging
import re
import sys
import urllib.parse
from datetime import date, timedelta

logging.disable(logging.INFO)   # 别让 scrapling 的 INFO 日志污染 stdout JSON

from scrapling.fetchers import StealthyFetcher


def _txt(sel_list) -> str:
    if not sel_list:
        return ""
    e = sel_list[0]
    # 用元素 HTML 直接去标签(不插空格)—— 雪球把搜索词包在高亮 span 里,
    # get_all_text 会按文本节点插空格,导致 "世纪互联" → "世 纪 互 联",破坏相关性匹配。
    h = getattr(e, "html_content", "") or ""
    if h:
        raw = re.sub(r'<[^>]+>', '', h)
    else:
        f = getattr(e, "get_all_text", None)
        raw = (f() if callable(f) else "") or str(getattr(e, "text", "") or "")
    return re.sub(r'[ \t​]+', ' ', raw).replace('\n', ' ').strip()


def _href(sel_list) -> str:
    if not sel_list:
        return ""
    e = sel_list[0]
    for attr in ("attrib", "attrs"):
        a = getattr(e, attr, None)
        if a:
            try:
                h = a.get("href") or ""
                if h.startswith("//"):
                    return "https:" + h
                if h.startswith("/"):
                    return "https://xueqiu.com" + h
                if h:
                    return h
            except Exception:
                pass
    return ""


def _parse_time(s: str, today: date):
    s = re.sub(r'·.*$', '', s).strip()            # 去掉 "· 来自iPhone"
    if not s:
        return None
    if re.search(r'\d+\s*(秒|分钟|小时)前', s) or s.startswith('今天'):
        d = today
    elif s.startswith('昨天'):
        d = today - timedelta(days=1)
    else:
        m = re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})', s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r'(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)', s)    # MM-DD → 今年
        if m:
            return f"{today.year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        return None
    hm = re.search(r'(\d{1,2}):(\d{2})', s)
    return f"{d.isoformat()}T{int(hm.group(1)):02d}:{hm.group(2)}" if hm else d.isoformat()


def _parse(page, today: date) -> list:
    out = []
    for it in page.css(".timeline__item"):
        text = _txt(it.css(".timeline__item__content"))
        if not text:
            continue
        ds = it.css(".date-and-source")
        out.append({
            "title": text[:48],
            "href": _href(ds).split("?")[0],
            "body": text,
            "publish_time": _parse_time(_txt(ds), today),
            "author": _txt(it.css(".user-name")) or None,
        })
    return out


def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "世纪互联"
    mx = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    url = "https://xueqiu.com/k?q=" + urllib.parse.quote(q)
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=90000)
        html = getattr(page, "html_content", "") or ""
        if "_waf_" in html and "timeline__item" not in html:
            print(json.dumps({"error": "WAF 未过"})); return
        rows = _parse(page, date.today())[:mx]
    except Exception as e:
        print(json.dumps({"error": repr(e)[:200]})); return
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
