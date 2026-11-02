"""ai_visibility — full multi-engine AI visibility audit.

Migrated from /geo_checker.py lines 5792-6367.
Depends on ai.py for engine queries + analysis helpers.
"""

import concurrent.futures
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..constants import PASS, WARN, FAIL, INFO, FIX
from ..io import fetch, get_soup, get_text_content
from ..output import print, emit_check, emit_fix, fix, _pad
from ..state import (
    SHOW_FIX, _scores, _page_cache, reset_state, track_score,
    get_ai_visibility_score, get_grade,
)
from ..ai import (
    _query_perplexity, _query_openai, _query_anthropic,
    _query_deepseek, _query_doubao, _query_qwen,
    _check_brand_in_result, _extract_competitors, _classify_framing,
)
from ..analyzers.source_trace import analyze_source_trace
from ..analyzers.source_preference import analyze_source_preference
from api_engine.base import Citation, EngineResult


def ai_visibility(url, custom_queries=None, return_data=False):
    """Comprehensive AI Visibility Audit — checks if AI would recommend the brand.

    When return_data=True, returns a dict with scorecard + per-engine visibility
    rates, top competitors, framings, and content gaps. Raises RuntimeError on
    missing API keys instead of sys.exit.
    """
    import os

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    # Detect available AI engines (using OpenRouter)
    engines = {}
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    doubao_key = os.environ.get("DOUBAO_API_KEY", "").strip()
    doubao_model = os.environ.get("DOUBAO_MODEL_ID", "").strip()
    qwen_key = os.environ.get("QWEN_API_KEY", "").strip()

    if openrouter_key:
        engines["Perplexity"] = ("perplexity", openrouter_key)
        engines["ChatGPT"] = ("openai", openrouter_key)
        engines["Claude"] = ("anthropic", openrouter_key)
    if deepseek_key:
        engines["DeepSeek"] = ("deepseek", deepseek_key)
    if doubao_key and doubao_model:
        engines["Doubao"] = ("doubao", doubao_key)
    elif doubao_key and not doubao_model:
        print(f"  [{WARN}] DOUBAO_API_KEY set but DOUBAO_MODEL_ID missing — skipping Doubao")
        print(f"           Set your endpoint ID: export DOUBAO_MODEL_ID='ep-20240...'")
    if qwen_key:
        engines["Qwen"] = ("qwen", qwen_key)

    if not engines:
        if return_data:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        print(f"\n  [{FAIL}] No AI API keys found. Set at least one:")
        print(f"    export OPENROUTER_API_KEY='your-key'   (recommended — Perplexity+ChatGPT+Claude)")
        print(f"    export DEEPSEEK_API_KEY='sk-...'")
        print(f"    export DOUBAO_API_KEY='...'  + DOUBAO_MODEL_ID='ep-...'")
        print(f"    export QWEN_API_KEY='sk-...'  (DashScope / 通义千问)")
        print(f"\n  This is a paid feature requiring AI API access.")
        sys.exit(1)

    engine_names = ", ".join(engines.keys())

    print(f"\n{'='*60}")
    print(f"  AI VISIBILITY AUDIT v2")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"  Engines: {engine_names}")
    print(f"{'='*60}")

    # ── Build query sets ──
    # Category 1: Entity definition queries
    entity_queries = [
        f"What is {brand}?",
        f"What does {domain} do?",
        f"Who is {brand} for?",
    ]

    # Category 2: Competitive/recommendation queries
    competitive_queries = [
        f"Best alternatives to {brand}",
        f"{brand} review",
        f"Is {brand} reliable and trustworthy?",
    ]

    # Category 3: Category association queries (derived from site meta)
    category_queries = []
    resp, soup = get_soup(base_url)
    site_description = ""
    if soup:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            raw_desc = meta_desc["content"]
            # Strip zero-width / BOM marks, collapse all whitespace runs to a
            # single space — keeps the gap-detection / category queries clean
            # so they don't render as visually broken in the PDF.
            cleaned = re.sub(r"[​-‏⁠﻿]", "", raw_desc)
            site_description = re.sub(r"\s+", " ", cleaned).strip()
        # Also check title for category hints
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        if site_description and len(site_description) > 10:
            snippet = site_description[:80].rstrip()
            if len(site_description) > 80:
                snippet += "…"
            category_queries.append(f"Best tools for {snippet}")
        if title_text and brand.lower() in title_text.lower():
            # Extract what comes after brand in title
            parts = title_text.lower().split(brand.lower(), 1)
            if len(parts) > 1 and len(parts[1].strip(" -—|:")) > 5:
                suffix = parts[1].strip(" -—|:").strip()[:60]
                category_queries.append(f"Best {suffix} tools")

    # Category 4: Custom queries from user
    user_queries = list(custom_queries) if custom_queries else []

    # Category 5: Gap detection queries (generic industry queries where brand should appear)
    gap_queries = []
    if site_description:
        # Build queries from site's own description that it should rank for
        gap_queries.append(f"Top {site_description[:50].split(',')[0].strip()} solutions")
    gap_queries.append(f"Best {brand} competitors 2025")

    all_query_groups = {
        "Entity Definition": entity_queries,
        "Competitive": competitive_queries,
        "Category Association": category_queries,
        "Custom": user_queries,
        "Gap Detection": gap_queries,
    }
    # Remove empty groups
    all_query_groups = {k: v for k, v in all_query_groups.items() if v}

    all_queries = []
    query_group_map = {}  # query -> group name
    for group, queries in all_query_groups.items():
        for q in queries:
            all_queries.append(q)
            query_group_map[q] = group

    total_api_calls = len(all_queries) * len(engines) * 3  # 3 runs for stability
    print(f"\n  Total queries: {len(all_queries)} x {len(engines)} engine(s) x 3 runs = {total_api_calls} API calls")
    print(f"  Estimated time: ~{total_api_calls * 2}s\n")

    # ── Query dispatcher ──
    def query_engine(query, engine_type, api_key):
        if engine_type == "perplexity":
            return _query_perplexity(query, api_key)
        elif engine_type == "openai":
            return _query_openai(query, api_key)
        elif engine_type == "anthropic":
            return _query_anthropic(query, api_key)
        elif engine_type == "deepseek":
            return _query_deepseek(query, api_key)
        elif engine_type == "doubao":
            return _query_doubao(query, api_key, doubao_model)
        elif engine_type == "qwen":
            return _query_qwen(query, api_key)
        return "", [], "unknown_engine"

    # ── Run all queries across all engines (parallel) ──
    # STABILITY_RUNS was 3 historically (inherited from upstream) to smooth
    # out AI temperature noise. 2026-04-17 收敛到 1:
    # - 调用数 10 × 3 × 3 = 90 → 10 × 3 × 1 = 30(省 67% 调用 + 成本)
    # - 耗时 120-180s → ~40-60s
    # - 分数方差 ±2-3 → ±5-8 分(用户无感;单次 snapshot 已足够)
    # - 单次 /visibility 成本 $0.84 → ~$0.28
    # Cost and convergence guidance:
    # docs/engineering/checker-reliability-and-performance.md
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    STABILITY_RUNS = 1

    def _make_error_entry():
        return {
            "answer": "", "citations": [], "error": True,
            "brand_result": {"cited": False, "domain_citations": [],
                             "mentioned_in_text": False, "all_citations": []},
            "framing": "not_mentioned",
        }

    # Pre-fill every slot with an error placeholder so downstream scoring can
    # uniformly read all_results[eng][query][run_idx] even if a task is skipped.
    all_results = {
        eng: {q: [_make_error_entry() for _ in range(STABILITY_RUNS)] for q in all_queries}
        for eng in engines
    }
    global_competitors = {}
    all_framings = []

    dead_engines = set()
    dead_lock = threading.Lock()

    def _run_one(eng_name, eng_type, api_key, query, run_idx):
        with dead_lock:
            if eng_name in dead_engines:
                return eng_name, query, run_idx, None
        answer, citations, error = query_engine(query, eng_type, api_key)
        if error == "invalid_key":
            with dead_lock:
                dead_engines.add(eng_name)
            return eng_name, query, run_idx, None
        if error:
            return eng_name, query, run_idx, None
        brand_result = _check_brand_in_result(answer, citations, domain, brand)
        framing = _classify_framing(answer, brand)
        competitors = _extract_competitors(citations, answer, domain)
        return eng_name, query, run_idx, {
            "answer": answer, "citations": citations, "error": False,
            "brand_result": brand_result, "framing": framing,
            "competitors": competitors,
        }

    tasks = [
        (eng_name, eng_type, api_key, query, run_idx)
        for eng_name, (eng_type, api_key) in engines.items()
        for query in all_queries
        for run_idx in range(STABILITY_RUNS)
    ]

    # max_workers 8→16: 30 calls / 16 = 2 批次 vs 之前 12 批次,进一步压低
    # 墙钟时间;OpenRouter 60 RPM 免费档里 16 并发也在安全区(30 calls 总量
    # 远低于 60/min 限制)。
    print(f"\n  Running {len(tasks)} API calls in parallel (max 16 concurrent)...")

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_run_one, *t) for t in tasks]
        for fut in as_completed(futures):
            eng_name, query, run_idx, result = fut.result()
            if result is None:
                continue  # keep error placeholder
            all_results[eng_name][query][run_idx] = result
            all_framings.append(result["framing"])
            for comp, count in result.get("competitors", {}).items():
                global_competitors[comp] = global_competitors.get(comp, 0) + count

    # ── Run DeepSeek via browser service if available ──
    # GEO_VISIBILITY_USE_BROWSER 默认 0:不走 browser-cn(每个 query 串行 30-60s
    # 是 visibility 主要耗时来源),让 OpenRouter / DeepSeek API / Doubao / Qwen
    # 全走 API 并发。要回退到 browser-cn 兜底,export GEO_VISIBILITY_USE_BROWSER=1。
    deepseek_results = []
    use_browser = os.environ.get("GEO_VISIBILITY_USE_BROWSER", "0").strip() == "1"
    try:
        from browser_engine.client import has_session, search as _browser_search
        if use_browser and has_session("deepseek"):
            try:
                print(f"\n  Running DeepSeek queries via browser service...")

                for query in all_queries:
                    try:
                        r = _browser_search("deepseek", query)
                        answer = r.get("answer", "")
                        # browser-cn returns Citation dataclasses serialized as
                        # dicts ({"url":..., "position":..., ...}); the rest of
                        # this module's helpers expect plain URL strings (same
                        # shape as the API engine path). Normalize here so
                        # _check_brand_in_result / _extract_competitors and the
                        # adapter_results loop below all see the same contract.
                        raw_cits = r.get("citations") or []
                        citations = []
                        for _c in raw_cits:
                            if isinstance(_c, dict):
                                _u = _c.get("url")
                            else:
                                _u = _c
                            if _u:
                                citations.append(_u)
                        deepseek_results.append({
                            "engine": "DeepSeek",
                            "query": query,
                            "answer": answer,
                            "citations": citations,
                            "error": r.get("error"),
                            "brand_result": _check_brand_in_result(answer, citations, domain, brand),
                            "framing": _classify_framing(answer, brand),
                            "competitors": _extract_competitors(citations, answer, domain),
                        })
                    except Exception as e:
                        deepseek_results.append({
                            "engine": "DeepSeek",
                            "query": query,
                            "answer": "",
                            "citations": [],
                            "error": str(e),
                            "brand_result": {"cited": False, "domain_citations": [], "mentioned_in_text": False, "all_citations": []},
                            "framing": "not_mentioned",
                            "competitors": {},
                        })

                print(f"  DeepSeek completed: {len([r for r in deepseek_results if not r['error']])} valid results")
            except Exception as e:
                print(f"  [{WARN}] DeepSeek browser service error: {e}")
        elif not use_browser:
            print(f"  [{INFO}] DeepSeek browser path disabled (GEO_VISIBILITY_USE_BROWSER!=1) — skipping")
        else:
            print(f"  [{WARN}] DeepSeek session not found. Upload session to browser service.")
    except Exception as e:
        print(f"  [{WARN}] Browser service unavailable: {e}")
    except Exception as e:
        print(f"  [{WARN}] DeepSeek Playwright not available: {e}")

    # Per-engine, per-query summary
    for eng_name in engines:
        print(f"\n--- Engine: {eng_name} ---")
        if eng_name in dead_engines:
            print(f"  [{FAIL}] Invalid {eng_name} API key. Engine skipped.")
            continue
        for query in all_queries:
            group = query_group_map[query]
            print(f"  [{INFO}] [{group}] \"{query}\"")
            run_results = all_results[eng_name][query]
            valid_runs = [r for r in run_results if not r.get("error")]
            cited_runs = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if len(valid_runs) == 0:
                print(f"    [{FAIL}] All runs failed")
            elif cited_runs == STABILITY_RUNS:
                print(f"    [{PASS}] STABLE — cited in {cited_runs}/{STABILITY_RUNS} runs")
            elif cited_runs > 0:
                print(f"    [{WARN}] UNSTABLE — cited in {cited_runs}/{STABILITY_RUNS} runs")
            else:
                print(f"    [{FAIL}] NOT CITED in any run")
            framings_this = [r["framing"] for r in valid_runs if r["framing"] != "not_mentioned"]
            if framings_this:
                primary_framing = max(set(framings_this), key=framings_this.count)
                print(f"           Framing: {primary_framing}")

    # DeepSeek Playwright summary
    if deepseek_results:
        print(f"\n--- Engine: DeepSeek (Playwright) ---")
        for query in all_queries:
            group = query_group_map[query]
            print(f"  [{INFO}] [{group}] \"{query}\"")
            run_results = [r for r in deepseek_results if r["query"] == query]
            valid_runs = [r for r in run_results if not r.get("error")]
            cited_runs = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if len(valid_runs) == 0:
                print(f"    [{FAIL}] All runs failed")
            elif cited_runs == len(valid_runs):
                print(f"    [{PASS}] STABLE — cited in {cited_runs}/{len(valid_runs)} runs")
            elif cited_runs > 0:
                print(f"    [{WARN}] UNSTABLE — cited in {cited_runs}/{len(valid_runs)} runs")
            else:
                print(f"    [{FAIL}] NOT CITED in any run")
            framings_this = [r["framing"] for r in valid_runs if r["framing"] != "not_mentioned"]
            if framings_this:
                primary_framing = max(set(framings_this), key=framings_this.count)
                print(f"           Framing: {primary_framing}")

    # ══════════════════════════════════════════════════════════════
    # ANALYSIS & SCORING
    # ══════════════════════════════════════════════════════════════

    print(f"\n{'='*60}")
    print(f"  AI VISIBILITY AUDIT — RESULTS")
    print(f"{'='*60}")

    # ── 1. Prompt Visibility Score (0-20) ──
    print(f"\n--- 1. Prompt Visibility ---")
    total_query_cited = 0
    total_query_count = 0
    per_engine_rates = {}

    # Process API engines
    for eng_name in engines:
        eng_cited = 0
        eng_total = 0
        for query in all_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if valid_runs:
                eng_total += 1
                # Cited if majority of runs cite it
                cited_count = sum(1 for r in valid_runs if r["brand_result"]["cited"])
                if cited_count > len(valid_runs) / 2:
                    eng_cited += 1
                    total_query_cited += 1
                total_query_count += 1
        rate = (eng_cited / eng_total * 100) if eng_total > 0 else 0
        per_engine_rates[eng_name] = rate
        print(f"  {eng_name}: {eng_cited}/{eng_total} queries cited ({rate:.0f}%)")

    # Process DeepSeek Playwright
    if deepseek_results:
        eng_name = "DeepSeek"
        eng_cited = 0
        eng_total = 0
        for query in all_queries:
            runs = [r for r in deepseek_results if r["query"] == query]
            valid_runs = [r for r in runs if not r.get("error")]
            if valid_runs:
                eng_total += 1
                # Cited if majority of runs cite it
                cited_count = sum(1 for r in valid_runs if r["brand_result"]["cited"])
                if cited_count > len(valid_runs) / 2:
                    eng_cited += 1
                    total_query_cited += 1
                total_query_count += 1
        rate = (eng_cited / eng_total * 100) if eng_total > 0 else 0
        per_engine_rates[eng_name] = rate
        print(f"  {eng_name} (Playwright): {eng_cited}/{eng_total} queries cited ({rate:.0f}%)")

    overall_cite_rate = (total_query_cited / total_query_count * 100) if total_query_count > 0 else 0
    visibility_score = round(overall_cite_rate / 5)  # 0-20
    print(f"  Overall: {overall_cite_rate:.0f}% → {visibility_score}/20 pts")

    # ── 2. Entity Clarity Score (0-20) ──
    print(f"\n--- 2. Entity Clarity ---")
    entity_score = 0
    entity_max = 20
    entity_answers = []

    # Process API engines
    for eng_name in engines:
        for query in entity_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            for r in valid_runs:
                if r["brand_result"]["cited"] or r["brand_result"]["mentioned_in_text"]:
                    entity_answers.append(r["answer"][:500])

    # Process DeepSeek Playwright
    if deepseek_results:
        for query in entity_queries:
            runs = [r for r in deepseek_results if r["query"] == query]
            valid_runs = [r for r in runs if not r.get("error")]
            for r in valid_runs:
                if r["brand_result"]["cited"] or r["brand_result"]["mentioned_in_text"]:
                    entity_answers.append(r["answer"][:500])

    if entity_answers:
        # Check consistency: do answers agree on what the brand is?
        # Simple approach: check if key phrases repeat across answers
        brand_lower = brand.lower()
        definitions = []
        for ans in entity_answers:
            ans_lower = ans.lower()
            # Extract the sentence containing the brand definition
            sentences = re.split(r'[.!?\n]', ans)
            for s in sentences:
                s_lower = s.lower().strip()
                if brand_lower in s_lower and ("is " in s_lower or "provides" in s_lower
                                                or "offers" in s_lower or "platform" in s_lower
                                                or "tool" in s_lower or "service" in s_lower):
                    definitions.append(s.strip())
                    break

        if definitions:
            print(f"  Found {len(definitions)} definition(s) across engines:")
            seen_defs = []
            for d in definitions[:6]:
                short = d[:120] + "..." if len(d) > 120 else d
                if short not in seen_defs:
                    seen_defs.append(short)
                    print(f"    \"{short}\"")

            # Score: definitions exist = 8pts, multiple consistent = up to 12 more
            entity_score += 8
            if len(definitions) >= 3:
                entity_score += 6
            if len(definitions) >= 6:
                entity_score += 6
        else:
            print(f"  [{WARN}] No clear definitions found in AI answers")
            entity_score += 2

        # Check for brand confusion
        confusion_terms = ["wallet", "exchange", "cryptocurrency exchange", "trading platform",
                           "social media", "game", "gambling"]
        confused = False
        for ans in entity_answers:
            ans_lower = ans.lower()
            for term in confusion_terms:
                if term in ans_lower and brand_lower in ans_lower:
                    # Check if it's actually describing the brand as this
                    pattern = f"{brand_lower}.*(?:is a|is an).*{term}"
                    if re.search(pattern, ans_lower):
                        print(f"  [{WARN}] Possible brand confusion: AI describes {brand} as a '{term}'")
                        confused = True
                        entity_score = max(entity_score - 5, 0)
                        break
            if confused:
                break
        if not confused:
            print(f"  [{PASS}] No brand confusion detected")
    else:
        print(f"  [{FAIL}] AI engines do not recognize {brand}")
        entity_score = 0

    entity_score = min(entity_score, entity_max)
    print(f"  Entity Clarity: {entity_score}/{entity_max} pts")

    # ── 3. Competitor Position Score (0-20) ──
    print(f"\n--- 3. Competitor Position ---")
    comp_score = 0

    # Show top competitors
    # Add DeepSeek Playwright competitors
    for r in deepseek_results:
        if not r.get("error"):
            for comp, count in r.get("competitors", {}).items():
                global_competitors[comp] = global_competitors.get(comp, 0) + count

    sorted_comps = sorted(global_competitors.items(), key=lambda x: -x[1])[:10]
    if sorted_comps:
        print(f"  Top competitors mentioned alongside queries:")
        for comp, count in sorted_comps:
            print(f"    {comp}: {count} mention(s)")

    # Analyze framing
    # Add DeepSeek Playwright framings
    for r in deepseek_results:
        if not r.get("error"):
            all_framings.append(r["framing"])

    framing_counts = {}
    for f in all_framings:
        framing_counts[f] = framing_counts.get(f, 0) + 1

    if framing_counts:
        print(f"\n  Brand framing across all answers:")
        framing_labels = {
            "recommended": "Recommended (strongest)",
            "leader": "Leader/major player",
            "option": "One of several options",
            "mentioned": "Passively mentioned",
            "niche": "Niche/experimental",
            "not_mentioned": "Not mentioned",
        }
        for framing, label in framing_labels.items():
            count = framing_counts.get(framing, 0)
            if count > 0:
                print(f"    {label}: {count}x")

    # Score based on framing quality
    rec_count = framing_counts.get("recommended", 0)
    leader_count = framing_counts.get("leader", 0)
    option_count = framing_counts.get("option", 0)
    mentioned_count = framing_counts.get("mentioned", 0)
    not_mentioned = framing_counts.get("not_mentioned", 0)

    total_framings = len(all_framings) or 1
    positive_ratio = (rec_count + leader_count) / total_framings
    if positive_ratio >= 0.5:
        comp_score = 20
    elif positive_ratio >= 0.3:
        comp_score = 15
    elif (rec_count + leader_count + option_count) / total_framings >= 0.3:
        comp_score = 10
    elif mentioned_count > not_mentioned:
        comp_score = 5
    else:
        comp_score = 0

    print(f"  Competitor Position: {comp_score}/20 pts")

    # ── 4. Answer Stability Score (0-20) ──
    print(f"\n--- 4. Answer Stability ---")
    stable_count = 0
    unstable_count = 0
    absent_count = 0

    # Process API engines
    for eng_name in engines:
        for query in all_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                absent_count += 1
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == len(valid_runs):
                stable_count += 1
            elif cited_in > 0:
                unstable_count += 1
            else:
                absent_count += 1

    # Process DeepSeek Playwright
    if deepseek_results:
        for query in all_queries:
            runs = [r for r in deepseek_results if r["query"] == query]
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                absent_count += 1
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == len(valid_runs):
                stable_count += 1
            elif cited_in > 0:
                unstable_count += 1
            else:
                absent_count += 1

    total_slots = stable_count + unstable_count + absent_count
    print(f"  Stable (all runs cited):   {stable_count}")
    print(f"  Unstable (some runs):      {unstable_count}")
    print(f"  Absent (never cited):      {absent_count}")

    if total_slots > 0:
        stability_ratio = (stable_count + unstable_count * 0.3) / total_slots
        stability_score = round(stability_ratio * 20)
    else:
        stability_score = 0

    print(f"  Answer Stability: {stability_score}/20 pts")

    # ── 5. Content Gap Score (0-20) ──
    print(f"\n--- 5. Content Gaps ---")
    gap_score = 20  # Start full, subtract for each gap found
    gaps_found = []

    # Process API engines
    for eng_name in engines:
        for query in all_queries:
            group = query_group_map[query]
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == 0:
                gap_entry = f"[{eng_name}] \"{query}\" ({group})"
                if gap_entry not in gaps_found:
                    gaps_found.append(gap_entry)

    # Process DeepSeek Playwright
    if deepseek_results:
        eng_name = "DeepSeek (Playwright)"
        for query in all_queries:
            group = query_group_map[query]
            runs = [r for r in deepseek_results if r["query"] == query]
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == 0:
                gap_entry = f"[{eng_name}] \"{query}\" ({group})"
                if gap_entry not in gaps_found:
                    gaps_found.append(gap_entry)

    # Deduplicate by query text
    seen_queries = set()
    unique_gaps = []
    for gap in gaps_found:
        # Extract query from gap entry
        q_match = re.search(r'"(.+?)"', gap)
        if q_match:
            q_text = q_match.group(1)
            if q_text not in seen_queries:
                seen_queries.add(q_text)
                unique_gaps.append(gap)

    if unique_gaps:
        print(f"  [{WARN}] {len(unique_gaps)} content gap(s) detected:")
        for gap in unique_gaps[:10]:
            print(f"    • {gap}")
            gap_score -= 3
        if len(unique_gaps) > 10:
            print(f"    ... and {len(unique_gaps) - 10} more")

        print(f"\n  Recommended actions to fill gaps:")
        print(f"    • Create dedicated pages for topics where {brand} is not cited")
        print(f"    • Add FAQ sections answering these exact queries on your site")
        print(f"    • Write comparison pages ({brand} vs [competitor]) for competitive queries")
        print(f"    • Publish content on third-party platforms (blog posts, Reddit, GitHub)")
    else:
        print(f"  [{PASS}] No major content gaps detected!")

    gap_score = max(gap_score, 0)
    print(f"  Content Gap: {gap_score}/20 pts")

    # ══════════════════════════════════════════════════════════════
    # COMPOSITE GEO HEALTH SCORECARD
    # ══════════════════════════════════════════════════════════════

    total_score = visibility_score + entity_score + comp_score + stability_score + gap_score
    total_max = 100

    print(f"\n{'='*60}")
    print(f"  GEO HEALTH SCORECARD")
    print(f"{'='*60}")

    categories = [
        ("Prompt Visibility", visibility_score, 20),
        ("Entity Clarity", entity_score, 20),
        ("Competitor Position", comp_score, 20),
        ("Answer Stability", stability_score, 20),
        ("Content Gap", gap_score, 20),
    ]

    for cat_name, earned, mx in categories:
        pct = (earned / mx * 100) if mx > 0 else 0
        bar_len = int(pct / 5)
        if pct >= 60:
            bar_color = "\033[92m"
        elif pct >= 30:
            bar_color = "\033[93m"
        else:
            bar_color = "\033[91m"
        bar = bar_color + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
        print(f"  {_pad(cat_name, 22)} {earned:>2}/{mx}  {bar}  {pct:.0f}%")

    print(f"  {'─'*22} {'─'*5}")
    print(f"  {_pad('GEO HEALTH', 22)} {total_score:>2}/{total_max}")

    # Overall grade
    if total_score >= 80:
        grade = "A — AI engines actively recommend this brand"
        grade_color = "\033[92m"
    elif total_score >= 60:
        grade = "B — Good visibility, some gaps to fill"
        grade_color = "\033[92m"
    elif total_score >= 40:
        grade = "C — Moderate visibility, significant gaps"
        grade_color = "\033[93m"
    elif total_score >= 20:
        grade = "D — Low visibility, major work needed"
        grade_color = "\033[93m"
    else:
        grade = "F — Not visible to AI engines"
        grade_color = "\033[91m"

    print(f"\n  Grade: {grade_color}{grade}\033[0m")

    # Multi-engine comparison
    if len(per_engine_rates) > 1:
        print(f"\n  Per-Engine Visibility:")
        for eng_name, rate in per_engine_rates.items():
            bar_len = int(rate / 5)
            if rate >= 60:
                bc = "\033[92m"
            elif rate >= 30:
                bc = "\033[93m"
            else:
                bc = "\033[91m"
            bar = bc + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
            print(f"    {eng_name:<15} {bar}  {rate:.0f}%")

    print(f"\n  Run periodically to track improvements over time.")
    print(f"  Tip: Use --queries to test your specific category prompts.")
    print(f"{'='*60}\n")

    if return_data:
        top_competitors = sorted(global_competitors.items(), key=lambda x: -x[1])[:10]

        # ── Build EngineResult list for source analyzers ──
        from api_engine.base import Citation, EngineResult as _ER

        adapter_results = []
        # Add API engine results
        for eng_name in engines:
            for query in all_queries:
                for run in all_results[eng_name].get(query, []):
                    if run.get("error"):
                        continue
                    cits = [
                        Citation.from_url(u, position=i + 1)
                        for i, u in enumerate(run.get("citations", []))
                    ]
                    adapter_results.append(_ER(
                        engine=eng_name, query=query,
                        answer=run.get("answer", ""), citations=cits,
                    ))

        # Add DeepSeek Playwright results
        for r in deepseek_results:
            if r.get("error"):
                continue
            cits = [
                Citation.from_url(u, position=i + 1)
                for i, u in enumerate(r.get("citations", []))
            ]
            adapter_results.append(_ER(
                engine="DeepSeek", query=r["query"],
                answer=r.get("answer", ""), citations=cits,
            ))

        source_trace = analyze_source_trace(adapter_results, target_domain=domain)
        source_pref = analyze_source_preference(adapter_results, target_domain=domain)

        # Include all engines used
        engines_used = list(per_engine_rates.keys())

        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "engines": engines_used,
            "scores": {
                "visibility": visibility_score,
                "entity": entity_score,
                "competitor": comp_score,
                "stability": stability_score,
                "content_gap": gap_score,
            },
            "total_score": total_score,
            "max_score": total_max,
            "grade": grade.split(" — ")[0] if " — " in grade else grade,
            "grade_label": grade,
            "per_engine_rates": {k: round(v, 1) for k, v in per_engine_rates.items()},
            "top_competitors": [{"domain": d, "mentions": c} for d, c in top_competitors],
            "framings": framing_counts,
            "content_gaps": unique_gaps[:20],
            "query_count": len(all_queries),
            "stability_runs": STABILITY_RUNS,
            "source_trace": source_trace,
            "source_preference": source_pref,
        }


# ---------------------------------------------------------------------------
# Entity GEO Audit  (--entity)
# ---------------------------------------------------------------------------
