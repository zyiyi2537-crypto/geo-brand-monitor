"""compare_urls — side-by-side GEO scorecard across multiple URLs.

Migrated from /geo_checker.py lines 3359-3617.
"""

import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..constants import AI_BOTS, AI_CRAWLERS, PASS, WARN, FAIL, INFO, FIX
from ..io import fetch, get_soup, get_text_content
from ..output import print, emit_check, emit_fix, fix, _pad
from ..state import (
    SHOW_FIX, _scores, _page_cache, reset_state, track_score,
    get_ai_visibility_score, get_grade,
)
from ..orchestrate import run_silent
from ..ai import (
    _query_perplexity, _query_openai, _query_anthropic,
    _query_deepseek, _query_doubao,
    _check_brand_in_result, _extract_competitors, _classify_framing,
)


def compare_urls(urls, return_data=False):
    """Compare GEO readiness across multiple URLs side-by-side.

    When return_data=True, skips CLI formatting and returns a JSON-serialisable
    dict with per-URL scores, per-category breakdown, and the computed winner.
    """
    results = []

    for url in urls:
        print(f"  Analyzing {url} ...", flush=True)
        score, scores_dict, normalized_url = run_silent(url)
        results.append({
            "url": normalized_url,
            "domain": urlparse(normalized_url).netloc,
            "score": score,
            "grade": get_grade(score),
            "categories": scores_dict,
        })

    # Collect all category names
    all_categories = sorted(set(
        cat for r in results for cat in r["categories"]
    ))

    # Display comparison
    domains = [r["domain"] for r in results]
    col_width = max(max(len(d) for d in domains) + 2, 14)

    print(f"\n{'='*60}")
    print(f"  GEO COMPETITIVE COMPARISON")
    print(f"{'='*60}\n")

    # Header row
    _W = 25
    header = f"  {_pad('Category', _W)}"
    for r in results:
        header += f" {r['domain']:>{col_width}}"
    print(header)
    print(f"  {'-'*_W}" + f" {'-'*col_width}" * len(results))

    # Category rows
    for cat in all_categories:
        row = f"  {_pad(cat, _W)}"
        cat_scores = []
        for r in results:
            vals = r["categories"].get(cat, {"earned": 0, "max": 0})
            earned = vals["earned"]
            mx = vals["max"]
            pct = round(earned / mx * 100) if mx > 0 else 0
            cat_scores.append(pct)
            row += f" {earned:>4.1f}/{mx:<3.0f} ({pct:>2}%)"

        # Mark the winner with color
        if len(cat_scores) > 1:
            max_pct = max(cat_scores)
            parts = row.split()
            # Just print the row — winner highlighting via score comparison table below
        print(row)

    # Totals
    print(f"  {'-'*_W}" + f" {'-'*col_width}" * len(results))
    total_row = f"  {_pad('AI VISIBILITY SCORE', _W)}"
    for r in results:
        total_row += f" {'':>{col_width - 10}}{r['score']:>3}/100 ({r['grade']})"
    print(total_row)

    # Winner
    if len(results) > 1:
        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        winner = sorted_results[0]
        runner_up = sorted_results[1]
        lead = winner["score"] - runner_up["score"]

        print(f"\n  Winner: {winner['domain']} ({winner['score']}/100, Grade {winner['grade']})")
        if lead > 0:
            print(f"  Lead: +{lead} points over {runner_up['domain']}")

        # Show where each site wins
        print(f"\n  Category Advantages:")
        for cat in all_categories:
            scores_per_url = []
            for r in results:
                vals = r["categories"].get(cat, {"earned": 0, "max": 0})
                mx = vals["max"]
                pct = (vals["earned"] / mx * 100) if mx > 0 else 0
                scores_per_url.append((r["domain"], pct))
            scores_per_url.sort(key=lambda x: x[1], reverse=True)
            if len(scores_per_url) > 1 and scores_per_url[0][1] > scores_per_url[1][1]:
                print(f"    {_pad(cat, _W)} → {scores_per_url[0][0]} ({scores_per_url[0][1]:.0f}% vs {scores_per_url[1][1]:.0f}%)")

    # ── AI Citation Share (when API keys available) ────────────
    import os as _os
    _pplx = _os.environ.get("PERPLEXITY_API_KEY", "").strip()
    _oai = _os.environ.get("OPENAI_API_KEY", "").strip()
    _anth = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
    _dsk = _os.environ.get("DEEPSEEK_API_KEY", "").strip()
    _dbao = _os.environ.get("DOUBAO_API_KEY", "").strip()
    _dbao_m = _os.environ.get("DOUBAO_MODEL_ID", "").strip()

    _engines = {}
    if _pplx:
        _engines["Perplexity"] = ("perplexity", _pplx)
    if _oai:
        _engines["ChatGPT"] = ("openai", _oai)
    if _anth:
        _engines["Claude"] = ("anthropic", _anth)
    if _dsk:
        _engines["DeepSeek"] = ("deepseek", _dsk)
    if _dbao and _dbao_m:
        _engines["Doubao"] = ("doubao", _dbao)

    if _engines and len(results) >= 2:
        print(f"{'='*60}")
        print(f"  AI CITATION SHARE")
        print(f"  Engines: {', '.join(_engines.keys())}")
        print(f"{'='*60}")

        # Build competitive queries from the domains
        brands = [r["domain"].replace("www.", "").split(".")[0] for r in results]
        category_hint = ""
        for r in results:
            resp_c, soup_c = get_soup(r["url"])
            if soup_c:
                meta_d = soup_c.find("meta", attrs={"name": "description"})
                if meta_d and meta_d.get("content"):
                    category_hint = meta_d["content"][:60].split(",")[0].strip()
                    break

        cite_queries = []
        if category_hint:
            cite_queries.append(f"Best {category_hint} tools")
            cite_queries.append(f"Top {category_hint} solutions in 2025")
        cite_queries.append(f"Compare {' vs '.join(brands[:3])}")
        cite_queries.append(f"Which is better: {' or '.join(brands[:3])}?")
        for b in brands:
            cite_queries.append(f"What is {b}?")

        # Query each engine
        def _dispatch_query(query, eng_type, api_key):
            if eng_type == "perplexity":
                return _query_perplexity(query, api_key)
            elif eng_type == "openai":
                return _query_openai(query, api_key)
            elif eng_type == "anthropic":
                return _query_anthropic(query, api_key)
            elif eng_type == "deepseek":
                return _query_deepseek(query, api_key)
            elif eng_type == "doubao":
                return _query_doubao(query, api_key, _dbao_m)
            return "", [], "unknown_engine"

        # Track citation counts per domain
        domain_citations = {r["domain"]: 0 for r in results}
        domain_mentions = {r["domain"]: 0 for r in results}
        total_queries_run = 0

        for eng_name, (eng_type, api_key) in _engines.items():
            print(f"\n--- {eng_name} ---")
            for query in cite_queries:
                print(f"  [{INFO}] \"{query}\"")
                answer, citations, error = _dispatch_query(query, eng_type, api_key)
                if error == "invalid_key":
                    print(f"    [{FAIL}] Invalid API key — skipping {eng_name}")
                    break
                if error:
                    print(f"    [{WARN}] Error: {error}")
                    continue

                total_queries_run += 1
                answer_lower = answer.lower()
                for r in results:
                    dom = r["domain"]
                    dom_bare = dom.replace("www.", "")
                    brand_name = dom_bare.split(".")[0].lower()
                    # Check citations
                    cited = any(dom_bare in c for c in citations)
                    # Check text mentions
                    mentioned = dom_bare in answer_lower or brand_name in answer_lower
                    if cited:
                        domain_citations[dom] += 1
                        status = PASS
                    elif mentioned:
                        domain_mentions[dom] += 1
                        status = INFO
                    else:
                        status = FAIL
                    print(f"    {dom:<30} [{'CITED' if cited else 'MENTIONED' if mentioned else 'ABSENT'}]")

                time.sleep(1)

        # Citation share summary
        if total_queries_run > 0:
            print(f"\n{'='*60}")
            print(f"  CITATION SHARE RESULTS ({total_queries_run} queries x {len(_engines)} engine(s))")
            print(f"{'='*60}\n")
            print(f"  {_pad('Domain', 30)} {'Cited':>6} {'Mentioned':>10} {'Share':>8}")
            print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*8}")

            total_cites = sum(domain_citations.values()) or 1
            for r in results:
                dom = r["domain"]
                cites = domain_citations[dom]
                mentions = domain_mentions[dom]
                share = round(cites / total_cites * 100)
                bar_len = share // 5
                if share >= 40:
                    bc = "\033[92m"
                elif share >= 20:
                    bc = "\033[93m"
                else:
                    bc = "\033[91m"
                bar = bc + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
                print(f"  {dom:<30} {cites:>6} {mentions:>10} {share:>6}%  {bar}")

            # Declare citation winner
            cite_winner = max(results, key=lambda r: domain_citations[r["domain"]])
            cite_loser = min(results, key=lambda r: domain_citations[r["domain"]])
            if domain_citations[cite_winner["domain"]] > domain_citations[cite_loser["domain"]]:
                print(f"\n  Citation leader: {cite_winner['domain']} "
                      f"({domain_citations[cite_winner['domain']]} citations, "
                      f"{round(domain_citations[cite_winner['domain']] / total_cites * 100)}% share)")

    elif not _engines and len(results) >= 2:
        print(f"\n  Tip: Set an AI API key to see Citation Share analysis")
        print(f"    export PERPLEXITY_API_KEY='pplx-...'   or   export OPENAI_API_KEY='sk-...'")

    print(f"\n{'='*60}\n")

    if return_data:
        # Build per-category advantage map used by the API consumer.
        advantages = []
        for cat in all_categories:
            per_url = []
            for r in results:
                vals = r["categories"].get(cat, {"earned": 0, "max": 0})
                mx = vals["max"]
                pct = (vals["earned"] / mx * 100) if mx > 0 else 0
                per_url.append({"domain": r["domain"], "percent": round(pct, 1)})
            per_url.sort(key=lambda x: x["percent"], reverse=True)
            advantages.append({"category": cat, "ranked": per_url})

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        winner = None
        if sorted_results:
            top = sorted_results[0]
            lead = 0
            if len(sorted_results) > 1:
                lead = top["score"] - sorted_results[1]["score"]
            winner = {"domain": top["domain"], "score": top["score"], "grade": top["grade"], "lead": lead}

        return {
            "urls": [r["url"] for r in results],
            "results": results,
            "categories": all_categories,
            "advantages": advantages,
            "winner": winner,
        }


