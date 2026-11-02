"""citation_check — AI citation check via Perplexity (OpenRouter).

Migrated from /geo_checker.py lines 5276-5535.
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
from ..output import print, emit_check, emit_fix, fix
from ..state import (
    SHOW_FIX, _scores, _page_cache, reset_state, track_score,
    get_ai_visibility_score, get_grade,
)
from ..ai import (
    _query_perplexity, _query_openai, _query_anthropic,
    _query_deepseek, _query_doubao,
    _check_brand_in_result, _extract_competitors, _classify_framing,
)


def citation_check(url, return_data=False):
    """Check if a site is being cited by AI engines using the OpenRouter API.

    When return_data=True, returns a dict with per-query citation results +
    overall citation rate. Raises RuntimeError on missing/invalid API key
    instead of sys.exit.
    """
    import os

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        if return_data:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        print(f"\n  [{FAIL}] OPENROUTER_API_KEY environment variable not set.")
        print(f"  This is a paid feature. Set your API key to use it:")
        print(f"    export OPENROUTER_API_KEY='your-openrouter-api-key'")
        print(f"  Get an API key at: https://openrouter.ai/")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  AI Citation Check (Powered by OpenRouter)")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"{'='*60}")
    print(f"\n  Sending brand-relevant queries to Perplexity AI via OpenRouter...")
    print(f"  Checking if {domain} appears in AI-generated citations...\n")

    # Build queries that should surface the brand if AI engines know about it
    queries = [
        f"What is {brand}?",
        f"What does {domain} do?",
        f"{brand} review",
        f"Best alternatives to {brand}",
        f"Is {brand} reliable and trustworthy?",
    ]

    # Fetch homepage to detect what the site is about for a category query.
    # Meta-description text often contains line breaks, double spaces, or
    # zero-width chars — clean those out before slicing, or the rendered
    # query looks garbled (especially in PDF where the cell wraps awkwardly).
    resp, soup = get_soup(base_url)
    if soup:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            raw_desc = meta_desc["content"]
            # Drop zero-width / BOM marks, then collapse all whitespace
            # (incl. newlines / tabs) to a single space so the truncated
            # query reads cleanly in the PDF cell.
            desc = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", raw_desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            if len(desc) > 10:
                snippet = desc[:80].rstrip()
                if len(desc) > 80:
                    snippet += "…"
                queries.append(f"Best tools for {snippet}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_url = "https://openrouter.ai/api/v1/chat/completions"

    total_queries = len(queries)
    cited_count = 0
    total_citations = 0
    results = []

    for i, query in enumerate(queries, 1):
        print(f"  [{INFO}] Query {i}/{total_queries}: \"{query}\"")

        payload = {
            "model": "perplexity/sonar",
            "messages": [
                {"role": "user", "content": query}
            ],
        }

        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if r.status_code == 401:
                if return_data:
                    raise RuntimeError("Invalid OPENROUTER_API_KEY")
                print(f"  [{FAIL}] Invalid API key. Check your OPENROUTER_API_KEY.")
                sys.exit(1)
            elif r.status_code == 429:
                print(f"  [{WARN}] Rate limited. Waiting before next query...")
                time.sleep(5)
                r = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                err_body = r.text[:200] if r.text else ""
                print(f"    [{WARN}] API error (HTTP {r.status_code}), skipping this query")
                results.append({
                    "query": query,
                    "cited": False,
                    "citations": [],
                    "error": True,
                    "upstream_status": r.status_code,
                    "upstream_body": err_body,
                })
                continue

            data = r.json()
            # Extract citations from the response
            citations = []
            # Also check the answer text for domain mentions
            answer = ""
            choices = data.get("choices", [])
            if choices:
                answer = choices[0].get("message", {}).get("content", "")

            # Check if our domain appears in citations
            domain_citations = []
            # Extract citations from the answer text
            url_pattern = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')
            found_urls = url_pattern.findall(answer)
            for url in found_urls:
                if domain in url:
                    domain_citations.append(url)

            domain_in_text = domain in answer.lower() or brand.lower() in answer.lower()

            if domain_citations:
                cited_count += 1
                total_citations += len(domain_citations)
                print(f"    [{PASS}] CITED! {len(domain_citations)} citation(s) from {domain}")
                for c in domain_citations:
                    print(f"           → {c}")
            elif domain_in_text:
                cited_count += 1
                print(f"    [{PASS}] MENTIONED in answer (no direct citation link)")
            else:
                print(f"    [{WARN}] Not cited. Found {len(found_urls)} other source(s) instead.")
                if found_urls:
                    for c in found_urls[:3]:
                        print(f"           → {c}")
                    if len(found_urls) > 3:
                        print(f"           ... and {len(found_urls) - 3} more")

            results.append({
                "query": query,
                "cited": bool(domain_citations or domain_in_text),
                "citations": domain_citations,
                "mentioned": domain_in_text,
                "total_sources": len(found_urls),
                "error": False,
            })

        except requests.RequestException as e:
            print(f"    [{FAIL}] Request failed: {e}")
            results.append({"query": query, "cited": False, "citations": [], "error": True})

        # Brief pause between queries to avoid rate limiting
        if i < total_queries:
            time.sleep(1)

    # ── Summary ──
    valid_results = [r for r in results if not r.get("error")]
    valid_count = len(valid_results)

    print(f"\n{'='*60}")
    print(f"  AI CITATION REPORT")
    print(f"{'='*60}")

    if valid_count == 0:
        print(f"  [{FAIL}] No queries completed successfully.")
        print(f"{'='*60}\n")
        if return_data:
            first_err = next((r for r in results if r.get("error")), {})
            upstream_status = first_err.get("upstream_status")
            upstream_body = first_err.get("upstream_body", "")
            msg = "All citation queries failed — upstream AI API returned no valid responses"
            if upstream_status:
                msg += f" (upstream HTTP {upstream_status})"
            if upstream_body:
                msg += f": {upstream_body}"
            msg += ". Check OPENROUTER_API_KEY quota and network connectivity."
            raise RuntimeError(msg)
        return

    citation_rate = (cited_count / valid_count * 100) if valid_count > 0 else 0

    print(f"\n  Citation Rate:  {cited_count}/{valid_count} queries ({citation_rate:.0f}%)")
    print(f"  Direct Links:   {total_citations} citation(s) pointing to {domain}")

    # Grade the citation presence
    if citation_rate >= 80:
        grade = "A — Excellent AI visibility"
        bar_color = "\033[92m"  # green
    elif citation_rate >= 60:
        grade = "B — Good AI visibility"
        bar_color = "\033[92m"
    elif citation_rate >= 40:
        grade = "C — Moderate AI visibility"
        bar_color = "\033[93m"  # yellow
    elif citation_rate >= 20:
        grade = "D — Low AI visibility"
        bar_color = "\033[93m"
    else:
        grade = "F — Not visible to AI engines"
        bar_color = "\033[91m"  # red

    bar_len = int(citation_rate / 5)
    bar = bar_color + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
    print(f"  AI Visibility:  {bar}  {citation_rate:.0f}%")
    print(f"  Grade:          {grade}")

    # Per-query breakdown
    print(f"\n  Query Results:")
    for r in results:
        if r.get("error"):
            status = f"[{WARN}] ERROR"
        elif r["cited"]:
            status = f"[{PASS}] CITED"
        else:
            status = f"[{FAIL}] NOT CITED"
        print(f"    {status}  \"{r['query']}\"")

    # Recommendations
    if citation_rate < 60:
        print(f"\n  Recommendations to improve AI citation rate:")
        print(f"    • Ensure your site has comprehensive, authoritative content about your brand")
        print(f"    • Add structured data (JSON-LD) with Organization schema")
        print(f"    • Create an llms.txt file to help AI engines understand your site")
        print(f"    • Build presence on platforms AI models reference (Wikipedia, Reddit, GitHub)")
        print(f"    • Publish original research, data, and expert content that AI engines want to cite")
        print(f"    • Ensure AI crawlers (GPTBot, ClaudeBot, PerplexityBot) are not blocked in robots.txt")

    print(f"\n  Note: Results reflect Perplexity AI's current knowledge. Other AI engines")
    print(f"  (ChatGPT, Gemini, Claude) may differ. Run periodically to track changes.")
    print(f"{'='*60}\n")

    if return_data:
        if citation_rate >= 80:
            grade_letter = "A"
        elif citation_rate >= 60:
            grade_letter = "B"
        elif citation_rate >= 40:
            grade_letter = "C"
        elif citation_rate >= 20:
            grade_letter = "D"
        else:
            grade_letter = "F"
        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "engine": "Perplexity",
            "total_queries": total_queries,
            "valid_queries": valid_count,
            "cited_queries": cited_count,
            "citation_rate": round(citation_rate, 1),
            "total_citations": total_citations,
            "grade": grade_letter,
            "queries": results,
        }


# ---------------------------------------------------------------------------
# AI Visibility Audit v2 (PAID — requires at least one AI API key)
# ---------------------------------------------------------------------------

