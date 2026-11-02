"""competitive_intel — Competitive Intelligence mode.

Orchestrates queries across all available AI engines (API + Playwright),
then runs three analyzers: source trace, source preference, competitor insight.

Concurrent execution: API engines run in parallel via ThreadPoolExecutor
(same pattern as --ai-visibility), Playwright engines run sequentially.

NOTE: This function runs inside FastAPI's threadpool (AnyIO worker thread),
so we must NOT use asyncio event loops. All engine adapters expose a
synchronous `search_sync` method for this reason.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..io import fetch, get_soup
from ..output import print
from ..constants import PASS, WARN, FAIL, INFO


# ── Data structures (lightweight, no async) ──────────────────

class _Citation:
    __slots__ = ("url", "domain", "title", "snippet", "position")

    def __init__(self, url="", domain="", title="", snippet="", position=0):
        self.url = url
        self.domain = domain
        self.title = title
        self.snippet = snippet
        self.position = position

    def to_dict(self):
        return {
            "url": self.url, "domain": self.domain, "title": self.title,
            "snippet": self.snippet, "position": self.position,
        }


class _EngineResult:
    __slots__ = ("engine", "query", "answer", "citations", "error")

    def __init__(self, engine="", query="", answer="", citations=None, error=None):
        self.engine = engine
        self.query = query
        self.answer = answer
        self.citations = citations or []
        self.error = error


# ── Synchronous engine helpers ───────────────────────────────

import re
import requests

_URL_RE = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')


def _extract_urls(text: str) -> List[str]:
    return list(dict.fromkeys(_URL_RE.findall(text)))


def _make_citation(url, title="", snippet="", position=0):
    try:
        domain = urlparse(url).netloc.replace("www.", "")
    except Exception:
        domain = url
    return _Citation(url=url, domain=domain, title=title, snippet=snippet, position=position)


def _query_kimi(query: str, api_key: str) -> _EngineResult:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "moonshot-v1-auto",
        "messages": [{"role": "user", "content": query}],
        "tools": [{"type": "builtin_function", "function": {"name": "web_search"}}],
    }
    try:
        r = requests.post("https://api.moonshot.cn/v1/chat/completions",
                          json=payload, headers=headers, timeout=60)
        if r.status_code == 401:
            return _EngineResult(engine="Kimi", query=query, error="invalid_key")
        if r.status_code != 200:
            return _EngineResult(engine="Kimi", query=query, error=f"http_{r.status_code}")
        data = r.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        urls = _extract_urls(answer)
        citations = [_make_citation(u, position=i+1) for i, u in enumerate(urls)]
        return _EngineResult(engine="Kimi", query=query, answer=answer, citations=citations)
    except Exception as e:
        return _EngineResult(engine="Kimi", query=query, error=str(e))


def _query_qwen(query: str, api_key: str) -> _EngineResult:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": query}],
        "enable_search": True,
    }
    try:
        r = requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                          json=payload, headers=headers, timeout=60)
        if r.status_code == 401:
            return _EngineResult(engine="通义千问", query=query, error="invalid_key")
        if r.status_code != 200:
            return _EngineResult(engine="通义千问", query=query, error=f"http_{r.status_code}")
        data = r.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        # Try structured search_results first
        citations = []
        sr = data.get("search_results", [])
        if not sr:
            sr = data.get("choices", [{}])[0].get("message", {}).get("search_results", [])
        for i, s in enumerate(sr):
            url = s.get("url", "") or s.get("link", "")
            if url:
                citations.append(_make_citation(url, title=s.get("title", ""),
                                                snippet=s.get("snippet", ""), position=i+1))
        if not citations:
            urls = _extract_urls(answer)
            citations = [_make_citation(u, position=i+1) for i, u in enumerate(urls)]
        return _EngineResult(engine="通义千问", query=query, answer=answer, citations=citations)
    except Exception as e:
        return _EngineResult(engine="通义千问", query=query, error=str(e))


def _query_zhipu(query: str, api_key: str) -> _EngineResult:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "glm-4-plus",
        "messages": [{"role": "user", "content": query}],
        "tools": [{"type": "web_search", "web_search": {"enable": True}}],
    }
    try:
        r = requests.post("https://open.bigmodel.cn/api/paas/v4/chat/completions",
                          json=payload, headers=headers, timeout=60)
        if r.status_code == 401:
            return _EngineResult(engine="智谱", query=query, error="invalid_key")
        if r.status_code != 200:
            return _EngineResult(engine="智谱", query=query, error=f"http_{r.status_code}")
        data = r.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        citations = []
        # Extract from tool_calls web_search results
        tcs = data.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
        for tc in tcs:
            if tc.get("type") == "web_search":
                for i, sr in enumerate(tc.get("web_search", {}).get("search_result", [])):
                    url = sr.get("link", "") or sr.get("url", "")
                    if url:
                        citations.append(_make_citation(url, title=sr.get("title", ""),
                                                        snippet=sr.get("content", ""), position=i+1))
        if not citations:
            urls = _extract_urls(answer)
            citations = [_make_citation(u, position=i+1) for i, u in enumerate(urls)]
        return _EngineResult(engine="智谱", query=query, answer=answer, citations=citations)
    except Exception as e:
        return _EngineResult(engine="智谱", query=query, error=str(e))


def _query_perplexity(query: str, api_key: str) -> _EngineResult:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "sonar", "messages": [{"role": "user", "content": query}]}
    try:
        r = requests.post("https://api.perplexity.ai/chat/completions",
                          json=payload, headers=headers, timeout=45)
        if r.status_code == 401:
            return _EngineResult(engine="Perplexity", query=query, error="invalid_key")
        if r.status_code != 200:
            return _EngineResult(engine="Perplexity", query=query, error=f"http_{r.status_code}")
        data = r.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        raw = data.get("citations", []) or _extract_urls(answer)
        citations = [_make_citation(u, position=i+1) for i, u in enumerate(raw)]
        return _EngineResult(engine="Perplexity", query=query, answer=answer, citations=citations)
    except Exception as e:
        return _EngineResult(engine="Perplexity", query=query, error=str(e))


# Also support the existing OpenRouter-based engines
def _query_openrouter_perplexity(query: str, api_key: str) -> _EngineResult:
    """Fallback: use OpenRouter if no native Perplexity key. Retries on 429."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "perplexity/sonar", "messages": [{"role": "user", "content": query}]}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              json=payload, headers=headers, timeout=45)
            if r.status_code == 401:
                return _EngineResult(engine="Perplexity", query=query, error="invalid_key")
            if r.status_code == 429:
                time.sleep(3 + attempt * 2)  # 3s, 5s, 7s backoff
                continue
            if r.status_code != 200:
                return _EngineResult(engine="Perplexity", query=query, error=f"http_{r.status_code}")
            data = r.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            urls = _extract_urls(answer)
            citations = [_make_citation(u, position=i+1) for i, u in enumerate(urls)]
            return _EngineResult(engine="Perplexity", query=query, answer=answer, citations=citations)
        except Exception as e:
            if attempt == max_retries - 1:
                return _EngineResult(engine="Perplexity", query=query, error=str(e))
            time.sleep(2)
    return _EngineResult(engine="Perplexity", query=query, error="max retries exceeded")


