"""竞品透视分析器 — How do competitors appear in AI answers?

Extracts competitor mentions from BOTH answer text and citation URLs,
performs framing analysis, and generates a competitive landscape overview.

Key insight: Many AI engines (especially via API) don't return structured
citation URLs but DO mention competitor brands by name in the answer text.
So text-level brand extraction is the PRIMARY signal, not citations.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


# Domains to exclude from competitor analysis (platforms, not brands)
_PLATFORM_DOMAINS = {
    "google.com", "youtube.com", "wikipedia.org", "reddit.com",
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "medium.com", "github.com", "stackoverflow.com", "quora.com",
    "amazon.com", "yelp.com", "bbb.org", "trustpilot.com",
    "zhihu.com", "baidu.com", "weibo.com", "bilibili.com",
    "csdn.net", "cnblogs.com", "jianshu.com", "juejin.cn",
    "dev.to", "v2ex.com", "segmentfault.com", "g2.com",
    "capterra.com", "producthunt.com",
}

# Common English words to exclude from brand detection
_COMMON_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "they",
    "are", "but", "not", "you", "all", "can", "had", "her", "was", "one",
    "our", "out", "has", "its", "let", "may", "who", "did", "get", "top",
    "best", "most", "also", "more", "very", "here", "just", "like", "make",
    "over", "such", "than", "them", "then", "what", "when", "will", "each",
    "key", "new", "now", "how", "why", "two", "way", "use", "see", "first",
    "some", "time", "been", "long", "note", "well", "back", "much", "take",
    "only", "come", "both", "many", "good", "year", "keep", "last", "same",
    "work", "need", "help", "high", "line", "turn", "move", "live", "real",
    "left", "team", "since", "every", "right", "large", "based", "after",
    "these", "those", "other", "their", "which", "about", "would", "there",
    "being", "great", "through", "still", "where", "should", "while", "world",
    "could", "below", "above", "today", "known", "using", "offer", "read",
    "built", "free", "full", "plan", "look", "find", "here", "type", "point",
    # Common sentence starters / section headers
    "overview", "features", "pricing", "summary", "conclusion", "introduction",
    "comparison", "alternative", "alternatives", "category", "solution",
    "solutions", "platform", "service", "services", "product", "products",
    "tool", "tools", "review", "reviews", "pros", "cons", "key",
    "however", "additionally", "furthermore", "moreover", "therefore",
    "overall", "specifically", "particularly", "essentially", "generally",
    "merchant", "record", "processing", "payment", "payments", "gateway",
    "integration", "transaction", "transactions", "business", "businesses",
    "global", "digital", "online", "credit", "debit", "card",
    # Common false positives from AI answers
    "agent", "base", "note", "step", "visit", "sign", "check", "data",
    "user", "code", "test", "link", "home", "page", "site", "blog",
    "post", "form", "view", "list", "item", "file", "docs", "head",
    "open", "next", "main", "core", "edge", "node", "true", "false",
    "null", "void", "scam", "spam", "fake", "risk", "safe", "chat",
    # Crypto terms (not brands)
    "usdc", "usdt", "eth", "btc", "sol", "bnb", "defi", "nft",
    "blockchain", "token", "tokens", "crypto", "chain", "web3",
    "solana", "polygon", "ethereum", "bitcoin", "arbitrum",
    # Generic tech terms
    "api", "sdk", "saas", "rest", "http", "json", "html", "css",
    "ios", "android", "linux", "windows", "macos", "docker", "cloud",
    # Single words that are usually not brand names
    "smart", "fast", "easy", "simple", "basic", "standard", "premium",
    "enterprise", "professional", "advanced", "custom", "modern",
    "universal", "protocol", "framework", "library", "module",
    # More false positives
    "success", "error", "result", "status", "response", "request",
    "github", "gitlab", "npm", "pip", "maven", "gradle",
    "gas", "gasless", "gasle", "fee", "fees", "cost", "costs",
    "low", "medium", "large", "small", "tiny", "huge",
    "setup", "config", "enable", "disable", "start", "stop",
    "input", "output", "source", "target", "debug", "log",
    "app", "web", "mobile", "desktop", "server", "client",
    "pro", "plus", "max", "mini", "lite", "basic",
    "beta", "alpha", "dev", "prod", "staging",
    # AI/ML terms
    "agent", "agents", "autonomous", "model", "models", "neural",
    "training", "inference", "prompt", "prompts", "embedding",
    # Generic verbs/adjectives appearing as capitalized sentence starters
    "search", "approval", "important", "available", "required",
    "supported", "included", "designed", "created", "built",
    "allows", "provides", "offers", "enables", "supports",
    "according", "depending", "including", "regarding", "following",
    # More noise
    "molt", "multi", "wallet", "march", "tempo", "fiat", "onramps",
    "strengths", "weaknesses", "reliable", "trustworthy",
    "chain", "smart", "contract", "contracts", "layer",
    "pre", "post", "sub", "non",
    # Multi-word noise patterns
    "simple integration", "gasless transactions", "easy setup",
    "fast processing", "low fees", "high performance",
    "real time", "open source", "cross border", "end to end",
}

# Framing classification patterns
_FRAMING_PATTERNS = {
    "recommended": [
        "recommend", "use", "consider", "try", "choose", "go with",
        "is the best", "is a leading", "is a top", "stands out",
        "ideal for", "great for", "perfect for", "excellent",
    ],
    "leader": [
        "is a leader", "is one of the leading", "is a major", "is a popular",
        "is well-known", "is widely used", "is a prominent", "market leader",
        "dominant", "largest",
    ],
    "option": [
        "is an option", "is one option", "is an alternative", "is another",
        "can also", "you could", "worth considering",
    ],
    "niche": [
        "is a niche", "is experimental", "is a newer", "is a small",
        "is relatively new", "is emerging", "lesser-known",
    ],
}


def _classify_framing(answer: str, brand: str) -> str:
    """Classify how an AI answer frames a brand."""
    answer_lower = answer.lower()
    brand_lower = brand.lower()
    if brand_lower not in answer_lower:
        return "not_mentioned"
    for framing, patterns in _FRAMING_PATTERNS.items():
        for pat in patterns:
            if f"{brand_lower} {pat}" in answer_lower or f"{pat} {brand_lower}" in answer_lower:
                return framing
    return "mentioned"


def _extract_brands_from_text(results, target_brand: str) -> Counter:
    """Extract brand names from answer text — the PRIMARY signal.

    Looks for capitalized multi-word names (e.g., "Shopify Payments") and
    single capitalized words that aren't common English.
    """
    brand_mentions = Counter()
    target_lower = target_brand.lower()

    for r in results:
        if r.error or not r.answer:
            continue

        # Strategy 1 (HIGH confidence): Extract bold/emphasized terms
        # AI engines typically bold brand names: **Stripe**, **PayPal**
        bold_names = re.findall(r'\*\*([A-Z][A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,2})\*\*', r.answer)
        for name in bold_names:
            nl = name.lower()
            if nl != target_lower and nl not in _COMMON_WORDS and len(name) > 2:
                brand_mentions[name] += 2  # double weight for bold names

        # Strategy 2 (HIGH confidence): Extract from numbered/bulleted lists
        # AI engines list competitors as "1. **Stripe** — ..." or "- PayPal: ..."
        list_items = re.findall(
            r'(?:^|\n)\s*(?:\d+\.\s*|\-\s*|\*\s*)(?:\*\*)?([A-Z][A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,2})(?:\*\*)?',
            r.answer,
        )
        for name in list_items:
            nl = name.lower()
            if nl != target_lower and nl not in _COMMON_WORDS and len(name) > 3:
                brand_mentions[name] += 2

        # Strategy 3 (MEDIUM confidence): Extract from "alternatives include X, Y, Z"
        list_pattern = re.findall(
            r'(?:include|such as|like|alternatives to)[:\s]+([^.]+)',
            r.answer, re.IGNORECASE,
        )
        for match in list_pattern:
            items = re.split(r'[,;]|\band\b', match)
            for item in items:
                item = item.strip().strip('*').strip()
                if (
                    item and item[0].isupper() and len(item) > 3
                    and item.lower() != target_lower
                    and item.lower() not in _COMMON_WORDS
                ):
                    brand_mentions[item] += 1

    return brand_mentions


def _extract_competitor_domains(results, target_domain: str) -> Counter:
    """Extract competitor domains from citation URLs (secondary signal)."""
    competitors = Counter()
    for r in results:
        if r.error:
            continue
        for c in r.citations:
            d = c.domain.lower()
            if (
                d and d != target_domain and "." in d
                and d not in _PLATFORM_DOMAINS
                and not any(d.endswith("." + p) for p in _PLATFORM_DOMAINS)
            ):
                competitors[d] += 1
    return competitors


def analyze_competitor_insight(
    results,
    target_domain: str = "",
    target_brand: str = "",
    competitor_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Analyze how competitors appear in AI engine responses.

    Uses BOTH text-level brand extraction (primary) and citation URL
    extraction (secondary) to build the competitor landscape.
    """
    valid_queries = [r for r in results if not r.error]
    total_valid = len(valid_queries) or 1

    # ── Primary: extract brands from answer text ─────────
    text_brands = _extract_brands_from_text(valid_queries, target_brand)

    # ── Secondary: extract from citation URLs ────────────
    url_competitors = _extract_competitor_domains(results, target_domain)

    # ── Merge: combine text brands + URL competitors ─────
    # Normalize: for URL competitors, create a brand name from domain
    all_brands: Dict[str, Dict] = {}

    # Add text-extracted brands (filter to those mentioned at least twice)
    for name, count in text_brands.most_common(50):
        if count >= 3:  # noise filter — need 3+ weighted mentions
            key = name.lower()
            all_brands[key] = {
                "name": name,
                "text_mentions": count,
                "citation_count": 0,
            }

    # Add/merge URL competitors
    for domain, cite_count in url_competitors.most_common(20):
        brand_name = domain.split(".")[0].capitalize()
        key = brand_name.lower()
        if key in all_brands:
            all_brands[key]["citation_count"] += cite_count
        else:
            all_brands[key] = {
                "name": brand_name,
                "text_mentions": 0,
                "citation_count": cite_count,
            }

    # Add user-specified competitors if not already found
    if competitor_domains:
        for cd in competitor_domains:
            brand_name = cd.split(".")[0].capitalize()
            key = brand_name.lower()
            if key not in all_brands:
                all_brands[key] = {
                    "name": brand_name,
                    "text_mentions": 0,
                    "citation_count": 0,
                }

    # ── Per-competitor deep analysis ─────────────────────
    competitors = []
    for key, info in all_brands.items():
        brand_name = info["name"]
        brand_lower = brand_name.lower()

        # Count unique query mentions + per-engine tracking
        mention_count = 0
        framings = Counter()
        engines_seen = set()

        for r in valid_queries:
            answer_lower = r.answer.lower()
            if brand_lower in answer_lower:
                mention_count += 1
                engines_seen.add(r.engine)
                framing = _classify_framing(r.answer, brand_name)
                framings[framing] += 1

        rate = round(mention_count / total_valid * 100, 1)
        primary_framing = framings.most_common(1)[0][0] if framings else "not_mentioned"

        # Only include if actually mentioned in at least 1 answer
        if mention_count > 0 or info["citation_count"] > 0:
            competitors.append({
                "domain": f"{brand_lower}.com",
                "name": brand_name,
                "citation_count": info["citation_count"],
                "mention_count": mention_count,
                "rate": rate,
                "framing": primary_framing,
                "framings": dict(framings),
                "engines": sorted(engines_seen),
            })

    # Sort by mention count (primary) + citation count (secondary)
    competitors.sort(key=lambda c: -(c["mention_count"] * 10 + c["citation_count"]))
    competitors = competitors[:20]  # cap at 20

    # ── Your brand analysis ──────────────────────────────
    top_competitor = competitors[0] if competitors else None
    your_mention_count = 0
    your_framings = Counter()
    for r in valid_queries:
        if target_brand and (
            target_brand.lower() in r.answer.lower()
            or target_domain in r.answer.lower()
        ):
            your_mention_count += 1
            framing = _classify_framing(r.answer, target_brand)
            your_framings[framing] += 1

    your_rate = round(your_mention_count / total_valid * 100, 1) if target_brand else 0

    return {
        "competitors": competitors,
        "total_competitors": len(competitors),
        "top_competitor": top_competitor["name"] if top_competitor else None,
        "top_competitor_rate": top_competitor["rate"] if top_competitor else 0,
        "top_competitor_mentions": top_competitor["mention_count"] if top_competitor else 0,
        "your_rate": your_rate,
        "your_framing": your_framings.most_common(1)[0][0] if your_framings else "not_mentioned",
        "monitored_keywords": 1,
    }
