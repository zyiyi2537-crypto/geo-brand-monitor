"""引用源偏好分析器 — What types of sources do different engines prefer?

Analyzes citation patterns per engine to reveal source type preferences
and generate optimization recommendations.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from api_engine.base import EngineResult
from .source_classify import classify_source


def analyze_source_preference(
    results: List[EngineResult],
    target_domain: str = "",
) -> Dict[str, Any]:
    """Analyze per-engine source type preferences.

    Returns a dict with:
    - per_engine: per-engine type distributions and top domains
    - overall_distribution: global source type distribution
    - recommendations: actionable optimization suggestions
    - stats: summary stats (total sources, total citations, avg)
    """
    # Per-engine tracking
    engine_types: Dict[str, Counter] = defaultdict(Counter)
    engine_domains: Dict[str, Counter] = defaultdict(Counter)
    engine_citation_count: Dict[str, int] = defaultdict(int)

    # Global tracking
    all_types = Counter()
    all_domains = Counter()
    total_citations = 0
    unique_sources = set()

    for r in results:
        if r.error:
            continue
        for c in r.citations:
            stype = classify_source(c.url, target_domain)
            engine_types[r.engine][stype] += 1
            engine_domains[r.engine][c.domain] += 1
            engine_citation_count[r.engine] += 1
            all_types[stype] += 1
            all_domains[c.domain] += 1
            total_citations += 1
            unique_sources.add(c.domain)

    # Per-engine analysis
    per_engine = []
    for engine in sorted(engine_types.keys()):
        type_counts = engine_types[engine]
        eng_total = engine_citation_count[engine]
        type_distribution = {
            t: round(c / eng_total * 100, 1) if eng_total else 0
            for t, c in type_counts.most_common()
        }
        top_domains = [
            {"domain": d, "count": c}
            for d, c in engine_domains[engine].most_common(5)
        ]
        per_engine.append({
            "engine": engine,
            "total_citations": eng_total,
            "type_distribution": type_distribution,
            "top_domains": top_domains,
        })

    # Overall distribution
    overall_total = sum(all_types.values()) or 1
    overall_distribution = {
        t: round(c / overall_total * 100, 1)
        for t, c in all_types.most_common()
    }

    # Engine totals for donut chart
    engine_totals = {
        engine: engine_citation_count[engine]
        for engine in sorted(engine_citation_count.keys())
    }

    # Generate recommendations
    recommendations = _generate_recommendations(engine_types, engine_citation_count, target_domain)

    return {
        "per_engine": per_engine,
        "overall_distribution": overall_distribution,
        "engine_totals": engine_totals,
        "recommendations": recommendations,
        "stats": {
            "total_sources": len(unique_sources),
            "total_citations": total_citations,
            "avg_citations": round(total_citations / max(len(unique_sources), 1), 1),
        },
    }


def _generate_recommendations(
    engine_types: Dict[str, Counter],
    engine_counts: Dict[str, int],
    target_domain: str,
) -> List[Dict[str, str]]:
    """Generate actionable optimization recommendations based on engine preferences."""
    recs = []

    for engine, type_counter in engine_types.items():
        total = engine_counts[engine]
        if total == 0:
            continue

        # Check if official sources are underrepresented
        official_pct = type_counter.get("official", 0) / total * 100
        if official_pct < 5 and target_domain:
            recs.append({
                "engine": engine,
                "type": "warning",
                "message": f"{engine} 几乎没有引用你的官方内容，建议优化官网的结构化数据和 SEO",
            })

        # Identify dominant source types per engine
        top_type, top_count = type_counter.most_common(1)[0] if type_counter else ("other", 0)
        top_pct = top_count / total * 100

        if top_type == "news" and top_pct > 25:
            recs.append({
                "engine": engine,
                "type": "insight",
                "message": f"{engine} {top_pct:.0f}% 引用来自新闻源，建议增加 PR 和新闻稿覆盖",
            })
        elif top_type == "blog" and top_pct > 25:
            recs.append({
                "engine": engine,
                "type": "insight",
                "message": f"{engine} {top_pct:.0f}% 引用来自博客平台，建议加强技术博客和内容营销",
            })
        elif top_type == "forum" and top_pct > 25:
            recs.append({
                "engine": engine,
                "type": "insight",
                "message": f"{engine} {top_pct:.0f}% 引用来自论坛/问答，建议在知乎、Reddit 等平台建立品牌存在",
            })
        elif top_type == "documentation" and top_pct > 25:
            recs.append({
                "engine": engine,
                "type": "insight",
                "message": f"{engine} 偏好文档类内容，建议完善官方文档并添加结构化标记",
            })

    if not recs:
        recs.append({
            "engine": "全部",
            "type": "info",
            "message": "引用源分布较均匀，继续保持多渠道内容分发策略",
        })

    return recs