def _query_openai(query: str, api_key: str) -> _EngineResult:
    """OpenAI Responses API with web_search tool — returns structured citations."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "input": query,
        "tools": [{"type": "web_search"}],
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = requests.post("https://api.openai.com/v1/responses",
                              json=payload, headers=headers, timeout=60)
            if r.status_code == 401:
                return _EngineResult(engine="OpenAI", query=query, error="invalid_key")
            if r.status_code == 429:
                time.sleep(3 + attempt * 2)
                continue
            if r.status_code != 200:
                return _EngineResult(engine="OpenAI", query=query, error=f"http_{r.status_code}")
            data = r.json()
            answer = ""
            citations = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            answer = content.get("text", "")
                            for ann in content.get("annotations", []):
                                if ann.get("type") == "url_citation":
                                    citations.append(_make_citation(
                                        ann["url"],
                                        title=ann.get("title", ""),
                                        position=len(citations) + 1,
                                    ))
            if not citations:
                urls = _extract_urls(answer)
                citations = [_make_citation(u, position=i+1) for i, u in enumerate(urls)]
            return _EngineResult(engine="OpenAI", query=query, answer=answer, citations=citations)
        except Exception as e:
            if attempt == max_retries - 1:
                return _EngineResult(engine="OpenAI", query=query, error=str(e))
            time.sleep(2)
    return _EngineResult(engine="OpenAI", query=query, error="max retries exceeded")


# ── DeepSeek Playwright bridge ──────────────────────────────

def _is_playwright_engine_available(engine_name: str) -> bool:
    """Check if a browser engine has a valid session via the browser service."""
    try:
        from browser_engine.client import has_session
        return has_session(engine_name)
    except Exception:
        return False


def _is_deepseek_available() -> bool:
    return _is_playwright_engine_available("deepseek")


def _is_doubao_available() -> bool:
    return _is_playwright_engine_available("doubao")


def _run_deepseek_queries(queries: List[dict], delay: float = 5.0) -> List[_EngineResult]:
    """Run all DeepSeek queries sequentially via browser service."""
    import time
    from browser_engine.client import search as _browser_search

    results = []
    for i, q in enumerate(queries):
        try:
            r = _browser_search("deepseek", q["query"])
            citations = [
                _make_citation(c.get("url", ""), title=c.get("title", ""),
                               snippet=c.get("snippet", ""), position=c.get("position", 0))
                for c in (r.get("citations") or [])
            ]
            results.append(_EngineResult(
                engine="DeepSeek", query=q["query"],
                answer=r.get("answer", ""), citations=citations, error=r.get("error"),
            ))
        except Exception as e:
            results.append(_EngineResult(engine="DeepSeek", query=q["query"], error=str(e)))
        if i < len(queries) - 1:
            time.sleep(delay)
    return results


def _run_doubao_queries(queries: List[dict], delay: float = 5.0) -> List[_EngineResult]:
    """Run all Doubao queries sequentially via browser service."""
    import time
    from browser_engine.client import search as _browser_search

    results = []
    for i, q in enumerate(queries):
        try:
            r = _browser_search("doubao", q["query"])
            citations = [
                _make_citation(c.get("url", ""), title=c.get("title", ""),
                               snippet=c.get("snippet", ""), position=c.get("position", 0))
                for c in (r.get("citations") or [])
            ]
            results.append(_EngineResult(
                engine="豆包", query=q["query"],
                answer=r.get("answer", ""), citations=citations, error=r.get("error"),
            ))
        except Exception as e:
            results.append(_EngineResult(engine="豆包", query=q["query"], error=str(e)))
        if i < len(queries) - 1:
            time.sleep(delay)
    return results


# ── Engine registry ──────────────────────────────────────────

def _get_available_engines() -> List[tuple]:
    """Return list of (engine_name, query_fn, api_key) for API-based engines."""
    engines = []

    # Primary engines
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        engines.append(("OpenAI", _query_openai, key))

    key = os.environ.get("KIMI_API_KEY", "").strip()
    if key:
        engines.append(("Kimi", _query_kimi, key))

    key = os.environ.get("QWEN_API_KEY", "").strip()
    if key:
        engines.append(("通义千问", _query_qwen, key))

    key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if key:
        engines.append(("智谱", _query_zhipu, key))

    key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if key:
        engines.append(("Perplexity", _query_perplexity, key))
    else:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if key:
            engines.append(("Perplexity", _query_openrouter_perplexity, key))

    return engines


# ── Query builder ────────────────────────────────────────────

def _build_queries(brand, domain, category="", competitor_domains=None):
    queries = []
    queries.append({"group": "品牌定义", "query": f"What is {brand}?"})
    queries.append({"group": "品牌定义", "query": f"What does {domain} do?"})
    queries.append({"group": "品牌定义", "query": f"{brand} 是什么？"})

    queries.append({"group": "竞品对比", "query": f"Best alternatives to {brand}"})
    queries.append({"group": "竞品对比", "query": f"{brand} 和竞品对比"})
    if competitor_domains:
        for cd in competitor_domains[:3]:
            comp_brand = cd.split(".")[0]
            queries.append({"group": "竞品对比", "query": f"{brand} vs {comp_brand}"})

    if category:
        queries.append({"group": "行业品类", "query": f"Best {category} tools 2026"})
        queries.append({"group": "行业品类", "query": f"{category} 领域有哪些好用的工具？"})
    else:
        queries.append({"group": "行业品类", "query": f"Best tools like {brand}"})

    queries.append({"group": "评价", "query": f"{brand} review pros and cons"})
    queries.append({"group": "评价", "query": f"{brand} 评价怎么样？"})
    queries.append({"group": "可信度", "query": f"Is {brand} reliable?"})
    queries.append({"group": "可信度", "query": f"{brand} 靠谱吗？"})
    return queries


# ── Main entry point ─────────────────────────────────────────

def competitive_intel(
    url: str,
    competitor_domains: Optional[List[str]] = None,
    return_data: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run competitive intelligence analysis.

    Fully synchronous — safe to call from FastAPI threadpool (AnyIO worker).
    Uses ThreadPoolExecutor for parallel API calls (same pattern as ai_visibility).
    """
    from ..analyzers.source_trace import analyze_source_trace
    from ..analyzers.source_preference import analyze_source_preference
    from ..analyzers.competitor_insight import analyze_competitor_insight

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    print(f"\n{'='*60}")
    print(f"  COMPETITIVE INTELLIGENCE ANALYSIS")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"{'='*60}")

    # Detect site category from meta description
    category = ""
    resp, soup = get_soup(base_url)
    if soup:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = meta_desc["content"].strip()
            if len(desc) > 10:
                category = desc[:60].split(",")[0].split("，")[0].strip()

    # Build queries
    queries = _build_queries(brand, domain, category, competitor_domains)
    print(f"\n  Queries: {len(queries)}")

    # Discover engines
    api_engines = _get_available_engines()
    has_deepseek = _is_deepseek_available()
    has_doubao = _is_doubao_available()

    if not api_engines and not has_deepseek and not has_doubao:
        msg = "No AI engines available. Set OPENAI_API_KEY or login to DeepSeek/Doubao (run scripts/deepseek_login.py or scripts/doubao_login.py)."
        if return_data:
            raise RuntimeError(msg)
        print(f"\n  [{FAIL}] {msg}")
        sys.exit(1)

    for name, _fn, _key in api_engines:
        print(f"  [{PASS}] {name} engine ready (API)")
    if has_deepseek:
        print(f"  [{PASS}] DeepSeek engine ready (Playwright)")
    if has_doubao:
        print(f"  [{PASS}] 豆包 engine ready (Playwright)")

    start_time = time.time()
    all_results: List[_EngineResult] = []

    # ── Phase A: API engines in parallel via ThreadPoolExecutor ─
    if api_engines:
        total_api_calls = len(queries) * len(api_engines)
        max_workers = min(4, total_api_calls)
        print(f"\n  Phase A — API: {total_api_calls} calls ({len(queries)} queries x {len(api_engines)} engines)")

        def _run_one(eng_name, query_fn, api_key, query_text):
            return query_fn(query_text, api_key)

        tasks = [
            (name, fn, key, q["query"])
            for name, fn, key in api_engines
            for q in queries
        ]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_one, *t): t for t in tasks}
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    all_results.append(result)
                except Exception as e:
                    t = futures[fut]
                    all_results.append(_EngineResult(engine=t[0], query=t[3], error=str(e)))

        api_valid = sum(1 for r in all_results if not r.error)
        print(f"  Phase A done — {api_valid} valid results")

    # ── Phase B: DeepSeek via Playwright (sequential) ──────────
    if has_deepseek:
        print(f"\n  Phase B — DeepSeek: {len(queries)} queries (sequential, ~5s interval)")
        try:
            ds_results = _run_deepseek_queries(queries)
            all_results.extend(ds_results)
            ds_valid = sum(1 for r in ds_results if not r.error)
            print(f"  Phase B done — {ds_valid} valid results")
        except Exception as e:
            print(f"  [{WARN}] DeepSeek failed: {e}")
            for q in queries:
                all_results.append(_EngineResult(engine="DeepSeek", query=q["query"], error=str(e)))

    # ── Phase C: Doubao via Playwright (sequential) ────────────
    if has_doubao:
        print(f"\n  Phase C — 豆包: {len(queries)} queries (sequential, ~5s interval)")
        try:
            db_results = _run_doubao_queries(queries)
            all_results.extend(db_results)
            db_valid = sum(1 for r in db_results if not r.error)
            print(f"  Phase C done — {db_valid} valid results")
        except Exception as e:
            print(f"  [{WARN}] 豆包 failed: {e}")
            for q in queries:
                all_results.append(_EngineResult(engine="豆包", query=q["query"], error=str(e)))

    elapsed = time.time() - start_time
    valid = [r for r in all_results if not r.error]
    errored = [r for r in all_results if r.error]
    print(f"\n  Completed in {elapsed:.1f}s — {len(valid)} valid, {len(errored)} errors")

    # ── Run analyzers ────────────────────────────────────────
    print(f"\n  Running analyzers...")

    source_trace = analyze_source_trace(all_results, target_domain=domain)
    source_pref = analyze_source_preference(all_results, target_domain=domain)
    competitor = analyze_competitor_insight(
        all_results,
        target_domain=domain,
        target_brand=brand,
        competitor_domains=competitor_domains,
    )

    # Brand ranking extraction across engines
    brand_ranking = None
    try:
        from ..analyzers.brand_ranking import aggregate_rankings
        brand_ranking = aggregate_rankings(all_results, brand)
    except Exception as e:
        print(f"  Brand ranking: failed ({e})")

    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"  Source Trace: {source_trace['total_sources']} sources, {source_trace['total_citations']} citations")
    print(f"  Source Preference: {len(source_pref['per_engine'])} engines")
    print(f"  Competitors: {competitor['total_competitors']} found, top = {competitor['top_competitor'] or 'N/A'}")
    if brand_ranking:
        print(f"  Brand Ranking: avg_position={brand_ranking.get('avg_position')} best={brand_ranking.get('best_position')}")

    if return_data:
        engines_used = sorted(set(r.engine for r in all_results if not r.error))
        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "engines": engines_used,
            "query_count": len(queries),
            "total_results": len(all_results),
            "valid_results": len(valid),
            "elapsed_seconds": round(elapsed, 1),
            "source_trace": source_trace,
            "source_preference": source_pref,
            "competitor_insight": competitor,
            "brand_ranking": brand_ranking,
        }

    return None
