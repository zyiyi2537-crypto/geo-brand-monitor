"""信源占比 (source_pct) 历史诊断 — 三口径并列 + 模型引用机制分析。

口径 A — owned_url(线上口径,backend/geo/api/ai_telemetry.py:_aggregate_position_breakdown,
        2026-05-21 commit 8d24d9c):
  - 分母 denom = 命中响应 (hit=True) 的 citation URL 归一化去重数
  - 分子 ownC  = 全部响应里 citation URL ∈ owned_urls 的条目数(不去重)
  - owned_urls = 该 topic 下 status='published' 的 TopicGeneratedDoc 的
                 publish_targets_json[].url 归一化集合

口径 B — brand_mention_meta(citation 元数据匹配):
  - 分母 denom = 同 A
  - 分子 brnC  = 全部响应里 citation 的 title / snippet / url / sitename 任一字段
                 包含 brand 词(topic.target + target_aliases_json)的条目数(不去重)
  - 只用 AI 引擎返回的 citation 元数据,不抓原文

口径 C — brand_mention_fulltext(实际抓原文,本次需求):
  - 分母 denom = 同 A
  - 分子 fullC = 全部响应里 citation URL 实际抓到的 HTML 正文(去 script/style 后)
                 包含 brand 词的条目数(不去重)
  - 需要 --fetch-fulltext(默认开),首次跑会抓 URL 写入 SQLite 缓存,
    后续跑直接读 cache;--limit-fetch N 控制单次最多抓多少新 URL,
    可分批跑直到 cache 跑满;--no-fetch 跳过抓取,只输出 A/B。

== 模型引用机制分析(--analyze)==
  - 每引擎 top domains:揭示信源偏好(豆包是否偏头条系 / 自家域)
  - meta-vs-fulltext 分歧:
       * meta=0 & full=1 → snippet 没提品牌但原文提了(引擎用 snippet 选 citation 的盲区)
       * meta=1 & full=0 → snippet 提了但原文没(引擎摘要"借题发挥",或抓取失败)
  - 平均 citation 数 / 命中率 / brand-fulltext 命中率

诊断分类(基于口径 A,与线上一致):
  no_owned_urls    topic 没配自有文章发布 URL  → 全引擎都是 0,产品上正常
  no_citations     该引擎所有响应都没抓到 citation → 浏览器/过滤问题
  no_hit_with_cit  有 citation 但全在 hit=False 的响应 → 分母=0
  no_owned_overlap 命中响应有 citation,但和 owned_urls 没交集 → 自有文章没被引(新口径正常 0)
  ok               source_pct > 0

Usage (vm02 prod) — 分批抓:
    cd /opt/geo/services/telemetry-service
    DATABASE_URL=sqlite:////opt/geo/backend/data/geo_checker.db \\
      /opt/geo/backend/venv/bin/python -u -m scripts.diagnose_source_pct \\
      --limit-fetch 500     # 第一批,抓 500 个新 URL 写 cache
    # 重复跑(同命令),直到 "to-fetch=0" 表示缓存跑满

    # 完事再加 --analyze 看模型行为:
    /opt/geo/backend/venv/bin/python -u -m scripts.diagnose_source_pct --analyze

Options:
    --topic-id N         只看一个 topic
    --engine NAME        只看一个引擎(豆包 / deepseek / qwen / 文心 / 元宝)
    --only-zero          只输出 ownSrc%=0 的 cell
    --json               机读 JSON 输出
    --no-fetch           跳过全文抓取(只算 A/B)
    --limit-fetch N      本次最多抓 N 个新 URL(默认 500)
    --max-concurrency N  抓取并发数(默认 6)
    --fetch-timeout S    单 URL 超时(默认 12s)
    --cache PATH         缓存 sqlite 路径(默认 scripts/.fetch_cache.sqlite)
    --analyze            额外打印模型引用行为分析
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine, text

DEFAULT_DB_URL = "sqlite:///./data/geo_checker.db"
DEFAULT_CACHE = str(Path(__file__).parent / ".fetch_cache.sqlite")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
MAX_TEXT_BYTES = 2_000_000     # 单页正文最多存 2MB
SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")

DIAG_LABELS = {
    "no_owned_urls":    "topic 无已发布自有 URL",
    "no_citations":     "该引擎从未抓到 citation",
    "no_hit_with_cit":  "有 citation 但全在 hit=False 响应",
    "no_owned_overlap": "命中响应有 citation,但与自有 URL 无交集",
    "ok":               "source_pct > 0",
}


# ─────────────────── URL / 文本工具 ───────────────────


def _norm_url(u: str) -> str:
    """与 backend/geo/api/ai_telemetry.py:_norm_url 同步。"""
    if not u:
        return ""
    u = u.strip()
    try:
        p = urlparse(u)
        host = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        q = ("?" + p.query) if p.query else ""
        return f"{p.scheme.lower()}://{host}{path}{q}"
    except Exception:  # noqa: BLE001
        return u


def _domain_of(url_norm: str) -> str:
    try:
        return urlparse(url_norm).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def _strip_html(html: str) -> str:
    """去 script/style/tag,返回纯文本(小写,截到 MAX_TEXT_BYTES)。"""
    if not html:
        return ""
    s = html[:MAX_TEXT_BYTES * 2]
    s = SCRIPT_RE.sub(" ", s)
    s = STYLE_RE.sub(" ", s)
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()[:MAX_TEXT_BYTES]


# ─────────────────── DB 加载 ───────────────────


def load_owned_urls(conn) -> dict[int, set[str]]:
    out: dict[int, set[str]] = defaultdict(set)
    rows = conn.execute(text(
        "SELECT topic_id, publish_targets_json "
        "FROM topic_generated_docs WHERE status = 'published'"
    )).fetchall()
    for topic_id, tgts_json in rows:
        try:
            tgts = json.loads(tgts_json or "[]")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(tgts, list):
            continue
        for t in tgts:
            if isinstance(t, dict):
                u = t.get("url") or ""
                if u:
                    out[topic_id].add(_norm_url(u))
    return out


def load_topic_names(conn) -> dict[int, str]:
    rows = conn.execute(text(
        "SELECT id, name, target FROM ai_telemetry_topics"
    )).fetchall()
    return {r[0]: (r[1] or r[2] or f"#{r[0]}") for r in rows}


def load_brand_terms(conn) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    rows = conn.execute(text(
        "SELECT id, target, target_aliases_json FROM ai_telemetry_topics"
    )).fetchall()
    for tid, target, aliases_json in rows:
        terms: list[str] = []
        if target and target.strip():
            terms.append(target.strip())
        try:
            aliases = json.loads(aliases_json or "[]")
        except Exception:  # noqa: BLE001
            aliases = []
        if isinstance(aliases, list):
            for a in aliases:
                if isinstance(a, str) and a.strip():
                    terms.append(a.strip())
        seen: set[str] = set()
        norm_terms: list[str] = []
        for t in terms:
            lt = t.lower()
            if lt and lt not in seen:
                seen.add(lt)
                norm_terms.append(lt)
        out[tid] = norm_terms
    return out


def collect_responses(conn) -> tuple[list[dict], set[str]]:
    """预扫一遍 ai_telemetry_responses,返回 [response_view, ...] 与去重原 URL 集合。

    response_view: {tid, engine, hit, error, items: [(url_norm, raw_url, meta_blob_lower)]}
    """
    rows = conn.execute(text(
        "SELECT topic_id, engine, hit, citations_json, error "
        "FROM ai_telemetry_responses"
    )).fetchall()
    views: list[dict] = []
    raw_urls: set[str] = set()
    for tid, eng, hit, cit_json, err in rows:
        if err:
            views.append({"tid": tid, "engine": eng, "hit": False,
                          "error": True, "items": []})
            continue
        try:
            cits = json.loads(cit_json or "[]")
        except Exception:  # noqa: BLE001
            cits = []
        items: list[tuple[str, str, str]] = []
        if isinstance(cits, list):
            for c in cits:
                if not isinstance(c, dict):
                    continue
                u = c.get("url") or ""
                if not u:
                    continue
                title = str(c.get("title") or "")
                snippet = str(c.get("snippet") or "")
                sitename = str(c.get("sitename") or c.get("site_name") or "")
                blob = f"{u} {title} {snippet} {sitename}".lower()
                items.append((_norm_url(u), u, blob))
                raw_urls.add(u)
        views.append({"tid": tid, "engine": eng, "hit": bool(hit),
                      "error": False, "items": items})
    return views, raw_urls


# ─────────────────── Fetch cache + async fetch ───────────────────


class FetchCache:
    """SQLite KV cache,url_norm → (status, text_lower).

    status:
      ok            正常抓到 HTML,text_lower 是去标签后的小写文本
      fail:<reason> 抓取/解析失败,text_lower 空字符串
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_cache (
                url_norm   TEXT PRIMARY KEY,
                fetched_at INTEGER NOT NULL,
                status     TEXT NOT NULL,
                text_lower TEXT NOT NULL DEFAULT ''
            )
        """)
        self.conn.commit()

    def has(self, url_norm: str) -> bool:
        r = self.conn.execute(
            "SELECT 1 FROM fetch_cache WHERE url_norm = ?", (url_norm,)
        ).fetchone()
        return r is not None

    def put(self, url_norm: str, status: str, text_lower: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO fetch_cache VALUES (?, ?, ?, ?)",
            (url_norm, int(time.time()), status, text_lower[:MAX_TEXT_BYTES]),
        )
        self.conn.commit()

    def load_all(self) -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        for url_norm, status, text_lower in self.conn.execute(
            "SELECT url_norm, status, text_lower FROM fetch_cache"
        ):
            out[url_norm] = (status, text_lower)
        return out

    def count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM fetch_cache"
        ).fetchone()[0]


async def _fetch_one(client: httpx.AsyncClient, url: str,
                     timeout: float) -> tuple[str, str]:
    """返回 (status, text_lower)。"""
    try:
        r = await client.get(url, follow_redirects=True, timeout=timeout)
    except httpx.TimeoutException:
        return "fail:timeout", ""
    except httpx.RequestError as e:
        return f"fail:{type(e).__name__}", ""
    except Exception as e:  # noqa: BLE001
        return f"fail:unknown:{type(e).__name__}", ""
    if r.status_code >= 400:
        return f"fail:http{r.status_code}", ""
    ct = (r.headers.get("content-type") or "").lower()
    if ct and ("html" not in ct and "text" not in ct and "xml" not in ct):
        return f"fail:ct:{ct.split(';', 1)[0].strip()}", ""
    try:
        html = r.text
    except Exception as e:  # noqa: BLE001
        return f"fail:decode:{type(e).__name__}", ""
    return "ok", _strip_html(html)


async def fetch_many(urls: list[str], cache: FetchCache,
                     max_conc: int, timeout: float) -> dict[str, int]:
    """并发抓 URL,边抓边写 cache。返回 {ok, fail, total} 计数。"""
    stats = {"ok": 0, "fail": 0, "total": len(urls)}
    if not urls:
        return stats
    sem = asyncio.Semaphore(max_conc)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    done = 0
    async with httpx.AsyncClient(
        headers=headers, timeout=timeout, limits=httpx.Limits(max_connections=max_conc * 2)
    ) as client:
        async def work(url: str) -> None:
            nonlocal done
            async with sem:
                status, text_lower = await _fetch_one(client, url, timeout)
                cache.put(_norm_url(url), status, text_lower)
                done += 1
                if status == "ok":
                    stats["ok"] += 1
                else:
                    stats["fail"] += 1
                if done % 50 == 0 or done == stats["total"]:
                    print(f"  fetched {done}/{stats['total']} "
                          f"(ok={stats['ok']}, fail={stats['fail']})",
                          file=sys.stderr)
        await asyncio.gather(*[work(u) for u in urls])
    return stats


# ─────────────────── 聚合 + 诊断 ───────────────────


def aggregate(
    response_views: list[dict],
    owned_by_topic: dict[int, set[str]],
    brand_by_topic: dict[int, list[str]],
    fulltext_index: dict[str, tuple[str, str]],
) -> dict:
    """三口径聚合 + 额外 per-cell 统计(top domains、meta/full 分歧)。"""
    cells: dict[tuple[int, str], dict] = {}

    def acc(tid: int, eng: str) -> dict:
        k = (tid, eng)
        c = cells.get(k)
        if c is None:
            c = {
                "total": 0, "errors": 0, "hits": 0,
                "with_cit": 0, "hit_with_cit": 0,
                "denom_urls": set(),
                "owned_cit_count": 0,
                "brand_meta_cit_count": 0,
                "brand_full_cit_count": 0,
                "fetch_ok_unique": set(),       # 去重: 该 cell 涉及的 URL 抓取成功的
                "fetch_fail_unique": set(),     # 抓取失败的
                "fetch_pending_unique": set(),  # 未抓的(不在 cache)
                "domains": Counter(),           # 该 cell 所有 citation 的 domain 计数(不去重)
                "meta_only": 0,                 # meta 提了 brand 但 full 没提
                "full_only": 0,                 # full 提了 brand 但 meta 没提
                "both": 0,
                "neither": 0,
                "cits_total": 0,                # 累计 citation 条目数(不去重,用于均值)
            }
            cells[k] = c
        return c

    for v in response_views:
        tid, eng = v["tid"], v["engine"]
        c = acc(tid, eng)
        c["total"] += 1
        if v["error"]:
            c["errors"] += 1
            continue
        items = v["items"]
        if items:
            c["with_cit"] += 1
        c["cits_total"] += len(items)
        if v["hit"]:
            c["hits"] += 1
            if items:
                c["hit_with_cit"] += 1
            for nu, _ru, _b in items:
                c["denom_urls"].add(nu)
        owned = owned_by_topic.get(tid, set())
        terms = brand_by_topic.get(tid, [])
        for nu, _ru, blob in items:
            c["domains"][_domain_of(nu)] += 1
            in_owned = bool(owned) and nu in owned
            in_meta = bool(terms) and any(t in blob for t in terms)
            entry = fulltext_index.get(nu)
            if entry is None:
                c["fetch_pending_unique"].add(nu)
                in_full = False
                full_known = False
            else:
                status, text_lower = entry
                if status == "ok":
                    c["fetch_ok_unique"].add(nu)
                    in_full = bool(terms) and any(t in text_lower for t in terms)
                    full_known = True
                else:
                    c["fetch_fail_unique"].add(nu)
                    in_full = False
                    full_known = False
            if in_owned:
                c["owned_cit_count"] += 1
            if in_meta:
                c["brand_meta_cit_count"] += 1
            if in_full:
                c["brand_full_cit_count"] += 1
            # meta-vs-full 分歧只对成功抓到的样本统计
            if full_known and terms:
                if in_meta and in_full:
                    c["both"] += 1
                elif in_meta and not in_full:
                    c["meta_only"] += 1
                elif (not in_meta) and in_full:
                    c["full_only"] += 1
                else:
                    c["neither"] += 1
    return cells


def diagnose(c: dict, owned: set[str]) -> tuple[str, float, float, float]:
    """返回 (diag, src_owned, src_brand_meta, src_brand_full)。diag 基于线上口径 A。"""
    denom = len(c["denom_urls"])
    src_owned = (c["owned_cit_count"] / denom * 100) if denom else 0.0
    src_meta = (c["brand_meta_cit_count"] / denom * 100) if denom else 0.0
    src_full = (c["brand_full_cit_count"] / denom * 100) if denom else 0.0
    out = (round(src_owned, 2), round(src_meta, 2), round(src_full, 2))
    if src_owned > 0:
        return ("ok", *out)
    if not owned:
        return ("no_owned_urls", *out)
    if c["with_cit"] == 0:
        return ("no_citations", *out)
    if c["hit_with_cit"] == 0:
        return ("no_hit_with_cit", *out)
    return ("no_owned_overlap", *out)


# ─────────────────── 输出 ───────────────────


def print_table(records: list[dict]) -> None:
    if not records:
        print("(no rows)")
        return
    headers = [
        "topic", "engine",
        "total", "err", "hit",
        "wCit", "hCit", "denom",
        "ownC", "ownU", "ownSrc%",
        "metaC", "metaSrc%",
        "fullC", "fullSrc%",
        "fOK", "fFail", "fPend",
        "diagnosis",
    ]
    rows: list[list[str]] = [headers]
    for r in records:
        rows.append([
            f"{r['topic_id']}:{r['topic_name'][:12]}",
            r["engine"],
            str(r["total"]), str(r["errors"]), str(r["hits"]),
            str(r["with_cit"]), str(r["hit_with_cit"]),
            str(r["denom"]),
            str(r["owned_cit"]), str(r["owned_urls_total"]), f"{r['source_pct_owned']:.2f}",
            str(r["brand_meta_cit"]), f"{r['source_pct_meta']:.2f}",
            str(r["brand_full_cit"]), f"{r['source_pct_full']:.2f}",
            str(r["fetch_ok"]), str(r["fetch_fail"]), str(r["fetch_pending"]),
            r["diagnosis"],
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    sep = "  "
    for i, row in enumerate(rows):
        print(sep.join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print(sep.join("-" * w for w in widths))


def print_summaries(records: list[dict]) -> None:
    print()
    print("=== 引擎汇总(诊断分布,基于 owned 口径)===")
    by_eng: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        by_eng[r["engine"]][r["diagnosis"]] += 1
    for engine in sorted(by_eng):
        diag_counts = by_eng[engine]
        total = sum(diag_counts.values())
        parts = ", ".join(
            f"{DIAG_LABELS[d]}={n}"
            for d, n in sorted(diag_counts.items(), key=lambda x: -x[1])
        )
        print(f"  {engine}: {total} cells — {parts}")

    print()
    print("=== 三口径对比 — 每引擎 source_pct > 0 的 cell 数 / 总 cell 数 ===")
    cmp: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "owned": 0, "meta": 0, "full": 0}
    )
    for r in records:
        e = cmp[r["engine"]]
        e["total"] += 1
        if r["source_pct_owned"] > 0: e["owned"] += 1
        if r["source_pct_meta"]  > 0: e["meta"]  += 1
        if r["source_pct_full"]  > 0: e["full"]  += 1
    for engine in sorted(cmp):
        e = cmp[engine]
        print(f"  {engine}: owned {e['owned']}/{e['total']}, "
              f"meta {e['meta']}/{e['total']}, full {e['full']}/{e['total']}")


def print_analysis(records: list[dict], cells: dict) -> None:
    """模型引用机制分析:top domains、meta-vs-full 分歧、平均 citation 数。"""
    print()
    print("=== 模型引用机制分析 ===")

    # 1. 每引擎 top 15 domains
    by_eng_dom: dict[str, Counter] = defaultdict(Counter)
    eng_metrics: dict[str, dict] = defaultdict(lambda: {
        "responses": 0, "hits": 0, "with_cit": 0,
        "cits_total": 0,
        "meta_only": 0, "full_only": 0, "both": 0, "neither": 0,
        "fetch_ok": 0, "fetch_fail": 0, "fetch_pending": 0,
    })
    for (tid, engine), c in cells.items():
        by_eng_dom[engine].update(c["domains"])
        m = eng_metrics[engine]
        m["responses"]      += c["total"]
        m["hits"]           += c["hits"]
        m["with_cit"]       += c["with_cit"]
        m["cits_total"]     += c["cits_total"]
        m["meta_only"]      += c["meta_only"]
        m["full_only"]      += c["full_only"]
        m["both"]           += c["both"]
        m["neither"]        += c["neither"]
        m["fetch_ok"]       += len(c["fetch_ok_unique"])
        m["fetch_fail"]     += len(c["fetch_fail_unique"])
        m["fetch_pending"]  += len(c["fetch_pending_unique"])

    print()
    print("--- 每引擎平均 citation 数 / hit 率 / 抓取覆盖 ---")
    for engine in sorted(eng_metrics):
        m = eng_metrics[engine]
        avg_cit = m["cits_total"] / m["responses"] if m["responses"] else 0
        hit_rate = m["hits"] / m["responses"] * 100 if m["responses"] else 0
        cit_rate = m["with_cit"] / m["responses"] * 100 if m["responses"] else 0
        fetch_total = m["fetch_ok"] + m["fetch_fail"] + m["fetch_pending"]
        cov = m["fetch_ok"] / fetch_total * 100 if fetch_total else 0
        print(f"  {engine}: avg_cit/resp={avg_cit:.2f}, "
              f"hit_rate={hit_rate:.1f}%, with_cit_rate={cit_rate:.1f}%, "
              f"fetch_coverage={cov:.1f}% "
              f"(ok={m['fetch_ok']}, fail={m['fetch_fail']}, pend={m['fetch_pending']})")

    print()
    print("--- meta-vs-fulltext 分歧(仅成功抓到的 citation,4 类计数)---")
    print("    both        — snippet 提到 brand,原文也提到")
    print("    meta_only   — snippet 提了,原文没提(引擎摘要可能借题发挥 / 编)")
    print("    full_only   — snippet 没提,原文提了(引擎 snippet 选错重点,brand 在文里)")
    print("    neither     — 都没提(citation 跟 brand 实际无关)")
    for engine in sorted(eng_metrics):
        m = eng_metrics[engine]
        total = m["both"] + m["meta_only"] + m["full_only"] + m["neither"]
        if total == 0:
            print(f"  {engine}: (no fetched citations to compare)")
            continue
        def pct(x): return x / total * 100
        print(f"  {engine}: total={total}  "
              f"both={m['both']} ({pct(m['both']):.1f}%), "
              f"meta_only={m['meta_only']} ({pct(m['meta_only']):.1f}%), "
              f"full_only={m['full_only']} ({pct(m['full_only']):.1f}%), "
              f"neither={m['neither']} ({pct(m['neither']):.1f}%)")

    print()
    print("--- 每引擎 top 15 信源 domain(citation 条目数,不去重)---")
    for engine in sorted(by_eng_dom):
        top = by_eng_dom[engine].most_common(15)
        print(f"  {engine}:")
        for dom, n in top:
            print(f"    {n:>5}  {dom or '(empty)'}")


# ─────────────────── 主流程 ───────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="信源占比历史诊断")
    ap.add_argument("--topic-id", type=int, default=None)
    ap.add_argument("--engine", type=str, default=None)
    ap.add_argument("--only-zero", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--no-fetch", action="store_true",
                    help="跳过全文抓取(只算 A/B)")
    ap.add_argument("--limit-fetch", type=int, default=500,
                    help="本次最多抓多少个新 URL(默认 500)")
    ap.add_argument("--max-concurrency", type=int, default=6)
    ap.add_argument("--fetch-timeout", type=float, default=12.0)
    ap.add_argument("--cache", type=str, default=DEFAULT_CACHE,
                    help=f"fetch cache 路径(默认 {DEFAULT_CACHE})")
    ap.add_argument("--analyze", action="store_true",
                    help="额外打印模型引用行为分析")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    eng = create_engine(db_url)

    print(f"DB: {db_url}", file=sys.stderr)
    with eng.connect() as conn:
        owned_by_topic = load_owned_urls(conn)
        brand_by_topic = load_brand_terms(conn)
        topic_names = load_topic_names(conn)
        response_views, raw_urls = collect_responses(conn)
    print(f"responses={len(response_views)}, unique raw URLs={len(raw_urls)}",
          file=sys.stderr)

    fulltext_index: dict[str, tuple[str, str]] = {}
    if not args.no_fetch:
        cache = FetchCache(args.cache)
        cached_before = cache.count()
        print(f"cache: {args.cache} (entries={cached_before})", file=sys.stderr)
        # 找出尚未在 cache 的 URL(按原始 URL,但 key 是归一)
        url_norm_seen: set[str] = set()
        to_fetch: list[str] = []
        for u in raw_urls:
            nu = _norm_url(u)
            if nu in url_norm_seen:
                continue
            url_norm_seen.add(nu)
            if not cache.has(nu):
                to_fetch.append(u)
        print(f"to-fetch (not in cache): {len(to_fetch)}", file=sys.stderr)
        if to_fetch and args.limit_fetch > 0:
            batch = to_fetch[: args.limit_fetch]
            print(f"fetching {len(batch)} URL(s) "
                  f"(concurrency={args.max_concurrency}, "
                  f"timeout={args.fetch_timeout}s)...",
                  file=sys.stderr)
            t0 = time.time()
            stats = asyncio.run(fetch_many(
                batch, cache, args.max_concurrency, args.fetch_timeout
            ))
            dt = time.time() - t0
            print(f"fetched: ok={stats['ok']}, fail={stats['fail']} "
                  f"in {dt:.1f}s", file=sys.stderr)
            print(f"cache after: {cache.count()} (was {cached_before})",
                  file=sys.stderr)
            remain = len(to_fetch) - len(batch)
            if remain > 0:
                print(f"[next batch] still {remain} URL(s) to fetch — "
                      "rerun the same command to continue",
                      file=sys.stderr)
        fulltext_index = cache.load_all()
    else:
        print("--no-fetch: skipping fulltext fetch (口径 C 全部为 0)",
              file=sys.stderr)

    cells = aggregate(response_views, owned_by_topic, brand_by_topic, fulltext_index)

    records: list[dict] = []
    for (tid, engine), c in cells.items():
        if args.topic_id is not None and tid != args.topic_id:
            continue
        if args.engine and engine != args.engine:
            continue
        owned = owned_by_topic.get(tid, set())
        diag, src_owned, src_meta, src_full = diagnose(c, owned)
        if args.only_zero and src_owned > 0:
            continue
        records.append({
            "topic_id": tid,
            "topic_name": topic_names.get(tid, f"#{tid}"),
            "engine": engine,
            "total": c["total"],
            "errors": c["errors"],
            "hits": c["hits"],
            "with_cit": c["with_cit"],
            "hit_with_cit": c["hit_with_cit"],
            "denom": len(c["denom_urls"]),
            "owned_cit": c["owned_cit_count"],
            "brand_meta_cit": c["brand_meta_cit_count"],
            "brand_full_cit": c["brand_full_cit_count"],
            "owned_urls_total": len(owned),
            "brand_terms": brand_by_topic.get(tid, []),
            "fetch_ok": len(c["fetch_ok_unique"]),
            "fetch_fail": len(c["fetch_fail_unique"]),
            "fetch_pending": len(c["fetch_pending_unique"]),
            "source_pct_owned": src_owned,
            "source_pct_meta": src_meta,
            "source_pct_full": src_full,
            "diagnosis": diag,
        })

    records.sort(key=lambda r: (r["topic_id"], r["engine"]))

    if args.as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    print_table(records)
    print_summaries(records)
    if args.analyze:
        # analyze 用全部 cells(不受 --engine/--topic-id 过滤,看全局更有意义)
        # 但若用户加了过滤,也尊重之
        if args.topic_id is not None or args.engine:
            filt: dict = {}
            for k, c in cells.items():
                tid, e = k
                if args.topic_id is not None and tid != args.topic_id:
                    continue
                if args.engine and e != args.engine:
                    continue
                filt[k] = c
            print_analysis(records, filt)
        else:
            print_analysis(records, cells)
    return 0


if __name__ == "__main__":
    sys.exit(main())
