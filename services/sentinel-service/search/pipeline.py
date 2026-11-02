"""Run a monitoring plan: search each query, dedupe, normalize, ingest into SQLite.

Output rows go into the same `posts` table the eastmoney crawler uses, so the
existing analyzer / brief / drafts / chat / report all work unchanged.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

from storage import (
    connect, init_schema, upsert_post,
    get_query_last_run, upsert_query_last_run,
)

from .baidu import baidu_search
from .cnbing import cnbing_search
from .ddg import ddg_search, throttle
from .sogou import sogou_search
from .searxng import searxng_search
from .weibo import weibo_search
from .zhihu import zhihu_search
from .xueqiu import xueqiu_search


# SearXNG 单引擎(server 端聚合多上游 + 处理反爬/IP池);自带引擎保留可回退。
DEFAULT_ENGINES = ("searxng",)


# DDG occasionally returns titles where the `&` of an HTML numeric entity has
# been replaced with `||`, e.g. `||#19990;纪互联`. Repair before persisting.
_BROKEN_ENTITY_RE = re.compile(r"\|\|(#\d+;)")


def _clean(text: str | None) -> str | None:
    if not text:
        return text
    text = _BROKEN_ENTITY_RE.sub(r"&\1", text)
    return html.unescape(text)


# Map well-known hostnames to short, stable source names so the analyzer +
# report group results by platform regardless of which specific subdomain
# they came back on.
_HOST_TO_SOURCE = [
    ("xueqiu.com",          "xueqiu"),
    ("guba.eastmoney.com",  "eastmoney"),
    ("eastmoney.com",       "eastmoney"),
    ("weibo.com",           "weibo"),
    ("weibo.cn",            "weibo"),
    ("zhihu.com",           "zhihu"),
    ("douban.com",          "douban"),
    ("tieba.baidu.com",     "tieba"),
    ("zhidao.baidu.com",    "zhidao"),
    ("news.baidu.com",      "baidu_news"),
    ("36kr.com",            "36kr"),
    ("caixin.com",          "caixin"),
    ("bilibili.com",        "bilibili"),
    ("toutiao.com",         "toutiao"),
    ("xiaohongshu.com",     "xiaohongshu"),
    ("xhslink.com",         "xiaohongshu"),
    ("kuaishou.com",        "kuaishou"),
    ("mp.weixin.qq.com",    "weixin"),
    ("weixin.qq.com",       "weixin"),
    ("sina.com",            "sina"),
    ("163.com",             "163"),
    ("qq.com",              "qq"),
    ("reddit.com",          "reddit"),
    ("twitter.com",         "twitter"),
    ("x.com",               "twitter"),
    ("youtube.com",         "youtube"),
    ("medium.com",          "medium"),
    ("seekingalpha.com",    "seekingalpha"),
    ("bloomberg.com",       "bloomberg"),
    ("ft.com",              "ft"),
    ("wsj.com",             "wsj"),
    ("nytimes.com",         "nyt"),
]


def url_to_post_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def domain_to_source(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for needle, name in _HOST_TO_SOURCE:
        if host == needle or host.endswith("." + needle):
            return name
    return host or "unknown"


# 发布日期抽取:SearXNG 上游不给 publishedDate 时,从标题 / 摘要里尽力抽一个
# **绝对**日期(必须带 4 位年份),让前端时间轴 / "最近 N 天" 不至于全空。
# 只认绝对日期 — 相对时间("3 天前")缺锚点容易猜错,宁可留 None。
_DATE_PATTERNS = [
    (re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"), (1, 2, 3)),       # 2026-06-15 / 2026/6/15
    (re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), (1, 2, 3)),  # 2026年6月15日
]
_EN_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_EN_DATE_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})",
    re.IGNORECASE,
)


def extract_publish_date(text: str | None) -> str | None:
    if not text:
        return None
    for rx, (yi, mi, di) in _DATE_PATTERNS:
        m = rx.search(text)
        if m:
            y, mo, d = int(m.group(yi)), int(m.group(mi)), int(m.group(di))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _EN_DATE_RE.search(text)
    if m:
        mo = _EN_MONTHS.get(m.group(1).lower()[:3])
        d, y = int(m.group(2)), int(m.group(3))
        if mo and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


# URL 内嵌日期抽取(②级,高可靠):多数中文新闻站把发布日期写进 URL —
#   sina   finance.sina.com.cn/.../2026-04-05/...        →  /20YY-MM-DD/
#   eastmoney  /news/20260616150020...   /a/202605173739...  →  8 位 20YYMMDD 连号
#   qq  /rain/a/20260514A00FU400    10jqka  /20260409/c...  →  8 位连号
# 比从摘要里猜可靠得多;校验月/日合法、年份 2000-2099,取第一个命中。
_URL_DATE_RES = [
    re.compile(r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:[-/_.]|$)"),  # /2026-06-15/  /2026/6/15
    re.compile(r"/(20\d{2})/(\d{2})(\d{2})(?:/|[?#]|$)"),             # /2026/0527/ (年/月日,如 eeo)
    re.compile(r"[/_a-zA-Z-](20\d{2})(\d{2})(\d{2})\d*"),             # /20260616 或 t20260618(字母/分隔前缀)
]


def extract_date_from_url(url: str | None) -> str | None:
    if not url:
        return None
    for rx in _URL_DATE_RES:
        m = rx.search(url)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


# ── #2 垃圾/非舆情页过滤(百科/行情/股吧列表/招聘/工商/采集农场)──────────────
# 这些页面会提及目标名却不是舆情,被打上近期时间戳就污染窗口。入库前在相关性闸门挡掉。
_JUNK_DOMAINS = {
    "baike.baidu.com", "baike.so.com", "wenku.baidu.com", "wen.baidu.com",
    "wenku.so.com", "aiqicha.baidu.com", "ai.so.com", "zh.wikipedia.org",
    "en.wikipedia.org", "www.qcc.com", "www.jobui.com", "m.jobui.com",
    "www.199it.com", "www.catl.com", "www.microsoft.com", "azure.microsoft.com",
    "www.azure.cn", "docs.azure.cn", "docs.microsoft.com", "learn.microsoft.com",
    "www.office.com", "account.microsoft.com", "www.onlinedown.net",
}
_JUNK_URL_RE = re.compile(
    r"(quote\.eastmoney|/quote/|/quotes/|/list,|/tags/|guba\.eastmoney\.com/list|"
    r"weibo\.com/u/|/company_|/wiki/|wikipedia\.org|/tashuo/|360kuai\.com|/baiqi/|"
    r"19lou\.com|book118|doc88|woc88|onlinedown|"
    # 自家官网静态营销/产品页(不是舆情;还会被动态生成的"当前时间"误标成今日)。
    # 仅挡根级 .html 公司页 + solution/sustainability 等目录;保留 /portal/article 新闻。
    r"vnet\.com/[a-z_-]+\.html|vnet\.com/(?:solution|sustainability|product|about|culture|partner|honor|service)\b)",
    re.I)
# SEO 采集农场:杂牌 教育/企业/地方站把新闻洗一遍蹭排名(非财经媒体)
_FARM_RE = re.compile(r"(sdzhedu|xbanche|wfshengda|hfteng|shengda\.|zhedu\.)", re.I)
_JUNK_TITLE_RE = re.compile(
    r"(百科|词条|行情中心|股票价格_|股价行情|股价_|资产负债表|财务分析|数据报告-雪球|"
    r"招聘|工资待遇|工商信息|爱企查|注册.{0,4}指南|开通指南|品牌排行|十大品牌|"
    r"的微博_微博|_相关报道|相关报道/新闻)")


def is_junk_page(url: str, title: str | None) -> bool:
    """非舆情结构页(百科/行情/列表/招聘/工商/采集农场)→ True,入库前丢弃。"""
    host = (urlparse(url or "").hostname or "").lower()
    if host in _JUNK_DOMAINS:
        return True
    if _JUNK_URL_RE.search(url or "") or _FARM_RE.search(url or ""):
        return True
    if title and _JUNK_TITLE_RE.search(title):
        return True
    return False


# ── ③ 抓全文 meta 补真实发布时间(给"引擎+URL 都没日期"的 undated 帖)──────────
_META_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_META_RES = [
    re.compile(r'<meta[^>]+(?:property|name|itemprop)=["\'](?:article:published_time|'
               r'og:published_time|og:release_time|publishdate|pubdate|pubtime|'
               r'weibo:\s*article:create_at|datePublished|date|apub:time)["\'][^>]*?'
               r'content=["\']([^"\']+)["\']', re.I),
    re.compile(r'content=["\']([^"\']+)["\'][^>]*(?:property|name|itemprop)=["\']'
               r'(?:article:published_time|og:published_time|datePublished|pubdate)["\']', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I),
]


def _date_from_text(s: str) -> str | None:
    m = re.search(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})', s or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    tm = re.search(r'(\d{1,2}):(\d{2})', s)
    return f"{y:04d}-{mo:02d}-{d:02d}" + (f"T{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "")


def _visible_publish_date(html: str) -> str | None:
    """页头可见中文发布时间:'2026年05月19日 16:35'(带年)/ '05月15日 12:35'(无年,带时分)。

    只取页头(前 ~8000 字,发布时间通常紧跟标题),避免抓到正文里提到的日期。
    无年份的按当年算,若落到未来则算去年。存的还是 ISO(YYYY-MM-DDTHH:MM)。
    """
    head = html[:8000]
    # **必须带"时:分"** —— 发布头有时分(2026年05月19日 16:35),正文提到的日期(截至2026年3月31日)
    # 没时分,以此区分,避免抓到正文里的日期。
    m = re.search(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s+(\d{1,2}):(\d{2})', head)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}T{int(m.group(4)):02d}:{m.group(5)}"
    # 无年份但带时分(每经:05月15日 12:35)→ 当年,落到未来则去年
    m = re.search(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日\s+(\d{1,2}):(\d{2})', head)
    if m:
        from datetime import date as _d
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            today = _d.today()
            y = today.year - (1 if (mo, d) > (today.month, today.day) else 0)
            return f"{y:04d}-{mo:02d}-{d:02d}T{int(m.group(3)):02d}:{m.group(4)}"
    return None


def _looks_like_now(date_str: str | None) -> bool:
    """抓到的"发布时间"是否约等于**现在**(抓取时刻)。

    有些站(36氪老 /p/ 页、vnet 官网)把动态生成的当前时间塞进 article:published_time,
    每次抓都是 now —— 那不是发布时间,是渲染时间。带时分的若落在 [now-10min, now+1h] 判为伪造。
    """
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})', date_str or "")
    if not m:
        return False          # 纯日期不算 now 伪造
    try:
        dt = datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return False
    now = datetime.now()
    return now - timedelta(minutes=10) <= dt <= now + timedelta(hours=1)


def fetch_meta_date(url: str) -> str | None:
    """GET 文章页,从 meta / JSON-LD / <time> / 页头可见时间抽真实发布时间。失败/无/疑似渲染时间 → None。"""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=10, allow_redirects=True,
                         headers={"User-Agent": _META_UA, "Accept-Language": "zh-CN,zh"})
        r.encoding = r.apparent_encoding or r.encoding   # 中文页正确解码,年月日才匹配得上
        html_txt = r.text[:300000]
    except Exception:
        return None
    for rx in _META_RES:
        m = rx.search(html_txt)
        if m:
            d = _date_from_text(m.group(1))
            if d and not _looks_like_now(d):      # 弃用"当前时间"伪造的发布时间
                return d
    # 兜底:财联社/每经等把发布时间放在页头可见文本(年月日 / 月日 时:分)
    v = _visible_publish_date(html_txt)
    return v if v and not _looks_like_now(v) else None


# 需浏览器过验证码/JS 才能拿到日期的站(纯 HTTP 只到验证码页,如 ZAKER 的长亭 WAF)
_SCRAPLING_PY = os.environ.get("SCRAPLING_PYTHON", "/opt/geo/scrapling-venv/bin/python")
_META_FETCH_PY = os.path.join(os.path.dirname(__file__), "meta_fetch.py")
_BROWSER_DATE_DOMAINS = {"www.myzaker.com", "myzaker.com", "m.myzaker.com",
                         "www.toutiao.com", "toutiao.com", "m.toutiao.com"}
_BROWSER_CAP = 8   # 浏览器很慢(~15-30s/条),每轮限量


def fetch_meta_date_browser(url: str) -> str | None:
    """对验证码/JS 站用独立 scrapling-venv 浏览器(过验证码,wait~12s)后抽发布时间。"""
    if not url or not os.path.exists(_SCRAPLING_PY):
        return None
    try:
        p = subprocess.run([_SCRAPLING_PY, _META_FETCH_PY, url],
                           capture_output=True, text=True, timeout=160)
    except Exception:
        return None
    lines = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not lines:
        return None
    try:
        return json.loads(lines[-1]).get("date")
    except Exception:
        return None


def resolve_undated_dates(conn, symbol: str, day: str, cap: int = 60,
                          workers: int = 8, verbose: bool = True) -> int:
    """对当日入库、引擎+URL 都没日期的相关帖,并发抓 meta 补真实发布时间。返回回填数。"""
    import concurrent.futures as _cf
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source, post_id, url FROM posts "
            "WHERE symbol = %s AND publish_time IS NULL "
            "AND substr(ingested_at, 1, 10) = %s AND url <> '' LIMIT %s",
            (symbol, day, cap),
        )
        rows = [(r["source"], r["post_id"], r["url"]) for r in cur.fetchall()]
    if not rows:
        return 0
    got: dict[tuple, str] = {}
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_meta_date, u): (s, p) for s, p, u in rows}
        for fut in _cf.as_completed(futs):
            try:
                d = fut.result()
            except Exception:
                d = None
            if d:
                got[futs[fut]] = d
    # 浏览器兜底:仍 undated 且属验证码/JS 站(ZAKER 等)的,用 Scrapling 过验证码补日期(慢,限量)
    browser_n = 0
    for s, p, u in rows:
        if (s, p) in got or browser_n >= _BROWSER_CAP:
            continue
        if (urlparse(u).hostname or "").lower() in _BROWSER_DATE_DOMAINS:
            browser_n += 1
            d = fetch_meta_date_browser(u)
            if d:
                got[(s, p)] = d
    with conn.cursor() as cur:
        for (s, p), d in got.items():
            cur.execute("UPDATE posts SET publish_time = %s "
                        "WHERE source = %s AND post_id = %s AND publish_time IS NULL",
                        (d, s, p))
    if verbose:
        print(f"  [meta-date] 扫 {len(rows)} 条 undated → 抓到 {len(got)} 条"
              f"(其中浏览器 {browser_n} 次)")
    return len(got)


def normalize_result(r: dict, symbol: str) -> dict:
    url = r.get("href") or r.get("url") or ""
    title = _clean(r.get("title"))
    body = _clean(r.get("body"))  # SERP snippet — short but usually enough
    # 发布时间解析(**只信可靠源**):① 召回自带 publishedDate → ② URL 内嵌日期(高可靠)。
    # 不再用"从标题/摘要文本猜日期"——它会把正文里提到的近期日期误当成发布日,导致老文
    # (如5月的公众号文)被算进近24h。拿不到 → None=undated,留库但不进时效窗口。
    pub = r.get("publish_time") or extract_date_from_url(url)
    return {
        "post_id": url_to_post_id(url),
        "source": domain_to_source(url),
        "symbol": symbol,
        "author": None,
        "title": title,
        "content": body,
        "publish_time": pub,
        "view_count": None,
        "reply_count": None,
        "url": url,
    }


def build_match_terms(plan: dict, symbol: str) -> list[str]:
    """监测目标的"必含词"集合:目标名 / 别名 / ticker / 同集团 targets。

    入库前用它做相关性闸门:命中结果的标题 / 摘要 / URL 至少要含其中一个,
    否则视为搜索噪声(同名实体、词典释义、泛词扩散,如「世纪互联」搜成「世纪」
    捞回的百度知道词条、同名酒店)丢弃。
    """
    raw = [plan.get("target"), symbol, plan.get("ticker"),
           *(plan.get("targets") or []), *(plan.get("aliases") or [])]
    terms: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip()
        # 太短的纯拉丁词(<3)做子串匹配易误命中;中文 2 字即可。
        if len(t) < 2 or (t.isascii() and len(t) < 3):
            continue
        k = t.lower()
        if k not in seen:
            seen.add(k)
            terms.append(t)
    return terms


def is_relevant(rec: dict, terms: list[str]) -> bool:
    # #2:百科/行情/列表/招聘/工商/采集农场等非舆情结构页,直接判不相关(入库前丢弃)
    if is_junk_page(rec.get("url") or "", rec.get("title")):
        return False
    if not terms:
        return True
    hay = " ".join(
        x for x in (rec.get("title"), rec.get("content"), rec.get("url")) if x
    ).lower()
    return any(t.lower() in hay for t in terms)


def _gap_to_timelimit(last_run_at: str | None, floor: str = "d") -> str:
    """Pick the narrowest DDG bucket that still covers the gap since last_run_at.

    Buckets: d=24h, w=7d, m=31d, y=365d. `floor` is used when there is no prior
    run or when the gap is smaller than the floor.
    """
    if not last_run_at:
        return floor
    try:
        prev = datetime.fromisoformat(last_run_at)
    except ValueError:
        return floor
    gap_h = (datetime.now() - prev).total_seconds() / 3600.0
    order = ["d", "w", "m", "y"]
    bucket = "y" if gap_h > 24 * 31 else "m" if gap_h > 24 * 7 else "w" if gap_h > 24 else "d"
    return bucket if order.index(bucket) >= order.index(floor) else floor


def _call_engine(eng: str, query: str, max_results: int,
                 region: str, timelimit: str | None) -> tuple[str, list[dict]]:
    """Call a single engine, return (engine_name, results). Thread-safe."""
    try:
        if eng == "searxng":
            r = searxng_search(query, max_results=max_results,
                               timelimit=timelimit)
        elif eng == "ddg":
            r = ddg_search(query, max_results=max_results,
                           region=region, timelimit=timelimit)
        elif eng == "cnbing":
            r = cnbing_search(query, max_results=max_results,
                              timelimit=timelimit)
        elif eng == "baidu":
            r = baidu_search(query, max_results=max_results,
                             timelimit=timelimit)
        elif eng == "sogou":
            # 微信公众号专用通道:query 含 site:mp.weixin 自动走 weixin.sogou.com
            # resolve_redirect=True: sogou /link?url=… → 真实目标 URL,
            # 否则 normalize_result 会把所有 sogou 命中标成 "unknown"
            channel = "auto"
            r = sogou_search(query, max_results=max_results,
                             timelimit=timelimit, channel=channel,
                             resolve_redirect=True)
        else:
            print(f"  [search] unknown engine: {eng!r}", file=sys.stderr)
            return eng, []
    except Exception as e:
        print(f"  [{eng}] error: {e}", file=sys.stderr)
        r = []
    return eng, r


def _search_engines(query: str, engines: tuple[str, ...],
                    max_results: int, region: str,
                    timelimit: str | None) -> tuple[list[dict], dict[str, int]]:
    """Fan out to each engine IN PARALLEL, concat results."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: list[dict] = []
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=len(engines)) as pool:
        futures = {
            pool.submit(_call_engine, eng, query, max_results, region, timelimit): eng
            for eng in engines
        }
        for fut in as_completed(futures):
            eng_name, results = fut.result()
            counts[eng_name] = len(results)
            out.extend(results)
    return out, counts


# 登录墙 UGC 直采源:搜索引擎进不去(微博/知乎登录墙),用 cookie 直采。
# 一小撮"目标名 + 负面词"定向查询,不混进 SearXNG plan(避免对平台高频请求被风控)。
_DIRECT_NEG = ("欠薪", "讨薪", "维权", "做空", "裁员", "爆雷", "亏损", "诉讼")
_DIRECT_SOURCES = (
    ("weibo", "WEIBO_COOKIE", weibo_search),
    ("zhihu", "ZHIHU_COOKIE", zhihu_search),
    ("xueqiu", None, xueqiu_search),     # 无需 cookie(WAF 走 Scrapling 浏览器,较重)
)


def collect_direct_sources(plan: dict, symbol: str, conn, seen: set[str],
                           match_terms: list[str], max_results: int = 15,
                           sleep_s: float = 1.5, verbose: bool = True) -> dict:
    """微博 / 知乎等登录墙平台直采(搜索引擎盲区)。cookie(env)未配的源自动跳过。

    复用相同的相关性闸门 + dedup(seen)+ upsert;发布时间由各 adapter 结构化提供,
    天然带准确 publish_time。任一源 / 查询失败仅跳过,不影响其它。
    """
    primary = (plan.get("target") or symbol or "").strip()
    if not primary:
        return {}
    queries = [primary] + [f"{primary} {n}" for n in _DIRECT_NEG]
    per_source: dict[str, int] = {}
    for name, env_key, fn in _DIRECT_SOURCES:
        if env_key and not os.environ.get(env_key):
            continue
        # 雪球走浏览器较重,单次"世纪互联"查询已返回大量讨论;只用实体词,不跑负面词矩阵
        qs = [primary] if name == "xueqiu" else queries
        got = 0
        for q in qs:
            try:
                rows = fn(q, max_results=max_results)
            except Exception as e:
                print(f"  [{name}] {q!r} error: {e}", file=sys.stderr)
                rows = []
            for r in rows:
                url = (r.get("href") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                rec = normalize_result(r, symbol)
                rec["source"] = name             # 统一来源名(weibo/zhihu)
                rec["author"] = r.get("author")  # 保留作者(normalize 默认置 None)
                if not is_relevant(rec, match_terms):
                    continue
                if upsert_post(conn, rec):
                    got += 1
                    per_source[name] = per_source.get(name, 0) + 1
            throttle(sleep_s)
        if verbose:
            print(f"  [direct:{name}] {got} new · {len(qs)} queries")
    return per_source


def run_plan(plan: dict, symbol: str,
             max_results_per_query: int = 10,
             timelimit: str | None = None,
             auto_widen: bool = True,
             region: str = "wt-wt",
             sleep_s: float = 1.5,
             engines: tuple[str, ...] | list[str] | None = None,
             verbose: bool = True) -> dict:
    """Execute every query in `plan`, dedupe by URL, ingest into SQLite.

    If `auto_widen` is True, `timelimit` acts as a floor and the actual bucket
    sent to DDG is widened per-query to cover the gap since `last_run_at`.
    If False, `timelimit` is passed through unchanged (None = no limit).
    """
    queries = plan.get("queries") or []
    if not queries:
        sys.exit("plan has no queries")

    eng_tuple = tuple(engines) if engines else DEFAULT_ENGINES
    floor = timelimit if timelimit in ("d", "w", "m", "y") else "d"

    conn = connect()
    init_schema(conn)

    match_terms = build_match_terms(plan, symbol)

    inserted = total = irrelevant = 0
    seen: set[str] = set()
    per_source: dict[str, int] = {}
    per_engine_total: dict[str, int] = {e: 0 for e in eng_tuple}

    for i, q in enumerate(queries, 1):
        query = q.get("query")
        if not query:
            continue

        last = get_query_last_run(conn, symbol, query) if auto_widen else None
        effective_tl = _gap_to_timelimit(last, floor=floor) if auto_widen else timelimit

        results, eng_counts = _search_engines(
            query, eng_tuple,
            max_results=max_results_per_query,
            region=region, timelimit=effective_tl,
        )
        for e, n in eng_counts.items():
            per_engine_total[e] = per_engine_total.get(e, 0) + n

        added = 0
        for r in results:
            url = (r.get("href") or r.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            rec = normalize_result(r, symbol)
            # 相关性闸门:标题 / 摘要 / URL 不含目标 / 别名 / ticker 即丢弃,
            # 拦掉同名实体、词典释义等搜索噪声(也省下后续 LLM 分析开销)。
            if not is_relevant(rec, match_terms):
                irrelevant += 1
                continue
            if upsert_post(conn, rec):
                inserted += 1
                added += 1
                per_source[rec["source"]] = per_source.get(rec["source"], 0) + 1
            total += 1

        upsert_query_last_run(conn, symbol, query)

        if verbose:
            short = (query[:78] + "…") if len(query) > 80 else query
            eng_breakdown = "+".join(f"{e}:{eng_counts.get(e, 0)}" for e in eng_tuple)
            tl_note = f" tl={effective_tl or 'none'}" if auto_widen else ""
            print(f"  [{i:>2}/{len(queries)}] {len(results):>2} results "
                  f"({eng_breakdown}){tl_note} · {added:>2} new · {short}")
        throttle(sleep_s)

    # 登录墙 UGC 直采(微博/知乎),与 SearXNG 召回合并入库
    direct = collect_direct_sources(plan, symbol, conn, seen, match_terms,
                                    sleep_s=sleep_s, verbose=verbose)
    for s, n in direct.items():
        per_source[s] = per_source.get(s, 0) + n
        inserted += n
        total += n

    # ③ 给"引擎+URL 都没日期"的当日帖,抓全文 meta 补真实发布时间(救近期、不救老闻/静态页)
    try:
        from datetime import date as _date
        resolve_undated_dates(conn, symbol, _date.today().isoformat(), verbose=verbose)
    except Exception as e:
        print(f"  [meta-date] 跳过(异常):{e}", file=sys.stderr)

    conn.commit()
    return {
        "queries": len(queries),
        "inserted": inserted,
        "total": total,
        "irrelevant": irrelevant,
        "by_source": per_source,
        "by_engine": per_engine_total,
        "engines": list(eng_tuple),
    }
